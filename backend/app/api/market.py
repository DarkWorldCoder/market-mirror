"""
MarketMirror API: marketing tests that run on a prepared simulation's personas.

    POST /api/simulation/feed-test             {simulation_id, creatives:[...], organic_per_feed?, max_personas?, parallel?}
    POST /api/simulation/market-task/status    {task_id}
    GET  /api/simulation/<simulation_id>/feed-test
    POST /api/simulation/analyst-panel         {simulation_id, material:{...}, analysts?, brief?}
    GET  /api/simulation/<simulation_id>/analyst-panel
    POST /api/simulation/ssr                   {items:[{id, scale, text}], temperature?}  (synchronous)

The feed test takes `seeds` (repeat with different seeds and report the spread)
or `seed` (one run with that seed).

Long work runs in a background thread tracked by the shared TaskManager; results
are saved as JSON in the simulation folder so exports can pick them up later.
"""

import json
import os
import threading
import traceback

from flask import jsonify, request

from . import simulation_bp
from ..config import Config
from ..models.task import TaskManager, TaskStatus
from ..services.simulation_manager import SimulationManager
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.market')

RESULT_FILES = {"feed-test": "feed_test.json", "analyst-panel": "analyst_panel.json",
                "market-report": "market_report.json", "pitch": "pitch.json"}


def _client():
    from openai import OpenAI
    if not Config.LLM_API_KEY:
        raise ValueError("LLM_API_KEY is not configured")
    return OpenAI(api_key=Config.LLM_API_KEY, base_url=Config.LLM_BASE_URL)


def _sim_dir(simulation_id: str) -> str:
    manager = SimulationManager()
    if not manager.get_simulation(simulation_id):
        raise LookupError(f"simulation not found: {simulation_id}")
    return manager._get_simulation_dir(simulation_id)


def _people(simulation_id: str):
    from ..services.feed_test import people_from_simulation
    manager = SimulationManager()
    cfg = manager.get_simulation_config(simulation_id) or {}
    profiles = []
    for platform in ("reddit", "twitter"):
        try:
            profiles = manager.get_profiles(simulation_id, platform)
        except ValueError:
            profiles = []
        if profiles:
            break
    return people_from_simulation(profiles, cfg.get("persona_index") or []), cfg


def _profile(simulation_id: str):
    """The project's product profile (or None) for a simulation."""
    try:
        from ..models.project import ProjectManager
        from ..services import product_profile as pp
        state = SimulationManager().get_simulation(simulation_id)
        pid = getattr(state, "project_id", None) if state else None
        return pp.load(ProjectManager._get_project_dir(pid)) if pid else None
    except Exception:  # noqa: BLE001 - optional
        return None


def _start(kind: str, simulation_id: str, work):
    tm = TaskManager()
    task_id = tm.create_task(task_type=f"market_{kind}", metadata={"simulation_id": simulation_id})

    def run():
        try:
            tm.update_task(task_id, status=TaskStatus.PROCESSING, progress=1, message=f"{kind} started")
            result = work(lambda done, total: tm.update_task(
                task_id, progress=int(100 * done / max(total, 1)), message=f"{kind}: {done}/{total}"))
            path = os.path.join(_sim_dir(simulation_id), RESULT_FILES[kind])
            with open(path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            tm.complete_task(task_id, {"simulation_id": simulation_id, "file": path})
        except Exception as e:  # noqa: BLE001 - reported through the task
            logger.error(f"{kind} failed: {e}\n{traceback.format_exc()}")
            tm.fail_task(task_id, str(e))

    threading.Thread(target=run, daemon=True).start()
    return task_id


@simulation_bp.route('/feed-test', methods=['POST'])
def start_feed_test():
    from ..services import feed_test
    data = request.get_json() or {}
    sid = data.get("simulation_id")
    try:
        _sim_dir(sid or "")
        creatives = feed_test.normalize_creatives(data.get("creatives"))
        landing = feed_test.normalize_landing(data.get("landing"))
        people, cfg = _people(sid)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    if not people:
        return jsonify({"success": False, "error": "no personas yet: prepare the simulation first"}), 400
    try:
        seed = int(data.get("seed") or 5)
        n_seeds = max(1, min(int(data.get("seeds") or 1), 10))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "seed and seeds must be integers"}), 400
    limit = data.get("max_personas")
    if isinstance(limit, int) and limit > 0:
        people = people[:limit]
    organic = max(2, min(int(data.get("organic_per_feed") or 5), 12))
    parallel = max(1, min(int(data.get("parallel") or 8), 32))
    context = json.dumps((cfg.get("persona_spec") or {}).get("segments") or [], ensure_ascii=False)[:2000]
    prof = _profile(sid)
    if prof:
        from ..services import product_profile as pp
        context = pp.render_text(prof, 1500) + "\n" + context

    def work(progress):
        return feed_test.run_multi_seed(_client(), Config.LLM_MODEL_NAME, creatives, people,
                                        seeds=feed_test.seed_list(seed, n_seeds), context=context,
                                        organic_per_feed=organic, parallel=parallel, progress=progress,
                                        waves=int(data.get("waves") or 3), landing=landing,
                                        exposures=int(data.get("exposures") or 2),
                                        attention_gate=data.get("attention_gate", True) is not False,
                                        benchmarks=data.get("benchmarks") if isinstance(data.get("benchmarks"), dict) else None)

    task_id = _start("feed-test", sid, work)
    feeds = len(feed_test.assign(creatives, people))
    return jsonify({"success": True, "data": {"task_id": task_id, "simulation_id": sid, "personas": len(people),
                                              "feeds": feeds, "creatives": len(creatives), "seeds": n_seeds}})


