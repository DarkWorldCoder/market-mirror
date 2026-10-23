"""Capture the README screenshots from a run's dashboard.html with the system Chrome (Playwright, channel "chrome").

    backend/.venv/bin/python scripts/readme_screenshots.py mirofish_runs/<run>/dashboard.html --out docs/images

Writes the light and dark hero (dashboard-results.png, dashboard-dark.png) and one image per dashboard section,
1600 px wide, each cut at MAX_HEIGHT so long sections stay readable in the README.
"""

import argparse
import os
import sys

from playwright.sync_api import sync_playwright

WIDTH, SCALE, MAX_HEIGHT = 1280, 1.25, 1700
# README image -> dashboard section id(s); several ids are captured together, top of the first to bottom of the last
SECTIONS = {
    "glance.png": ["kpis", "decision"],
    "map.png": ["worldmap"],
    "report.png": ["report"],
    "results.png": ["results"],
    "models.png": ["models"],
    "playbook.png": ["playbook"],
    "pitch.png": ["pitch"],
    "feed-test.png": ["feedtest"],
    "social-feed.png": ["socialfeed"],
    "audiences.png": ["audiences"],
    "objections.png": ["objections"],
    "messages.png": ["messages"],
    "pricing.png": ["pricing"],
    "analysts.png": ["analysts"],
    "people.png": ["agents"],
}


def settle(page, ms=900):
    page.wait_for_timeout(ms)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dashboard")
    ap.add_argument("--out", default="docs/images")
    ap.add_argument("--only", nargs="*", help="image names to capture (default: all)")
    a = ap.parse_args()
    url = "file://" + os.path.abspath(a.dashboard)
    os.makedirs(a.out, exist_ok=True)
    want = set(a.only or [])
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        for scheme, name in (("light", "dashboard-results.png"), ("dark", "dashboard-dark.png")):
            if want and name not in want:
                continue
            page = browser.new_page(viewport={"width": WIDTH, "height": round(1067 / SCALE)}, device_scale_factor=SCALE,
                                    color_scheme=scheme)
            page.goto(url, wait_until="load")
            settle(page, 1500)
            page.screenshot(path=os.path.join(a.out, name))
            print("wrote", name, flush=True)
            page.close()
        page = browser.new_page(viewport={"width": WIDTH, "height": 1000}, device_scale_factor=SCALE, color_scheme="light")
        page.goto(url, wait_until="load")
        settle(page, 1500)
        # the sticky top bar and filter chips would sit on top of every section shot
        page.evaluate("""() => { for (const el of document.querySelectorAll('body *')) {
            const pos = getComputedStyle(el).position;
            if (pos === 'sticky' || pos === 'fixed') el.style.setProperty('position', 'static', 'important'); } }""")
        for name, ids in SECTIONS.items():
            if want and name not in want:
                continue
            first = page.locator(f"#{ids[0]}")
            if not first.count():
                print("missing section", ids[0], "for", name, file=sys.stderr)
                continue
            for sid in ids:                                   # charts render when they scroll into view
                page.locator(f"#{sid}").scroll_into_view_if_needed()
                settle(page)
            top = page.evaluate(f"document.getElementById('{ids[0]}').getBoundingClientRect().top + window.scrollY")
            r = page.evaluate(f"(() => {{ const b = document.getElementById('{ids[-1]}').getBoundingClientRect();"
                              f" return {{x: b.left + window.scrollX, bottom: b.bottom + window.scrollY, w: b.width}}; }})()")
            height = min(r["bottom"] - top, MAX_HEIGHT)
            page.evaluate(f"window.scrollTo(0, {max(0, top - 20)})")
            settle(page)
            page.screenshot(path=os.path.join(a.out, name), full_page=True,
                            clip={"x": r["x"], "y": top, "width": r["w"], "height": height})
            print("wrote", name, int(r["w"] * SCALE), "x", int(height * SCALE), flush=True)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
