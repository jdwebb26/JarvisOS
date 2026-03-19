# Kitt Packet Hardening — 2026-03-19

## What changed

Enriched Kitt's paper-trade packets, events, and briefs so downstream consumers can understand position state and thesis from the packet alone.

### Richer packet content (both cycle and quant packets)

Per-position fields added:
- `unrealized_pnl_pts` / `unrealized_pnl_usd` — live P&L
- `reward_risk` — R:R ratio from entry/stop/target
- `dist_to_stop_pts` / `dist_to_target_pts` — distance to levels
- `position_age_minutes` — how long the position has been open (quant packet)
- `thesis` — the reasoning/rationale for the trade (quant packet)

Cycle-level fields added:
- `regime` — classified from ATR/deviation (low_vol, normal, extended, trending)
- `signal` — current signal snapshot (direction, ATR, deviation, EMAs)
- `cycle_event` — what event was emitted this cycle (or null)
- `invalidation` — what would invalidate the current thesis

### Better event emission

New events:
- `target_hit` — emitted when take-profit is reached (with full position context)
- `thesis_changed` — emitted on regime shifts or signal reversals while a position is open

Existing events unchanged:
- `position_opened`, `position_closed`, `stop_triggered` — already emitted correctly

Bounded: thesis_changed only fires on material changes (regime shift or signal reversal), not every cycle.

### Thesis state tracking

New file: `workspace/quant_infra/kitt/thesis_state.json`
- Persisted each cycle with: regime, signal_direction, ATR, deviation, position_id
- Compared against previous cycle to detect meaningful changes
- Simple JSON, overwritten each cycle

### Better brief output

The Kitt brief now includes:
- Regime and signal snapshot
- Per-position: R:R, unrealized P&L, distances, thesis, invalidation level
- What event was emitted this cycle
- "Changes Since Last Cycle" section showing regime/signal shifts

## Files changed

| File | Change |
|------|--------|
| `workspace/quant_infra/kitt/run_kitt_cycle.py` | Thesis tracking, regime classification, enriched packet/brief, target_hit integration |
| `workspace/quant_infra/kitt/paper_trader.py` | `check_targets()`, enriched `_write_kitt_packet()` with computed fields |

## Verification

- Dry-run: clean
- Stateful cycle: hold decision with all enriched fields populated
- Cycle packet: regime, signal, invalidation, per-position enrichment confirmed
- Quant packet: position_age_minutes, thesis, all computed fields confirmed
- Thesis state persisted and loadable
- Preflight: CLEAR
- Postdeploy: CLEAN
