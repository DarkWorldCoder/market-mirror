"""Audience from web analytics: GA4 and PostHog exports in their real shapes, shares without double counting across
breakdowns, nothing invented for a country the data leaves out, contact details never read, and a persona spec the
planner accepts."""

import json

from app.services import analytics_audience as aa
from app.services import persona_planner as pp

GA4_CSV = """# ----------------------------------------
# Demo store
# Start date: 20261001
# End date: 20261031
# ----------------------------------------
Country,City,Active users,Key events
United States,New York,4200,210
United States,Los Angeles,2600,104
United States,(not set),700,10
India,Mumbai,2100,21
India,Bengaluru,1500,30
United Kingdom,London,900,27
Germany,Berlin,300,3
Grand total,,12300,405

Country,Age,Active users
United States,25-34,1500
United States,35-44,1100
United States,18-24,500
United States,45-54,300
United States,unknown,4000
India,18-24,900
India,25-34,1200
India,unknown,1400

Country,Gender,Active users
United States,female,1800
United States,male,1500
United States,unknown,4200
India,male,1500
India,female,700
India,unknown,1400

Country,Device category,Session default channel group,Active users
United States,mobile,Organic Search,3000
United States,desktop,Organic Search,1600
United States,mobile,Paid Social,2200
United States,mobile,Direct,700
India,mobile,Organic Social,2800
India,desktop,Organic Search,800
United Kingdom,desktop,Referral,900
Germany,desktop,Direct,300
"""


def ga4(tmp_path):
    p = tmp_path / "ga4.csv"
    p.write_text(GA4_CSV, encoding="utf-8")
    return aa.read_sources([str(p)])


def test_ga4_csv_tables_period_and_shares(tmp_path):
    rows, meta = ga4(tmp_path)
    a = aa.analyse(rows, meta)
    assert a["source"] == "ga4" and a["period"] == "2026-10-01 to 2026-10-31" and a["tables"] == 4
    assert a["users"] == 12300                      # the grand-total row is skipped, not counted
    # country shares come from one table (the largest), not the four tables added together
    assert a["dimensions"]["country"]["shares"]["United States"] == round(7500 / 12300, 3)
    us = a["by"]["country"]["United States"]
    assert us["city"]["shares"] == {"New York": round(4200 / 6800, 3), "Los Angeles": round(2600 / 6800, 3)}
    assert us["city"]["unknown_share"] == round(700 / 7500, 3)
    assert us["age"]["shares"]["25-34"] == round(1500 / 3400, 3) and "unknown" not in us["age"]["shares"]
    assert us["key_events_per_user"] == round(324 / 7500, 4)
    assert "United Kingdom" not in {k for k, v in a["by"]["country"].items() if "age" in v}


def test_spec_segments_population_and_nothing_invented(tmp_path):
    rows, meta = ga4(tmp_path)
    res = aa.run(rows, meta, people=20)
    segs = {s["country"]: s for s in res["segments"]}
    assert list(segs) == ["United States", "India", "United Kingdom"]          # Germany is under 5% of users
    assert sum(s["count"] for s in res["segments"]) == 20 and res["left_out_share"] == round(300 / 12300, 3)
    us = segs["United States"]
    assert us["cities"] == ["New York", "Los Angeles"] and (us["age_min"], us["age_max"]) == (18, 44)
    assert us["gender_mix"] == "0.55" and us["source"] == "analytics"
    assert "Organic Search 61%" in us["notes"] and "per 100 users" in us["notes"] and "not the whole market" in us["notes"]
    # the age table is per country and leaves the UK out: its age and gender stay unknown, not borrowed
    uk = segs["United Kingdom"]
    assert "age_min" not in uk and "gender_mix" not in uk and "United Kingdom" not in res["population"]
    assert res["population"]["India"]["gender"] == {"male": 0.682, "female": 0.318}
    assert res["population"]["India"]["scope"] == "country"
    assert any("Google signals" in c and "5,500 of 12,300" in c for c in res["caveats"])
    md = aa.render_markdown(res)
    assert "| United Kingdom visitors | 1 | United Kingdom | London | unknown | unknown |" in md
    assert "No other column was read." in md


def test_channel_segments_take_the_channels_own_country(tmp_path):
    rows, meta = ga4(tmp_path)
    res = aa.run(rows, meta, people=12, segment_by="channel")
    by = {s["label"]: s for s in res["segments"]}
    assert by["Organic Social visitors"]["country"] == "India"
    assert by["Organic Social visitors"]["cities"] == ["Mumbai", "Bengaluru"]
    assert by["Referral visitors"]["country"] == "United Kingdom"
    assert "came from Organic Search" in by["Organic Search visitors"]["notes"]
    assert "whole-site figures" in by["Organic Search visitors"]["notes"]


def test_ga4_data_api_responses():
    def report(dims, mets, rows):
        return {"dimensionHeaders": [{"name": d} for d in dims], "metricHeaders": [{"name": m} for m in mets],
                "rows": [{"dimensionValues": [{"value": v} for v in r[:len(dims)]],
                          "metricValues": [{"value": str(v)} for v in r[len(dims):]]} for r in rows],
                "metadata": {"dateRanges": [{"startDate": "2026-08-01", "endDate": "2026-10-31"}]}}
    batch = {"reports": [report(["country", "city"], ["activeUsers"], [["Brazil", "São Paulo", 800], ["Mexico", "CDMX", 200]]),
                         report(["country", "userAgeBracket"], ["activeUsers"], [["Brazil", "25-34", 300], ["Brazil", "65+", 100]])]}
    rows, meta = aa.rows_from_json(batch, "api")
    res = aa.run(rows, meta, people=5)
    assert res["analysis"]["source"] == "ga4" and res["analysis"]["period"] == "2026-08-01 to 2026-10-31"
    br = res["segments"][0]
    assert br["country"] == "Brazil" and br["count"] == 4 and br["cities"] == ["São Paulo"]
    assert (br["age_min"], br["age_max"]) == (25, 80) and res["population"]["Brazil"]["age"] == {"25-34": 0.75, "65+": 0.25}


