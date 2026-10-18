"""Real-people grounding: what people actually say about a product, a category or a competitor, from public,
keyless sources, cached in the scenario folder and turned into (1) a seed document with themes and quotes,
(2) a voice store the personas and feeds draw on, (3) evidence for the report and the test ideas.

Sources (no logins, polite rate limits, every quote keeps its link):
  - Hacker News (Algolia API): stories and comments
  - App Store (iTunes search + customer-review RSS): ratings and reviews per country
  - Reddit (public JSON): tried with a browser user agent; Reddit often blocks data-centre and CLI traffic,
    so a block is reported, not hidden, and the skill tells the agent to use its own browser for Reddit
  - any web page (landing page, review page, forum thread): readable text

Sentiment is a word-list heuristic (labelled as such). Nothing here calls the model; `summarize()` groups
quotes into themes by keyword overlap so the output is useful even offline.
"""

import json
import os
import re
import time
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional

from ..utils.logger import get_logger
from .product_profile import html_to_text

logger = get_logger('mirofish.research')
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 MarketMirror/0.3"
POS = {"love", "great", "good", "easy", "best", "works", "helpful", "worth", "recommend", "amazing", "perfect", "finally", "nice", "happy", "useful"}
NEG = {"scam", "bad", "worst", "hate", "broken", "expensive", "useless", "cancel", "refund", "crash", "slow", "bug", "ads", "spam", "annoying",
       "disappointed", "terrible", "waste", "charged", "fake", "doesn't", "dont", "won't", "never"}


# --------------------------------------------------------------------------
# HTTP (one place, so tests can fake it)
# --------------------------------------------------------------------------

def _get(url: str, timeout: float = 20, params: Optional[Dict[str, Any]] = None, json_: bool = True) -> Any:
    import requests
    r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": UA, "Accept": "application/json,text/html;q=0.9"})
    r.raise_for_status()
    if json_:
        ctype = r.headers.get("content-type", "")
        if "json" not in ctype and not r.text.lstrip().startswith(("{", "[")):
            raise ValueError(f"not JSON ({ctype.split(';')[0] or 'unknown type'}): the source is blocking this client")
        return r.json()
    return r.text


def sentiment(text: str) -> str:
    words = set(re.findall(r"[a-z']+", (text or "").lower()))
    p, n = len(words & POS), len(words & NEG)
    return "pos" if p > n else "neg" if n > p else "neu"


def _quote(source: str, text: str, url: str, author: str = "", date: str = "", score: Any = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return {"source": source, "text": text[:600], "url": url, "author": str(author or "")[:60], "date": str(date or "")[:20],
            "score": score, "sentiment": sentiment(text), **(extra or {})}


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------

def hacker_news(query: str, limit: int = 30, get: Callable = _get) -> List[Dict[str, Any]]:
    out = []
    for tags in ("story", "comment"):
        try:
            data = get("https://hn.algolia.com/api/v1/search", params={"query": query, "tags": tags, "hitsPerPage": limit})
        except Exception as e:  # noqa: BLE001
            logger.warning(f"hacker news {tags} failed: {e}")
            continue
        for h in data.get("hits") or []:
            text = h.get("comment_text") or h.get("story_text") or h.get("title") or ""
            text = html_to_text(text) if "<" in text else text
            url = f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            out.append(_quote("hackernews", text, url, h.get("author"), (h.get("created_at") or "")[:10], h.get("points") or h.get("num_comments"),
                              {"title": h.get("story_title") or h.get("title")}))
        time.sleep(0.3)
    return [q for q in out if len(q["text"]) > 20]


def app_store(query: str, country: str = "us", limit_apps: int = 3, reviews_per_app: int = 30, get: Callable = _get) -> List[Dict[str, Any]]:
    out = []
    try:
        data = get("https://itunes.apple.com/search", params={"term": query, "entity": "software", "limit": limit_apps, "country": country})
    except Exception as e:  # noqa: BLE001
        logger.warning(f"app store search failed: {e}")
        return out
    for app in data.get("results") or []:
        app_id, name = app.get("trackId"), app.get("trackName")
        out.append(_quote("appstore", f"{name}: {app.get('description') or ''}"[:400], app.get("trackViewUrl") or "", app.get("sellerName"),
                          (app.get("currentVersionReleaseDate") or "")[:10], app.get("averageUserRating"),
                          {"kind": "listing", "app": name, "rating_count": app.get("userRatingCount"), "price": app.get("formattedPrice")}))
        try:
            feed = get(f"https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortBy=mostRecent/json")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"app store reviews for {name} failed: {e}")
            continue
        entries = (feed.get("feed") or {}).get("entry") or []
        if isinstance(entries, dict):
            entries = [entries]
        for e in entries[:reviews_per_app]:
            text = (e.get("content") or {}).get("label") or ""
            title = (e.get("title") or {}).get("label") or ""
            rating = (e.get("im:rating") or {}).get("label")
            out.append(_quote("appstore", f"{title}. {text}" if title else text, app.get("trackViewUrl") or "", (e.get("author") or {}).get("name", {}).get("label"),
                              (e.get("updated") or {}).get("label", "")[:10], int(rating) if str(rating).isdigit() else None, {"kind": "review", "app": name}))
        time.sleep(0.5)
    return out


