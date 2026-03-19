#!/usr/bin/env bash
# postdeploy.sh — post-deploy / post-upgrade verification
#
# Runs after a deploy, upgrade, or config change to verify the runtime
# is healthy and nothing regressed.
#
# Usage:
#   bash scripts/postdeploy.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FAILED=0
WARNED=0

section() { echo ""; echo "── $1 ──"; }
pass()    { echo "  [OK] $1"; }
warn()    { echo "  [!!] $1"; WARNED=$((WARNED + 1)); }
fail()    { echo "  [XX] $1"; FAILED=$((FAILED + 1)); }

# ── OpenClaw substrate ──

section "Gateway health probe"
GW_JSON=$(openclaw gateway status --json 2>/dev/null || echo '{}')
GW_STATE=$(echo "$GW_JSON" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    rt = d.get('service',{}).get('runtime',{})
    print(rt.get('status','unknown'))
except: print('unknown')
" 2>/dev/null)
if [ "$GW_STATE" = "running" ]; then
  pass "Gateway running"
else
  fail "Gateway not running (state=$GW_STATE) — try: systemctl --user restart openclaw-gateway.service"
fi

section "OpenClaw doctor (post-deploy)"
DOC_OUT=$(openclaw doctor --non-interactive 2>&1 || true)
if echo "$DOC_OUT" | grep -qi "Config invalid"; then
  fail "Config invalid after deploy — run: openclaw doctor --fix"
else
  pass "Config valid"
fi

section "OpenClaw status"
STATUS_EXIT=0
openclaw status 2>/dev/null 1>/dev/null || STATUS_EXIT=$?
if [ "$STATUS_EXIT" -eq 0 ]; then
  pass "openclaw status clean"
else
  warn "openclaw status exited $STATUS_EXIT — run: openclaw status"
fi

# ── Jarvis runtime ──

section "Jarvis smoke test"
cd "$ROOT"
SMOKE_EXIT=0
python3 scripts/smoke_test.py 2>/dev/null || SMOKE_EXIT=$?
if [ "$SMOKE_EXIT" -eq 0 ]; then
  pass "smoke_test.py green"
else
  fail "smoke_test.py failed (exit=$SMOKE_EXIT)"
fi

section "Jarvis runtime doctor"
DOC_EXIT=0
DOC_OUT=$(python3 scripts/runtime_doctor.py 2>&1) || DOC_EXIT=$?
echo "$DOC_OUT" | grep -E '^\s+\[(XX|!!)\]' || true
if [ "$DOC_EXIT" -eq 0 ]; then
  pass "runtime_doctor green"
else
  fail "runtime_doctor FAIL — check output above"
fi

section "Systemd unit sync"
DRIFT=$(python3 -c "
from scripts.sync_systemd_units import compute_plan, discover_repo_units
plan = compute_plan(discover_repo_units())
print(len(plan))
" 2>/dev/null || echo "?")
if [ "$DRIFT" = "0" ]; then
  pass "Systemd units in sync"
elif [ "$DRIFT" = "?" ]; then
  warn "Could not check systemd drift"
else
  warn "Systemd drift: $DRIFT unit(s) — run: python3 scripts/sync_systemd_units.py"
fi

# ── HTTP endpoints ──

section "HTTP endpoint probes"
for URL in "http://127.0.0.1:18789/health" "http://127.0.0.1:18790/health"; do
  LABEL=$(echo "$URL" | sed 's|.*:\([0-9]*\)/.*|\1|')
  HTTP_OK=$(python3 -c "
import urllib.request, json, sys
try:
    with urllib.request.urlopen('$URL', timeout=5) as r:
        d = json.loads(r.read())
        print('ok' if d.get('ok') else 'bad')
except: print('unreachable')
" 2>/dev/null)
  if [ "$HTTP_OK" = "ok" ]; then
    pass "Port $LABEL health OK"
  else
    fail "Port $LABEL health: $HTTP_OK"
  fi
done

# ── Summary ──

section "Post-deploy summary"
echo "  failed=$FAILED  warned=$WARNED"

if [ "$FAILED" -gt 0 ]; then
  echo ""
  echo "POST-DEPLOY: ISSUES — $FAILED failure(s). Investigate before relying on runtime."
  exit 1
else
  echo ""
  echo "POST-DEPLOY: CLEAN"
  exit 0
fi
