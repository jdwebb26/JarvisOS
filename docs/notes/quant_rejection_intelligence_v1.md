# Quant Rejection Intelligence v1

**Status**: Live (scripts), no runtime hooks yet
**Added**: 2026-03-19
**Scope**: Additive feature — durable rejection ledger, normalization, scoreboards, feedback export

## What it does

Normalizes rejection outputs from Strategy Factory, Sigma, and Executor into a canonical durable ledger. Builds family/regime scoreboards and compact feedback summaries for Atlas, Fish, and Kitt.

## Files

### Runtime modules (`runtime/quant/`)

| File | Purpose |
|------|---------|
| `rejection_types.py` | `RejectionRecord` dataclass, `PrimaryReason` / `NextActionHint` / `SourceLane` enums |
| `rejection_normalizer.py` | Deterministic rule-based normalizer for 3 source formats |
| `rejection_ledger.py` | Durable append-only ledger: individual JSON + JSONL index |
| `rejection_scoreboard.py` | Family scoreboard, regime scoreboard, learning summary |
| `rejection_feedback.py` | Feedback export for Atlas, Fish, Kitt (JSON + Markdown) |

### Scripts (`scripts/`)

| Script | Usage |
|--------|-------|
| `audit_rejection_ledger.py` | `--ingest` scans live sources, `--rebuild-index` repairs index, `--summary` prints stats |
| `build_rejection_scoreboard.py` | Builds family/regime/learning scoreboards from ledger |
| `export_rejection_feedback.py` | Exports feedback snapshots (JSON + Markdown) |

### State outputs (`state/quant/rejections/`)

| File | Description |
|------|-------------|
| `rej_<id>.json` | Individual canonical rejection record |
| `index.jsonl` | Append-only index for fast scanning |
| `family_scoreboard.json` | Per-family rejection stats, cooldown flags, near-misses |
| `regime_scoreboard.json` | Per-regime rejection breakdown |
| `learning_summary.json` | Top reasons, failing families, exploration shift recommendations |
| `feedback_snapshot.json` | Combined feedback for Atlas/Fish/Kitt |
| `feedback_snapshot.md` | Human-readable Markdown version |

## Source mapping

| Source | Packet type / field | Reason field | ID field |
|--------|-------------------|-------------|----------|
| Strategy Factory (`candidate_result.json`) | `status: "REJECT"` | `reject_reason` | `candidate_id` |
| Strategy Factory (`STRATEGIES.jsonl`) | `gate_overall: "FAIL"` | inferred from `stress_overall`, `perturbation_robust`, `score` | `candidate_id` |
| Sigma | `packet_type: "strategy_rejection_packet"` | `rejection_reason` | `strategy_id` |
| Executor | `packet_type: "execution_rejection_packet"` | `execution_rejection_reason` | `strategy_id` |

## Normalization rules

- Deterministic/rule-based: gate text mapped to `PrimaryReason` enum
- When no explicit reason: heuristic from `stress_overall`, `perturbation_robust`, `score`, `fold_count`
- Near-miss detection: only 1 gate failed out of total → `promising_near_miss` hint
- Family inferred from strategy_id prefix when not explicit
- Raw reason always preserved in `raw_reason`
- Confidence: 0.9 (explicit), 0.7 (inferred), 0.3 (unknown)

## What this does NOT do

- Does not auto-change live trading behavior
- Does not add dashboard UI
- Does not modify existing quant lane code
- Does not have runtime hooks (scripts only for v1)
- Does not touch live timers/services

## Next steps

- Wire `audit_rejection_ledger.py --ingest` into Lane B cycle as a post-step
- Add regime tagging from Fish scenario data
- Consider `#kitt` brief integration for rejection trend summaries
