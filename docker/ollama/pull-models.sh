#!/usr/bin/env sh
set -eu

# Pull the comma-separated list of Ollama models specified by
# OLLAMA_PULL_MODELS. Runs as a one-shot init container against the long-lived
# `ollama` service; idempotent — already-pulled models are skipped quickly.

OLLAMA_HOST_URL="${OLLAMA_HOST_URL:-http://ollama:11434}"
MODELS="${OLLAMA_PULL_MODELS:-qwen2.5-coder:7b,llama3.1:8b,phi3:mini}"

echo "[ollama-init] target host: ${OLLAMA_HOST_URL}"
echo "[ollama-init] models to pull: ${MODELS}"

# Wait for the ollama daemon to come up.
i=0
until curl -fsS "${OLLAMA_HOST_URL}/api/tags" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    echo "[ollama-init] ollama API never came up at ${OLLAMA_HOST_URL}" >&2
    exit 1
  fi
  echo "[ollama-init] waiting for ollama… (${i}/60)"
  sleep 2
done

# Split MODELS by comma and pull each, ignoring empty entries.
echo "$MODELS" | tr ',' '\n' | while IFS= read -r model; do
  trimmed=$(printf '%s' "$model" | sed 's/^ *//;s/ *$//')
  [ -n "$trimmed" ] || continue
  echo "[ollama-init] pulling ${trimmed}…"
  curl -fsS -X POST "${OLLAMA_HOST_URL}/api/pull" \
       -H 'content-type: application/json' \
       -d "{\"name\":\"${trimmed}\",\"stream\":false}" \
       || echo "[ollama-init] WARN: failed to pull ${trimmed} (continuing)"
done

echo "[ollama-init] done."
