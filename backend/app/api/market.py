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

from claude_cli import actuals
from ..services import predict as prediction

from . import simulation_bp
from ..config import Config
from ..models.task import TaskManager, TaskStatus
from ..services.simulation_manager import SimulationManager
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.market')

RESULT_FILES = {"feed-test": "feed_test.json", "analyst-panel": "analyst_panel.json",
                "market-report": "market_report.json", "pitch": "pitch.json", "email-test": "email_test.json",
                "website-test": "website_test.json", "thought-stream": "thought_stream.json"}


@simulation_bp.route('/website-test', methods=['POST'])
def start_website_test():
    """Run a bounded real-browser journey with the simulation's existing personas."""
    from ..services import website_test
    import uuid
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"success": False, "error": "request body must be an object"}), 400
    sid = data.get("simulation_id") or ""
    try:
        root = _sim_dir(sid)
        spec = website_test.normalize(data.get("spec"))
        people, _ = _people(sid)
        if not people:
            raise ValueError("prepare personas before testing a website")
    except LookupError as error:
        return jsonify({"success": False, "error": str(error)}), 404
    except (ValueError, TypeError) as error:
        return jsonify({"success": False, "error": str(error)}), 400
    run_id = "website_" + uuid.uuid4().hex[:12]
    def work(progress):
        client = _client().with_options(timeout=60, max_retries=1)
        result = website_test.run(client, Config.LLM_MODEL_NAME, people, spec,
                                  os.path.join(root, run_id), progress)
        result["run_id"] = run_id
        with open(result["files"]["result"], "w", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
        if result["status"] == "failed":
            raise RuntimeError("All browser sessions failed; inspect " + result["files"]["result"])
        return result
    return jsonify({"success": True, "data": {"task_id": _start("website-test", sid, work),
                                               "simulation_id": sid, "run_id": run_id}})


@simulation_bp.route('/<simulation_id>/website-test', methods=['GET'])
def get_website_test(simulation_id):
    try:
        root = _sim_dir(simulation_id)
        run_id = request.args.get("run_id")
        if run_id:
            if not __import__('re').fullmatch(r"website_[a-f0-9]{12}", run_id):
                raise ValueError("invalid website run_id")
            root = os.path.join(root, run_id)
        with open(os.path.join(root, "website_test.json"), encoding="utf-8") as source:
            return jsonify({"success": True, "data": json.load(source)})
    except (LookupError, FileNotFoundError) as error:
        return jsonify({"success": False, "error": str(error)}), 404
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 400


@simulation_bp.route('/actuals-import', methods=['POST'])
def import_actuals():
    """Normalize a local export with row-level validation and provenance."""
    data = request.get_json(silent=True) or {}
    try:
        result = actuals.normalize(str(data.get("file") or ""), str(data.get("source_type") or ""),
                                   data.get("mapping"), str(data.get("source") or ""),
                                   str(data.get("market") or ""), str(data.get("date") or ""),
                                   str(data.get("quality") or ""))
        out_dir = os.path.join(Config.UPLOAD_FOLDER, "actuals_imports")
        path = actuals.save(result, os.path.join(out_dir, f"actuals_{__import__('uuid').uuid4().hex[:12]}.json"))
        return jsonify({"success": True, "data": {"file": path, **result}})
    except (OSError, ValueError) as e:
        return jsonify({"success": False, "error": str(e)}), 400


@simulation_bp.route('/holdout-backtest', methods=['POST'])
def holdout_backtest():
    data = request.get_json(silent=True) or {}
    try:
        pairs = data.get("pairs")
        if not isinstance(pairs, list):
            raise ValueError("pairs must be an array")
        return jsonify({"success": True, "data": prediction.holdout_backtest(pairs)})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400


def _client():
    from openai import OpenAI
    if Config.LLM_POOL:
        pool = Config.get_model_pool()
        if pool.slots:
            return pool
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


def _voices(simulation_id: str):
    """voices.json of the simulation's project (from `research`), or None."""
    try:
        from ..models.project import ProjectManager
        state = SimulationManager().get_simulation(simulation_id)
        pid = getattr(state, "project_id", None) if state else None
        path = os.path.join(ProjectManager._get_project_dir(pid), "voices.json") if pid else ""
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:  # noqa: BLE001 - optional
        pass
    return None


MEMORY_EVENTS = {"feed-test": "events_from_feed_test", "email-test": "events_from_email_test", "pitch": "events_from_pitch"}


def _memory_scope(data) -> str:
    """Which behaviour-state scope a test reads and writes ("" = memory off). Study cells pass their own name."""
    scope = data.get("memory_scope")
    if scope is False or (scope is not None and str(scope).lower() in ("off", "none", "false")):
        return ""
    return str(scope or "default")[:80]


def _brand(simulation_id: str) -> str:
    prof = _profile(simulation_id) or {}
    return str(prof.get("name") or "the brand")[:60]


def _with_history(people, simulation_id: str, scope: str):
    """Copy of people with each person's memory block (what already happened to them) under "history"."""
    if not scope:
        return people
    from ..services import behavior_state
    try:
        sim_dir = _sim_dir(simulation_id)
    except LookupError:
        return people
    data = behavior_state.load(sim_dir)
    return [{**p, "history": behavior_state.prompt_block(sim_dir, p["agent_id"], scope, data=data)} for p in people]


def _record_memory(kind: str, simulation_id: str, result, scope: str) -> None:
    if not scope or kind not in MEMORY_EVENTS or not isinstance(result, dict):
        return
    from ..services import behavior_state
    try:
        events = getattr(behavior_state, MEMORY_EVENTS[kind])(result, _brand(simulation_id))
        n = behavior_state.record(_sim_dir(simulation_id), events, scope)
        result["memory"] = {"scope": scope, "events_recorded": n}
    except Exception as e:  # noqa: BLE001 - memory is an extra, never fails a test
        logger.warning(f"{kind}: behaviour memory not recorded: {e}")


def _start(kind: str, simulation_id: str, work, memory_scope: str = ""):
    tm = TaskManager()
    task_id = tm.create_task(task_type=f"market_{kind}", metadata={"simulation_id": simulation_id})

    def run():
        try:
            tm.update_task(task_id, status=TaskStatus.PROCESSING, progress=1, message=f"{kind} started")
            result = work(lambda done, total: tm.update_task(
                task_id, progress=int(100 * done / max(total, 1)), message=f"{kind}: {done}/{total}"))
            _record_memory(kind, simulation_id, result, memory_scope)
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
        competitor = feed_test.normalize_competitor(data.get("competitor"))
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

    voices = _voices(sid)
    scope = _memory_scope(data)
    people = _with_history(people, sid, scope)

    def work(progress):
        return feed_test.run_multi_seed(_client(), Config.LLM_MODEL_NAME, creatives, people,
                                        seeds=feed_test.seed_list(seed, n_seeds), context=context, voices=voices,
                                        organic_per_feed=organic, parallel=parallel, progress=progress,
                                        waves=int(data.get("waves") or 3), landing=landing,
                                        exposures=int(data.get("exposures") or 2),
                                        attention_gate=data.get("attention_gate", True) is not False,
                                        benchmarks=data.get("benchmarks") if isinstance(data.get("benchmarks"), dict) else None,
                                        competitor=competitor,
                                        include_generic_baseline=bool(data.get("include_generic_baseline")))

    task_id = _start("feed-test", sid, work, **({"memory_scope": scope} if scope else {}))
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

    scope = _memory_scope(data)
    people = _with_history(people, sid, scope)

    def work(progress):
        return pitch_svc.run(interview_batch, people, script, rebuttals, product,
                             str(data.get("channel") or "message"), batch=batch, progress=progress)

    task_id = _start("pitch", sid, work, **({"memory_scope": scope} if scope else {}))
    return jsonify({"success": True, "data": {"task_id": task_id, "simulation_id": sid, "people": len(people),
                                              "rebuttals": sorted(rebuttals)}})


@simulation_bp.route('/email-test', methods=['POST'])
def start_email_test():
    """POST {simulation_id, emails: [...] | {emails, list_size, benchmarks, familiarity}, seed?, parallel?, max_personas?}
    -> task writing email_test.json (GET /<sid>/email-test). Subject lines, senders, send times and sequences
    tested on the simulated people's inboxes."""
    from ..services import email_test
    data = request.get_json() or {}
    sid = data.get("simulation_id")
    try:
        _sim_dir(sid or "")
        emails, opts = email_test.normalize_emails(data.get("emails"))
        people, cfg = _people(sid)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    if not people:
        return jsonify({"success": False, "error": "no personas yet: prepare the simulation first"}), 400
    limit = data.get("max_personas")
    if isinstance(limit, int) and limit > 0:
        people = people[:limit]
    seed = int(data.get("seed") or 5)
    parallel = max(1, min(int(data.get("parallel") or 8), 32))
    list_size = data.get("list_size") or opts.get("list_size")
    bench = data.get("benchmarks") or opts.get("benchmarks")
    fam = float(data.get("familiarity") if data.get("familiarity") is not None else opts.get("familiarity", 0.2))
    prof = _profile(sid)
    product = ((prof or {}).get("one_liner") or (prof or {}).get("name") or "")
    scope = _memory_scope(data)
    people = _with_history(people, sid, scope)

    def work(progress):
        return email_test.run_email_test(_client(), Config.LLM_MODEL_NAME, emails, people, product=product, seed=seed,
                                         parallel=parallel, list_size=int(list_size) if list_size else None,
                                         benchmarks=bench, familiarity=fam, progress=progress)

    task_id = _start("email-test", sid, work, **({"memory_scope": scope} if scope else {}))
    return jsonify({"success": True, "data": {"task_id": task_id, "simulation_id": sid, "emails": len(emails), "people": len(people)}})


@simulation_bp.route('/predict', methods=['POST'])
def predict_run():
    """POST {brand, summary, feed_test?, email_test?, targets?: {ctr, cpl, would_convert, click_rate}} -> predictions with
    intervals and P(target), scaled by the calibration store; synchronous, no LLM."""
    from ..services import predict
    data = request.get_json() or {}
    if not isinstance(data.get("summary"), dict) and not data.get("feed_test"):
        return jsonify({"success": False, "error": "summary (summary.json) or feed_test is required"}), 400
    out = predict.predict_run(data.get("summary") or {}, data.get("feed_test") or {}, str(data.get("brand") or ""),
                              {k: float(v) for k, v in (data.get("targets") or {}).items() if v is not None}, data.get("email_test"))
    return jsonify({"success": True, "data": out})


@simulation_bp.route('/forecast', methods=['POST'])
def forecast_run():
    """POST {feed_test, feed_story?, spend?, days?} -> adoption curve over time from the best ad, its landing conversion
    and the word of mouth seen in the rounds; synchronous."""
    from ..services import predict
    data = request.get_json() or {}
    out = predict.forecast_run(data.get("feed_test") or {}, data.get("feed_story") or {}, data.get("spend"), int(data.get("days") or 90))
    if not out:
        return jsonify({"success": False, "error": "forecast needs a feed test with benchmarks (cpm and budget)"}), 400
    return jsonify({"success": True, "data": out})


@simulation_bp.route('/calibration-pairs', methods=['POST', 'GET'])
def calibration_pairs():
    """POST {brand, metric, pairs: [{sim, real, label}], source} stores real-vs-simulated pairs; GET lists the fits."""
    from ..services import predict
    if request.method == "GET":
        store = predict.load_store()
        metrics = sorted({p.get("metric") for p in store.get("pairs") or []})
        brands = sorted({p.get("brand") for p in store.get("pairs") or []})
        return jsonify({"success": True, "data": {"pairs": len(store.get("pairs") or []), "brands": brands,
                                                  "fits": {m: predict.fit(request.args.get("brand") or "", m, store) for m in metrics}}})
    data = request.get_json() or {}
    pairs = data.get("pairs")
    if not isinstance(pairs, list) or not data.get("metric"):
        return jsonify({"success": False, "error": "metric and pairs are required"}), 400
    n = predict.add_pairs(str(data.get("brand") or ""), str(data["metric"]), pairs, str(data.get("source") or "manual"))
    return jsonify({"success": True, "data": {"stored": n}})


@simulation_bp.route('/study-report', methods=['POST'])
def study_report():
    """POST {summary: study_summary.json, brand?} -> {markdown, method} (one Claude call, number-guarded; synchronous)."""
    from ..services import market_report
    from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text
    data = request.get_json() or {}
    summary = data.get("summary")
    if not isinstance(summary, dict) or not summary.get("scenarios"):
        return jsonify({"success": False, "error": "summary with scenarios is required"}), 400
    brand = str(data.get("brand") or summary.get("name") or "the brand")[:120]
    facts = json.dumps(summary, ensure_ascii=False, default=str)[:50000]
    prompt = (f"Write a short study report for {brand} from these facts (several scenarios run on the same simulated people, "
              f"each with several random seeds).\n\nFACTS:\n{facts}\n\n"
              "Markdown, under 500 words, for a business owner: a one-line exploratory scenario ranking with its agreement across simulated seeds, a table of the scenarios "
              "side by side (mean and seed-to-seed spread), what changed against the first scenario and whether the change is "
              "outside the spread, the decision agreement across seeds, and what to do next. Every number must come from the facts. "
              "Say 'simulated people' at least once. Do not call seed agreement real-world confidence, predict a success probability, or claim real-world lift without an independent held-out backtest. Spreads describe simulation variation only.")
    try:
        system = market_report.SYSTEM.replace("Return only valid JSON.", "Answer in Markdown only (no JSON, no code fence).")
        resp = create_chat_completion(_client(), model=Config.LLM_MODEL_NAME, temperature=0.3, max_tokens=3000,
                                      messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}])
        md = market_report.unwrap_markdown(extract_chat_completion_text(resp) or "")
        md = market_report.check_numbers_markdown(md, market_report._fact_numbers(summary))
        return jsonify({"success": True, "data": {"markdown": md, "method": "llm"}})
    except Exception as e:  # noqa: BLE001
        logger.error(f"study report failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


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
        corr = out.get("corrected") or {}
        if corr.get("estimate") is not None and corr.get("naive_syn"):
            from ..services import predict
            predict.add_pairs(str(data.get("brand") or ""), "would_convert" if str(data.get("field") or "would_convert") == "would_convert" else str(data.get("field")),
                              [{"sim": 100 * corr["naive_syn"], "real": 100 * corr["real_mean"], "label": "calibrate"}], "calibrate")
            out["stored_pair"] = True
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
@simulation_bp.route('/<simulation_id>/email-test', methods=['GET'], defaults={"kind": "email-test"})
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

def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def _runner_status(sim_dir: str) -> str:
    """The runner status on file; "running" whose process is gone (machine restart, killed server) reads as "stopped"."""
    try:
        with open(os.path.join(sim_dir, "run_state.json"), encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        return ""
    status = str(st.get("runner_status") or "")
    if status == "running" and st.get("process_pid") and not _pid_alive(st["process_pid"]):
        return "stopped"
    return status


@simulation_bp.route('/<simulation_id>/memory', methods=['GET', 'POST'])
def simulation_memory(simulation_id: str):
    """GET ?scope=&agent= -> behaviour-state summary (or one person's state and memories).
    POST {scope?, events?: [{agent_id, test, kind, text}], survey?: {responses, offer}} -> record events."""
    from ..services import behavior_state
    try:
        sim_dir = _sim_dir(simulation_id)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    if request.method == "GET":
        scope = request.args.get("scope") or "default"
        agent = request.args.get("agent")
        if agent is not None:
            data = behavior_state.load(sim_dir)
            person = ((data.get("scopes") or {}).get(scope) or {}).get(str(agent))
            return jsonify({"success": True, "data": {"scope": scope, "agent_id": agent, "person": person}})
        return jsonify({"success": True, "data": behavior_state.summary(sim_dir, scope)})
    data = request.get_json() or {}
    scope = str(data.get("scope") or "") or _memory_scope(data) or "default"
    events = [e for e in (data.get("events") or []) if isinstance(e, dict)]
    survey = data.get("survey")
    if isinstance(survey, dict):
        events += behavior_state.events_from_survey(survey.get("responses") or [], str(survey.get("offer") or ""))
    n = behavior_state.record(sim_dir, events, scope)
    return jsonify({"success": True, "data": {"scope": scope, "events_recorded": n, **behavior_state.summary(sim_dir, scope)}})


@simulation_bp.route('/<simulation_id>/context', methods=['PUT', 'GET'])
def simulation_context(simulation_id: str):
    """PUT {text, source?, round?} appends a context update (news, what people say today, a competitor move) to
    event_config.context_updates; the runner re-reads the file every round and every persona card carries it from
    that round on. Allowed while the simulation runs: that is the point. GET lists the updates."""
    try:
        sim_dir = _sim_dir(simulation_id)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    cfg_path = os.path.join(sim_dir, "simulation_config.json")
    if not os.path.exists(cfg_path):
        return jsonify({"success": False, "error": "prepare the simulation first (no simulation_config.json)"}), 400
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    ev = cfg.setdefault("event_config", {})
    ups = ev.setdefault("context_updates", [])
    if request.method == "GET":
        return jsonify({"success": True, "data": {"context_updates": ups}})
    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "").strip()
    if not text:
        return jsonify({"success": False, "error": "text is required"}), 400
    try:
        rnd = int(data.get("round")) if data.get("round") is not None else None
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "round must be an integer"}), 400
    if rnd is None:                                            # default: from the next round on
        try:
            with open(os.path.join(sim_dir, "run_state.json"), encoding="utf-8") as f:
                rnd = int((json.load(f).get("current_round") or 0)) + 1
        except (OSError, ValueError, TypeError):
            rnd = 0
    ups.append({"round": rnd, "text": text[:400], "source": str(data.get("source") or "")[:60]})
    tmp = cfg_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, cfg_path)
    return jsonify({"success": True, "data": {"context_updates": ups, "running": _runner_status(sim_dir) == "running"}})


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


