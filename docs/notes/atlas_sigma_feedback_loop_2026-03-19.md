# Atlas ↔ Sigma Feedback Loop — 2026-03-19

## Summary

Closed-loop between Sigma validation and Atlas experiment generation. When Sigma flags or rejects, Atlas automatically ingests the structured feedback and generates a bounded experiment proposal.

## Flow

```
Sigma packet (paper_trade_validator)
    ↓
sigma/feedback_extractor.py
    → bottleneck classification
    → mutation hints
    → packets/sigma/latest.json (sigma_feedback)
    → research/sigma_feedback/latest.md
    ↓
atlas/proposal_generator.py
    → experiment templates matched to bottleneck
    → deduplication by bottleneck class
    → packets/atlas/latest.json (atlas_proposal)
    → research/atlas_proposals/latest.md
```

## Bottleneck Classes

| Bottleneck | Triggering Check | Experiment Type | Mutation |
|------------|-----------------|-----------------|----------|
| stop_placement | distance_to_stop | parameter_sweep | ATR-scaled stop distance |
| risk_reward | reward_risk_ratio | parameter_sweep | R/R ratio adjustment |
| entry_timing | unrealized_pnl | filter_addition | momentum confirmation |
| thesis_alignment | scenario_contradiction | regime_gate | scenario consensus filter |
| risk_exposure | stop_out_probability | position_sizing | VIX-scaled sizing |
| target_placement | distance_to_target | parameter_sweep | ATR-based targets |

## Usage

```bash
# Full loop
.venv/bin/python3 workspace/quant_infra/run_feedback_loop.py

# With auto-submit to Atlas queue
.venv/bin/python3 workspace/quant_infra/run_feedback_loop.py --submit

# Check current state
.venv/bin/python3 workspace/quant_infra/run_feedback_loop.py --status
```

## Files Added

- `workspace/quant_infra/sigma/feedback_extractor.py`
- `workspace/quant_infra/atlas/proposal_generator.py`
- `workspace/quant_infra/run_feedback_loop.py`
- Updated: `workspace/quant_infra/README.md`, `RUNTIME_INTEGRATION.md`

## Verified

- End-to-end proof: Sigma flag (distance_to_stop + scenario_contradiction) → stop_placement bottleneck → ATR stop sweep proposal
- Preflight: CLEAR
- Postdeploy: CLEAN
