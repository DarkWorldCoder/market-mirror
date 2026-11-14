#!/usr/bin/env python3
"""Build the no-install example gallery (docs/gallery/) from finished runs.

    python docs/make_gallery.py --runs-root /path/to/repo   # reads docs/gallery/gallery.json

Each entry in gallery.json names a finished run folder (relative to --runs-root) with an invented brand. The run is
re-rendered offline with the current dashboard exporter after every local file path is removed from its data, gets a
banner saying the brand is invented and every number simulated, and is written to docs/gallery/<slug>/index.html.
docs/gallery/index.html lists the entries (and any "link" entries, such as the existing /demo/). Stdlib only.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from typing import Any, Dict, List

DOCS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(DOCS)
sys.path.insert(0, os.path.join(REPO, "backend", "claude_cli"))

import exporter  # noqa: E402

GALLERY = os.path.join(DOCS, "gallery")
# local paths in run files (home folders, temp folders, Windows profiles) never reach a public page
_PATHS = re.compile(r"(/home/[^/\s\"']+|/Users/[^/\s\"']+|[A-Za-z]:\\\\?Users\\\\?[^\\\s\"']+|/tmp/[^\s\"']*|/private/[^\s\"']*)"
                    r"[^\s\"'<>]*")
BANNER = ('<div role="note" style="position:sticky;top:0;z-index:50;padding:10px 16px;background:#f3d64b;color:#111;'
          'font:600 14px/1.4 system-ui,sans-serif;text-align:center">Example run: {brand} is an invented brand and every '
          'number is simulated. <a href="../" style="color:#111">More examples</a> · '
          '<a href="https://github.com/DarkWorldCoder/market-mirror" style="color:#111">Run your own</a></div>')


def scrub(value: Any) -> Any:
    """The same data with every local file path replaced by its file name."""
    if isinstance(value, str):
        return _PATHS.sub(lambda m: os.path.basename(m.group(0).rstrip("/\\")) or "", value)
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    return value


def build_one(entry: Dict[str, Any], runs_root: str) -> Dict[str, Any]:
    run_dir = os.path.join(runs_root, entry["run_dir"])
    bundle = scrub(exporter.load_run_dir(run_dir))
    page, _, summary = exporter.render_dashboard(bundle, title=entry.get("title"))
    page = page.replace("<body>", "<body>" + BANNER.format(brand=html.escape(entry.get("brand") or "This brand")), 1)
    if _PATHS.search(page):
        raise SystemExit(f"{entry['slug']}: a local path is still in the page; not writing it")
    out = os.path.join(GALLERY, entry["slug"])
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    mk = summary.get("marketing") or {}
    return {**entry, "href": f"{entry['slug']}/", "people": mk.get("people") or summary.get("agents"),
            "size_kb": len(page.encode()) // 1024}


def index_page(cards: List[Dict[str, Any]]) -> str:
    items = "".join(
        f'<li><a href="{html.escape(c["href"])}"><strong>{html.escape(c["title"])}</strong></a>'
        f'<span>{html.escape(c.get("about") or "")}</span>'
        f'<small>{html.escape(", ".join(x for x in (str(c["people"]) + " simulated people" if c.get("people") else "", c.get("tests") or "") if x))}'
        f'</small></li>' for c in cards)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>MarketMirror example runs</title>
<meta name="description" content="Finished MarketMirror dashboards you can open in the browser: invented brands, simulated buyers, no install or API key.">
<link rel="canonical" href="https://darkworldcoder.github.io/market-mirror/gallery/">
<style>
:root{{--bg:#fbfaf6;--fg:#141414;--muted:#5b5b5b;--card:#fff;--line:#e4e1d8;--accent:#f3d64b}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141414;--fg:#f2f0ea;--muted:#a9a59b;--card:#1e1e1e;--line:#333}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:40px 16px}}
h1{{font-size:28px;margin:0 0 8px}} p{{color:var(--muted)}}
ul{{list-style:none;padding:0;display:grid;gap:12px}}
li a{{color:var(--fg)}} li{{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--accent);border-radius:10px;padding:14px 16px;display:grid;gap:4px}}
li span{{color:var(--muted)}} li small{{color:var(--muted)}}
</style></head><body><main>
<h1>Example runs</h1>
<p>Finished MarketMirror dashboards you can open right here: no install, no API key. Every brand is invented and every
number comes from simulated buyers, so read them as directions, not measurements.</p>
<ul>{items}</ul>
<p><a href="https://github.com/DarkWorldCoder/market-mirror">Run your own test</a> · <a href="../">MarketMirror home</a></p>
</main></body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs-root", default=REPO, help="folder the run_dir paths in gallery.json are relative to")
    ap.add_argument("--spec", default=os.path.join(GALLERY, "gallery.json"))
    a = ap.parse_args()
    with open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    cards = []
    for entry in spec:
        if entry.get("link"):
            cards.append({**entry, "href": entry["link"]})
        else:
            cards.append(build_one(entry, a.runs_root))
            print(f"wrote gallery/{entry['slug']}/index.html ({cards[-1]['size_kb']} KB)")
    with open(os.path.join(GALLERY, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_page(cards))
    print(f"wrote gallery/index.html ({len(cards)} examples)")


if __name__ == "__main__":
    main()
