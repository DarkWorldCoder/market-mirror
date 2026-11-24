# TRIBE v2 brain-response server for the owner's own PRIVATE Hugging Face Space (Docker SDK, GPU hardware) or a
# Hugging Face Inference Endpoint (custom container). Documentation only: MarketMirror never creates or publishes one.
# See README.md next to this file. License of the model: CC BY-NC 4.0 (noncommercial).
#
# Build context: backend/brain_sidecar (so tribe_server.py and requirements.txt are copied in):
#   docker build -f backend/brain_sidecar/space/Dockerfile -t mm-tribe backend/brain_sidecar
# Secrets (set in the Space or Endpoint settings, never in this file):
#   HF_TOKEN       a read token of an account that accepted the meta-llama/Llama-3.2-3B license
#   MM_TRIBE_TOKEN a long random string; MarketMirror sends it as MM_BRAIN_RESPONSE_TOKEN
FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg curl && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces run the container as user 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

COPY --chown=user requirements.txt ./
RUN pip install --no-cache-dir --user -r requirements.txt
COPY --chown=user tribe_server.py ./

# 0.0.0.0 inside the container; the server refuses a non-loopback host unless MM_TRIBE_TOKEN is set
ENV MM_TRIBE_HOST=0.0.0.0 MM_TRIBE_PORT=7860 MM_TRIBE_CACHE=/home/user/app/cache MM_TRIBE_ALLOW_PATHS=0
EXPOSE 7860
CMD ["python", "tribe_server.py"]
