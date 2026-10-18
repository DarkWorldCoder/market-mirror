"""
feed_story.py - the post-by-post story of a simulation: who posted what, from which
country and segment, in which round, and how people reacted (likes, quotes, reposts,
comments), plus how the brand's own injected posts performed.

Sources (all read-only):
  <sim>/twitter_simulation.db, <sim>/reddit_simulation.db   OASIS tables post, comment,
                                                             like, dislike, user, follow,
                                                             comment_like
  <sim>/<platform>/actions.jsonl                             round_start rows give the
                                                             round and simulated hour;
                                                             action rows carry the ids
                                                             (new_post_id, comment_id,
                                                             like_id, dislike_id) that map
                                                             rows to rounds. CREATE_POST
                                                             rows carry no id, so posts
                                                             map by (agent, content).
  config["persona_index"], config["event_config"]            who is who; which posts were
                                                             injected by the brand.

Round-0 rows are logged twice by the runner (round 0 and again in round 1); the
first row wins. Without actions.jsonl every round is None and posts are ordered by
created_at (an integer step on Twitter, a datetime string on Reddit).

Data shapes
  Author   = {agent_id, name, segment, country, kind}
  PostView = {post_id, platform, kind: post|quote|repost, author, round, hour, created_at,
              content, is_brand, quote_content, original{post_id, author}|None,
              likes, dislikes, likers[Author], reposts, quotes[post_id],
              comments[{comment_id, author, content, round, hour, likes, sentiment}],
              engagement{by_segment, by_country}, reach_proxy, reply_sentiment{pos, neg, neu},
              sentiment, score}
  RoundView = {round, hour, posts, comments, likes, top_posts[post_id x3], brand_sentiment}

Sentiment is a small multilingual lexicon plus an emoji heuristic and is flagged
"lexicon" in the output so nobody mistakes it for a model judgement.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

PLATFORMS = ("twitter", "reddit")
DB_FILES = {"twitter": "twitter_simulation.db", "reddit": "reddit_simulation.db"}
SENTIMENT_METHOD = "lexicon"

# --------------------------------------------------------------------------
# Sentiment: tiny multilingual lexicon (English, Hinglish, Taglish, Swahili,
# Indonesian, Spanish, Nepali in Roman script) + emoji
# --------------------------------------------------------------------------

_POS_WORDS = """
good great love loved loving awesome amazing excellent perfect best nice helpful worth recommend recommended
happy glad excited thanks thank useful works worked easy brilliant fantastic wonderful solid legit genuine cool
yes definitely absolutely finally impressed impressive affordable cheap bargain value convenient fun motivated
accha acha achha badhiya mast sahi bahut-accha zabardast shandar bindaas sundar ramro ekdam dhanyabad
maganda ganda galing astig sulit okay-naman mabuti salamat gusto pwede-na solid-sulit
nzuri safi poa bomba vizuri asante freshi
bagus mantap keren hebat suka terima-kasih murah
bueno buena genial excelente perfecto gracias barato
""".split()
_NEG_WORDS = """
bad worst hate hated terrible awful scam scammy fraud fake suspicious shady sketchy overpriced expensive pricey
disappointed disappointing useless waste annoying spam spammy hidden catch worried worry risk risky dangerous
no never cancel cancelled charged charge refund problem problems issue issues bug bugs crash crashes slow laggy
red-flag redflag doubt doubtful skeptical sceptical pass avoid regret regretted unfair pathetic lame boring
bekar bakwas ghatiya mehenga mehnga mahanga dhokha fraud-hai galat kharab nahi nahin mat dar darr chor
mahal panget pangit ayaw hindi niloko scam-yan peke sayang walang-kwenta
mbaya ghali hapana tapeli feki uongo
jelek mahal buruk penipuan tidak jangan
malo mala caro estafa terrible horrible nunca
""".split()
_NEGATIONS = {"not", "no", "never", "dont", "don't", "doesnt", "doesn't", "didnt", "didn't", "isnt", "isn't", "cant",
              "can't", "nahi", "nahin", "mat", "hindi", "wala", "si", "tidak", "jangan", "hapana"}
_POS_EMOJI = "😀😁😂🤣😃😄😅😆😊😍🥰😘🤩👍👏🙌💪❤️🧡💛💚💙💜🔥✨🎉✅💯🙏🥳😎"
_NEG_EMOJI = "😠😡🤬😤😒🙄😞😟😕☹️🙁😣😖😫😩😢😭👎💔🚩❌⚠️🤮🤢😬🥱"
_WORD = re.compile(r"[a-zA-ZÀ-ɏ][a-zA-ZÀ-ɏ'\-]*")


def sentiment_score(text: Any) -> float:
    """Signed lexicon score: positive words and emoji count +1, negative -1, a negation
    word right before a hit flips it. 0.0 for empty or neutral text."""
    if not text:
        return 0.0
    s = str(text)
    score = 0.0
    words = [w.lower() for w in _WORD.findall(s)]
    pos, neg = set(_POS_WORDS), set(_NEG_WORDS)
    for i, w in enumerate(words):
        hit = 1.0 if w in pos else -1.0 if w in neg else 0.0
        if not hit:
            continue
        if i and words[i - 1] in _NEGATIONS:
            hit = -hit
        score += hit
    for ch in s:
        if ch in _POS_EMOJI:
            score += 1.0
        elif ch in _NEG_EMOJI:
            score -= 1.0
    return score


def sentiment_label(text: Any) -> str:
    """'pos' | 'neg' | 'neu' from the lexicon score."""
    sc = sentiment_score(text)
    return "pos" if sc >= 1 else "neg" if sc <= -1 else "neu"


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

def _norm_key(content: Any) -> str:
    return " ".join(str(content or "").split()).strip().lower()


def round_index(sim_dir: str, platform: str) -> Dict[str, Any]:
    """Map DB rows to rounds from <sim>/<platform>/actions.jsonl.

    Returns {"available": bool, "rounds": {round: hour}, "posts": {post_id: round},
             "post_keys": {(agent_id, normalised content): round}, "comments": {comment_id: round},
             "likes": {like_id: round}, "dislikes": {dislike_id: round}, "comment_likes": {comment_id: round}}.
    The first row for an id or key wins, so round-0 rows beat their round-1 duplicates."""
    out: Dict[str, Any] = {"available": False, "rounds": {}, "posts": {}, "post_keys": {}, "comments": {},
                           "likes": {}, "dislikes": {}, "comment_likes": {}}
    path = os.path.join(sim_dir, platform, "actions.jsonl")
    if not os.path.exists(path):
        return out
    out["available"] = True
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        out["available"] = False
        return out
    current: Optional[int] = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        ev = row.get("event_type")
        if ev == "round_start":
            try:
                current = int(row.get("round"))
            except (TypeError, ValueError):
                continue
            out["rounds"].setdefault(current, row.get("simulated_hour"))
            continue
        if ev:
            continue
        rnd = row.get("round", current)
        try:
            rnd = int(rnd) if rnd is not None else None
        except (TypeError, ValueError):
            rnd = None
        if rnd is None:
            continue
        out["rounds"].setdefault(rnd, None)
        args = row.get("action_args") or {}
        if not isinstance(args, dict):
            args = {}
        kind = row.get("action_type")
        aid = row.get("agent_id")
        if kind == "CREATE_POST":
            # Round-0 initial posts are logged without an id; their round-1 replay (from the
            # trace table) carries one. The earliest round for the same (agent, content) wins.
            key = (aid, _norm_key(args.get("content")))
            out["post_keys"].setdefault(key, rnd)
            if args.get("post_id") is not None:
                out["posts"].setdefault(_int(args.get("post_id")), min(rnd, out["post_keys"][key]))
        elif kind in ("QUOTE_POST", "REPOST") and args.get("new_post_id") is not None:
            out["posts"].setdefault(_int(args.get("new_post_id")), rnd)
        elif kind == "CREATE_COMMENT" and args.get("comment_id") is not None:
            out["comments"].setdefault(_int(args.get("comment_id")), rnd)
        elif kind == "LIKE_POST" and args.get("like_id") is not None:
            out["likes"].setdefault(_int(args.get("like_id")), rnd)
        elif kind == "DISLIKE_POST" and args.get("dislike_id") is not None:
            out["dislikes"].setdefault(_int(args.get("dislike_id")), rnd)
        elif kind == "LIKE_COMMENT" and args.get("comment_id") is not None:
            out["comment_likes"].setdefault(_int(args.get("comment_id")), rnd)
    return out


def _int(v: Any) -> Any:
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def _rows(conn: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    try:
        cur = conn.execute(f"SELECT * FROM {table}")
    except sqlite3.Error:
        return []
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def load_platform(db_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """Read the OASIS tables we need from one platform database (read-only)."""
    empty = {"users": [], "posts": [], "comments": [], "likes": [], "dislikes": [], "follows": [], "comment_likes": []}
    if not os.path.exists(db_path):
        return empty
    uri = "file:" + os.path.abspath(db_path).replace("?", "%3F").replace("#", "%23") + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return empty
    try:
        return {"users": _rows(conn, "user"), "posts": _rows(conn, "post"), "comments": _rows(conn, "comment"),
                "likes": _rows(conn, "like"), "dislikes": _rows(conn, "dislike"), "follows": _rows(conn, "follow"),
                "comment_likes": _rows(conn, "comment_like")}
    finally:
        conn.close()


def _created_key(v: Any) -> float:
    """Sortable number for created_at: Twitter stores an int step, Reddit a datetime string."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    try:
        return float(s)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------
