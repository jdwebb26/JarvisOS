# Post-Merge Runtime Truth — 2026-03-19

Updated after merging `feat/atlas-sigma-feedback-loop-clean` and `feat/kitt-packet-hardening` onto main.

---

## Commits Landed This Pass

```
dabb86f fix(preflight): add missing shadowbroker_summary in build_doctor_report
3b84d64 Merge feat/atlas-sigma-feedback-loop-clean: wire Sigma→Atlas structured feedback loop
1ba28f1 Merge feat/kitt-packet-hardening: enrich Kitt packet, brief, and event emission
```

## Preflight Status

```
PREFLIGHT: CLEAR
validate: PASS (pass=395 warn=1 fail=0)
runtime_doctor: WARN (1 drifted unit: openclaw-gateway.service)
health_monitor: HEALTHY (13/13)
```

---

## What Is Now Landed on Main

### Core Quant Infrastructure
- `workspace/quant_infra/` backbone (packets, events, warehouse, DuckDB)
- Quant event handshake: Kitt → Salmon/Fish → Sigma → Jarvis/operator

### Lane Runtime
| Lane | Status | Key Capability |
|------|--------|----------------|
| **Kitt** | Live paper loop on timer | Thesis state, regime classification, enriched briefs (spec §7), target detection, thesis_changed/target_hit events |
| **Fish/Salmon** | Live scenario lane on timer | Scenario generation, calibration, risk maps |
| **Sigma** | Live validation lane | Structured validation, rejection packets, bottleneck classification |
| **Atlas** | Live experiment lane | Experiment proposals, health summaries, failure learning |
| **Hermes** | Live research lane | Datasets, research, theme extraction |

### Atlas ↔ Sigma Feedback Loop (NEW)
- `sigma/feedback_extractor.py` — Extracts structured feedback from Sigma validation packets
- `atlas/proposal_generator.py` — Consumes feedback, generates bounded experiment proposals
- `run_feedback_loop.py` — Orchestrator entry point (CLI + programmatic)
- Currently manually triggered (`python3 workspace/quant_infra/run_feedback_loop.py --submit`)

### Kitt Packet Hardening (NEW)
- `check_targets()` — Take-profit detection with `target_hit` event emission
- Thesis state persistence (`thesis_state.json`)
- Regime classification: low_vol / normal / extended / trending
- `thesis_changed` event when regime shifts or signal reversals occur
- Enriched packet payload: unrealized PnL, R:R, distance to stop/target, position age, thesis

### Rejection Intelligence v1
- Canonical types, normalizer, ledger, scoreboards, feedback exports
- Governor reads `rejection_feedback.json` for atlas cooldown gating
- Ingest orchestrator exists but is manually triggered (no cron)

### Operator Surfaces
- LIVE_QUEUED approval state resolution
- Discord type-aware live approval messaging
- Dashboard, operator snapshot, review inbox

### OpenBB Market Context
- OpenBB + yfinance fallback
- Timer-driven context updates

### Strategy Factory
- Daily/hourly/4h/15m dataset support
- Batch optimization and validation sweeps

---

## What Is Partial on Main

### Rejection Intelligence
- Library is complete and tested
- Governor consumes cooldown flags (partial)
- **No automated ingest** — packets normalize only when manually triggered
- **Scoreboards produced but unconsumed** by any runtime path
- **Fish regime feedback** produced but unconsumed
- **Kitt brief** does not include learning summary

### Atlas ↔ Sigma Loop
- Exists and works end-to-end
- Manually triggered only — no timer/hook automation
- Does not yet consume rejection ledger (reads Sigma packets directly)

### Kitt Intelligence
- Thesis tracking and regime classification landed
- Brief now has 9 spec §7 sections
- Still relatively simple signal layer (SMA crossover + ATR + deviation)

### Paper Control Plane
- Positions, fills, decisions tracked
- No unified exposure/rejects/pending-approvals surface yet

---

## What Is Not Done

1. **Automated rejection ingest** — No cron/hook to normalize packets into ledger
2. **Scoreboard consumption** — family/regime/learning scoreboards unused by runtime
3. **Fish regime guidance consumption** — Produced but Fish doesn't read it
4. **Kitt brief enrichment from rejection data** — Learning summary not integrated
5. **Regime memory** — No remembered view of recent regimes / family failures by regime
6. **Operator truth pack** — No single unified truth surface
7. **Paper control plane** — Active positions, exposure, approval queue not unified
8. **Multi-strategy runtime** — System not yet truly multi-strategy in live behavior
9. **Options-aware quant layer** — Not operationalized

---

## Branch Status

### Merged and Done
- `feat/atlas-sigma-feedback-loop-clean` — merged
- `feat/kitt-packet-hardening` — merged
- All earlier feature branches (fish, sigma, atlas, salmon, openbb, factory-4h, etc.)

### Can Be Deleted
- `feat/atlas-sigma-feedback-loop` (superseded by clean version)
- `feat/atlas-lane-activation` / `feat/atlas-lane-activation-clean` (already merged)
- `feat/sigma-lane-activation` / `feat/sigma-lane-activation-clean` (already merged)
- `feat/salmon-runtime` (merged)
- `feat/fish-lane-activation` (merged)
- `feat/openbb-context` (merged)
- `feat/factory-4h` (merged)
- `feat/kitt-paper-loop` (merged)
- `feat/quant-infra-spine-v1` (merged)
- `feat/proof-operator-surfaces` (merged)
- `feat/openclaw-substrate-alignment-clean` (merged/superseded)
- `feat/quant-event-handshake` (merged)

---

## Uncommitted Working Tree

The working tree has uncommitted enhancements to:
- `kitt/paper_trader.py` — Slippage simulation, enriched brief close messages
- `kitt/run_kitt_cycle.py` — Governor integration, spec §7 brief sections (portfolio, pipeline, lane activity, tradefloor, health, feedback loops, operator actions)
- `events/emitter.py`, `handshake.py`, `salmon/adapter.py`, `warehouse/sql/schema.sql`
- `executor/executor_lane.py`, `executor/proof_tracker.py`
- Various state/log files from live runtime

These are live-evolving and not yet committed. They should be reviewed and landed incrementally.

---

## Next Priority Order

1. **Wire automated rejection ingest** — Safest first consumer; closes packet→ledger→feedback→governor loop
2. **Land uncommitted Kitt/quant enhancements** — Review, test, commit the working tree improvements
3. **Connect scoreboards to operator brief** — Feed family/regime/learning data into Kitt brief
4. **Wire Fish regime guidance** — Fish reads rejection_feedback.json for scenario prioritization
5. **Build operator truth pack** — Unified surface for runtime state
6. **Delete stale branches** — Clean up the 12+ merged/superseded branches