def test_posthog_hogql_and_persons_never_read_contact_details(tmp_path):
    hogql = {"columns": ["country", "city", "device", "source", "count(distinct person_id)"],
             "results": [["Canada", "Toronto", "Desktop", "google", 40], ["Canada", "Vancouver", "Mobile", "newsletter", 20],
                         ["India", "Pune", "Mobile", "instagram", 40]]}
    rows, meta = aa.rows_from_json(hogql, "hogql")
    res = aa.run(rows, meta, people=10)
    assert res["analysis"]["source"] == "posthog" and res["analysis"]["weight"] == "users"
    assert [s["country"] for s in res["segments"]] == ["Canada", "India"]
    persons = {"results": [
        {"id": "1", "properties": {"email": "jane@example.com", "name": "Jane Doe", "$geoip_country_name": "Canada",
                                   "$geoip_city_name": "Toronto", "$initial_utm_source": "google"}},
        {"id": "2", "properties": {"email": "raj@example.com", "$geoip_country_name": "India", "$device_type": "Mobile"}},
        {"id": "3", "properties": {"$geoip_country_name": "Canada"}}]}
    p = tmp_path / "persons.json"
    p.write_text(json.dumps(persons), encoding="utf-8")
    rows, meta = aa.read_sources([str(p)])
    res = aa.run(rows, meta, people=3)
    out = json.dumps(res) + aa.render_markdown(res)
    assert "example.com" not in out and "Jane" not in out and "jane" not in out
    assert res["analysis"]["tables"] == 1                      # missing properties do not split the people into tables
    assert res["segments"][0]["country"] == "Canada" and res["segments"][0]["count"] == 2
    assert any("each row counts as one person" in c for c in res["caveats"])


def test_one_list_mixing_breakdowns_is_not_double_counted():
    rows = [{"country": "France", "city": "Paris", "users": 600}, {"country": "France", "city": "Lyon", "users": 400},
            {"country": "Spain", "city": "Madrid", "users": 500},
            {"country": "France", "gender": "female", "users": 300}, {"country": "France", "gender": "male", "users": 100}]
    a = aa.analyse([{**r, "_table": "agent"} for r in rows])
    assert a["tables"] == 2 and a["users"] == 1500
    assert a["dimensions"]["country"]["shares"] == {"France": round(1000 / 1500, 3), "Spain": round(500 / 1500, 3)}
    assert a["by"]["country"]["France"]["gender"]["shares"] == {"female": 0.75, "male": 0.25}


def test_map_for_renamed_columns_and_clear_errors():
    rows = [{"Market": "Kenya", "Visitors": "1,200", "_table": "x"}, {"Market": "Nigeria", "Visitors": "800", "_table": "x"}]
    res = aa.run(rows, {}, field_map={"country": "Market", "users": "Visitors"}, people=4)
    assert [(s["country"], s["count"]) for s in res["segments"]] == [("Kenya", 2), ("Nigeria", 2)]
    try:
        aa.run([{"foo": 1, "_table": "x"}], {})
        raise AssertionError("expected an error")
    except ValueError as e:
        assert "--map" in str(e)
    try:
        aa.run(rows, {}, field_map={"country": "Market"}, segment_by="channel")
        raise AssertionError("expected an error")
    except ValueError as e:
        assert "no channel" in str(e)


def test_merge_keeps_the_owners_segments_and_shares(tmp_path):
    rows, meta = ga4(tmp_path)
    built = aa.run(rows, meta, people=20)
    own = {"segments": [{"label": "Teachers", "count": 5, "country": "India"}],
           "population": {"India": {"age": {"25-34": 1.0}}}}
    spec = aa.merge_into_spec(built, own)
    assert spec["segments"][0]["label"] == "Teachers" and len(spec["segments"]) == 4
    assert spec["population"]["India"] == {"age": {"25-34": 1.0}}          # the owner's shares win
    assert spec["population"]["United States"]["source"] == "analytics"
    again = aa.merge_into_spec(built, spec)                                  # a re-run replaces, never stacks
    assert len(again["segments"]) == 4
    assert aa.merge_into_spec(built, own, replace=True)["population"]["India"]["source"] == "analytics"
    only = aa.merge_into_spec(built, own, population_only=True)
    assert only["segments"] == own["segments"] and "United States" in only["population"]


def test_planner_accepts_the_spec(tmp_path):
    rows, meta = ga4(tmp_path)
    spec = pp.PersonaSpec.from_dict(aa.merge_into_spec(aa.run(rows, meta, people=20), {}))
    us = next(s for s in spec.segments if s.country == "United States")
    assert (us.age_min, us.age_max, us.count) == (18, 44, 13) and pp._female_share(us.gender_mix) == 0.55
    assert spec.population["United States"]["age"]["25-34"] == round(1500 / 3400, 3)
