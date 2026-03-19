# Factory Weekly Scheduler — Ops Note

**Installed**: 2026-03-19
**Mechanism**: systemd user timer (`openclaw-factory-weekly`)
**Schedule**: Every Sunday at 02:00 CT

## What it runs

1. `python3 -m strategy_factory weekly-run` (full 7-phase pipeline)
2. `python3 scripts/emit_factory_packet.py` (idempotent safety net — skips if Phase 7 already emitted)

## Operator commands

```bash
# Check status
systemctl --user status openclaw-factory-weekly.timer
systemctl --user status openclaw-factory-weekly.service

# Next trigger time
systemctl --user list-timers openclaw-factory-weekly.timer

# Tail logs (journal)
journalctl --user -u openclaw-factory-weekly -f

# Tail logs (file)
tail -f ~/.openclaw/workspace/artifacts/strategy_factory/factory_weekly.log

# Manual run
systemctl --user start openclaw-factory-weekly.service

# Disable
systemctl --user stop openclaw-factory-weekly.timer
systemctl --user disable openclaw-factory-weekly.timer

# Re-enable
systemctl --user enable openclaw-factory-weekly.timer
systemctl --user start openclaw-factory-weekly.timer

# Force re-emit only (no pipeline rerun)
cd ~/.openclaw/workspace/jarvis-v5
python3 scripts/emit_factory_packet.py --force
```

## File locations

| File | Path |
|------|------|
| Timer unit | `jarvis-v5/systemd/user/openclaw-factory-weekly.timer` |
| Service unit | `jarvis-v5/systemd/user/openclaw-factory-weekly.service` |
| Wrapper script | `jarvis-v5/scripts/run_factory_weekly.sh` |
| Emit safety net | `jarvis-v5/scripts/emit_factory_packet.py` |
| Installed copies | `~/.config/systemd/user/openclaw-factory-weekly.*` |
| Log file | `artifacts/strategy_factory/factory_weekly.log` |
| Artifacts per run | `artifacts/strategy_factory/YYYY-MM-DD/` |

## Delivery path

Pipeline → operator_packet.json → Phase 7 emit → 3 outbox entries → outbox sender timer (60s) → Discord webhooks:
- Sigma owner channel
- Worklog mirror
- Jarvis forward