# People and brand posts
# --------------------------------------------------------------------------

def _author(row: Optional[Dict[str, Any]], agent_id: Any, fallback_name: str = "") -> Dict[str, Any]:
    row = row or {}
    return {"agent_id": agent_id, "name": row.get("name") or fallback_name or f"agent {agent_id}",
            "segment": row.get("segment"), "country": row.get("country"), "kind": row.get("kind") or "unknown"}


def _people(config: Dict[str, Any], users: Iterable[Dict[str, Any]]) -> Dict[Any, Dict[str, Any]]:
    index = {}
    for r in (config or {}).get("persona_index") or []:
        if isinstance(r, dict) and r.get("agent_id") is not None:
            index[_int(r["agent_id"])] = r
    people: Dict[Any, Dict[str, Any]] = {}
    for u in users:
        aid = _int(u.get("agent_id") if u.get("agent_id") is not None else u.get("user_id"))
        people[aid] = _author(index.get(aid), aid, u.get("name") or u.get("user_name") or "")
    for aid, r in index.items():
        people.setdefault(aid, _author(r, aid))
    return people


def _resolve_agent(ref: Any, config: Dict[str, Any]) -> Any:
    """An agent id, or a persona_index name."""
    if ref is None:
        return None
    if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit()):
        return int(ref)
    name = _norm_key(ref)
    for r in (config or {}).get("persona_index") or []:
        if _norm_key(r.get("name")) == name:
            return _int(r.get("agent_id"))
    return None


