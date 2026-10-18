"""Calibration store, fits, predictions with intervals and targets, forecast, and the API."""

import json

from app.services import predict as pr


def test_store_fit_and_predict(tmp_path):
    path = str(tmp_path / "store.json")
    assert pr.fit("Fitloop", "ctr", path=path)["basis"] == "uncalibrated prior"
    p0 = pr.predict(4.0, "ctr", "Fitloop", target=2.0, path=path)
    assert p0["predicted"] == 4.0 and p0["pairs"] == 0 and p0["low"] < 4.0 < p0["high"] and 0 < p0["p_success"] < 1
    n = pr.add_pairs("Fitloop", "ctr", [{"sim": 4.0, "real": 2.0, "label": "a"}, {"sim": 6.0, "real": 2.9}, {"sim": "bad"}], "backtest", path)
    assert n == 2
    f = pr.fit("Fitloop", "ctr", path=path)
    assert f["n"] == 2 and 0.45 < f["factor"] < 0.55 and "Fitloop" in f["basis"]
    p1 = pr.predict(4.0, "ctr", "Fitloop", target=1.5, path=path)
    assert 1.8 < p1["predicted"] < 2.2 and p1["pairs"] == 2 and p1["p_success"] > 0.5
    # another brand borrows the pool, and says so
    f2 = pr.fit("Other", "ctr", path=path)
    assert f2["n"] == 2 and "other brands" in f2["basis"]
    # lower-is-better targets
    pc = pr.predict(10.0, "cpl", "Fitloop", target=12.0, higher_is_better=False, path=path)
    assert pc["p_success"] > 0.5


def test_predict_run_and_forecast(tmp_path):
    path = str(tmp_path / "store.json")
    feed = {"summary": {"ranked": ["a", "b"], "per_creative": {"a": {"expected_ctr": 5.0, "projection": {"cpl": 8.0, "cpm": 2.0, "budget": 300, "currency": "USD"},
                                                                     "landing": {"conversion_after_click": 10.0}},
                                                               "b": {"expected_ctr": 1.0, "projection": {"cpl": 30.0, "cpm": 2.0, "budget": 300}}}}}
    summary = {"marketing": {"overall": {"convert_yes": 4.0}, "by_segment": [{"key": "Students", "convert_yes": 10.0}]}}
    out = pr.predict_run(summary, feed, "Fitloop", {"ctr": 2.0}, path=path)
    whats = [p["what"] for p in out["predictions"]]
    assert "CTR of a" in whats and "cost per lead of a" in whats and "would convert: Students" in whats
    assert out["calibrated"] is False and "No real results" in out["note"]
    story = {"brand_posts": [{"quotes": [1, 2, 3], "reposts": 2, "comments": [1, 2], "reach_proxy": 40}, {"quotes": [], "reposts": 0, "comments": [], "reach_proxy": 10}]}
    kf = pr.k_factor(story)
    assert 0 < kf["k"] <= 2.0 and kf["posts"] == 2
    fc = pr.forecast_run(feed, story, spend=600, days=90)
    assert fc["creative"] == "a" and fc["customers_total"] > 0 and fc["curve"][-1]["day"] == 90 and fc["cac"] is not None
    assert fc["spend_total"] == 1800.0
    assert pr.forecast_run({"summary": {"per_creative": {}}}, {}, None) is None
    assert pr.k_factor({})["k"] == 0.0


def test_predict_api(monkeypatch, tmp_path):
    from app import create_app
    from app.services import predict as svc
    monkeypatch.setattr(svc, "STORE", str(tmp_path / "s.json"))
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    assert c.post("/api/simulation/predict", json={}).status_code == 400
    r = c.post("/api/simulation/calibration-pairs", json={"brand": "Fitloop", "metric": "ctr", "pairs": [{"sim": 4, "real": 2}], "source": "test"})
    assert r.get_json()["data"]["stored"] == 1
    g = c.get("/api/simulation/calibration-pairs?brand=Fitloop").get_json()["data"]
    assert g["pairs"] == 1 and g["fits"]["ctr"]["n"] == 1
    feed = {"summary": {"ranked": ["a"], "per_creative": {"a": {"expected_ctr": 5.0, "projection": {"cpm": 2.0, "budget": 300}}}}}
    r = c.post("/api/simulation/predict", json={"brand": "Fitloop", "summary": {}, "feed_test": feed, "targets": {"ctr": 2}})
    d = r.get_json()["data"]
    assert d["calibrated"] is True and d["predictions"][0]["predicted"] == 2.5
    f = c.post("/api/simulation/forecast", json={"feed_test": feed, "spend": 300})
    assert f.status_code == 200 and f.get_json()["data"]["customers_total"] >= 0
    assert c.post("/api/simulation/forecast", json={"feed_test": {}}).status_code == 400
