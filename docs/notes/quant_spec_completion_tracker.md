# Quant Lanes Spec Completion Tracker

Source: `docs/spec/QUANT_LANES_OPERATING_SPEC_v3.5.1.md`
Last updated: 2026-03-19 (closing-gaps pass)

## Status Key

- **LIVE** — Implemented, tested, passing
- **PARTIAL** — Core logic exists but missing capabilities
- **STUB** — Interface exists, logic is placeholder
- **MISSING** — Not yet started

---

## Core Infrastructure

| Area | Status | Notes |
|------|--------|-------|
| Packet schema / contracts (§10) | LIVE | Frozen, validated, 30+ types |
| Packet store + shared/latest (§18) | LIVE | Lane dirs + latest routing |
| Strategy registry (§4) | LIVE | Locked, append-only, 15 states, lineage query |
| Approval registry (§5) | LIVE | Approval objects, revocation, expiry |
| Scheduler / host-aware concurrency (§2) | LIVE | NIMO/SonLM caps, priority, overflow |
| Adaptive governor (§3) | LIVE | Threshold-based, push/hold/backoff/pause |
| Restart / recovery (§19) | LIVE | Stale cleanup, coherence, cadence/dedup preservation |
| Stale lane detection | LIVE | `check_stale_lanes()` — configurable age threshold |
| Kill switch (§14) | LIVE | `check_kill_switch()` — Executor refuses when engaged, surfaced in health |
| Portfolio risk checks | LIVE | `check_portfolio_risk()` — exposure, concentration, limits from risk_limits.json |
| Operator CLI (scripts/quant_lanes.py) | LIVE | status, strategies, brief, observe, doctor, acceptance |

## Lanes

### Kitt (§6)
| Area | Status | Notes |
|------|--------|-------|
| Brief producer (§7 format) | LIVE | All sections, proof artifact filter, TradeFloor surfacing |
| TradeFloor tier routing | LIVE | Tiers 3-4 escalated to operator |
| Pipeline section | LIVE | Strategy state formatting |
| Feedback-loop visibility | LIVE | FEEDBACK LOOPS section: Atlas learning, Fish calibration, Sigma pressure, TradeFloor tier, stale warnings |

### Atlas (§6)
| Area | Status | Notes |
|------|--------|-------|
| Candidate generation | LIVE | Rejection-aware, knowledge-driven |
| Rejection-aware iteration | LIVE | `iterate_candidate()` consumes ITERATE + guidance |
| Experiment lineage/history | LIVE | `get_lineage()`, `get_children()`, parent_id chain |
| Duplicate prevention (ID + thesis) | LIVE | Registry-level + Jaccard similarity dedup |
| Failure learning from rejections | LIVE | `build_knowledge()` reads rejections + learnings + paper reviews |
| Parameter adjustments from failures | LIVE | `_compute_parameter_adjustments()` — banned params, per-cluster rules |
| Batch generation with scheduler | LIVE | Dedup-aware, governor-gated |
| Health summary with governor | LIVE | Knowledge summary included |

### Fish (§6)
| Area | Status | Notes |
|------|--------|-------|
| Scenario emission + history | LIVE | `get_scenario_history()` with symbol filter + limit |
| Forecast with direction/value | LIVE | Includes status=pending tracking |
| Pending forecast tracking | LIVE | `get_pending_forecasts()` — unresolved forecasts |
| Calibration (forecast vs realized) | LIVE | Track-record-aware confidence |
| Calibration state persistence | LIVE | `build_calibration_state()` — hit rate, streak, trend, tr_confidence |
| Risk map emission + aggregation | LIVE | `get_active_risk_zones()` — merged view for TradeFloor/Kitt |
| Health summary with calibration | LIVE | Includes track_record, pending count, calibration state |

### Sigma (§6)
| Area | Status | Notes |
|------|--------|-------|
| Candidate validation gates | LIVE | PF, Sharpe, DD, trades |
| Configurable thresholds | LIVE | `load_thresholds()` from review_thresholds.json, safe fallback to defaults |
| Rejection with reason enum | LIVE | Full spec reason set |
| Promotion path | LIVE | validation → promotion → papertrade_candidate |
| Paper review (§11) | LIVE | advance_to_live / iterate / kill, thresholds from config |
| Health summary with governor | LIVE | `emit_health_summary()` — validations, promotions, rejections |