def _injected_posts(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """[{key, agent_id, platform, source, round}] for event_config initial_posts and scheduled_events."""
    ev = (config or {}).get("event_config") or {}
    out = []
    for source, rows in (("initial_post", ev.get("initial_posts")), ("scheduled_event", ev.get("scheduled_events"))):
        for r in rows or []:
            if not isinstance(r, dict) or not r.get("content"):
                continue
            agent = r.get("poster_agent_id")
            if agent is None:
                agent = r.get("agent_id") if r.get("agent_id") is not None else r.get("agent")
            out.append({"key": _norm_key(r["content"]), "agent_id": _resolve_agent(agent, config),
                        "platform": (r.get("platform") or "").lower() or None, "source": source,
                        "round": _int(r.get("round")) if r.get("round") is not None else None})
    return out


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def _hour_label(hour: Any) -> Optional[str]:
    if hour is None:
        return None
    try:
        h = int(hour) % 24
    except (TypeError, ValueError):
        return str(hour)
    return f"{h:02d}:00"


def _build_platform(platform: str, data: Dict[str, List[Dict[str, Any]]], ridx: Dict[str, Any],
                    people: Dict[Any, Dict[str, Any]], injected: List[Dict[str, Any]],
                    max_posts: Optional[int]) -> Dict[str, Any]:
    user_to_agent = {}
    for u in data["users"]:
        user_to_agent[u.get("user_id")] = _int(u.get("agent_id") if u.get("agent_id") is not None else u.get("user_id"))

    def who(user_id: Any) -> Dict[str, Any]:
        aid = user_to_agent.get(user_id, _int(user_id))
        return people.get(aid) or _author(None, aid)

    followers: Dict[Any, Set[Any]] = defaultdict(set)
    for f in data["follows"]:
        followers[f.get("followee_id")].add(user_to_agent.get(f.get("follower_id"), f.get("follower_id")))

    # dedupe rows by id (the DB has one row per id, but be safe with replayed exports)
    posts_by_id: Dict[Any, Dict[str, Any]] = {}
    for p in data["posts"]:
        posts_by_id.setdefault(_int(p.get("post_id")), p)
    comments_by_id: Dict[Any, Dict[str, Any]] = {}
    for c in data["comments"]:
        comments_by_id.setdefault(_int(c.get("comment_id")), c)
    likes_by_post: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    seen_like: Set[Any] = set()
    for lk in data["likes"]:
        if lk.get("like_id") in seen_like:
            continue
        seen_like.add(lk.get("like_id"))
        likes_by_post[_int(lk.get("post_id"))].append(lk)
    dislikes_by_post: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    seen_dis: Set[Any] = set()
    for dk in data["dislikes"]:
        if dk.get("dislike_id") in seen_dis:
            continue
        seen_dis.add(dk.get("dislike_id"))
        dislikes_by_post[_int(dk.get("post_id"))].append(dk)
    clikes: Counter = Counter(_int(cl.get("comment_id")) for cl in data["comment_likes"])
    comments_by_post: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for cid, c in comments_by_id.items():
        comments_by_post[_int(c.get("post_id"))].append(c)
    children: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for pid, p in posts_by_id.items():
        if p.get("original_post_id") is not None:
            children[_int(p.get("original_post_id"))].append(p)

    rounds_meta = ridx.get("rounds") or {}
    injected_keys = {(i["key"], i["agent_id"]) for i in injected if i["platform"] in (None, platform)}
    injected_any = {i["key"] for i in injected if i["platform"] in (None, platform)}
    injected_source = {i["key"]: i["source"] for i in injected if i["platform"] in (None, platform)}

    def post_round(p: Dict[str, Any]) -> Optional[int]:
        pid = _int(p.get("post_id"))
        aid = user_to_agent.get(p.get("user_id"), _int(p.get("user_id")))
        text = p.get("quote_content") if p.get("quote_content") else p.get("content")
        found = [r for r in (ridx["posts"].get(pid), ridx["post_keys"].get((aid, _norm_key(text)))) if r is not None]
        return min(found) if found else None

    views: Dict[Any, Dict[str, Any]] = {}
    for pid, p in posts_by_id.items():
        author = who(p.get("user_id"))
        aid = author["agent_id"]
        orig_id = _int(p.get("original_post_id")) if p.get("original_post_id") is not None else None
        is_quote = orig_id is not None and bool(p.get("quote_content"))
        is_repost = orig_id is not None and not is_quote
        kind = "quote" if is_quote else "repost" if is_repost else "post"
        content = p.get("quote_content") if is_quote else ("" if is_repost else (p.get("content") or ""))
        orig = posts_by_id.get(orig_id) if orig_id is not None else None
        quote_content = None
        original = None
        if orig_id is not None:
            quote_content = (orig.get("content") if orig else p.get("content")) or ""
            original = {"post_id": orig_id, "author": who(orig.get("user_id")) if orig else _author(None, None, "unknown")}
        key = _norm_key(content)
        is_brand = (kind == "post" and ((key, aid) in injected_keys or key in injected_any)) or author.get("kind") == "community"
        rnd = post_round(p)
        comments = []
        for c in sorted(comments_by_post.get(pid, []), key=lambda c: (_created_key(c.get("created_at")), _int(c.get("comment_id")) or 0)):
            cid = _int(c.get("comment_id"))
            crnd = ridx["comments"].get(cid)
            comments.append({"comment_id": cid, "author": who(c.get("user_id")), "content": c.get("content") or "",
                             "round": crnd, "hour": _hour_label(rounds_meta.get(crnd)) if crnd is not None else None,
                             "likes": max(int(c.get("num_likes") or 0), clikes.get(cid, 0)),
                             "sentiment": sentiment_label(c.get("content"))})
        likers = [who(lk.get("user_id")) for lk in likes_by_post.get(pid, [])]
        dislikers = [who(dk.get("user_id")) for dk in dislikes_by_post.get(pid, [])]
        quotes = [_int(ch.get("post_id")) for ch in children.get(pid, []) if ch.get("quote_content")]
        reposters = [who(ch.get("user_id")) for ch in children.get(pid, []) if not ch.get("quote_content")]
        quoters = [who(ch.get("user_id")) for ch in children.get(pid, []) if ch.get("quote_content")]
        likes_n = max(len(likers), int(p.get("num_likes") or 0))
        dislikes_n = max(len(dislikers), int(p.get("num_dislikes") or 0))
        engagers = likers + dislikers + [c["author"] for c in comments] + reposters + quoters
        by_segment: Counter = Counter((e.get("segment") or "unknown") for e in engagers)
        by_country: Counter = Counter((e.get("country") or "unknown") for e in engagers)
        reach: Set[Any] = set(followers.get(p.get("user_id"), set()))
        for e in engagers:
            reach.add(e["agent_id"])
        for r in reposters + quoters:
            for uid, a in user_to_agent.items():
                if a == r["agent_id"]:
                    reach |= followers.get(uid, set())
        reach.discard(aid)
        reply_texts = [c["content"] for c in comments] + [ch.get("quote_content") or "" for ch in children.get(pid, []) if ch.get("quote_content")]
        reply_sent = Counter(sentiment_label(t) for t in reply_texts)
        views[pid] = {
            "post_id": pid, "platform": platform, "kind": kind, "author": author, "round": rnd,
            "hour": _hour_label(rounds_meta.get(rnd)) if rnd is not None else None,
            "created_at": p.get("created_at"), "content": content, "is_brand": bool(is_brand),
            "brand_source": injected_source.get(key) if is_brand and kind == "post" and key in injected_source else ("community" if is_brand else None),
            "quote_content": quote_content, "original": original,
            "likes": likes_n, "dislikes": dislikes_n, "likers": likers, "reposts": len(reposters), "quotes": quotes,
            "comments": comments,
            "engagement": {"by_segment": dict(by_segment.most_common()), "by_country": dict(by_country.most_common())},
            "reach_proxy": len(reach),
            "reply_sentiment": {"pos": reply_sent.get("pos", 0), "neg": reply_sent.get("neg", 0), "neu": reply_sent.get("neu", 0)},
            "sentiment": sentiment_label(content),
            "score": likes_n + 2 * len(quotes) + len(reposters) + 2 * len(comments) - dislikes_n,
        }

    ordered = sorted(views.values(), key=lambda v: (v["round"] if v["round"] is not None else 10 ** 9,
                                                   _created_key(v["created_at"]), v["post_id"] if isinstance(v["post_id"], int) else 0))
    total = len(ordered)
    if max_posts is not None and total > max_posts:
        ordered = ordered[:max_posts]

    # rounds
    round_views: List[Dict[str, Any]] = []
    all_rounds = set(r for r in rounds_meta if r is not None)
    all_rounds |= {v["round"] for v in views.values() if v["round"] is not None}
    all_rounds |= {c["round"] for v in views.values() for c in v["comments"] if c["round"] is not None}
    likes_per_round: Counter = Counter(r for r in ridx["likes"].values() if r is not None)
    for rnd in sorted(all_rounds):
        in_round = [v for v in views.values() if v["round"] == rnd]
        comments_in = [c for v in views.values() for c in v["comments"] if c["round"] == rnd]
        brand_replies = Counter(c["sentiment"] for v in views.values() if v["is_brand"] for c in v["comments"] if c["round"] == rnd)
        for v in in_round:
            if v["kind"] == "quote" and v["original"] and views.get(v["original"]["post_id"], {}).get("is_brand"):
                brand_replies[v["sentiment"]] += 1
        top = sorted(in_round, key=lambda v: (-v["score"], v["post_id"] if isinstance(v["post_id"], int) else 0))[:3]
        round_views.append({"round": rnd, "hour": _hour_label(rounds_meta.get(rnd)),
                            "posts": len(in_round), "comments": len(comments_in), "likes": likes_per_round.get(rnd, 0),
                            "top_posts": [t["post_id"] for t in top],
                            "brand_sentiment": {"pos": brand_replies.get("pos", 0), "neg": brand_replies.get("neg", 0),
                                                "neu": brand_replies.get("neu", 0)}})
    return {"posts": ordered, "rounds": round_views, "total_posts": total, "truncated": total > len(ordered),
            "rounds_known": bool(ridx.get("available")), "comments": sum(len(v["comments"]) for v in views.values()),
            "likes": sum(v["likes"] for v in views.values())}


def _best_worst(post: Dict[str, Any], platform_posts: Dict[Any, Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    replies = [{"author": c["author"], "content": c["content"], "sentiment": c["sentiment"], "score": sentiment_score(c["content"])}
               for c in post["comments"]]
    for qid in post.get("quotes") or []:
        q = platform_posts.get(qid)
        if q:
            replies.append({"author": q["author"], "content": q["content"], "sentiment": q["sentiment"], "score": sentiment_score(q["content"])})
    if not replies:
        return None, None
    best = max(replies, key=lambda r: r["score"])
    worst = min(replies, key=lambda r: r["score"])
    strip = lambda r: {"author": r["author"], "content": r["content"], "sentiment": r["sentiment"]}  # noqa: E731
    return strip(best), (strip(worst) if worst is not best else None)


def build_feed_story(sim_dir: str, config: Dict[str, Any], max_posts: Optional[int] = 300) -> Dict[str, Any]:
    """The whole story for one simulation folder. Platforms without a database are skipped."""
    config = config or {}
    users: List[Dict[str, Any]] = []
    loaded: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for platform in PLATFORMS:
        path = os.path.join(sim_dir, DB_FILES[platform])
        if os.path.exists(path):
            loaded[platform] = load_platform(path)
            users.extend(loaded[platform]["users"])
    people = _people(config, users)
    injected = _injected_posts(config)
    platforms: Dict[str, Any] = {}
    brand_posts: List[Dict[str, Any]] = []
    for platform, data in loaded.items():
        ridx = round_index(sim_dir, platform)
        pv = _build_platform(platform, data, ridx, people, injected, max_posts)
        platforms[platform] = pv
        by_id = {v["post_id"]: v for v in pv["posts"]}
        for v in pv["posts"]:
            if v["is_brand"]:
                best, worst = _best_worst(v, by_id)
                brand_posts.append({**v, "source": v.get("brand_source") or "injected", "best_reply": best, "worst_reply": worst})
    return {"platforms": platforms, "brand_posts": brand_posts,
            "people": {str(aid): a for aid, a in sorted(people.items(), key=lambda kv: str(kv[0]))},
            "sentiment_method": SENTIMENT_METHOD, "max_posts": max_posts,
            "generated_at": datetime.now().isoformat(timespec="seconds")}


# --------------------------------------------------------------------------
# Knowledge-graph overlay: who talks about which entity
# --------------------------------------------------------------------------

def mention_edges(feed_story: Dict[str, Any], graph_nodes: List[Dict[str, Any]], min_name_len: int = 3) -> List[Dict[str, Any]]:
    """Extra graph edges persona -> MENTIONS -> entity for every graph node whose name appears
    (whole word, case-insensitive) in that persona's posts or comments. Persona node ids follow
    feed_view.augment_graph: the graph node with the same name if one exists, else mm_p<agent_id>."""
    texts: Dict[Any, List[str]] = defaultdict(list)
    names: Dict[Any, str] = {}
    for pv in (feed_story.get("platforms") or {}).values():
        for v in pv.get("posts") or []:
            a = v.get("author") or {}
            if a.get("kind") == "persona" and v.get("content"):
                texts[a["agent_id"]].append(str(v["content"]))
                names[a["agent_id"]] = a.get("name") or ""
            for c in v.get("comments") or []:
                ca = c.get("author") or {}
                if ca.get("kind") == "persona" and c.get("content"):
                    texts[ca["agent_id"]].append(str(c["content"]))
                    names[ca["agent_id"]] = ca.get("name") or ""
    if not texts:
        return []
    by_name = {_norm_key(n.get("name")): n.get("uuid") for n in graph_nodes if n.get("name") and n.get("uuid")}
    targets = []
    for n in graph_nodes:
        name = str(n.get("name") or "").strip()
        if len(name) < min_name_len or not n.get("uuid"):
            continue
        labels = {str(l) for l in (n.get("labels") or [])}
        if labels & {"Persona", "Segment", "Country", "Community"}:
            continue
        targets.append((n["uuid"], name, re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.IGNORECASE)))
    edges: List[Dict[str, Any]] = []
    for aid, chunks in texts.items():
        blob = "\n".join(chunks)
        pname = names.get(aid) or f"person {aid}"
        src = by_name.get(_norm_key(pname)) or f"mm_p{aid}"
        for uuid, name, rx in targets:
            if uuid == src or _norm_key(name) == _norm_key(pname):
                continue
            n = len(rx.findall(blob))
            if n:
                edges.append({"uuid": f"mm_m{len(edges)}_{aid}", "name": "MENTIONS",
                              "fact": f"{pname} mentions {name} in {n} post{'s' if n != 1 else ''} or comment{'s' if n != 1 else ''}",
                              "source_node_uuid": src, "target_node_uuid": uuid, "attributes": {"count": n}})
    return edges
