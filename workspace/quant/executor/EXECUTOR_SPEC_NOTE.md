# Executor Lane — Operator Spec Note

## Paper → Review → Live Path

```
PROMOTED → PAPER_QUEUED → PAPER_ACTIVE → PAPER_REVIEW → LIVE_QUEUED → LIVE_ACTIVE
                                            ↓                            ↓
                                         ITERATE → CANDIDATE          LIVE_REVIEW
                                         PAPER_KILLED                 LIVE_KILLED
```

## Key Rules

1. **paper_active ≠ live-eligible.** A strategy in PAPER_ACTIVE is gathering proof. It is not ready for review until it has enough trades over its proof window.

2. **Proof windows are strategy-specific.** Each strategy type has different horizon requirements. A 15m-timeframe mean-reversion strategy might need 50+ trades over 2 weeks. A daily-timeframe trend strategy might need 20 trades over 2 months. The proof window is not global.

3. **Promotion goes to review.** When Sigma determines a paper-active strategy has accumulated enough proof, it transitions to PAPER_REVIEW. The operator then sees it in the review queue.

4. **Review decides.** Review outcomes:
   - `approve_live_candidate` → LIVE_QUEUED (still needs live-execution approval)
   - `reject` → PAPER_KILLED (terminal)
   - `continue_paper` → back to PAPER_ACTIVE (more proof needed)
   - `rerun_with_changes` → ITERATE → CANDIDATE (Atlas re-generates with guidance)

5. **Live execution requires explicit approval.** LIVE_QUEUED → LIVE_ACTIVE only happens via the executor lane with a valid live_trade approval_ref. Casual chat cannot trigger this.

6. **Kill switch stops everything.** Engaging the kill switch halts all execution (paper and live) immediately.

## Why Something Is Not Yet Live-Eligible

| Current State     | Why Not Live                                        |
|-------------------|-----------------------------------------------------|
| PAPER_QUEUED      | Paper trades not yet placed                         |
| PAPER_ACTIVE      | Still accumulating proof (trades, time, stats)      |
| PAPER_REVIEW      | Awaiting operator review decision                   |
| ITERATE           | Review said "rerun with changes" — back to Atlas    |
| PAPER_KILLED      | Review rejected it permanently                      |
| LIVE_QUEUED       | Approved for live but execution not yet triggered   |
| LIVE_ACTIVE       | Already live                                        |

## Proof Profile (Per-Strategy)

Proof requirements depend on strategy type:

```json
{
  "min_trades": 20,
  "min_days": 14,
  "min_profit_factor": 1.3,
  "min_sharpe": 0.8,
  "max_drawdown_pct": 0.15,
  "min_fill_rate": 0.90,
  "max_correlation": 0.70
}
```

These thresholds live in `shared/config/review_thresholds.json` and are loaded by Sigma at review time. Strategies that don't meet them get `iterate` or `kill` outcomes.
