"""geo_tiers: aliases, known(), spread() rounding, city vs national mode and seed reuse."""

import random

from app.services.geo_tiers import country_key, known, spread

SETTLEMENTS = ("metro", "city", "town", "rural")


def test_country_key_aliases_and_normalisation():
    assert country_key("usa") == "united states"
    assert country_key("USA") == "united states"
    assert country_key("uk") == "united kingdom"
    assert country_key("UK") == "united kingdom"
    assert country_key("ph") == "philippines"
    assert country_key("philippines") == "philippines"
    assert country_key("türkiye") == "turkey"
    assert country_key("in") == "india"
    assert country_key("  India ") == "india"          # strip + lower
    assert country_key(None) == ""
    assert country_key("atlantis") == "atlantis"       # unknown passes through unchanged


def test_known():
    assert known("India")
    assert known("usa")
    assert known("Philippines")
    assert not known("Atlantis")
    assert not known("")
    assert not known(None)


def test_spread_returns_exactly_n_pairs_for_several_n_and_mixes():
    for n in (1, 3, 5, 12, 25):
        for mode in ("cities", "national"):
            out = spread("India", ["Pune"], n, random.Random(0), mode=mode)
            assert len(out) == n
            assert all(isinstance(x, tuple) and len(x) == 2 for x in out)
            assert all(t in SETTLEMENTS for _, t in out)
    # custom mix still yields exactly n pairs over all four tiers
    out = spread("India", ["Pune"], 13, random.Random(1), mode="national",
                 mix={"metro": 0.6, "city": 0.2, "town": 0.1, "rural": 0.1})
    assert len(out) == 13
    assert {t for _, t in out} == set(SETTLEMENTS)


def test_mode_cities_stays_in_the_given_cities():
    for n in (1, 5, 12):
        out = spread("India", ["Pune"], n, random.Random(2), mode="cities")
        assert len(out) == n
        assert {p for p, _ in out} == {"Pune"}
    out = spread("India", ["Pune", "Mumbai"], 20, random.Random(3), mode="cities")
    assert set(p for p, _ in out) <= {"Pune", "Mumbai"}


def test_auto_switches_to_national_at_n_ge_12():
    small = spread("India", ["Pune"], 11, random.Random(4), mode="auto")
    assert {t for _, t in small} <= {"metro", "city"}  # cities mode: only metro/city
    big = spread("India", ["Pune"], 12, random.Random(5), mode="auto")
    assert {t for _, t in big} == set(SETTLEMENTS)     # national mode spreads over all tiers


def test_unknown_country_with_no_cities_returns_empty_places_not_an_error():
    for n in (1, 5):
        out = spread("Atlantis", [], n, random.Random(6), mode="auto")
        assert len(out) == n
        assert all(p == "" for p, _ in out)
    # with given places it uses them instead
    out = spread("Atlantis", ["Town X"], 3, random.Random(7), mode="auto")
    assert {p for p, _ in out} == {"Town X"}


def test_same_seed_gives_same_result():
    args = ("India", ["Pune"], 17)
    a = spread(*args, mode="national", rng=random.Random(99))
    b = spread(*args, mode="national", rng=random.Random(99))
    assert a == b
