# =============================================================================
# HexStrike-AI control plane — Flask API on :8888.
# =============================================================================

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates curl git build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/hexstrike

# Copy the upstream HexStrike-AI source tree (vendored under hexstrike-ai/ in
# the repo) and install its requirements if a requirements file is present.
COPY hexstrike-ai/ /opt/hexstrike/

RUN if [ -f requirements.txt ]; then \
        pip install --no-cache-dir -r requirements.txt; \
    fi \
 && pip install --no-cache-dir flask waitress requests

EXPOSE 8888

# The upstream entrypoint is hexstrike_server.py and listens on 8888 by
# default (overridable with --port).
CMD ["python", "-u", "hexstrike_server.py", "--port", "8888"]