@simulation_bp.route('/ssr', methods=['POST'])
def semantic_similarity_rating():
    """Map free-text survey answers to 5-point rating distributions (arXiv 2510.08338)."""
    from ..services import ssr
    data = request.get_json() or {}
    items = data.get("items")
    if not isinstance(items, list) or len(items) > 5000:
        return jsonify({"success": False, "error": "items must be a list of {id, scale, text} (max 5000)"}), 400
    rows = [it if isinstance(it, dict) else {} for it in items]
    try:
        temperature = float(data.get("temperature") or 1.0)
        rated = ssr.rate([(str(r.get("scale") or ""), r.get("text")) for r in rows], temperature=temperature)
    except ssr.SSRUnavailable as e:
        return jsonify({"success": False, "error": str(e)}), 503
    except (TypeError, ValueError) as e:
        return jsonify({"success": False, "error": str(e)}), 400
    embedder = ssr.get_embedder()
    return jsonify({"success": True, "data": {
        "model": getattr(embedder, "model_name", None), "anchors_version": ssr.ANCHORS_VERSION,
        "scales": list(ssr.SCALES), "temperature": temperature,
        "results": [{"id": r.get("id"), "scale": r.get("scale"), **res} for r, res in zip(rows, rated) if res]}})


@simulation_bp.route('/analyst-panel', methods=['POST'])
def start_analyst_panel():
    from ..services import analyst_panel
    data = request.get_json() or {}
    sid = data.get("simulation_id")
    try:
        _sim_dir(sid or "")
        material = analyst_panel.normalize_material(data.get("material"))
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    analysts = max(2, min(int(data.get("analysts") or 5), 9))
    brief = str(data.get("brief") or "")[:4000]

    def work(progress):
        return analyst_panel.run_panel(_client(), Config.LLM_MODEL_NAME, material, brief, analysts, progress=progress)

    task_id = _start("analyst-panel", sid, work)
    return jsonify({"success": True, "data": {"task_id": task_id, "simulation_id": sid, "analysts": analysts}})


