# Predicted brain response (TRIBE v2, research view)

MarketMirror can show how an average viewer's brain is predicted to respond to an ad, second by second. It uses
Meta's **TRIBE v2** research model ([model](https://huggingface.co/facebook/tribev2),
[code](https://github.com/facebookresearch/tribev2)), which you run yourself on a GPU. It is off by default and
never part of a normal install.

> Predicted for an average viewer by Meta's TRIBE v2 research model (noncommercial license). It predicts brain
> activity, not attention, feelings, memory or buying. Not validated for ads.

## What it does and doesn't mean

TRIBE v2 was trained to predict fMRI responses of people watching films, listening to audio and reading. Given a
video, an audio clip or a text, it predicts the cortical activity of an *average* person, about once per second,
on the fsaverage5 brain surface (about 20,000 points). Its output is already shifted 5 seconds earlier to make up
for the slow blood-flow response, so the seconds line up with the ad. Treat each peak as accurate to a few seconds.

MarketMirror reduces that to a small summary, and raw vertices never leave the sidecar:

- **Visual areas** (occipital lobe), **hearing areas** (transverse and superior temporal), **language areas**
  (inferior frontal, angular and supramarginal, middle temporal) and the **whole cortex**, as groups from nilearn's
  Destrieux surface atlas.
- For each group, the mean predicted response per second, **z-scored within the ad**. Zero is the ad's own average,
  so compare the shape over time inside one ad, not heights between ads.
- The seconds where each group peaks, the duration, the model id, the license and the lag note.

What it is **not**:

- It is not attention, liking, emotion, memory, recall, brand lift or purchase intent. TRIBE has no output for any
  of these.
- It is not validated for ads. Nobody has shown that these predicted peaks predict ad performance.
- It is an average brain. It says nothing about any segment or any simulated person.

How MarketMirror uses it:

- It is stored next to the feed test (`brain_response.json` in the run folder, and a `brain_response` key on each
  feed-test creative row) with one plain line per ad, for example "Predicted brain response for an average viewer
  (TRIBE v2, research model): language areas peak at 0:04-0:07."
- It is **never** put into persona prompts as a feeling or attention level, and it changes no simulated number.
- A **timing check** looks for moments that the simulated people name in their feed reactions ("at 0:05", "at the
  end") and counts how many fall within 2 seconds of a predicted peak. It is observational, and both sides are
  model outputs. Today's feed reactions rarely name a moment, so the check usually says it needs reactions tied to
  video timestamps.
- Image-only ads are skipped with a reason, because TRIBE has no image input. A video gets the video, an audio
  clip gets the audio, and a text-only ad gets its caption.

## License

TRIBE v2 code and weights are **CC BY-NC 4.0: noncommercial use only**. Its text encoder is
`meta-llama/Llama-3.2-3B`, which is gated: accept the Llama 3.2 license on Hugging Face with your own account.
`brain_sidecar.sh setup` refuses to install anything until you set `MM_TRIBE_ACCEPT_NONCOMMERCIAL=1`, and it
prints these steps. If you use MarketMirror commercially, you can't use this add-on for that work.

## Route 1: free Colab T4 (recommended)

1. Open `backend/brain_sidecar/colab/MarketMirror_TRIBE_v2.ipynb` in Google Colab (File > Upload notebook, or
   open it from GitHub).
2. *Runtime > Change runtime type > T4 GPU.*
3. Run cell 1 (installs TRIBE v2 with `uv`), then *Runtime > Restart session*.
4. Run the login cell and paste your own Hugging Face read token (from an account that accepted the Llama 3.2
   license). The notebook never prints or stores it.
5. Run the next cells. They fetch `tribe_server.py` from the repo (branch variable, default
   `feat/codex-workspace-features`, with an embedded copy as fallback), make a fresh `MM_TRIBE_TOKEN` with
   `secrets.token_urlsafe`, start the server on `127.0.0.1:7860` and open a Cloudflare quick tunnel
   (`cloudflared` from Cloudflare's GitHub releases).
6. The last setup cell prints two lines. Paste them into MarketMirror's `.env`:

   ```
   MM_BRAIN_RESPONSE_URL=https://<random>.trycloudflare.com
   MM_BRAIN_RESPONSE_TOKEN=<shown only in your notebook>
   ```

7. Restart the MarketMirror backend (`backend/claude_cli/stop_server.sh && backend/claude_cli/start_server.sh`).
   The CLI reads `.env` itself.
8. Optional: run the smoke-test cell. It sends the CC-BY Sintel trailer to the server and plots the four groups.

The tunnel and the token end when the Colab session ends. Next time, run the cells again and paste the two new
lines. Free Colab GPUs have daily limits.

## Route 2: your own GPU

```bash
MM_TRIBE_ACCEPT_NONCOMMERCIAL=1 backend/brain_sidecar/brain_sidecar.sh setup   # own venv, never backend/.venv
huggingface-cli login                                                          # your token, typed by you
export MM_TRIBE_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
backend/brain_sidecar/brain_sidecar.sh start      # 127.0.0.1:7860, log in backend/logs/brain_sidecar.out
backend/brain_sidecar/brain_sidecar.sh status
```

Then set `MM_BRAIN_RESPONSE_URL=http://127.0.0.1:7860` and `MM_BRAIN_RESPONSE_TOKEN` (the same value) in `.env`.
The server binds 127.0.0.1 by default and refuses any other host without `MM_TRIBE_TOKEN`.

## Route 3: your own private Hugging Face Space or Inference Endpoint

`backend/brain_sidecar/space/` has a Dockerfile and a README. MarketMirror never creates or publishes one; you do it
from your own account. A private Space needs your Hugging Face token on each request, so set
`MM_BRAIN_RESPONSE_HF_TOKEN` too. MarketMirror then sends the Hugging Face token as `Authorization` and the server
token as `X-MM-Tribe-Token`.

## Running it

```bash
C="python backend/claude_cli/mirofish.py"
$C brain-response --run-dir mirofish_runs/x --creatives @scenarios/x/creatives.json
$C brain-response --run-dir mirofish_runs/x          # the ads of the run's feed test (text and image rows only)
```

- `--creatives` takes the same file as the feed test. A creative's `video` or `audio` is a local file path
  (relative to the creatives file). Web addresses aren't fetched; download the file first. Video paths are
  only in the creatives file, not in `feed_test.json`, so pass `--creatives` for video ads.
- In `market_test.json`, `"brain_response": true` runs it right after the feed test when the URL is set, and
  logs a skip otherwise.
- API: `POST /api/simulation/brain-response {simulation_id, creatives?}` (background task; paths are files on the
  backend's machine), then `GET /api/simulation/<id>/brain-response`.
- MCP: the `brain_response` tool (`run`, optional `creatives`). In the in-app chat it is an "outside" tool, so you
  get a Go / Skip notice because it sends your ads to your sidecar.

Results are cached by a hash of the content in `brain_response.json`, so re-running the same ad costs nothing.
Every failure (no URL, sidecar down, wrong token, timeout, file over `MM_BRAIN_RESPONSE_MAX_MB`, image-only ad) is
recorded as skipped with a reason. It never stops a run.

The dashboard shows **Predicted brain response (research)** under the feed test: one small chart per ad, with lines
for the visual, hearing and language areas and the whole cortex. The run view in the app shows the same chart as a
Results section.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `MM_BRAIN_RESPONSE_URL` | unset (off) | the sidecar's address |
| `MM_BRAIN_RESPONSE_TOKEN` | unset | the sidecar's `MM_TRIBE_TOKEN` |
| `MM_BRAIN_RESPONSE_HF_TOKEN` | unset | only for a private Space or protected Endpoint |
| `MM_BRAIN_RESPONSE_TIMEOUT` | 900 | seconds per ad, polling included |
| `MM_BRAIN_RESPONSE_REQUEST_TIMEOUT` | 90 | seconds per HTTP request |
| `MM_BRAIN_RESPONSE_MAX_MB` | 100 | larger files are skipped |
| `MM_TRIBE_HOST` / `MM_TRIBE_PORT` | 127.0.0.1 / 7860 | sidecar bind address |
| `MM_TRIBE_TOKEN` | unset | sidecar bearer token (required off loopback) |
| `MM_TRIBE_MAX_MB` | 200 | sidecar upload limit |
| `MM_TRIBE_ALLOW_PATHS` | 0 | let the sidecar read local paths instead of uploads |

The sidecar answers long jobs asynchronously (`"async": true`, then `GET /jobs/<id>`), because Cloudflare quick
tunnels cut a request after about 100 seconds.

## GPU and cost

- **Colab free T4:** no cost, daily limits, and the session ends when Colab disconnects.
- **Own GPU:** needs a CUDA card. The first prediction downloads about 1 GB of TRIBE weights plus the Llama 3.2 3B,
  WhisperX, DINOv2 and V-JEPA2 encoders.
- **Private Space or Endpoint:** billed per hour or minute by Hugging Face while it runs. Set sleep or
  scale-to-zero.

No model-provider calls are made, so the run's spend cap doesn't count this. These timings and costs are
estimates. MarketMirror's own tests use a fake predictor, and the real model hasn't been run as part of this
integration.
