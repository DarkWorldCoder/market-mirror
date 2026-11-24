"""Write MarketMirror_TRIBE_v2.ipynb (nbformat 4) from tribe_server.py, so the notebook's embedded fallback copy of
the server always matches the file in the repo. Run after changing tribe_server.py:

    python backend/brain_sidecar/colab/build_notebook.py

A test checks that the committed notebook is current.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(HERE), "tribe_server.py")
OUT = os.path.join(HERE, "MarketMirror_TRIBE_v2.ipynb")
REPO = "DarkWorldCoder/market-mirror"
BRANCH = "feat/codex-workspace-features"


def _lines(text: str):
    parts = text.split("\n")
    return [p + "\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def md(text: str):
    return {"cell_type": "markdown", "metadata": {}, "source": _lines(text.strip("\n"))}


def code(text: str):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": _lines(text.strip("\n"))}


def build(server_source: str):
    cells = [
        md("""
# MarketMirror: predicted brain response with TRIBE v2 (free Colab T4)

This notebook runs Meta's **TRIBE v2** research model on a free Colab GPU and gives MarketMirror a private web
address to send your ads to. MarketMirror then shows, second by second, how an *average* viewer's brain is
predicted to respond to each ad.

**License.** TRIBE v2 code and weights are **CC BY-NC 4.0: noncommercial use only**. Its text encoder,
`meta-llama/Llama-3.2-3B`, is gated: accept its license at https://huggingface.co/meta-llama/Llama-3.2-3B with
your own Hugging Face account before step 3. By running this notebook you accept both licenses.

**GPU.** Choose *Runtime > Change runtime type > T4 GPU* before running anything. The free T4 has limited
hours per day; the session (and the web address it makes) ends when Colab disconnects.

**What it means.** It predicts brain activity for an average viewer, not attention, feelings, memory or
buying. It is not validated for ads. Treat it as a research view next to the simulated buyers, never as a score.
"""),
        md("## 1. Install TRIBE v2\nThis takes a few minutes. When it finishes, use *Runtime > Restart session*, then run the cells below (skip this one)."),
        code("""
!pip -q install uv
!uv pip install --system "tribev2[plotting] @ git+https://github.com/facebookresearch/tribev2.git"
"""),
        md("## 2. Sign in to Hugging Face\nPaste your own read token in the box (from https://huggingface.co/settings/tokens). It is kept by Colab for this session; this notebook never prints or stores it."),
        code("""
from huggingface_hub import notebook_login
notebook_login()
"""),
        md("## 3. Get the MarketMirror server\nDownloads `tribe_server.py` from the repo. If the repo or branch is private or missing, the copy embedded below is used instead."),
        code(f'''
import urllib.request, pathlib
REPO = "{REPO}"
BRANCH = "{BRANCH}"   # change to the branch you run MarketMirror from
url = f"https://raw.githubusercontent.com/{{REPO}}/{{BRANCH}}/backend/brain_sidecar/tribe_server.py"
EMBEDDED = {json.dumps(server_source)}
try:
    source = urllib.request.urlopen(url, timeout=30).read().decode("utf-8")
    print("downloaded", url)
except Exception as e:
    source = EMBEDDED
    print("using the embedded copy (", type(e).__name__, ")")
pathlib.Path("tribe_server.py").write_text(source, encoding="utf-8")
'''),
        md("## 4. Start the server\nMakes a fresh access token for this session and starts the server on `127.0.0.1:7860` (only reachable inside this Colab machine until step 5). The model weights (about 1 GB plus the encoders) download on the first prediction."),
        code("""
import os, secrets, subprocess, sys, time, json, urllib.request
MM_TRIBE_TOKEN = secrets.token_urlsafe(32)
env = dict(os.environ, MM_TRIBE_TOKEN=MM_TRIBE_TOKEN, MM_TRIBE_HOST="127.0.0.1", MM_TRIBE_PORT="7860",
           MM_TRIBE_CACHE="/content/tribe_cache")
server = subprocess.Popen([sys.executable, "tribe_server.py"], env=env,
                          stdout=open("tribe_server.log", "w"), stderr=subprocess.STDOUT)