@simulation_bp.route('/pitch', methods=['POST'])
def start_pitch():
    """POST {simulation_id, script, rebuttals?: {objection_type: text, "*": generic} | text, product?, channel?,
    segment?, agents?[], batch?} -> task. Pitches every simulated buyer (interview API, so the environment must be
    alive), then answers objections with the matching rebuttal. Result: pitch.json (GET /<sid>/pitch)."""
    from ..services import pitch as pitch_svc
    from ..services.simulation_runner import SimulationRunner
    data = request.get_json() or {}
    sid = data.get("simulation_id")
    script = str(data.get("script") or "").strip()
    if not script:
        return jsonify({"success": False, "error": "script is required"}), 400
    try:
        people, cfg = _people(sid or "")
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    if data.get("segment"):
        people = [p for p in people if p.get("segment") == data["segment"]]
    if data.get("agents"):
        wanted = {int(a) for a in data["agents"]}
        people = [p for p in people if p["agent_id"] in wanted]
    if not people:
        return jsonify({"success": False, "error": "no simulated people match (prepare the simulation first)"}), 400
    rebuttals = pitch_svc.parse_rebuttals(data.get("rebuttals"))
    platform = data.get("platform") or ("reddit" if (cfg.get("enable_reddit", True)) else "twitter")
    timeout = float(data.get("timeout") or 600)
    batch = max(1, min(int(data.get("batch") or 40), 64))

    def interview_batch(items):
        res = SimulationRunner.interview_agents_batch(
            sid, [{"agent_id": it["agent_id"], "prompt": it["prompt"], "platform": platform} for it in items],
            platform=platform, timeout=timeout)
        out = {}
        results = (res.get("result") or {}).get("results") if isinstance(res.get("result"), dict) else None
        if isinstance(results, dict):
            results = list(results.values())
        for it in results or []:
            if isinstance(it, dict) and it.get("agent_id") is not None and it.get("response") not in (None, ""):
                resp = it["response"]
                out[int(it["agent_id"])] = json.dumps(resp, ensure_ascii=False) if isinstance(resp, (dict, list)) else str(resp)
        return out

    product = str(data.get("product") or "")
    if not product:
        prof = _profile(sid)
        product = (prof or {}).get("one_liner") or (prof or {}).get("name") or ""

    def work(progress):
        return pitch_svc.run(interview_batch, people, script, rebuttals, product,
                             str(data.get("channel") or "message"), batch=batch, progress=progress)

    task_id = _start("pitch", sid, work)
    return jsonify({"success": True, "data": {"task_id": task_id, "simulation_id": sid, "people": len(people),
                                              "rebuttals": sorted(rebuttals)}})


