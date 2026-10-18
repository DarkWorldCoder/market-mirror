"""Render README screenshots of single dashboard sections with headless Chrome (light mode)."""
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageChops

dashboard, out_dir = sys.argv[1], sys.argv[2]
shots = [s.split("=", 1) for s in sys.argv[3:]]  # name=selector-spec
html = open(dashboard, encoding="utf-8").read()
os.makedirs(out_dir, exist_ok=True)

for name, spec in shots:
    # spec: comma list of section ids to keep; "header" keeps the page header
    keep = spec.split(",")
    width = 1280
    css = ["nav.toc,#tip,footer,h2.divider,.theme-btn{display:none!important}", "section{display:none!important}",
           ".wrap{padding-top:24px!important}", "html,body{background:#eeeeea!important}"]
    if "header" not in keep:
        css.append("header.top{display:none!important}")
    for k in keep:
        if k.startswith("first-ftc") or k.startswith("ftc-"):
            nth = 1 if k.startswith("first-ftc") else int(k.split("-")[1])
            css.append(f"#feedtest .ftc:not(:nth-child({nth})),#feedtest .grid2{{display:none!important}}")
            k = "feedtest"
        if k != "header":
            css.append(f"#{k}{{display:block!important}}")
    page = html.replace("<html lang=\"en\">", "<html lang=\"en\" data-theme=\"light\">", 1)
    page = page.replace("</head>", "<style>" + "".join(css) + "</style></head>", 1)
    tmp = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
    tmp.write(page)
    tmp.close()
    raw = os.path.join(out_dir, f".{name}.raw.png")
    subprocess.run(["google-chrome", "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-sandbox",
                    "--force-device-scale-factor=1.5", f"--window-size={width},2600", "--virtual-time-budget=6000",
                    f"--screenshot={raw}", "file://" + tmp.name], check=True, capture_output=True, timeout=120)
    img = Image.open(raw).convert("RGB")
    bg = Image.new("RGB", img.size, img.getpixel((2, 2)))
    box = ImageChops.difference(img, bg).getbbox()
    if box:
        pad = 30
        box = (max(0, box[0] - pad), max(0, box[1] - pad), min(img.width, box[2] + pad), min(img.height, box[3] + pad))
        img = img.crop(box)
    img.save(os.path.join(out_dir, f"{name}.png"), optimize=True)
    os.remove(raw)
    os.remove(tmp.name)
    print(name, img.size)