### Hermes (§6)
| Area | Status | Notes |
|------|--------|-------|
| Research emission | LIVE | Source quality weighting |
| Dedup (24h window) | LIVE | Configurable, force override |
| Dataset/repo/theme packets | LIVE | |
| Research request intake | LIVE | |
| Watchlist wiring | LIVE | `run_watchlist_batch()` reads watch_list.json, respects active flag, dedup holds |
| Watchlist observability | LIVE | `get_watchlist_status()` — total/active/inactive/topics |
| Batch with scheduler | LIVE | |
| Health summary | LIVE | |

### Executor (§6)
| Area | Status | Notes |
|------|--------|-------|
| Paper trade execution | LIVE | Full pre-flight validation |
| Pre-flight checks (§5) | LIVE | Kill switch, approval, mode, symbol, risk limits, broker health |
| Paper adapter | LIVE | Simulated fills |
| Portfolio risk checks | LIVE | `check_portfolio_risk()` — exposure, concentration |
| Health summary with governor | LIVE | Kill switch status, portfolio exposure in thesis |
| Live adapter | STUB | Throws "not implemented" — intentionally blocked until paper path proven |

### TradeFloor (§8/§9)
| Area | Status | Notes |
|------|--------|-------|
| Synthesis from shared/latest | LIVE | Packet-type preference per lane, evidence-backed |
| Agreement tiers (0-4) | LIVE | Full tier calculation per spec §8 |
| Fish calibration integration (§9) | LIVE | `_apply_calibration_adjustments()` — penalizes poor track record |
| Risk zone integration | LIVE | Reads `get_active_risk_zones()`, surfaces high zones in synthesis |
| Evidence trail | LIVE | `evidence_refs` links contributing packets |
| 6h sparse cadence | LIVE | CadenceRefused exception |
| Degraded mode when scheduler-blocked | LIVE | |
| Health summary with governor | LIVE | Syntheses, cadence refusals, degraded count |

## Proofs & Tests

| Area | Status | Tests |
|------|--------|-------|
| test_closing_gaps.py | LIVE | 18 — Sigma config, Hermes watchlist, Kitt feedback, observability |
| test_hardening_acceptance.py | LIVE | 17 — health summaries, stale detection, kill switch, portfolio risk, full e2e |
| test_tradefloor_synthesis.py | LIVE | 39 — evidence-driven synthesis + tier logic |
| test_fish_calibration.py | LIVE | 36 — forecast→outcome→recalibration |
| test_atlas_adaptation.py | LIVE | 48 — rejection-aware behavior |
| test_lane_b.py | LIVE | 40 — scheduler, governor, all lanes |
| test_lane_b_cycle.py | LIVE | 6 — cycle runner integration |
| test_quant_packets.py | LIVE | 11 — contract validation |
| test_executor_lane.py | LIVE | 10 — pre-flight + paper trading |
| test_quant_doctor_acceptance.py | LIVE | 7 — operator health check |
| test_quant_discord_bridge.py | LIVE | 13 — event routing |
| test_kitt_quant_workflow.py | LIVE | 10 — brief production |
| Phase 0 / Lane A / Lane B proofs | LIVE | Standalone proof scripts |
| **Total** | | **273 tests** |

## Implementation Phases (spec §22)

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 0 — vertical slice | LIVE | |
| Phase 1 — Atlas real | LIVE | |
| Phase 2 — executor + approval | LIVE (paper path) | Live adapter intentionally STUB |
| Phase 3 — discovery + scenarios + synthesis | LIVE | |
| Phase 4 — observability | LIVE | Health summaries, feedback loops in brief, `observe` command |

---

## Remaining gaps (honest)

| Gap | Severity | Notes |
|-----|----------|-------|
| Executor live adapter | Blocked | Intentionally STUB until paper path proven in production |
| Live trading e2e proof | Blocked | Requires live adapter + real broker |

All other spec areas are LIVE and tested.

## Verification commands

```bash
cd ~/.openclaw/workspace/jarvis-v5

# Full regression suite (273 tests)
pytest tests/test_closing_gaps.py tests/test_hardening_acceptance.py tests/test_tradefloor_synthesis.py tests/test_fish_calibration.py tests/test_atlas_adaptation.py tests/test_lane_b.py tests/test_lane_b_cycle.py tests/test_quant_packets.py tests/test_executor_lane.py tests/test_quant_doctor_acceptance.py tests/test_quant_discord_bridge.py tests/test_kitt_quant_workflow.py -v

# Observability surface
python3 scripts/quant_lanes.py observe

# Operator health check
python3 scripts/quant_lanes.py doctor

# Acceptance suite
python3 scripts/quant_lanes.py acceptance
```