@simulation_bp.route('/thought-stream', methods=['POST'])
def start_thought_stream():
    """POST {simulation_id, stimulus: str|{headline,text,price,channel}, max_personas?, parallel?, seed?}
    Runs a live cognitive inner-monologue simulation across the simulation's personas."""
    from ..services import agent_thoughts
    data = request.get_json(silent=True) or {}
    sid = str(data.get("simulation_id") or "").strip()
    stimulus = data.get("stimulus")
    try:
        root = _sim_dir(sid)
        people, _ = _people(sid)
        if not people:
            raise ValueError("no personas found in simulation")
        if not stimulus:
            raise ValueError("stimulus is required")
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    max_personas = max(1, min(int(data.get("max_personas") or 40), 200))
    parallel = max(1, min(int(data.get("parallel") or 8), 24))
    seed = int(data.get("seed") or 7)
    scope = _memory_scope(data)
    if scope:
        people = _with_history(people, sid, scope)

    if data.get("sync"):
        try:
            res = agent_thoughts.run_thought_simulation(
                _client(), Config.LLM_MODEL_NAME, stimulus, people,
                max_personas=max_personas, parallel=parallel, seed=seed
            )
            with open(os.path.join(root, "thought_stream.json"), "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
            return jsonify({"success": True, "data": res})
        except Exception as e:  # noqa: BLE001
            return jsonify({"success": False, "error": str(e)}), 500

    def work(progress):
        return agent_thoughts.run_thought_simulation(
            _client(), Config.LLM_MODEL_NAME, stimulus, people,
            max_personas=max_personas, parallel=parallel, seed=seed, progress=progress
        )

    task_id = _start("thought-stream", sid, work)
    return jsonify({"success": True, "data": {"task_id": task_id, "simulation_id": sid, "personas": min(len(people), max_personas)}})


@simulation_bp.route('/<simulation_id>/thought-stream', methods=['GET'])
def get_thought_stream(simulation_id: str):
    """Return the unified agent cognitive mindstream harvested across all touchpoints in the simulation."""
    from ..services import agent_thoughts
    try:
        root = _sim_dir(simulation_id)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    return jsonify({"success": True, "data": agent_thoughts.harvest_thoughts(root)})


@simulation_bp.route('/buying-committee', methods=['POST'])
def start_buying_committee():
    """POST {simulation_id, offer: str|{headline,text,price}, mode?: auto|b2b|household, committee_count?, seed?}"""
    from ..services import gtm_suite
    data = request.get_json(silent=True) or {}
    sid = str(data.get("simulation_id") or "").strip()
    try:
        root = _sim_dir(sid)
        people, _ = _people(sid)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    offer = data.get("offer") or "15-Minute Daily Routine App"
    mode = str(data.get("mode") or "auto")
    count = int(data.get("committee_count") or 6)
    client = _client() if data.get("use_llm") else None
    res = gtm_suite.run_buying_committee(client, Config.LLM_MODEL_NAME, offer, people, mode=mode, committee_count=count, seed=int(data.get("seed") or 17))
    with open(os.path.join(root, "buying_committee.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    return jsonify({"success": True, "data": res})


@simulation_bp.route('/creative-optimizer', methods=['POST'])
def start_creative_optimizer():
    """POST {simulation_id, creative: str|{headline,text,cta,price}, generations?: 3, seed?}"""
    from ..services import gtm_suite
    data = request.get_json(silent=True) or {}
    sid = str(data.get("simulation_id") or "").strip()
    try:
        root = _sim_dir(sid)
        people, _ = _people(sid)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    creative = data.get("creative") or data.get("offer") or "Start your 7-day free trial today"
    gens = int(data.get("generations") or 3)
    client = _client() if data.get("use_llm") else None
    res = gtm_suite.run_creative_optimizer(client, Config.LLM_MODEL_NAME, creative, people, generations=gens, seed=int(data.get("seed") or 23))
    with open(os.path.join(root, "creative_optimizer.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    return jsonify({"success": True, "data": res})


@simulation_bp.route('/sales-battlecard', methods=['POST'])
def start_sales_battlecard():
    """POST {simulation_id, offer?, competitor?}"""
    from ..services import gtm_suite
    data = request.get_json(silent=True) or {}
    sid = str(data.get("simulation_id") or "").strip()
    try:
        root = _sim_dir(sid)
        people, _ = _people(sid)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    res = gtm_suite.run_sales_battlecard(
        None, Config.LLM_MODEL_NAME, people,
        offer=str(data.get("offer") or ""),
        competitor=str(data.get("competitor") or "Status Quo / Free Alternatives"),
    )
    with open(os.path.join(root, "sales_battlecard.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    return jsonify({"success": True, "data": res})


@simulation_bp.route('/journey', methods=['POST'])
def start_journey_simulation():
    """POST {simulation_id, offer?, cpm?, retargeting_cpm?, monthly_price?, seed?}"""
    from ..services import gtm_suite
    data = request.get_json(silent=True) or {}
    sid = str(data.get("simulation_id") or "").strip()
    try:
        root = _sim_dir(sid)
        people, _ = _people(sid)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    res = gtm_suite.run_journey_simulation(
        None, Config.LLM_MODEL_NAME, data.get("offer") or "Offer", people,
        cpm=float(data.get("cpm") or 4.5),
        retargeting_cpm=float(data.get("retargeting_cpm") or 6.0),
        monthly_price=float(data["monthly_price"]) if data.get("monthly_price") is not None else None,
        seed=int(data.get("seed") or 29),
    )
    with open(os.path.join(root, "journey_sim.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    return jsonify({"success": True, "data": res})


@simulation_bp.route('/pricing-conjoint', methods=['POST'])
def start_pricing_conjoint():
    """POST {simulation_id, tiers?, base_price?, currency?, seed?}"""
    from ..services import gtm_suite
    data = request.get_json(silent=True) or {}
    sid = str(data.get("simulation_id") or "").strip()
    try:
        root = _sim_dir(sid)
        people, _ = _people(sid)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    res = gtm_suite.run_pricing_conjoint(
        None, Config.LLM_MODEL_NAME, people,
        tiers=data.get("tiers"),
        base_price=float(data.get("base_price") or 12.0),
        currency=str(data.get("currency") or "USD"),
        seed=int(data.get("seed") or 37),
    )
    with open(os.path.join(root, "pricing_conjoint.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    return jsonify({"success": True, "data": res})


@simulation_bp.route('/gtm-suite', methods=['POST'])
def start_gtm_suite():
    """POST {simulation_id, offer?, competitor?, seed?} — runs all 5 Marketing & Sales GTM engines."""
    from ..services import gtm_suite
    data = request.get_json(silent=True) or {}
    sid = str(data.get("simulation_id") or "").strip()
    try:
        root = _sim_dir(sid)
        people, _ = _people(sid)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    client = _client() if data.get("use_llm") else None
    res = gtm_suite.run_full_gtm_suite(
        client, Config.LLM_MODEL_NAME, people,
        offer=data.get("offer"),
        competitor=str(data.get("competitor") or "Status Quo / Free Alternatives"),
        run_dir=root,
        seed=int(data.get("seed") or 19),
    )
    return jsonify({"success": True, "data": res})


@simulation_bp.route('/<simulation_id>/gtm-suite', methods=['GET'])
def get_gtm_suite(simulation_id: str):
    """GET the saved (or on-the-fly generated) Marketing & Sales GTM suite for a simulation."""
    from ..services import gtm_suite
    try:
        root = _sim_dir(simulation_id)
        people, _ = _people(simulation_id)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    p = os.path.join(root, "gtm_suite.json")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return jsonify({"success": True, "data": json.load(f)})
    res = gtm_suite.run_full_gtm_suite(None, Config.LLM_MODEL_NAME, people, run_dir=root)
    return jsonify({"success": True, "data": res})


@simulation_bp.route('/competitor-analysis', methods=['POST'])
def start_competitor_analysis():
    """POST {simulation_id, offer?, competitors?: [str|dict], seed?} — Multi-agent Competitor Bake-Off & AI Suggestion Engine."""
    from ..services import gtm_suite
    data = request.get_json(silent=True) or {}
    sid = str(data.get("simulation_id") or "").strip()
    try:
        root = _sim_dir(sid)
        people, _ = _people(sid)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    client = _client() if data.get("use_llm") else None
    res = gtm_suite.run_competitor_intelligence(
        client, Config.LLM_MODEL_NAME, data.get("offer") or "Our Product", people,
        competitors=data.get("competitors"),
        seed=int(data.get("seed") or 41),
    )
    with open(os.path.join(root, "competitor_intel.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    return jsonify({"success": True, "data": res})


@simulation_bp.route('/<simulation_id>/competitor-analysis', methods=['GET'])
def get_competitor_analysis(simulation_id: str):
    """GET the Competitor Bake-Off, Feature Gap Matrix, and AI Suggestions for a simulation."""
    from ..services import gtm_suite
    try:
        root = _sim_dir(simulation_id)
        people, _ = _people(simulation_id)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    p = os.path.join(root, "competitor_intel.json")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return jsonify({"success": True, "data": json.load(f)})
    res = gtm_suite.run_competitor_intelligence(None, Config.LLM_MODEL_NAME, "Our Product", people)
    return jsonify({"success": True, "data": res})


@simulation_bp.route('/landing-teardown', methods=['POST'])
def start_landing_teardown():
    """POST {simulation_id, url?: str, page?: dict|str, seed?} — Wynter + Neurons 5-Second Teardown & Scroll Decay."""
    from ..services import cro_and_sparring
    data = request.get_json(silent=True) or {}
    sid = str(data.get("simulation_id") or "").strip()
    try:
        root = _sim_dir(sid)
        people, _ = _people(sid)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    page_input = data.get("url") or data.get("page") or data.get("offer") or "15-Minute Daily Routine App"
    res = cro_and_sparring.run_landing_teardown(None, Config.LLM_MODEL_NAME, page_input, people, seed=int(data.get("seed") or 53))
    with open(os.path.join(root, "landing_teardown.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    return jsonify({"success": True, "data": res})


@simulation_bp.route('/sales-roleplay', methods=['POST'])
def start_sales_roleplay():
    """POST {simulation_id, rep_messages?: [str], persona_id?: int, offer?: str} — Hyperbound/Yoodli AI Buyer Roleplay Dojo."""
    from ..services import cro_and_sparring
    data = request.get_json(silent=True) or {}
    sid = str(data.get("simulation_id") or "").strip()
    try:
        root = _sim_dir(sid)
        people, _ = _people(sid)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    res = cro_and_sparring.run_sales_roleplay(
        None, Config.LLM_MODEL_NAME, people,
        rep_messages=data.get("rep_messages"),
        persona_id=data.get("persona_id"),
        offer=str(data.get("offer") or ""),
    )
    with open(os.path.join(root, "sales_roleplay.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    return jsonify({"success": True, "data": res})


@simulation_bp.route('/whatif-simulator', methods=['POST'])
def start_whatif_simulator():
    """POST {simulation_id, base_price?: float, currency?: str} — Subconscious.ai Causal Marginal Utility & What-If Model."""
    from ..services import cro_and_sparring
    data = request.get_json(silent=True) or {}
    sid = str(data.get("simulation_id") or "").strip()
    try:
        root = _sim_dir(sid)
        people, _ = _people(sid)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    res = cro_and_sparring.run_causal_whatif_model(
        people,
        base_price=float(data.get("base_price") or 12.0),
        currency=str(data.get("currency") or "USD"),
    )
    with open(os.path.join(root, "causal_whatif.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    return jsonify({"success": True, "data": res})


@simulation_bp.route('/segment-personalizer', methods=['POST'])
def start_segment_personalizer():
    """POST {simulation_id, offer?} — Mutiny 1:1 Segment Personalizer & Evidenza Category Entry Points (CEPs)."""
    from ..services import cro_and_sparring
    data = request.get_json(silent=True) or {}
    sid = str(data.get("simulation_id") or "").strip()
    try:
        root = _sim_dir(sid)
        people, _ = _people(sid)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    res = cro_and_sparring.run_segment_personalizer(None, Config.LLM_MODEL_NAME, data.get("offer") or "15-Min Daily Routine", people)
    with open(os.path.join(root, "segment_personalization.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    return jsonify({"success": True, "data": res})




