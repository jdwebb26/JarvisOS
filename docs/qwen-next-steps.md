# Qwen Next Steps

## Runtime Milestone

Current runtime regression pack is green:

- command: `python3 runtime/core/run_runtime_regression_pack.py`
- result: `ok: true`, `total: 5`, `passed: 5`, `failed: 0`
- proven chain: intake -> waiting_review -> review/approval -> ready_to_ship -> shipped -> gateway publish-complete -> completed + output record

## Next Non-Runtime Slices

- Dashboard/export consistency and naming cleanup
  Reason: operator visibility should reflect the now-proven runtime lifecycle without mixed naming or stale handoff language.
- Candidate/apply/operator flow polish
  Reason: `candidate_ready_for_live_apply` is now a meaningful handoff marker; the operator path around approvals, apply intent, and state explanations should be made clearer.
- Docs/runbook/deployment tightening
  Reason: the runtime core is ahead of the operational docs; the next agent should be able to rerun regressions and understand deployment/operator expectations immediately.

## Keep

- Keep `qwen_agent_smoke.py` as the safe standalone entry point and continue wiring the script through `scripts/qwen_agent_health.py` whenever the agent bridge must be verified.
- Keep `qwen_task_adapter.py` read-only for now.
- Use Qwen for workspace inspection, runtime summaries, and doc/artifact generation.
