"""Calibration diagnostics (overlap, conditional calibration, stability) and the AIPW correction on synthetic data."""

import random

from app.services import calibration as cal


def _panel(n, rng, bias=0.0, shift_country=None):
    rows = []
    for i in range(n):
        seg = rng.choice(["students", "parents"])
        country = rng.choice(["India", "Philippines"]) if shift_country is None else shift_country
        gender = rng.choice(["female", "male"])
        age = rng.randint(18, 60)
        base = {"students": 0.3, "parents": 0.5}[seg] + (0.1 if country == "Philippines" else 0.0)
        y = 1.0 if rng.random() < min(0.95, max(0.02, base + bias)) else 0.0
        rows.append({"segment": seg, "country": country, "gender": gender, "age": age, "y": y})
    return rows


def test_overlap_good_and_bad():
    rng = random.Random(1)
    syn, real = _panel(300, rng), _panel(120, rng)
    ov = cal.overlap(syn, real)
    assert ov["auc"] < 0.7 and ov["ess_ratio"] > 0.5 and ov["verdict"] == "ok"
    real_far = _panel(120, rng, shift_country="Kenya")               # nobody synthetic lives there
    ov2 = cal.overlap(syn, real_far)
    assert ov2["auc"] > 0.95 and ov2["verdict"] == "walk-away"


def test_conditional_calibration_and_verdicts():
    rng = random.Random(2)
    syn = _panel(400, rng)
    real_same = _panel(200, rng)
    c = cal.conditional_calibration(syn, real_same)
    assert set(c["by_group"]) == {"students", "parents"}
    assert all(v["verdict"] in ("trust", "correct") for v in c["by_group"].values())
    real_biased = _panel(200, rng, bias=0.25)                        # synthetic panel too pessimistic everywhere
    c2 = cal.conditional_calibration(syn, real_biased)
    assert all(v["verdict"] in ("correct", "walk-away") for v in c2["by_group"].values())
    assert cal.conditional_calibration(syn, real_same[:3])["by_group"]["students"]["verdict"] == "walk-away"


def test_aipw_recovers_the_real_mean_when_synthetic_is_biased():
    rng = random.Random(3)
    syn = _panel(600, rng, bias=-0.2)                                 # synthetic under-estimates by 20 points
    real = _panel(150, rng)
    out = cal.correct(syn, real)
    assert out["estimate"] is not None and out["se"] is not None
    assert abs(out["estimate"] - out["real_mean"]) < 0.08              # close to the real sample
    assert abs(out["naive_syn"] - out["real_mean"]) > 0.12             # while the raw synthetic mean is far off
    assert cal.correct(syn, real[:5])["estimate"] is None


def test_stability_and_spearman():
    assert cal.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert cal.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0
    assert cal.spearman([1, 2], [1, 2]) is None
    good = cal.stability([{"a": 0.1, "b": 0.3, "c": 0.5, "d": 0.7}, {"a": 0.12, "b": 0.25, "c": 0.55, "d": 0.6}])
    assert good["verdict"] == "ok" and good["min_rho"] == 1.0
    bad = cal.stability([{"a": 0.1, "b": 0.3, "c": 0.5, "d": 0.7}, {"a": 0.7, "b": 0.5, "c": 0.3, "d": 0.1}])
    assert bad["verdict"] == "walk-away"
    assert cal.stability([{"a": 1}])["verdict"] == "unknown"


def test_diagnose_overall():
    rng = random.Random(4)
    syn, real = _panel(300, rng), _panel(120, rng)
    d = cal.diagnose(syn, real)
    assert d["verdict"] in ("trust", "correct") and d["corrected"]["estimate"] is not None
    assert "overlap" in d and "weights" not in d["overlap"] and d["reading"]
    far = cal.diagnose(syn, _panel(120, rng, shift_country="Kenya"))
    assert far["verdict"] == "walk-away"


def test_calibrate_api():
    from app import create_app
    rng = random.Random(5)
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    assert c.post("/api/simulation/calibrate", json={"synthetic": [], "real": []}).status_code == 400
    r = c.post("/api/simulation/calibrate", json={"synthetic": _panel(200, rng), "real": _panel(80, rng), "field": "would_convert"})
    assert r.status_code == 200
    d = r.get_json()["data"]
    assert d["verdict"] in ("trust", "correct", "mixed") and d["field"] == "would_convert" and "reading" in d