@simulation_bp.route('/calibrate', methods=['POST'])
def calibrate_panel():
    """POST {synthetic: [rows], real: [rows], key?} rows = {segment, country, gender, age, y in [0,1]}
    -> overlap, per-subgroup calibration, verdict, AIPW-corrected rate (synchronous, no LLM)."""
    from ..services import calibration
    data = request.get_json() or {}
    syn, real = data.get("synthetic") or [], data.get("real") or []
    if not isinstance(syn, list) or not isinstance(real, list) or not syn or not real:
        return jsonify({"success": False, "error": "synthetic and real rows are required"}), 400
    try:
        out = calibration.diagnose([r for r in syn if isinstance(r, dict) and "y" in r],
                                   [r for r in real if isinstance(r, dict) and "y" in r], str(data.get("key") or "segment"))
        out["field"] = data.get("field")
        return jsonify({"success": True, "data": out})
    except Exception as e:  # noqa: BLE001
        logger.error(f"calibrate failed: {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "error": str(e)}), 500


@simulation_bp.route('/ideas', methods=['POST'])
def generate_ideas():
    """POST {brand?, brief?, ads?: [rows from an ad-account export or a connected ads tool] | ads_summary?,
    run_summary?: summary.json of a run, n?} -> {ideas: [...], evidence: [...]} (synchronous, one LLM call).
    Proposes the next tests to run from what real ads and the simulation already showed."""
    from ..services import ideas as ideas_svc
    data = request.get_json() or {}
    try:
        evidence = ideas_svc.build_evidence(data.get("ads") or [], data.get("ads_summary") or {},
                                            data.get("run_summary") or {}, str(data.get("brief") or ""),
                                            profile=data.get("profile") if isinstance(data.get("profile"), dict) else None)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    if not evidence["signals"]:
        return jsonify({"success": False, "error": "nothing to reason from: pass ads rows, an ads summary or a run summary"}), 400
    try:
        out = ideas_svc.generate(_client(), Config.LLM_MODEL_NAME, evidence, str(data.get("brand") or ""),
                                 n=int(data.get("n") or 8))
        return jsonify({"success": True, "data": out})
    except Exception as e:  # noqa: BLE001
        logger.error(f"ideas failed: {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "error": str(e)}), 500


@simulation_bp.route('/market-report', methods=['POST'])
def start_market_report():
    """POST {simulation_id, material, brand?} -> background job writing market_report.json (plain-language report)."""
    from ..services import market_report
    data = request.get_json() or {}
    sid = data.get("simulation_id")
    material = data.get("material")
    try:
        _sim_dir(sid or "")
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    if not isinstance(material, dict) or not material:
        return jsonify({"success": False, "error": "material (the compact fact sheet) is required"}), 400
    brand = str(data.get("brand") or material.get("brand") or "")[:120]

    prof = _profile(sid)

    def work(progress):
        progress(1, 2)
        facts = market_report.compact_material(material) if "summary" in material else material
        if prof and isinstance(facts, dict) and "product" not in facts:
            facts["product"] = {k: prof.get(k) for k in ("name", "category", "one_liner", "offer", "pricing", "proofs",
                                                         "differentiators", "competitors", "likely_objections", "funnel_goal")}
        out = market_report.generate(_client(), Config.LLM_MODEL_NAME, facts, brand or None)
        progress(2, 2)
        return out

    task_id = _start("market-report", sid, work)
    return jsonify({"success": True, "data": {"task_id": task_id, "simulation_id": sid}})


@simulation_bp.route('/<simulation_id>/market-report', methods=['GET'], defaults={"kind": "market-report"})
def market_report_result(simulation_id: str, kind: str):
    return market_result(simulation_id, kind)


@simulation_bp.route('/market-task/status', methods=['POST'])
def market_task_status():
    task_id = (request.get_json() or {}).get("task_id")
    task = TaskManager().get_task(task_id) if task_id else None
    if not task:
        return jsonify({"success": False, "error": "task not found"}), 404
    return jsonify({"success": True, "data": task.to_dict()})


@simulation_bp.route('/<simulation_id>/feed-test', methods=['GET'], defaults={"kind": "feed-test"})
@simulation_bp.route('/<simulation_id>/analyst-panel', methods=['GET'], defaults={"kind": "analyst-panel"})
@simulation_bp.route('/<simulation_id>/pitch', methods=['GET'], defaults={"kind": "pitch"})
def market_result(simulation_id: str, kind: str):
    if kind not in RESULT_FILES:
        return jsonify({"success": False, "error": "not found"}), 404
    try:
        path = os.path.join(_sim_dir(simulation_id), RESULT_FILES[kind])
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    if not os.path.exists(path):
        return jsonify({"success": False, "error": f"no {kind} result yet"}), 404
    with open(path, encoding="utf-8") as f:
        return jsonify({"success": True, "data": json.load(f)})


# --------------------------------------------------------------------------
# Brand posts and scheduled events inside the simulation (MarketMirror)
# --------------------------------------------------------------------------

def _runner_status(sim_dir: str) -> str:
    try:
        with open(os.path.join(sim_dir, "run_state.json"), encoding="utf-8") as f:
            return str(json.load(f).get("runner_status") or "")
    except (OSError, ValueError):
        return ""


@simulation_bp.route('/<simulation_id>/events', methods=['PUT', 'GET'])
def simulation_events(simulation_id: str):
    """PUT {posts:[{agent, content, platform?}], events:[{round, agent, content, platform?, label?}]}
    writes event_config.initial_posts / scheduled_events into simulation_config.json. GET returns them."""
    import sys
    scripts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from event_schedule import normalize_events
    try:
        sim_dir = _sim_dir(simulation_id)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    cfg_path = os.path.join(sim_dir, "simulation_config.json")
    if not os.path.exists(cfg_path):
        return jsonify({"success": False, "error": "prepare the simulation first (no simulation_config.json)"}), 400
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    if request.method == 'GET':
        ev = cfg.get("event_config") or {}
        return jsonify({"success": True, "data": {"initial_posts": ev.get("initial_posts") or [],
                                                  "scheduled_events": ev.get("scheduled_events") or []}})
    if _runner_status(sim_dir) == "running":
        return jsonify({"success": False, "error": "simulation is running; stop it before changing events"}), 409
    data = request.get_json() or {}
    try:
        frag = normalize_events(cfg, data.get("posts"), data.get("events"))
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    ev = cfg.setdefault("event_config", {})
    if data.get("posts") is not None:
        ev["initial_posts"] = frag["initial_posts"] if data.get("replace", True) else (ev.get("initial_posts") or []) + frag["initial_posts"]
    if data.get("events") is not None:
        ev["scheduled_events"] = frag["scheduled_events"]
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return jsonify({"success": True, "data": {"initial_posts": ev.get("initial_posts") or [],
                                              "scheduled_events": ev.get("scheduled_events") or []}})


CAPTION_SYSTEM = (
    "You are a senior social media copywriter who writes platform-native posts and ad captions that real people "
    "in the target country would stop for. Write in the language mix the audience uses. Never invent statistics, "
    "awards or customer numbers. Return only valid JSON."
)


@simulation_bp.route('/captions', methods=['POST'])
def generate_captions():
    """POST {brief, platform, n?, audience?, objections?[], tone?, language?, brand?} -> {captions:[...]}
    Each caption: {hook, body, hashtags[], cta, format, why}. Usable as brand posts or feed-test creatives."""
    from ..services.persona_planner import parse_json_block
    from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text
    data = request.get_json() or {}
    brief = str(data.get("brief") or "").strip()
    if not brief:
        return jsonify({"success": False, "error": "brief is required"}), 400
    platform = str(data.get("platform") or "instagram").lower()
    n = max(1, min(int(data.get("n") or 6), 12))
    objections = [str(x) for x in (data.get("objections") or [])][:8]
    prompt = (
        f"Write {n} different {platform} posts/ad captions for this brief.\n\nBrief:\n{brief[:4000]}\n\n"
        f"Audience: {data.get('audience') or 'see brief'}\nLanguage: {data.get('language') or 'the audience\'s everyday mix'}\n"
        f"Tone: {data.get('tone') or 'natural for the platform'}\n"
        + (f"Objections real people raised that the captions should pre-empt: {'; '.join(objections)}\n" if objections else "")
        + f"\nRules for {platform}: " + {
            "instagram": "first line is the hook (under 8 words), 2-4 short lines, emoji ok, 3-6 hashtags, one clear CTA.",
            "facebook": "conversational, 2-5 sentences, one question people will answer in comments, CTA at the end.",
            "tiktok": "on-screen hook under 6 words plus a 15-second script in 3 beats, casual, no hashtags over 4.",
            "reddit": "honest, no marketing speak, a title under 90 chars and a body that gives real information, no hashtags.",
            "linkedin": "professional, a story or a number, line breaks, no hashtags over 3.",
            "x": "under 240 characters, punchy, one hashtag at most.",
        }.get(platform, "short and native to the platform.")
        + "\nMake them genuinely different angles (price, proof, fear of missing out, how-to, social proof, humour, question).\n"
        'Return JSON: {"captions": [{"angle": "...", "hook": "...", "body": "...", "hashtags": ["..."], "cta": "...", '
        '"format": "image|video|reel|carousel|text", "media": "what the image/video should show", "why": "one line"}]}'
    )
    try:
        resp = create_chat_completion(_client(), model=Config.LLM_MODEL_NAME, temperature=0.9, max_tokens=3500,
                                      messages=[{"role": "system", "content": CAPTION_SYSTEM},
                                                {"role": "user", "content": prompt}])
        parsed = parse_json_block(extract_chat_completion_text(resp))
        rows = parsed.get("captions") if isinstance(parsed, dict) else parsed
        caps = []
        for i, r in enumerate([x for x in (rows or []) if isinstance(x, dict)][:n]):
            hook, body = str(r.get("hook") or "").strip(), str(r.get("body") or "").strip()
            text = (hook + "\n" + body).strip() if hook and hook not in body else (body or hook)
            caps.append({"id": f"{platform[:2]}_{i + 1}", "platform": platform, "angle": str(r.get("angle") or "")[:60],
                         "hook": hook[:200], "body": body[:1500], "text": text[:1700],
                         "hashtags": [str(h).lstrip("#") for h in (r.get("hashtags") or [])][:8],
                         "cta": str(r.get("cta") or "")[:60], "format": str(r.get("format") or "image")[:20],
                         "media": str(r.get("media") or "")[:300], "why": str(r.get("why") or "")[:200]})
        return jsonify({"success": True, "data": {"platform": platform, "captions": caps}})
    except Exception as e:  # noqa: BLE001
        logger.error(f"captions failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
