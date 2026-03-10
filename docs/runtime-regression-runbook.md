# Runtime Regression Runbook

## Command

```bash
python3 runtime/core/run_runtime_regression_pack.py
```

## Deployment Baseline Commands

```bash
python3 scripts/validate.py
python3 scripts/smoke_test.py
python3 scripts/doctor.py
```

Use these alongside the regression pack:

- `validate.py` for repo-local preflight
- `smoke_test.py` for a compact deployment/runtime smoke
- `doctor.py` for one operator-facing health verdict and next actions

## Green Pack Meaning

A green pack currently means:

- runtime regression pack summary is `ok: true`
- total checks: `5`
- passed checks: `5`
- failed checks: `0`
- intake reaches `waiting_review`
- review and approval routing works
- approval moves to `ready_to_ship` when `final_outcome == candidate_ready_for_live_apply`
- `ready_to_ship -> shipped` works
- `runtime/gateway/complete_from_artifact.py` completes a shipped task
- output record creation succeeds
- ops-report executor regression is covered, with environment-only readonly DB cases treated as a clean skip

## Current Proven Runtime Milestone

The repo now has a proven disposable runtime chain for:

- task intake
- review and approval handoff
- ready-to-ship promotion
- ship
- publish-and-complete
- final `completed` task status
- output record generation

## Practical Operator Move After Green

Once the baseline is green:

1. check `state/logs/operator_snapshot.json`
2. clear pending review or approval work first
3. move the next `ready_to_ship` candidate through apply, or the next `shipped` task through publish-complete

## Next Non-Runtime Slices

- Dashboard and export consistency cleanup
  Reason: runtime state is now reliable; operator-facing JSON and status naming should stay fully aligned and easy to scan.
- Candidate/apply operator flow polish
  Reason: the `candidate_ready_for_live_apply` handoff now works, but the approval/apply/operator story still needs a clearer human run path and status visibility.
- Operator docs and deployment/runbook tightening
  Reason: the fastest leverage after green smokes is reducing setup friction and making reruns, triage, and handoff obvious for the next session.