def reddit(query: str, subreddit: Optional[str] = None, limit: int = 30, get: Callable = _get) -> Dict[str, Any]:
    """Public search JSON. Returns {"quotes": [...], "blocked": bool, "note": ...}."""
    base = f"https://www.reddit.com/r/{subreddit}/search.json" if subreddit else "https://www.reddit.com/search.json"
    params = {"q": query, "limit": limit, "sort": "relevance", "t": "year"}
    if subreddit:
        params["restrict_sr"] = 1
    try:
        data = get(base, params=params)
    except Exception as e:  # noqa: BLE001
        return {"quotes": [], "blocked": True, "note": f"Reddit did not answer this client ({str(e)[:80]}); use the agent's browser or the official API for Reddit"}
    out = []
    for ch in ((data.get("data") or {}).get("children") or []):
        d = ch.get("data") or {}
        text = f"{d.get('title') or ''}. {d.get('selftext') or ''}".strip(". ")
        out.append(_quote("reddit", text, "https://www.reddit.com" + (d.get("permalink") or ""), d.get("author"),
                          time.strftime("%Y-%m-%d", time.gmtime(d.get("created_utc") or 0)), d.get("score"),
                          {"subreddit": d.get("subreddit"), "comments": d.get("num_comments")}))
    return {"quotes": [q for q in out if len(q["text"]) > 20], "blocked": False, "note": ""}


def web_page(url: str, get: Callable = _get) -> Optional[Dict[str, Any]]:
    try:
        text = get(url, json_=False)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"page {url} failed: {e}")
        return None
    text = html_to_text(text) if "<" in text[:2000] else text
    return _quote("web", text[:4000], url, "", "", None, {"kind": "page"})


# --------------------------------------------------------------------------
# Summarise
# --------------------------------------------------------------------------

STOP = set("the a an and or of to in for on with is are was were be it this that i you we they my our your not no but so as at by from have has had do does did "
           "can could would should will just very really also than then there here what which who when how all any some more most other same such only into out up "
           "about over after before again off get got like one two app apps use using used".split())


