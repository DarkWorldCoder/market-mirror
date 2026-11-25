"""Durable job queue (app/jobs): claims, limits, retries without silent re-spend, recovery, cancellation, spend cap,
replay of endpoint jobs and the /api/jobs endpoints. No model calls: `spend_cap.check()` stands in for the start of
one (it is what every real call runs first)."""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.jobs import context as jctx
from app.jobs.limits import Limits, parse
from app.jobs.runner import JobRunner, retryable
from app.jobs.store import (CANCELLED, FAILED, NEEDS_APPROVAL, QUEUED, RUNNING, SUCCEEDED, JobStore)
from app.utils import spend_cap


def _limits(provider="", workspace="", lane=""):
    return Limits(provider=parse(provider, 0), workspace=parse(workspace, 0), lane=parse(lane, 0))


def _wait(pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def store(tmp_path):
    return JobStore(str(tmp_path / "jobs.sqlite"))


@pytest.fixture
def runners():
    started = []

    def make(store, **kw):
        kw.setdefault("limits", _limits())
        kw.setdefault("lease_s", 2.0)
        kw.setdefault("poll_s", 0.05)
        r = JobRunner(store, **kw).start()
        started.append(r)
        return r
    yield make
    for r in started:
        r.stop(2)


def test_limits_parse_and_wait_reason():
    lim = Limits(provider=parse("claude=1", 4), workspace=parse("", 2), lane=parse("oasis=2", 0))
    running = {"provider": {"claude": 1}, "workspace": {}, "lane": {}}
    assert "provider claude" in lim.allows({"provider": "claude", "workspace": "a", "lane": "default"}, running)
    assert lim.allows({"provider": "openai", "workspace": "a", "lane": "default"}, running) is None
    assert lim.lane_limit("default") is None and lim.lane_limit("oasis") == 2


def test_each_job_runs_exactly_once_across_two_runners(store, runners):
    handled = []
    lock = threading.Lock()

    def handler(payload):
        with lock:
            handled.append(payload["n"])
        time.sleep(0.01)
        return {"n": payload["n"]}
    for n in range(40):
        store.enqueue(f"j{n}", "t", handler="h", payload={"n": n}, spends=False)
    runners(store, threads=4, handlers={"h": handler})
    runners(store, threads=4, handlers={"h": handler})
    assert _wait(lambda: store.stats()["counts"][SUCCEEDED] == 40)
    assert sorted(handled) == list(range(40))
    assert all(j["attempts"] == 1 for j in store.list(limit=100))


def test_provider_and_workspace_limits_hold(store, runners):
    live = {"claude": 0, "ws:a": 0}
    peak = {"claude": 0, "ws:a": 0}
    lock = threading.Lock()

    def handler(payload):
        keys = [k for k in (payload.get("provider"), "ws:" + payload["ws"]) if k in live]
        with lock:
            for k in keys:
                live[k] += 1
                peak[k] = max(peak[k], live[k])
        time.sleep(0.05)
        with lock:
            for k in keys:
                live[k] -= 1
    for n in range(12):
        store.enqueue(f"c{n}", "t", handler="h", provider="claude", workspace="b", payload={"provider": "claude", "ws": "b"},
                      spends=False)
        store.enqueue(f"a{n}", "t", handler="h", provider="openai", workspace="a", payload={"provider": "openai", "ws": "a"},
                      spends=False)
    runners(store, threads=8, handlers={"h": handler}, limits=_limits(provider="claude=2", workspace="a=1"))
    assert _wait(lambda: store.stats()["counts"][SUCCEEDED] == 24, 20)
    assert peak["claude"] == 2 and peak["ws:a"] == 1


def test_retry_without_model_calls_then_needs_approval_after_calls(store, runners):
    attempts = {"x": 0, "y": 0}

    def flaky(payload):
        attempts["x"] += 1
        if attempts["x"] == 1:
            raise ConnectionError("upstream reset")
        return "ok"

    def spends_then_fails(payload):
        attempts["y"] += 1
        spend_cap.check()                       # a model call started
        raise ConnectionError("upstream reset after a call")
    store.enqueue("x", "t", handler="flaky", max_attempts=3)
    store.enqueue("y", "t", handler="spend", max_attempts=3)
    runners(store, threads=2, handlers={"flaky": flaky, "spend": spends_then_fails})
    assert _wait(lambda: store.get("x")["status"] == SUCCEEDED, 15)
    assert store.get("x")["attempts"] == 2 and store.get("x")["model_calls"] == 0
    assert _wait(lambda: store.get("y")["status"] == NEEDS_APPROVAL)
    y = store.get("y")
    assert attempts["y"] == 1 and y["model_calls"] == 1 and y["attempts"] == 1   # never retried on its own
    store.approve("y")
    assert _wait(lambda: attempts["y"] == 2)
    assert _wait(lambda: store.get("y")["status"] == NEEDS_APPROVAL)


def test_non_retryable_error_fails(store, runners):
    store.enqueue("z", "t", handler="bad")
    runners(store, threads=1, handlers={"bad": lambda p: (_ for _ in ()).throw(ValueError("bad input"))})
    assert _wait(lambda: store.get("z")["status"] == FAILED)
    assert "bad input" in store.get("z")["error"] and store.get("z")["attempts"] == 1
    assert retryable(TimeoutError()) and not retryable(spend_cap.SpendCapReached("x"))


def _fake_running(store, job_id, worker, attempt_calls=0, handler="h"):
    store.enqueue(job_id, "t", handler=handler)
    with store._db(immediate=True) as conn:
        conn.execute("UPDATE jobs SET status = ?, worker = ?, lease_until = ?, attempts = 1, attempt_calls = ?, "
                     "model_calls = ? WHERE job_id = ?", (RUNNING, worker, time.time() + 600, attempt_calls,
                                                          attempt_calls, job_id))


def test_recovery_after_a_crash_never_re_spends(store):
    dead = "somehost-that-died:1:abc"
    _fake_running(store, "clean", dead, attempt_calls=0)
    _fake_running(store, "spent", dead, attempt_calls=3)
    _fake_running(store, "closure", dead, attempt_calls=0, handler="")
    store.enqueue("orphan", "t", handler="", owner=dead, bound=True)
    store.enqueue("orphan_replay", "t", handler="replay", owner=dead, bound=True)
    changed = {c["job_id"]: c["action"] for c in store.recover(lambda token: False)}
    assert changed == {"clean": QUEUED, "spent": NEEDS_APPROVAL, "closure": FAILED, "orphan": FAILED,
                       "orphan_replay": "unbound"}
    assert "approve a retry" in store.get("spent")["message"]
    assert store.get("orphan_replay")["bound"] is False and store.get("orphan_replay")["status"] == QUEUED


def test_live_worker_keeps_its_jobs(store):
    _fake_running(store, "mine", "me:1:x")
    assert store.recover(lambda token: token == "me:1:x") == []


def test_dead_pid_on_this_host_is_detected(store):
    import socket
    store.register_worker(f"{socket.gethostname()}:999999999:dead", {})
    alive = store.worker_alive_fn(stale_after_s=60)
    assert alive(f"{socket.gethostname()}:999999999:dead") is False


def test_cancel_queued_and_running(store, runners):
    started = threading.Event()

    def long(payload):
        started.set()
        for _ in range(500):
            spend_cap.check()                   # each model call is a cancellation point
            time.sleep(0.01)
        return "finished"
    store.enqueue("q", "t", handler="long", workspace="w", spends=False)
    store.enqueue("q2", "t", handler="long", workspace="w", spends=False)
    store.cancel("q2")
    assert store.get("q2")["status"] == CANCELLED
    runners(store, threads=1, handlers={"long": long}, lease_s=0.6)
    assert started.wait(5)
    store.cancel("q")
    assert _wait(lambda: store.get("q")["status"] == CANCELLED, 10)
    assert store.get("q")["result"] is None


def test_spend_cap_reached_fails_before_start(store, runners, tmp_path, monkeypatch):
    monkeypatch.setenv("MM_SPEND_FILE", str(tmp_path / "cap.json"))
    import app.jobs as jobs_mod
    st = spend_cap.arm(0.01, "test")
    spend_cap.charge_tokens("claude-haiku-4-5", 100000, 10000)
    ran = []
    store.enqueue("s", "t", handler="h")
    try:
        runners(store, threads=1, handlers={"h": lambda p: ran.append(1)}, admit=jobs_mod._admit)
        assert _wait(lambda: store.get("s")["status"] == FAILED)
    finally:
        spend_cap.disarm(st["cap_id"])
    assert ran == [] and "spend cap reached" in store.get("s")["error"] and store.get("s")["model_calls"] == 0


def test_estimate_waits_for_budget(store, tmp_path, monkeypatch):
    monkeypatch.setenv("MM_SPEND_FILE", str(tmp_path / "cap2.json"))
    import app.jobs as jobs_mod
    st = spend_cap.arm(1.0, "test")
    try:
        assert jobs_mod._admit({"estimate_usd": 0.4}, [{"spends": 1, "estimate_usd": 0.7}]) == "waiting for spend-cap budget"
        assert jobs_mod._admit({"estimate_usd": 2.0}, []).startswith("fail:")
        assert jobs_mod._admit({"estimate_usd": 0.2}, [{"spends": 1, "estimate_usd": 0.7}]) is None
    finally:
        spend_cap.disarm(st["cap_id"])


def test_calls_in_thread_pools_count_against_their_job(store, runners):
    def fan_out(payload):
        with ThreadPoolExecutor(4) as pool:
            list(pool.map(lambda _: spend_cap.check(), range(10)))
        return "ok"
    store.enqueue("fan", "t", handler="fan")
    runners(store, threads=1, handlers={"fan": fan_out})
    assert _wait(lambda: store.get("fan")["status"] == SUCCEEDED)
    assert store.get("fan")["model_calls"] == 10


def test_bound_closure_runs_only_in_its_process(store, runners):
    r1 = runners(store, threads=1)
    other = runners(store, threads=1, handlers={})
    out = []
    store.enqueue("b", "t", owner=r1.worker, bound=True)
    r1.bind("b", lambda: out.append(r1.worker) or "done")
    assert _wait(lambda: store.get("b")["status"] == SUCCEEDED)
    assert out == [r1.worker] and other.completed == 0


def test_queue_wait_and_stats(store, runners):
    for n in range(5):
        store.enqueue(f"w{n}", "t", handler="h", spends=False)
    time.sleep(0.1)
    runners(store, threads=2, handlers={"h": lambda p: None})
    assert _wait(lambda: store.stats()["counts"][SUCCEEDED] == 5)
    st = store.stats()
    assert st["queue_wait_s"]["n"] == 5 and st["queue_wait_s"]["p50"] >= 0.1
    assert len(st["workers"]) == 1


# ------------------------------------------------------------------ server integration


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    """An app on temporary databases. The process-wide runner it starts is stopped before the paths are restored,
    so no test thread ever polls the normal queue database."""
    from app import create_app, jobs
    jobs.stop_runner(timeout=5)
    monkeypatch.setenv("MM_TASK_DB_PATH", str(tmp_path / "tasks.sqlite"))
    monkeypatch.setenv("MM_JOB_DB_PATH", str(tmp_path / "tasks.sqlite"))
    yield create_app()
    jobs.stop_runner(timeout=5)


def test_task_recovery_skips_job_backed_tasks(app_env):
    from app import jobs
    from app.models.task import TaskManager, TaskStatus
    tm = TaskManager()
    plain = tm.create_task("plain")
    queued = tm.create_task("queued")
    # bound to another process, so this process's runner never claims it and moves the task to processing
    jobs.store().enqueue(queued, "t", handler="replay", payload={"path": "/x"}, bound=True, owner="another-process")
    tm.release(plain)
    tm.release(queued)
    tm.recover_interrupted_tasks()
    assert tm.get_task(plain).status == TaskStatus.FAILED
    assert tm.get_task(queued).status == TaskStatus.PENDING
    jobs.store().cancel(queued)


def test_replay_reuses_the_task_and_runs_inline(app_env):
    """A worker without the closure re-runs the endpoint: create_task() returns the job's id, submit() runs inline."""
    from flask import jsonify
    from app import jobs
    from app.jobs.replay import run_replay
    from app.models.task import TaskManager
    seen = {}
    route = f"/api/simulation/_replay_probe_{uuid.uuid4().hex[:6]}"

    def probe():
        tm = TaskManager()
        tid = tm.create_task("probe")

        def work():
            seen["thread"] = threading.current_thread().name
            seen["task"] = tid
            tm.complete_task(tid, {"ok": True})
        jobs.submit(tid, work, kind="probe", replay=True)
        return jsonify({"success": True, "data": {"task_id": tid}})
    app_env.add_url_rule(route, route, probe, methods=["POST"])
    job_id = str(uuid.uuid4())
    TaskManager().create_task("probe")             # unrelated task, to show the replay does not make a new one
    with TaskManager()._db() as conn:
        conn.execute("INSERT INTO tasks (task_id, task_type, status, created_at, updated_at) VALUES (?, 'probe', 'pending', "
                     "datetime('now'), datetime('now'))", (job_id,))
    ctx = jctx.JobContext(job_id=job_id)
    token = jctx.activate(ctx)
    try:
        data = run_replay({"payload": {"method": "POST", "path": route, "json": {}}}, ctx)
    finally:
        jctx.deactivate(ctx, token)
    assert data == {"task_id": job_id} and seen["task"] == job_id
    assert seen["thread"] == threading.current_thread().name
    assert TaskManager().get_task(job_id).status.value == "completed"


def test_replay_hands_back_work_errors(app_env):
    from flask import jsonify
    from app import jobs
    from app.jobs.replay import run_replay
    from app.models.task import TaskManager
    route = f"/api/simulation/_replay_fail_{uuid.uuid4().hex[:6]}"

    def probe():
        tid = TaskManager().create_task("probe")
        jobs.submit(tid, lambda: (_ for _ in ()).throw(ConnectionError("provider down")), kind="probe", replay=True)
        return jsonify({"success": True, "data": {}})
    app_env.add_url_rule(route, route, probe, methods=["POST"])
    ctx = jctx.JobContext(job_id="nope")
    token = jctx.activate(ctx)
    try:
        with pytest.raises(ConnectionError):
            run_replay({"payload": {"path": route, "json": {}}}, ctx)
    finally:
        jctx.deactivate(ctx, token)


def test_submit_runs_through_the_server_runner_and_mirrors_the_task(app_env):
    from app import jobs
    from app.models.task import TaskManager
    tm = TaskManager()
    tid = tm.create_task("demo")
    jobs.submit(tid, lambda: {"answer": 42}, kind="demo", spends=False)
    assert _wait(lambda: jobs.get(tid)["status"] == SUCCEEDED)
    assert _wait(lambda: tm.get_task(tid).status.value == "completed")
    assert tm.get_task(tid).result == {"answer": 42}


def test_jobs_api(app_env):
    from app import jobs
    from app.models.task import TaskManager
    client = app_env.test_client()
    gate = threading.Event()
    tid = TaskManager().create_task("api")
    jobs.submit(tid, lambda: gate.wait(10), kind="api_demo", spends=False, workspace="team-a")
    assert client.get("/api/jobs?status=bogus").status_code == 400
    listed = client.get("/api/jobs?kind=api_demo").get_json()["data"]
    assert [j["job_id"] for j in listed] == [tid] and "payload" not in listed[0]
    assert client.get(f"/api/jobs/{tid}").get_json()["data"]["workspace"] == "team-a"
    stats = client.get("/api/jobs/stats").get_json()["data"]
    assert "queue_wait_s" in stats and "limits" in stats
    status = client.post("/api/simulation/market-task/status", json={"task_id": tid}).get_json()["data"]
    assert status["job"]["lane"] == "default"
    assert client.post(f"/api/jobs/{tid}/retry", json={}).status_code == 400
    assert client.post(f"/api/jobs/{tid}/cancel").get_json()["data"]["cancel_requested"] is True
    gate.set()
    assert _wait(lambda: jobs.get(tid)["status"] == CANCELLED)
    assert TaskManager().get_task(tid).error == "cancelled"
    assert client.get("/api/jobs/missing").status_code == 404


def test_oasis_gate_counts_runs_and_starts_in_flight(monkeypatch):
    import app.jobs as jobs_mod
    from app.services.simulation_runner import SimulationRunner
    monkeypatch.setenv("MM_OASIS_MAX_RUNS", "2")
    monkeypatch.setattr(SimulationRunner, "active_run_count", classmethod(lambda cls: 1))
    assert jobs_mod._oasis_gate({"lane": {}}) is True
    assert jobs_mod._oasis_gate({"lane": {"oasis": 1}}) is False


def test_queued_run_state_round_trip(tmp_path, monkeypatch):
    from app.services.simulation_runner import RunnerStatus, SimulationRunner
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    sid = "sim_q_" + uuid.uuid4().hex[:6]
    SimulationRunner.mark_queued(sid, "job1")
    SimulationRunner._run_states.pop(sid)
    assert SimulationRunner.get_run_state(sid).runner_status == RunnerStatus.QUEUED
    assert SimulationRunner.active_run_count() >= 0
    SimulationRunner.mark_unqueued(sid)
    assert SimulationRunner.get_run_state(sid).runner_status == RunnerStatus.STOPPED
    SimulationRunner._run_states.pop(sid, None)


def test_start_queues_when_the_runner_is_full_then_starts_and_stop_cancels(app_env, tmp_path, monkeypatch):
    """OASIS starts wait in the oasis lane while MM_OASIS_MAX_RUNS runs play rounds; the server starts them later by
    re-running the request; /stop on a queued start cancels it."""
    from types import SimpleNamespace
    from app import jobs
    from app.api import simulation as simulation_api
    from app.models.task import TaskManager
    from app.services.simulation_manager import SimulationStatus
    from app.services.simulation_runner import RunnerStatus, SimulationRunner, SimulationRunState
    monkeypatch.setenv("MM_OASIS_MAX_RUNS", "1")
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    sims = {}

    def get_sim(sid):
        return sims.setdefault(sid, SimpleNamespace(simulation_id=sid, project_id="p", graph_id="g", enable_twitter=True,
                                                    enable_reddit=True, status=SimulationStatus.READY, error=None))
    monkeypatch.setattr(simulation_api, "SimulationManager",
                        lambda: SimpleNamespace(get_simulation=get_sim, _save_simulation_state=lambda s: None))
    full = {"n": 1}
    monkeypatch.setattr(SimulationRunner, "active_run_count", classmethod(lambda cls: full["n"]))
    started = []

    def fake_start(cls, simulation_id, **kw):
        started.append(simulation_id)
        st = SimulationRunState(simulation_id=simulation_id, runner_status=RunnerStatus.RUNNING, total_rounds=3)
        cls._save_run_state(st)
        return st
    monkeypatch.setattr(SimulationRunner, "start_simulation", classmethod(fake_start))
    client = app_env.test_client()
    sid, sid2 = "sim_q1_" + uuid.uuid4().hex[:6], "sim_q2_" + uuid.uuid4().hex[:6]

    first = client.post("/api/simulation/start", json={"simulation_id": sid, "platform": "parallel"}).get_json()["data"]
    assert first["runner_status"] == "queued" and first["queued"] is True and started == []
    again = client.post("/api/simulation/start", json={"simulation_id": sid}).get_json()["data"]
    assert again["job_id"] == first["job_id"]
    assert client.get(f"/api/simulation/{sid}/run-status").get_json()["data"]["runner_status"] == "queued"
    second = client.post("/api/simulation/start", json={"simulation_id": sid2}).get_json()["data"]
    assert second["queue_position"] == 2

    assert client.post("/api/simulation/stop", json={"simulation_id": sid2}).get_json()["data"]["runner_status"] == "stopped"
    assert jobs.get(second["job_id"])["status"] == CANCELLED

    full["n"] = 0                                   # a run finished: the queued start goes ahead
    jobs.runner().wake()
    assert _wait(lambda: jobs.get(first["job_id"])["status"] == SUCCEEDED)
    assert started == [sid]
    assert TaskManager().get_task(first["job_id"]).status.value == "completed"

    # a start stopped while its replay is about to begin does not start
    full["n"] = 1
    sid3 = "sim_q3_" + uuid.uuid4().hex[:6]
    third = client.post("/api/simulation/start", json={"simulation_id": sid3}).get_json()["data"]
    st = SimulationRunner.get_run_state(sid3)
    st.runner_status = RunnerStatus.STOPPED          # what /stop leaves when it wins the race
    SimulationRunner._save_run_state(st)
    full["n"] = 0
    jobs.runner().wake()
    assert _wait(lambda: jobs.get(third["job_id"])["status"] == FAILED)
    assert sid3 not in started and "stopped" in jobs.get(third["job_id"])["error"]
    for s in (sid, sid2, sid3):
        SimulationRunner._run_states.pop(s, None)


def test_local_workspace_has_no_cap_by_default(monkeypatch):
    from app.jobs.limits import from_env
    monkeypatch.delenv("MM_JOB_LIMIT_WORKSPACE", raising=False)
    lim = from_env()
    assert lim.workspace_limit("local") is None and lim.workspace_limit("acme") == 2


# ------------------------------------------------------------------ review findings


def test_out_of_process_spend_always_needs_approval(store):
    store.enqueue("pitch", "market_pitch", handler="replay", spends="out_of_process")
    with store._db(immediate=True) as conn:
        conn.execute("UPDATE jobs SET status = ?, worker = 'gone:1:x', lease_until = 0, attempts = 1 WHERE job_id = 'pitch'",
                     (RUNNING,))
    assert [c["action"] for c in store.recover(lambda t: False)] == [NEEDS_APPROVAL]


def test_out_of_process_spend_is_not_retried_after_an_error(store, runners):
    store.enqueue("p2", "t", handler="h", spends="out_of_process")
    runners(store, threads=1, handlers={"h": lambda p: (_ for _ in ()).throw(ConnectionError("down"))})
    assert _wait(lambda: store.get("p2")["status"] == NEEDS_APPROVAL)
    assert store.get("p2")["attempts"] == 1


def test_admission_failure_settles_the_task(app_env, store, runners, tmp_path, monkeypatch):
    monkeypatch.setenv("MM_SPEND_FILE", str(tmp_path / "cap3.json"))
    import app.jobs as jobs_mod
    from app.models.task import TaskManager
    tid = TaskManager().create_task("capped")
    st = spend_cap.arm(0.01, "test")
    spend_cap.charge_tokens("claude-haiku-4-5", 100000, 10000)
    try:
        r = runners(store, threads=1, admit=jobs_mod._admit)
        store.enqueue(tid, "t", owner=r.worker, bound=True)
        r.bind(tid, lambda: "never")
        assert _wait(lambda: TaskManager().get_task(tid).status.value == "failed")
    finally:
        spend_cap.disarm(st["cap_id"])
    assert "spend cap" in TaskManager().get_task(tid).error and tid not in r._bound


def test_cancel_requested_before_a_crash_ends_cancelled(store):
    _fake_running(store, "c1", "gone:1:x")
    store.cancel("c1")
    assert [c["action"] for c in store.recover(lambda t: False)] == [CANCELLED]
    assert store.get("c1")["status"] == CANCELLED


def test_live_pid_on_this_host_survives_a_long_pause(store):
    import os
    import socket
    token = f"{socket.gethostname()}:{os.getpid()}:sleepy"
    store.register_worker(token, {})
    with store._db(immediate=True) as conn:
        conn.execute("UPDATE job_workers SET heartbeat_at = ? WHERE worker = ?", (time.time() - 3600, token))
    _fake_running(store, "nap", token)
    with store._db(immediate=True) as conn:
        conn.execute("UPDATE jobs SET lease_until = 0 WHERE job_id = 'nap'")
    assert store.recover(store.worker_alive_fn(stale_after_s=10)) == []


def test_lost_lease_is_reported_and_its_outcome_dropped(store):
    _fake_running(store, "l1", "a:1:x")
    with store._db(immediate=True) as conn:
        conn.execute("UPDATE jobs SET worker = 'b:2:y' WHERE job_id = 'l1'")
    assert store.renew("a:1:x", ["l1"], 10) == {"l1"}
    assert store.finish("l1", "a:1:x", SUCCEEDED) is False


def test_slot_taken_requeues_without_using_an_attempt(store, runners):
    from app.jobs import SlotTaken
    tries = []

    def handler(p):
        tries.append(1)
        if len(tries) == 1:
            raise SlotTaken("full")
        return "ok"
    store.enqueue("st", "t", handler="h", max_attempts=1)
    runners(store, threads=1, handlers={"h": handler})
    assert _wait(lambda: store.get("st")["status"] == SUCCEEDED, 10)
    assert store.get("st")["attempts"] == 1 and len(tries) == 2


def test_claim_sees_jobs_behind_many_others(store, runners):
    for n in range(250):
        store.enqueue(f"other{n}", "t", owner="elsewhere:1:x", bound=True)
    store.enqueue("late", "t", handler="h", spends=False)
    runners(store, threads=1, handlers={"h": lambda p: "ok"})
    assert _wait(lambda: store.get("late")["status"] == SUCCEEDED)


def test_failed_queued_start_does_not_stay_queued(tmp_path, monkeypatch):
    import app.jobs as jobs_mod
    from app.services.simulation_runner import RunnerStatus, SimulationRunner
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    sid = "sim_f_" + uuid.uuid4().hex[:6]
    SimulationRunner.mark_queued(sid, "j")
    jobs_mod._on_end({"kind": "simulation_start", "subject": sid}, FAILED, "prepare files missing")
    st = SimulationRunner.get_run_state(sid)
    assert st.runner_status == RunnerStatus.FAILED and "prepare files missing" in st.error
    SimulationRunner._run_states.pop(sid, None)


def test_stale_starting_file_does_not_hold_a_slot(tmp_path, monkeypatch):
    from app.services.simulation_runner import RunnerStatus, SimulationRunner, SimulationRunState
    sid = "sim_s_" + uuid.uuid4().hex[:6]
    SimulationRunner._run_states[sid] = SimulationRunState(simulation_id=sid, runner_status=RunnerStatus.STARTING,
                                                           started_at="2020-01-01T00:00:00")
    try:
        before = SimulationRunner.active_run_count()
        SimulationRunner._run_states[sid].started_at = __import__("datetime").datetime.now().isoformat()
        assert SimulationRunner.active_run_count() == before + 1
    finally:
        SimulationRunner._run_states.pop(sid, None)


# ------------------------------------------------------------------ PR review threads


def test_runner_starts_after_every_route_exists(tmp_path, monkeypatch):
    from app import create_app, jobs
    jobs.stop_runner(timeout=5)
    monkeypatch.setenv("MM_TASK_DB_PATH", str(tmp_path / "t.sqlite"))
    seen = {}
    real = jobs.start_runner

    def spy(**kw):
        from app.jobs.replay import _APP
        seen["routes"] = {str(r) for r in _APP.url_map.iter_rules()}
        return real(**kw)
    monkeypatch.setattr(jobs, "start_runner", spy)
    create_app()
    try:
        assert "/api/jobs/<job_id>" in seen["routes"] and "/api/simulation/start" in seen["routes"]
    finally:
        jobs.stop_runner(timeout=5)


def test_workflow_jobs_keep_the_setup_token_boundary(app_env):
    from app import jobs
    from app.api.setup import SETUP_TOKEN
    jobs.store().enqueue("wf1", "workflow_people", spends=False)
    jobs.store().enqueue("mk1", "market_survey", spends=False)
    c = app_env.test_client()
    ids = {j["job_id"] for j in c.get("/api/jobs").get_json()["data"]}
    assert "mk1" in ids and "wf1" not in ids
    assert c.get("/api/jobs/wf1").status_code == 403
    assert c.post("/api/jobs/wf1/cancel").status_code == 403
    assert c.post("/api/jobs/wf1/retry", json={"approve_spend": True}).status_code == 403
    assert c.get("/api/jobs/wf1", headers={"X-Setup-Token": SETUP_TOKEN}).status_code == 200
    jobs.store().cancel("wf1")
    jobs.store().cancel("mk1")


def test_hidden_workflow_jobs_do_not_shorten_the_page(app_env):
    from app import jobs
    market = ["mk_p1", "mk_p2"]
    workflow = ["wf_p1", "wf_p2", "wf_p3"]
    for jid in market:
        jobs.store().enqueue(jid, "market_survey", spends=False)
        time.sleep(0.01)
    for jid in workflow:   # newer, so they fill the first page without the token
        jobs.store().enqueue(jid, "workflow_people", spends=False)
        time.sleep(0.01)
    c = app_env.test_client()
    rows = c.get("/api/jobs?limit=2").get_json()["data"]
    assert [j["job_id"] for j in rows] == ["mk_p2", "mk_p1"], rows
    non_ascii = c.get("/api/jobs?limit=2", headers={"X-Setup-Token": "é"})
    assert non_ascii.status_code == 200
    assert [j["job_id"] for j in non_ascii.get_json()["data"]] == ["mk_p2", "mk_p1"]
    for jid in market + workflow:
        jobs.store().cancel(jid)


def test_a_replaced_queued_start_does_not_run(app_env):
    from app import jobs
    from app.api import simulation as simulation_api
    sid = "sim_r_" + uuid.uuid4().hex[:6]
    jobs.store().enqueue("old_start", "simulation_start", subject=sid, lane="oasis", handler="replay")
    time.sleep(0.01)
    jobs.store().enqueue("new_start", "simulation_start", subject=sid, lane="oasis", handler="replay")
    ctx = jctx.JobContext(job_id="old_start", replay=True)
    token = jctx.activate(ctx)
    try:
        assert "replaced" in simulation_api._queued_start_gone(sid)
    finally:
        jctx.deactivate(ctx, token)
    for j in ("old_start", "new_start"):
        jobs.store().cancel(j)


def test_approval_resets_the_task_before_the_job_can_be_claimed(app_env, monkeypatch):
    from app import jobs
    from app.models.task import TaskManager, TaskStatus
    tm = TaskManager()
    tid = tm.create_task("held")
    tm.update_task(tid, status=TaskStatus.FAILED, error="needs approval")
    monkeypatch.setitem(jobs.GATES, "held", lambda running: False)
    jobs.store().enqueue(tid, "t", handler="replay", payload={"path": "/x"}, lane="held")
    with jobs.store()._db(immediate=True) as conn:
        conn.execute("UPDATE jobs SET status = 'needs_approval' WHERE job_id = ?", (tid,))
    seen = {}
    real = jobs.store().approve

    def approve(job_id):
        seen["task_status"] = TaskManager().get_task(job_id).status
        return real(job_id)
    monkeypatch.setattr(jobs.store(), "approve", approve)
    jobs.stop_runner(timeout=5)                    # nobody claims it during the check
    monkeypatch.setattr(jobs, "runner", lambda: type("R", (), {"wake": lambda self: None})())
    assert jobs.approve(tid)["status"] == QUEUED
    assert seen["task_status"] == TaskStatus.PENDING


def test_a_refused_approval_puts_the_task_back(app_env, monkeypatch):
    from app import jobs
    from app.models.task import TaskManager, TaskStatus
    monkeypatch.setitem(jobs.GATES, "held", lambda running: False)
    tm = TaskManager()
    tid = tm.create_task("done")
    tm.complete_task(tid, {"ok": True})
    jobs.store().enqueue(tid, "t", handler="replay", lane="held")
    with jobs.store()._db(immediate=True) as conn:
        conn.execute("UPDATE jobs SET status = 'succeeded' WHERE job_id = ?", (tid,))
    assert jobs.approve(tid) is None
    assert tm.get_task(tid).status == TaskStatus.COMPLETED


def test_first_call_is_refused_when_the_attempt_lost_its_claim():
    jctx.install()
    ctx = jctx.JobContext(job_id="stale")
    ctx.record_first_call = lambda: False
    token = jctx.activate(ctx)
    try:
        with pytest.raises(RuntimeError, match="no longer owns"):
            spend_cap.check()
    finally:
        jctx.deactivate(ctx, token)
    assert ctx.calls == 0


def test_note_first_call_reports_ownership(store):
    _fake_running(store, "own", "me:1:x")
    assert store.note_first_call("own", "me:1:x") is True
    assert store.note_first_call("own", "me:1:x") is True        # a concurrent call already recorded it: still ours
    assert store.note_first_call("own", "other:2:y") is False


def test_spend_cap_refuses_before_a_call_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("MM_SPEND_FILE", str(tmp_path / "cap4.json"))
    jctx.install()
    st = spend_cap.arm(0.01, "test")
    spend_cap.charge_tokens("claude-haiku-4-5", 100000, 10000)
    ctx = jctx.JobContext(job_id="capped")
    recorded = []
    ctx.record_first_call = lambda: recorded.append(1) or True
    token = jctx.activate(ctx)
    try:
        with pytest.raises(spend_cap.SpendCapReached):
            spend_cap.check()
    finally:
        jctx.deactivate(ctx, token)
        spend_cap.disarm(st["cap_id"])
    assert recorded == [] and ctx.calls == 0


def test_stop_keeps_claims_while_a_handler_still_runs(store):
    gate = threading.Event()
    r = JobRunner(store, threads=1, limits=_limits(), lease_s=1.0, poll_s=0.05,
                  handlers={"h": lambda p: gate.wait(10)}).start()
    store.enqueue("busy", "t", handler="h", spends=False)
    assert _wait(lambda: store.get("busy")["status"] == RUNNING)
    r.stop(timeout=0.2)
    assert r.worker in {w["worker"] for w in store.stats(stale_after_s=60)["workers"]}
    assert store.get("busy")["worker"] == r.worker
    gate.set()
    assert _wait(lambda: store.get("busy")["status"] == SUCCEEDED)


def test_outcome_write_is_retried_without_rerunning_the_handler(store, runners, monkeypatch):
    runs = []
    real = store.finish
    fails = {"n": 2}

    def flaky_finish(*a, **kw):
        if fails["n"]:
            fails["n"] -= 1
            raise RuntimeError("database is locked")
        return real(*a, **kw)
    monkeypatch.setattr(store, "finish", flaky_finish)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    store.enqueue("fw", "t", handler="h", spends=False)
    runners(store, threads=1, handlers={"h": lambda p: runs.append(1) or "ok"})
    assert _wait(lambda: store.get("fw")["status"] == SUCCEEDED)
    assert runs == [1]


def test_recovered_cancellation_reaches_the_task(app_env):
    from app.jobs.runner import _mirror_recovery
    from app.models.task import TaskManager
    tm = TaskManager()
    tid = tm.create_task("x")
    tm.release(tid)
    _mirror_recovery({"job_id": tid, "action": CANCELLED})
    t = tm.get_task(tid)
    assert t.status.value == "failed" and t.error == "cancelled"


def test_blocked_jobs_do_not_hide_an_eligible_one(store, runners):
    for n in range(600):
        store.enqueue(f"blocked{n}", "t", handler="h", lane="blocked", spends=False)
    store.enqueue("free", "t", handler="h", spends=False)
    runners(store, threads=1, handlers={"h": lambda p: "ok"}, gates={"blocked": lambda running: False})
    assert _wait(lambda: store.get("free")["status"] == SUCCEEDED, 15)


def test_admission_failure_unbinds_the_job(store, runners, tmp_path, monkeypatch):
    monkeypatch.setenv("MM_SPEND_FILE", str(tmp_path / "cap5.json"))
    import app.jobs as jobs_mod
    st = spend_cap.arm(0.01, "test")
    spend_cap.charge_tokens("claude-haiku-4-5", 100000, 10000)
    discarded = []
    try:
        r = runners(store, threads=1, admit=jobs_mod._admit)
        store.enqueue("closure_only", "t", owner=r.worker, bound=True)
        r.bind("closure_only", lambda: "never", on_discard=lambda: discarded.append(1))
        assert _wait(lambda: store.get("closure_only")["status"] == FAILED)
    finally:
        spend_cap.disarm(st["cap_id"])
    assert store.get("closure_only")["bound"] is False and discarded == [1]
    with pytest.raises(ValueError):
        store.approve("closure_only")


def test_cancel_recorded_during_an_attempt_wins_over_a_requeue(store):
    _fake_running(store, "cr", "me:1:x")
    store.cancel("cr")
    assert store.finish("cr", "me:1:x", QUEUED, retry_in=1) == CANCELLED
    assert store.get("cr")["status"] == CANCELLED


def test_recovery_reads_heartbeats_in_its_own_transaction(store):
    import os
    import socket
    token = f"{socket.gethostname()}:{os.getpid()}:fresh"
    store.register_worker(token, {})
    _fake_running(store, "fresh_job", token)
    assert store.recover(stale_after_s=60) == []
    assert store.get("fresh_job")["status"] == RUNNING


def test_task_cleanup_is_skipped_when_the_queue_cannot_be_read(app_env, monkeypatch):
    from app import jobs
    from app.models.task import TaskManager, TaskStatus
    tm = TaskManager()
    tid = tm.create_task("maybe queued")
    tm.release(tid)

    def broken():
        raise RuntimeError("queue database unavailable")
    monkeypatch.setattr(jobs.store(), "active_ids", broken)
    assert tm.recover_interrupted_tasks() == 0
    assert tm.get_task(tid).status == TaskStatus.PENDING


def test_mirror_changes_only_its_own_columns(app_env):
    from app.models.task import TaskManager, TaskStatus
    tm = TaskManager()
    tid = tm.create_task("x")
    tm.update_task(tid, status=TaskStatus.PROCESSING, progress=70, result={"partial": 1})
    tm.release(tid)                               # owned by "another process" now
    tm.mirror(tid, message="note")
    t = tm.get_task(tid)
    assert t.progress == 70 and t.result == {"partial": 1} and t.message == "note"
    assert t.status == TaskStatus.PROCESSING


def test_cancelling_a_queued_report_releases_its_graph_reader(app_env, monkeypatch):
    from app import jobs
    from app.models.task import TaskManager
    from app.utils.zep_lifecycle import get_graph_readers, register_graph_reader, unregister_graph_reader
    gid, rid = "g_" + uuid.uuid4().hex[:6], "r_" + uuid.uuid4().hex[:6]
    register_graph_reader(gid, rid)
    monkeypatch.setitem(jobs.GATES, "held", lambda running: False)     # keep the job queued
    tid = TaskManager().create_task("report")
    jobs.submit(tid, lambda: None, kind="report_generate", lane="held",
                on_discard=lambda: unregister_graph_reader(gid, rid))
    assert rid in get_graph_readers(gid)
    jobs.cancel(tid)
    assert rid not in get_graph_readers(gid)
    assert TaskManager().get_task(tid).error == "cancelled"
