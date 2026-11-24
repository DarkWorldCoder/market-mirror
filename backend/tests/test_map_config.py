"""The workspace map's tile hosts come from MM_MAP_TILES, so a production install can use its own or none."""
from app import create_app
from app.api.workflows import map_config


def test_default_uses_openfreemap_and_nasa(monkeypatch):
    monkeypatch.delenv("MM_MAP_TILES", raising=False)
    cfg = map_config()
    assert cfg["mode"] == "openfreemap"
    assert cfg["streets"].startswith("https://tiles.openfreemap.org/")
    assert "gibs.earthdata.nasa.gov" in cfg["satellite"]


def test_off_makes_no_outside_requests(monkeypatch):
    monkeypatch.setenv("MM_MAP_TILES", "off")
    cfg = map_config()
    assert cfg["mode"] == "off"
    assert not any(cfg[k] for k in ("streets", "dark", "satellite", "glyphs"))


def test_custom_reads_own_hosts(monkeypatch):
    monkeypatch.setenv("MM_MAP_TILES", "custom")
    monkeypatch.setenv("MM_MAP_STYLE_URL", "https://tiles.example.test/style.json")
    monkeypatch.delenv("MM_MAP_DARK_STYLE_URL", raising=False)
    monkeypatch.delenv("MM_MAP_SATELLITE_TILES", raising=False)
    cfg = map_config()
    assert cfg["streets"] == cfg["dark"] == "https://tiles.example.test/style.json"
    assert cfg["satellite"] is None


def test_route_serves_config(monkeypatch):
    monkeypatch.setenv("MM_MAP_TILES", "off")
    client = create_app().test_client()
    res = client.get("/geo/map-config.json")
    assert res.status_code == 200
    assert res.get_json()["mode"] == "off"
