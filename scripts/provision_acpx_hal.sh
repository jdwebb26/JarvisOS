#!/usr/bin/env bash
# provision_acpx_hal.sh — Idempotently registers the 'hal' agent in ~/.acpx/config.json
# so that `acpx ... hal sessions ensure ...` resolves to `openclaw acp`.
#
# Root cause: gateway's spawnAcpDirect passes agent="hal" to acpx, but acpx
# AGENT_REGISTRY only knows "openclaw". Without this mapping, acpx falls back to
# running `hal` as a raw command (binary not found) → exit code 1 → sessions_spawn fails.
#
# Usage:
#   bash scripts/provision_acpx_hal.sh           # apply (idempotent)
#   bash scripts/provision_acpx_hal.sh --check   # dry-run, exit 1 if missing

set -euo pipefail

ACPX_CONFIG="${HOME}/.acpx/config.json"
REQUIRED_AGENT="hal"
REQUIRED_COMMAND="openclaw acp"
CHECK_ONLY=0

for arg in "$@"; do
  [[ "$arg" == "--check" ]] && CHECK_ONLY=1
done

_has_mapping() {
  [[ -f "$ACPX_CONFIG" ]] || return 1
  python3 - "$ACPX_CONFIG" "$REQUIRED_AGENT" "$REQUIRED_COMMAND" << 'PYEOF'
import json, sys
cfg = json.loads(open(sys.argv[1]).read())
agent = sys.argv[2]; cmd = sys.argv[3]
entry = cfg.get("agents", {}).get(agent, {})
actual = entry.get("command", "") if isinstance(entry, dict) else entry
sys.exit(0 if actual == cmd else 1)
PYEOF
}

if _has_mapping; then
  echo "OK: ~/.acpx/config.json already maps '${REQUIRED_AGENT}' -> '${REQUIRED_COMMAND}'"
  exit 0
fi

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  echo "MISSING: ~/.acpx/config.json does not map '${REQUIRED_AGENT}' -> '${REQUIRED_COMMAND}'"
  echo "Fix: bash scripts/provision_acpx_hal.sh"
  exit 1
fi

# Apply fix: merge into existing config or create new
mkdir -p "$(dirname "$ACPX_CONFIG")"
python3 - "$ACPX_CONFIG" "$REQUIRED_AGENT" "$REQUIRED_COMMAND" << 'PYEOF'
import json, sys
path, agent, cmd = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    cfg = json.loads(open(path).read())
except Exception:
    cfg = {}
cfg.setdefault("agents", {})[agent] = {"command": cmd}
open(path, "w").write(json.dumps(cfg, indent=2) + "\n")
print(f"APPLIED: {path}  agents.{agent}.command = {cmd!r}")
PYEOF
