#!/usr/bin/env bash
# rotate_orchestration_sessions.sh — Archive and reset oversized orchestration sessions.
#
# Archives transcript files and resets token counts for Jarvis, HAL, and Archimedes
# main sessions. Run before delegation chains to prevent context overflow from
# accumulated session history.
#
# Safe to run repeatedly (idempotent). Does not touch Discord-bound sessions.
#
# Usage:
#   bash scripts/rotate_orchestration_sessions.sh          # rotate all
#   bash scripts/rotate_orchestration_sessions.sh --check  # dry-run: report sizes only

set -euo pipefail

AGENTS_DIR="${HOME}/.openclaw/agents"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
CHECK_ONLY=0
for arg in "$@"; do [[ "$arg" == "--check" ]] && CHECK_ONLY=1; done

# Only rotate these agents' main sessions (not Discord-bound sessions).
AGENTS=("jarvis" "hal" "archimedes")

rotate_agent() {
  local agent="$1"
  local sessions_json="${AGENTS_DIR}/${agent}/sessions/sessions.json"
  local sessions_dir="${AGENTS_DIR}/${agent}/sessions"

  if [[ ! -f "$sessions_json" ]]; then
    echo "SKIP: ${agent} — no sessions.json"
    return
  fi

  # Read current main session metadata
  local main_key="agent:${agent}:main"
  local tokens
  tokens=$(python3 -c "
import json, sys
d = json.loads(open('${sessions_json}').read())
entry = d.get('${main_key}', {})
print(entry.get('contextTokens') or entry.get('tokens') or 0)
" 2>/dev/null || echo "0")

  # Find transcript file (sessionFile is authoritative; sessionId may differ)
  local transcript=""
  transcript=$(python3 -c "
import json
d = json.loads(open('${sessions_json}').read())
entry = d.get('${main_key}', {})
sf = entry.get('sessionFile') or ''
if not sf:
    sid = entry.get('sessionId') or ''
    if sid:
        sf = '${sessions_dir}/' + sid + '.jsonl'
print(sf)
" 2>/dev/null || echo "")

  local transcript_lines=0
  local transcript_size="0"
  if [[ -n "$transcript" && -f "$transcript" ]]; then
    transcript_lines=$(wc -l < "$transcript")
    transcript_size=$(du -h "$transcript" | cut -f1)
  fi
  local transcript_basename=""
  [[ -n "$transcript" ]] && transcript_basename=$(basename "$transcript")

  if [[ "$CHECK_ONLY" -eq 1 ]]; then
    echo "${agent}: tokens=${tokens} transcript=${transcript_lines}lines/${transcript_size} file=${transcript_basename:-none}"
    return
  fi

  # Skip if session is already clean (tokens=0 or null, transcript <10 lines)
  if [[ "$tokens" == "0" && "$transcript_lines" -lt 10 ]]; then
    echo "OK: ${agent} — already clean (tokens=${tokens}, ${transcript_lines} lines)"
    return
  fi

  # Archive transcript if it exists and has content
  if [[ -n "$transcript" && -f "$transcript" && "$transcript_lines" -gt 0 ]]; then
    local archive="${sessions_dir}/archived-${TIMESTAMP}-${transcript_basename}"
    cp "$transcript" "$archive"
    : > "$transcript"  # truncate to empty
    echo "ARCHIVED: ${agent} transcript ${transcript_lines} lines → $(basename "$archive")"
  fi

  # Reset tokens and model in sessions.json for main key
  python3 - "$sessions_json" "$main_key" << 'PYEOF'
import json, sys
path, key = sys.argv[1], sys.argv[2]
d = json.loads(open(path).read())
if key in d:
    d[key]["tokens"] = None
    d[key]["contextTokens"] = None
    d[key]["model"] = None
    open(path, "w").write(json.dumps(d, indent=2))
    print(f"RESET: {key} tokens/model cleared in sessions.json")
else:
    print(f"SKIP: {key} not found in sessions.json")
PYEOF
}

echo "=== Orchestration session rotation (${TIMESTAMP}) ==="
for agent in "${AGENTS[@]}"; do
  rotate_agent "$agent"
done
echo "=== Done ==="
