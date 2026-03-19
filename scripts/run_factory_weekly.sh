#!/usr/bin/env bash
# run_factory_weekly.sh — weekly strategy factory cycle + emit safety net
#
# Called by: openclaw-factory-weekly.service (systemd timer)
# Manual:   bash scripts/run_factory_weekly.sh
#
# Logs: journalctl --user -u openclaw-factory-weekly -f
#       or: ~/.openclaw/workspace/artifacts/strategy_factory/factory_weekly.log

set -euo pipefail

FACTORY_ROOT="$HOME/.openclaw/workspace/strategy_factory"
JARVIS_ROOT="$HOME/.openclaw/workspace/jarvis-v5"
LOG_DIR="$HOME/.openclaw/workspace/artifacts/strategy_factory"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/factory_weekly.log"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG_FILE"; }

log "=== Factory weekly cycle starting ==="

# Phase 1: Run the full weekly pipeline (includes inline emit in Phase 7)
log "Running: python3 -m strategy_factory weekly-run"
cd "$FACTORY_ROOT"
if python3 -m strategy_factory weekly-run 2>&1 | tee -a "$LOG_FILE"; then
    log "Weekly pipeline completed successfully"
else
    log "WARNING: Weekly pipeline exited non-zero ($?)"
fi

# Phase 2: Idempotent emit safety net (skips if Phase 7 already emitted)
log "Running emit safety net"
cd "$JARVIS_ROOT"
python3 scripts/emit_factory_packet.py 2>&1 | tee -a "$LOG_FILE"

# Phase 3: Consume factory-origin Kitt briefs (idempotent — skips already-consumed)
log "Consuming Kitt briefs"
python3 scripts/consume_kitt_briefs.py -v 2>&1 | tee -a "$LOG_FILE"

log "=== Factory weekly cycle finished ==="
