"""The world map must not merge Singapore into Malaysia."""

from claude_cli import geo_view


def test_singapore_is_off_map_not_malaysia():
    assert geo_view.geo_name("sg") is None
    assert geo_view.geo_name("Singapore") is None
    assert geo_view.geo_name("Malaysia") == "Malaysia"


def test_both_countries_keep_their_own_row():
    bundle = {"config": {"persona_index": [
        {"country": "Singapore", "kind": "persona", "agent_id": 1},
        {"country": "Malaysia", "kind": "persona", "agent_id": 2},
    ]}}
    rows = {row["country"]: row for row in geo_view.country_rows(bundle)}
    assert rows["Singapore"]["people"] == 1 and rows["Singapore"]["geo"] is None
    assert rows["Malaysia"]["people"] == 1 and rows["Malaysia"]["geo"] == "Malaysia"
