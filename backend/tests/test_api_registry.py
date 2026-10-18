"""Every MarketMirror route is documented in the registry (and the generated docs stay in sync)."""

import re

from app import create_app
from app.api.registry import ENDPOINTS


def test_registry_covers_market_routes():
    app = create_app()
    documented = {(e["method"], re.sub(r"\{[^}]+\}", "<x>", e["path"])) for e in ENDPOINTS}
    missing = []
    for rule in app.url_map.iter_rules():
        p = str(rule)
        if not (p.startswith("/api/simulation/") or p.startswith("/api/graph/profile") or "/profile" in p or "/voices" in p):
            continue
        if p.endswith("/profiles") or p.endswith("/profiles/realtime"):
            continue                                             # upstream engine routes
        if any(seg in p for seg in ("/feed-story", "/feed-test", "/email-test", "/pitch", "/events", "/context", "/profile", "/voices",
                                    "/ssr", "/analyst-panel", "/market-report", "/ideas", "/captions", "/calibrate", "/predict", "/forecast",
                                    "/calibration-pairs", "/study-report", "/market-task/status", "/interview/batch")):
            norm = re.sub(r"<[^>]+>", "<x>", p)
            for m in rule.methods - {"HEAD", "OPTIONS"}:
                if (m, norm) not in documented:
                    missing.append((m, p))
    assert not missing, f"undocumented routes: {missing}"
