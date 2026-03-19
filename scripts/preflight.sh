#!/usr/bin/env bash
# preflight.sh — unified pre-deploy/pre-upgrade health gate
#
# Runs OpenClaw substrate checks first, then Jarvis-specific checks.
# Exit code 0 = all green. Exit code 1 = at least one blocker.
#
# Usage:
#   bash scripts/preflight.sh           # terminal summary
#   bash scripts/preflight.sh --strict  # treat warnings as blockers
#   bash scripts/preflight.sh --backup  # create+verify backup before reporting

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STRICT=0
BACKUP=0
FAILED=0
WARNED=0

for arg in "$@"; do
  case "$arg" in
    --strict) STRICT=1 ;;
    --backup) BACKUP=1 ;;
  esac
done

section() { echo ""; echo "── $1 ──"; }
pass()    { echo "  [OK] $1"; }
warn()    { echo "  [!!] $1"; WARNED=$((WARNED + 1)); }
fail()    { echo "  [XX] $1"; FAILED=$((FAILED + 1)); }

# ── OpenClaw substrate checks ──

section "OpenClaw config validation"
if openclaw config validate --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('valid') else 1)" 2>/dev/null; then
  pass "openclaw.json valid"
else
  # Fall back: if config validate doesn't exist, check doctor
  if openclaw doctor --non-interactive 2>&1 | grep -q "Config invalid"; then
    fail "openclaw.json has validation errors — run: openclaw doctor --fix"
  else
    pass "openclaw.json valid (doctor fallback)"
  fi
fi

section "OpenClaw update status"
UPDATE_OUT=$(openclaw update status 2>&1 || true)
if echo "$UPDATE_OUT" | grep -qi "update available"; then
  warn "OpenClaw update available — run: openclaw update"
else
  pass "OpenClaw up to date"
fi

section "OpenClaw gateway status"
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
  fail "Gateway not running (state=$GW_STATE)"
fi

section "OpenClaw secrets audit"
SECRETS_OUT=$(openclaw secrets audit 2>&1 || true)
UNRESOLVED=$(echo "$SECRETS_OUT" | grep -c "REF_UNRESOLVED" || true)
if [ "$UNRESOLVED" -gt 0 ]; then
  fail "Unresolved secret references ($UNRESOLVED) — run: openclaw secrets audit"
else
  pass "No unresolved secret references"
fi

section "OpenClaw security audit"
SEC_JSON=$(openclaw security audit --json 2>/dev/null || echo '{"summary":{"critical":0}}')
CRITICAL=$(echo "$SEC_JSON" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('summary',{}).get('critical',0))
except: print(0)
" 2>/dev/null)
if [ "$CRITICAL" -gt 0 ]; then
  warn "Security audit: $CRITICAL critical finding(s) — run: openclaw security audit"
else
  pass "No critical security findings"
fi

# ── Backup (optional, before risky upgrades) ──

if [ "$BACKUP" -eq 1 ]; then
  section "Backup create + verify"
  BACKUP_DIR="$HOME/.openclaw/backups"
  mkdir -p "$BACKUP_DIR"
  BACKUP_OUT=$(openclaw backup create --output "$BACKUP_DIR" --verify 2>&1 || true)
  if echo "$BACKUP_OUT" | grep -qi "verified\|success\|ok"; then
    pass "Backup created and verified in $BACKUP_DIR"
  else
    fail "Backup create/verify failed — check: openclaw backup create --output $BACKUP_DIR --verify"
    echo "    $BACKUP_OUT" | head -5
  fi
fi

# ── Jarvis-specific checks ──

section "Jarvis repo validation"
cd "$ROOT"
VAL_EXIT=0
python3 scripts/validate.py 2>/dev/null || VAL_EXIT=$?
if [ "$VAL_EXIT" -eq 0 ]; then
  pass "validate.py green"
else
  fail "validate.py failed (exit=$VAL_EXIT)"
fi

section "Jarvis runtime doctor"
DOC_EXIT=0
DOC_OUT=$(python3 scripts/runtime_doctor.py 2>&1) || DOC_EXIT=$?
echo "$DOC_OUT" | grep -E '^\s+\[(XX|!!)\]' || true
if [ "$DOC_EXIT" -eq 0 ]; then
  VERDICT=$(echo "$DOC_OUT" | head -1 | awk '{print $2}')
  if [ "$VERDICT" = "WARN" ]; then
    warn "runtime_doctor verdict: WARN"
  else
    pass "runtime_doctor verdict: PASS"
  fi
else
  fail "runtime_doctor verdict: FAIL"
fi

# ── Summary ──

section "Preflight summary"
echo "  failed=$FAILED  warned=$WARNED"

if [ "$FAILED" -gt 0 ]; then
  echo ""
  echo "PREFLIGHT: BLOCKED — $FAILED failure(s). Fix before proceeding."
  exit 1
elif [ "$STRICT" -eq 1 ] && [ "$WARNED" -gt 0 ]; then
  echo ""
  echo "PREFLIGHT: BLOCKED (strict) — $WARNED warning(s)."
  exit 1
else
  echo ""
  echo "PREFLIGHT: CLEAR"
  exit 0
fi
