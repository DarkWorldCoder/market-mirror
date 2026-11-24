# TRIBE v2 server as your own private Space or Inference Endpoint

This folder documents how to run the brain-response server (`../tribe_server.py`) on a GPU you rent from
Hugging Face. MarketMirror never creates, publishes or pays for one. You do it from your own account.
The cheaper route for occasional use is the free Colab notebook (`../colab/MarketMirror_TRIBE_v2.ipynb`).

**License.** TRIBE v2 code and weights are CC BY-NC 4.0: noncommercial use only. The text encoder,
`meta-llama/Llama-3.2-3B`, is gated: accept its license on Hugging Face with the account whose token the
server uses.

## Private Space (Docker SDK)

1. On huggingface.co create a new Space: SDK **Docker**, visibility **Private**, hardware with a GPU
   (an A10G small or a T4 is enough for short ads). GPU Spaces are billed per hour while running; set a sleep
   time so it stops when idle.
2. Copy `tribe_server.py`, `requirements.txt` and this `Dockerfile` into the Space repository (put the
   Dockerfile at the repository root and keep the two `COPY` lines pointing at files next to it).
   Add `app_port: 7860` to the Space README front matter.
3. In the Space settings, add two **secrets**:
   - `HF_TOKEN`: a read token of an account that accepted the Llama 3.2 license.
   - `MM_TRIBE_TOKEN`: a long random string, for example from `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
4. Wait for the build, then check `https://<user>-<space>.hf.space/health`. A private Space needs your
   Hugging Face token on every request, so the health check is
   `curl -H "Authorization: Bearer $HF_TOKEN" https://<user>-<space>.hf.space/health`.
5. In MarketMirror's `.env`:

   ```
   MM_BRAIN_RESPONSE_URL=https://<user>-<space>.hf.space
   MM_BRAIN_RESPONSE_TOKEN=<the MM_TRIBE_TOKEN secret>
   MM_BRAIN_RESPONSE_HF_TOKEN=<a Hugging Face read token that can open your private Space>
   ```

   With `MM_BRAIN_RESPONSE_HF_TOKEN` set, MarketMirror sends the Hugging Face token as `Authorization` and the
   server token as `X-MM-Tribe-Token`.

## Inference Endpoint (custom container)

Build and push the image (`docker build -f backend/brain_sidecar/space/Dockerfile -t <registry>/mm-tribe backend/brain_sidecar`),
create a **protected** endpoint with a custom container on port 7860 and a GPU, set the same two secrets as
environment variables, and use the endpoint URL with the same three `.env` lines. Endpoints are billed per
minute while running; turn on scale-to-zero.

## Cost and speed (rough, not measured here)

The first request downloads about 1 GB of TRIBE weights plus the Llama 3.2 3B, WhisperX, DINOv2 and V-JEPA2
encoders, so it takes minutes. After that a 30-second video ad takes on the order of a minute on a T4. Nothing
here was run on a GPU by MarketMirror's authors; check the time and the bill on your own account.

## What the server returns

Only a compact summary: per-second, clip-z-scored mean response for visual, hearing and language areas and the
whole cortex (Destrieux atlas on fsaverage5), peak seconds, duration, model id, license and the lag note. Raw
vertices never leave the server. It predicts an average viewer's brain activity, not attention, feelings,
memory or buying, and it is not validated for ads.
