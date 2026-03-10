#!/usr/bin/env bash
set -u

cd /home/rollan/.openclaw/workspace/jarvis-v5 || exit 1
source /home/rollan/.openclaw/workspace/jarvis-v5/.venv-qwen-agent/bin/activate

export QWEN_AGENT_MODEL_SERVER=http://100.70.114.34:1234/v1
export QWEN_AGENT_MODEL=qwen3.5-35b-a3b
export QWEN_AGENT_API_KEY=lm-studio
export JARVIS_WORKSPACE=/home/rollan/.openclaw/workspace
export QWEN_AGENT_ENABLE_THINKING=false
export QWEN_AGENT_THOUGHT_IN_CONTENT=true
export QWEN_AGENT_USE_RAW_API=false

mkdir -p /home/rollan/.openclaw/workspace/artifacts/qwen_live

CYCLES="${1:-16}"
SLEEP_SEC="${2:-1800}"

i=1
while [ "$i" -le "$CYCLES" ]; do
  echo "[$(date -Is)] qwen overnight cycle $i/$CYCLES"
  python3 /home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/qwen_nq_overnight.py || true
  if [ "$i" -lt "$CYCLES" ]; then
    sleep "$SLEEP_SEC"
  fi
  i=$((i+1))
done
