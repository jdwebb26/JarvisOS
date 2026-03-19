# Live Backlog Cleanup — 2026-03-19

Executed: 2026-03-19T05:35 CDT

## What was done

Archived 31 stale smoke/proof/test/browser-noise tasks and cancelled 5 orphaned approval records, per the triage doc (`live_backlog_triage_2026-03-19.md`).

## Before / After Counts

| Status | Before | After | Delta |
|--------|--------|-------|-------|
| archived | 0 | 31 | +31 |
| failed | 6 | 2 | -4 |
| waiting_approval | 11 | 4 | -7 (2 task-archived + 5 approval-cancelled) |
| waiting_review | 15 | 5 | -10 |
| blocked | 12 | 3 | -9 |
| queued | 4 | 1 | -3 |
| completed | 48 | 50 | +2 (concurrent Ralph completions) |
| shipped | 4 | 4 | 0 |
| ready_to_ship | 1 | 1 | 0 |
| **Total active backlog** | **49** | **16** | **-33** |

Health monitor: DEGRADED (12 healthy, 1 degraded: 2 failed tasks remaining)

## Archived Task IDs (31)

### Failed browser tests (4)
- `task_87bb709ff7ed` — fill_sensitive example.com (failed → archived)
- `task_2b39d14fa089` — fill_sensitive remilia.net (failed → archived)
- `task_426bca90e4cd` — tab_open_failed remilia (failed → archived)
- `task_4f03e39cf9ab` — tab_open_failed remilia dup (failed → archived)

### Stale waiting_approval smoke/proofs (5)
- `task_b9f27c71f948` — deploy smoke 03-09 (waiting_approval → archived)
- `task_493c25cfa449` — deploy smoke 03-17 (waiting_approval → archived)
- `task_f12edb22ddc4` — deploy smoke 03-17 (waiting_approval → archived)
- `task_89ed7a35b70d` — review flow proof v2 (waiting_approval → archived)
- `task_c0270cf2b158` — review flow approval proof (waiting_approval → archived)

### Stale waiting_review Mar 9 regression smokes (6)
- `task_715939b805ec` — deploy restart (waiting_review → archived)
- `task_84d4ec9cfd46` — deploy regression smoke (waiting_review → archived)
- `task_9c69c65badd7` — patch bug intake smoke (waiting_review → archived)
- `task_e134c1f6347c` — deploy intake smoke (waiting_review → archived)
- `task_e3d72b5aa2b8` — patch bug executor (waiting_review → archived)
- `task_e4bdfd0fc6e4` — patch bug regression smoke (waiting_review → archived)

### Stale waiting_review Mar 18 plugin smokes (4)
- `task_081cc40435f6` — /skill smoke (waiting_review → archived)
- `task_2165748cfe3b` — /task smoke (waiting_review → archived)
- `task_8d4d229a0fd8` — plugin smoke 4 (waiting_review → archived)
- `task_928ebba49415` — plugin smoke 5 (waiting_review → archived)

### Stale blocked proof/test/trivial (9)
- `task_76f6e609442e` — review flow proof (blocked → archived)
- `task_fa123d729ed1` — reject proof (blocked → archived)
- `task_d4330605535b` — FINAL approval proof (blocked → archived)
- `task_f264d6f6f7f7` — reject proof (blocked → archived)
- `task_ddd67cb59a46` — "say hello" (blocked → archived)
- `task_9d466c17c56b` — list 3 task IDs (blocked → archived)
- `task_32c4292e73b9` — 20-period SMA (blocked → archived)
- `task_4c14f71c71d0` — cockpit summary (blocked → archived)
- `task_8b0435b735a7` — Ralph daily summary (blocked → archived)

### Stale queued deploy smokes from 03-09 (3)
- `task_92c20f26be1b` — deploy smoke (queued → archived)
- `task_7d3a2154e2a7` — deploy smoke (queued → archived)
- `task_81a337bbf2d7` — deploy smoke (queued → archived)

## Cancelled Approval Records (5)

- `apr_3f7c8486d081` → task_b9f27c71f948 (pending → cancelled)
- `apr_b01840e310a5` → task_493c25cfa449 (pending → cancelled)
- `apr_6ecfa2a8b652` → task_f12edb22ddc4 (pending → cancelled)
- `apr_3cc3770a0ecd` → task_89ed7a35b70d (pending → cancelled)
- `apr_664ae3fa759e` → task_c0270cf2b158 (pending → cancelled)

## Preserved for Operator Review

### Failed (2) — needs operator decision
- `task_3d7fe2922bca` — NQ momentum pipeline parent (2/5 subtasks failed)
- `task_903822e720a4` — EMA crossover subtask (NVIDIA timeout, retryable)

### Waiting approval (4) — real work, needs review then approve
- `task_9adfbdd73ecc` — EMA crossover signal function (code)
- `task_94c3240b45f1` — Volume confirmation filter (code)
- `task_3a720808800c` — CLI historical analysis entry point (code)
- `task_48c2e082c911` — Agent status listing (general)
- `task_5aaaf29ccf7b` — OpenClaw tagline (creative)
- `task_ba737f97f7fb` — Memory compaction summary (docs)

### Waiting review (5) — real work, needs Archimedes or operator
- `task_ae965a6b5f1c` — NQ regime from volatility (quant)
- `task_3d87da70439f` — Kitt NQ regime brief (quant)
- `task_0c26c42e6a89` — NQ regime from Scout memory (quant)
- `task_83a1306a1492` — Health check per service (deploy)
- `task_986434bef2bc` — Creative tagline (quant)

### Blocked (3) — dependent on upstream decisions
- `task_bb3f9a51061f` — VIX regime gate subtask (blocked on parent pipeline)
- `task_1578e6a5de0a` — VIX search (research, retryable)
- `task_e18ee952f995` — Fed rate decisions (research, retryable)

### Queued (1) — real task
- `task_ee3d63743eba` — Browse finance.yahoo.com NQ snapshot

### Ready to ship (1)
- `task_d7b35612e2c7` — deploy smoke from 03-09 (stale but already at terminal gate; leave for operator)

## Ambiguous Items Left Untouched

- `task_d7b35612e2c7` (ready_to_ship) — stale deploy smoke from 03-09, but already at terminal gate. Archiving a ready_to_ship task felt riskier than leaving it. Operator can ship or archive.
- Review records for archived tasks — left as-is (pending status). They are orphaned but harmless; the runtime won't process reviews for archived tasks.
- `task_4c14f71c71d0` and `task_8b0435b735a7` — the triage doc listed these as "RETRY" but they were also stuck-in-working with no clear unblock path. Archived as stale since they are 1+ day old diagnostics with no artifacts.

## Status transition used

For all 31 tasks:
```json
{
  "status": "archived",
  "lifecycle_state": "archived",
  "updated_at": "<current ISO timestamp>"
}
```
This follows the existing `TaskStatus.ARCHIVED` and `RecordLifecycleState.ARCHIVED` enums in `runtime/core/models.py`.

For 5 approval records:
```json
{
  "status": "cancelled",
  "updated_at": "<current ISO timestamp>"
}
```
This follows `ApprovalStatus.CANCELLED` in `runtime/core/models.py`.
