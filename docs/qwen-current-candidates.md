# Qwen Current In-Scope Candidates

Recent tasks from `workspace_scope_candidates` that are currently in scope for the initial Qwen lane.

| Task ID | Title | Priority | Reason |
|---------|-------|----------|--------|
| 67 | NQ SF P1.3 implement synthetic data + sim early-exit + smoke test RETRY | 10 | strategy-factory workflow with structured phase/step naming |
| 68 | NQ SF P2.1 implement gates + regimes + tests RETRY | 10 | strategy-factory workflow with structured phase/step naming |
| 64 | NQ SF P1.2 implement fold builder + purge enforcement + tests | 9 | strategy-factory workflow with structured phase/step naming |
| 65 | NQ SF P1.3 implement synthetic data + sim early-exit + smoke test | 9 | strategy-factory workflow with structured phase/step naming |
| 66 | NQ SF P2.1 implement gates + regimes + tests | 9 | strategy-factory workflow with structured phase/step naming |
| 63 | NQ SF P1.1 create repo skeleton + config + artifacts + folds + sim + synthetic smoke test | 9 | strategy-factory workflow with structured phase/step naming |
| 61 | implement real ops report from task 17 outline | 5 | implementation-oriented title |
| 60 | implement real ops report from task 17 outline | 5 | implementation-oriented title |

## Summary

- **Total scanned**: 20 recent tasks
- **In scope (allowed)**: 8 tasks
- **Out of scope (rejected)**: 12 tasks

### Allowed Task Categories

1. **Strategy-factory workflow** (6 tasks): Tasks 63, 64, 65, 66, 67, 68 - all follow `NQ SF P{phase}.{step}` pattern with priority ≥9
2. **Implementation-oriented** (2 tasks): Tasks 60, 61 - concrete implementation work with priority ≥5

### Rejection Reasons for Out-of-Scope Tasks

- Priority too low (<5 or <9 depending on category)
- Generic helper/stub/smoke test without strong implementation signals
- Missing structured phase/step naming
- Unexpected status=blocked
- No payload_path present

---
*Generated from workspace_scope_candidates scan.*