for _ in range(60):
    try:
        health = json.loads(urllib.request.urlopen("http://127.0.0.1:7860/health", timeout=2).read())
        print("server is up:", {k: health[k] for k in ("model", "license", "device", "auth")})
        break
    except Exception:
        if server.poll() is not None:
            print(open("tribe_server.log").read()[-2000:]); raise SystemExit("the server stopped")
        time.sleep(1)
else:
    raise SystemExit("the server did not answer; see tribe_server.log")
"""),
        md("## 5. Open a temporary tunnel\nDownloads `cloudflared` from Cloudflare's official GitHub releases and opens a quick tunnel to the server. Anyone with the address still needs the token from step 4."),
        code("""
import re, subprocess, time, urllib.request, os
CF = "/content/cloudflared"
if not os.path.exists(CF):
    urllib.request.urlretrieve(
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64", CF)
    os.chmod(CF, 0o755)
tunnel = subprocess.Popen([CF, "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:7860"],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
PUBLIC_URL = None
deadline = time.time() + 60
while time.time() < deadline and PUBLIC_URL is None:
    line = tunnel.stdout.readline()
    m = re.search(r"https://[-a-z0-9]+\\.trycloudflare\\.com", line or "")
    if m:
        PUBLIC_URL = m.group(0)
if not PUBLIC_URL:
    raise SystemExit("no tunnel address yet; run this cell again")
print("tunnel:", PUBLIC_URL)
"""),
        md("## 6. Connect MarketMirror\nCopy the two lines below into MarketMirror's `.env` (next to `LLM_API_KEY`) and restart the backend. The token is shown only to you, in this notebook. The tunnel and the token end when this Colab session ends; run steps 4 to 6 again next time."),
        code("""
print("MM_BRAIN_RESPONSE_URL=" + PUBLIC_URL)
print("MM_BRAIN_RESPONSE_TOKEN=" + MM_TRIBE_TOKEN)
"""),
        md("## 7. Optional: smoke test on the Sintel trailer\nSends the CC-BY Sintel trailer (Blender Foundation) to the local server and plots the four groups. The first run downloads the weights, so it can take several minutes."),
        code("""
import base64, json, time, urllib.request
import matplotlib.pyplot as plt
clip = "/content/sintel_trailer-480p.mp4"
if not os.path.exists(clip):
    urllib.request.urlretrieve("https://download.blender.org/durian/trailer/sintel_trailer-480p.mp4", clip)
headers = {"Authorization": "Bearer " + MM_TRIBE_TOKEN, "Content-Type": "application/json"}
body = json.dumps({"kind": "video", "filename": "sintel.mp4", "async": True,
                   "data_b64": base64.b64encode(open(clip, "rb").read()).decode()}).encode()
job = json.loads(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:7860/predict", data=body, headers=headers)).read())["job"]
while True:
    state = json.loads(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:7860/jobs/" + job, headers=headers)).read())
    if state["status"] != "running":
        break
    time.sleep(5)
if state["status"] != "done":
    raise SystemExit(state.get("error"))
s = state["summary"]
plt.figure(figsize=(10, 3.5))
for key, g in s["groups"].items():
    plt.plot(s["seconds"], g["z"], label=g["label"])
plt.axhline(0, color="#999", lw=0.6)
plt.xlabel("seconds into the clip"); plt.ylabel("z within clip"); plt.legend(); plt.title("Predicted response, average viewer (TRIBE v2)")
plt.show()
print(s["label"]); print(s["lag_note"])
for key, g in s["groups"].items():
    print(g["label"], "peaks:", [(p["start"], p["end"]) for p in g["peaks"]])
"""),
    ]
    return {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"provenance": [], "gpuType": "T4"},
                                         "kernelspec": {"display_name": "Python 3", "name": "python3"},
                                         "language_info": {"name": "python"}},
            "nbformat": 4, "nbformat_minor": 0}


def render() -> str:
    with open(SERVER, encoding="utf-8") as f:
        return json.dumps(build(f.read()), ensure_ascii=False, indent=1) + "\n"


def main() -> int:
    text = render()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print(OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