def themes(quotes: List[Dict[str, Any]], n: int = 8) -> List[Dict[str, Any]]:
    """Keyword themes: the most frequent content words across quotes, each with its share, sentiment mix and examples."""
    docs = []
    for q in quotes:
        words = {w for w in re.findall(r"[a-z]{4,}", q["text"].lower()) if w not in STOP}
        docs.append(words)
    freq = Counter(w for ws in docs for w in ws)
    out = []
    for word, count in freq.most_common(40):
        if count < max(2, len(quotes) // 15):
            continue
        hits = [q for q, ws in zip(quotes, docs) if word in ws]
        sent = Counter(q["sentiment"] for q in hits)
        out.append({"theme": word, "mentions": count, "share_pct": round(100.0 * count / max(1, len(quotes)), 1),
                    "sentiment": dict(sent), "examples": [{"text": q["text"][:220], "url": q["url"], "source": q["source"]} for q in hits[:3]]})
        if len(out) >= n:
            break
    return out


def summarize(query: str, quotes: List[Dict[str, Any]], notes: List[str]) -> Dict[str, Any]:
    by_source = Counter(q["source"] for q in quotes)
    sent = Counter(q["sentiment"] for q in quotes)
    ratings = [q["score"] for q in quotes if q.get("kind") == "review" and isinstance(q.get("score"), int)]
    th = themes(quotes)
    top = sorted(quotes, key=lambda q: -(q.get("score") or 0) if isinstance(q.get("score"), (int, float)) else 0)[:8]
    return {"query": query, "quotes": len(quotes), "by_source": dict(by_source), "sentiment": dict(sent),
            "sentiment_method": "word list, not a model",
            "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None, "ratings": len(ratings),
            "themes": th, "top_quotes": [{k: q.get(k) for k in ("source", "text", "url", "score", "sentiment", "app")} for q in top],
            "notes": notes, "fetched_at": time.strftime("%Y-%m-%d %H:%M")}


def render_markdown(summary: Dict[str, Any]) -> str:
    out = [f"# What real people say about: {summary['query']}", "",
           f"{summary['quotes']} quotes from {', '.join(f'{k} ({v})' for k, v in summary['by_source'].items())}, fetched {summary['fetched_at']}. "
           f"Sentiment counts come from a word list ({summary['sentiment']}).", ""]
    if summary.get("avg_rating") is not None:
        out += [f"Average app-store rating across {summary['ratings']} recent reviews: {summary['avg_rating']} / 5.", ""]
    if summary.get("themes"):
        out += ["## Themes", ""]
        for t in summary["themes"]:
            out += [f"### {t['theme']} ({t['mentions']} mentions, {t['share_pct']}%; {t['sentiment']})", ""]
            out += [f"- \"{e['text']}\" ({e['source']}, {e['url']})" for e in t["examples"]] + [""]
    if summary.get("top_quotes"):
        out += ["## Most-upvoted or most-rated", ""] + [f"- [{q['source']}{(' ' + q['app']) if q.get('app') else ''}] \"{q['text'][:300]}\" ({q['url']})" for q in summary["top_quotes"]] + [""]
    if summary.get("notes"):
        out += ["## Notes", ""] + [f"- {n}" for n in summary["notes"]] + [""]
    return "\n".join(out)


# --------------------------------------------------------------------------
# Voice store: quotes by country / role for personas and feeds
# --------------------------------------------------------------------------

def voices(quotes: List[Dict[str, Any]], country_hint: str = "") -> List[Dict[str, Any]]:
    """Short, first-person quotes real people wrote, for persona interviews and organic feeds."""
    out = []
    for q in quotes:
        t = q["text"]
        if 30 <= len(t) <= 400 and q.get("kind") != "listing" and q.get("kind") != "page":
            out.append({"text": t, "source": q["source"], "url": q["url"], "sentiment": q["sentiment"], "country": country_hint,
                        "app": q.get("app"), "rating": q.get("score") if q.get("kind") == "review" else None})
    return out[:300]


def pick_voices(store: List[Dict[str, Any]], n: int = 4, country: str = "", sentiment_mix: bool = True) -> List[Dict[str, Any]]:
    """A few real voices for a prompt: prefer the country, keep both positive and negative."""
    pool = [v for v in store if not country or not v.get("country") or v["country"].lower() == country.lower()] or store
    if not pool:
        return []
    if not sentiment_mix:
        return pool[:n]
    by = defaultdict(list)
    for v in pool:
        by[v["sentiment"]].append(v)
    out = []
    for s in ("neg", "pos", "neu"):
        out += by[s][: max(1, n // 2)]
    return out[:n]


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------

def run(query: str, sources: List[str], out_dir: str, country: str = "us", subreddits: Optional[List[str]] = None,
        urls: Optional[List[str]] = None, limit: int = 30, get: Callable = _get, log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    quotes: List[Dict[str, Any]] = []
    notes: List[str] = []
    say = log or (lambda m: None)
    if "hn" in sources or "hackernews" in sources:
        q = hacker_news(query, limit, get)
        say(f"research: hacker news {len(q)} quotes")
        quotes += q
    if "appstore" in sources or "apps" in sources:
        q = app_store(query, country.lower()[:2], 3, limit, get)
        say(f"research: app store {len(q)} listings/reviews ({country})")
        quotes += q
    if "reddit" in sources:
        for sub in (subreddits or [None]):
            r = reddit(query, sub, limit, get)
            if r["blocked"]:
                notes.append(r["note"])
                say(f"research: reddit blocked ({sub or 'all'})")
                break
            say(f"research: reddit r/{sub or 'all'} {len(r['quotes'])} posts")
            quotes += r["quotes"]
            time.sleep(1.0)
    for u in urls or []:
        p = web_page(u, get)
        if p:
            quotes.append(p)
            say(f"research: page {u}")
    seen, uniq = set(), []
    for q in quotes:
        key = q["text"][:120].lower()
        if key not in seen:
            seen.add(key)
            uniq.append(q)
    summary = summarize(query, uniq, notes)
    with open(os.path.join(out_dir, "research.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "quotes": uniq}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "research.md"), "w", encoding="utf-8") as f:
        f.write(render_markdown(summary))
    vs = voices(uniq, country)
    with open(os.path.join(out_dir, "voices.json"), "w", encoding="utf-8") as f:
        json.dump(vs, f, ensure_ascii=False, indent=2)
    return {"summary": summary, "files": {"json": os.path.join(out_dir, "research.json"), "md": os.path.join(out_dir, "research.md"),
                                          "voices": os.path.join(out_dir, "voices.json")}, "voices": len(vs)}
