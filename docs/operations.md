# Jarvis v5 Operations Notes

This document describes the operator-facing expectations for everyday use.

## Jarvis in `#jarvis`

Jarvis should:
- remain conversational
- answer status questions quickly
- help plan next steps
- support explicit task creation
- avoid silently turning ordinary conversation into queued work

## Task visibility

Durable task state should make it easy to answer:
- what is running?
- what is blocked?
- what is awaiting review?
- what just finished?
- what failed?

## Review visibility

The operator should be able to see:
- which tasks need Archimedes review
- which tasks need Anton review
- which approvals are pending
- what decisions were made

## Flowstate visibility

The operator should be able to see:
- what sources were ingested
- what was extracted
- what was distilled
- what is awaiting promotion approval

## Health visibility

The system should provide:
- heartbeat summaries
- stalled-task detection
- queue health
- recent errors
- recent completions

## Current Operator Baseline

Run these before treating the repo as deployable:

```bash
python3 scripts/validate.py
python3 scripts/smoke_test.py
python3 scripts/doctor.py
```

Use them this way:

- `validate.py` answers whether the repo, configs, imports, and writable paths are ready.
- `smoke_test.py` answers whether the current repo-local deployment baseline plus the proven runtime lifecycle are still green.
- `doctor.py` answers what is healthy, what is degraded, and what the operator should do next.

## Practical Next Move After Green

After the baseline is green:

1. inspect `state/logs/operator_snapshot.json` and `state/logs/state_export.json`
2. clear any pending reviews or approvals first
3. move the next `candidate_ready_for_live_apply` task through live apply, or the next `shipped` task through publish-complete

Use [docs/operator-first-run.md](docs/operator-first-run.md) as the first-live operator checklist.

## Overnight Operator Flow Tonight

Use the thin orchestration wrapper when you want one bounded happy-path run over the new v5.1 subsystems.

Hermes -> replay eval -> Ralph -> memory retrieval:

```bash
python3 scripts/overnight_operator_run.py \
  --task-id TASK_ID \
  --flow hermes \
  --include-candidate-memory \
  --hermes-response-file /tmp/hermes_response.json
```

Autoresearch -> Ralph -> memory retrieval:

```bash
python3 scripts/overnight_operator_run.py \
  --task-id TASK_ID \
  --flow research \
  --objective "Improve benchmark score on the bounded slice" \
  --objective-metric accuracy \
  --primary-metric accuracy \
  --include-candidate-memory \
  --research-response-file /tmp/research_runs.json
```

What this wrapper does:

- calls the existing gateway wrappers only
- returns one stable JSON object with `steps`, `summary`, `ok`, and `failed_step`
- stops at the first failing step and reports where it failed
- respects the existing control-state, review, approval, and promotion rules because it does not bypass subsystem gateways

What it does not do:

- it does not auto-promote artifacts or memory
- it does not auto-clear review or approval queues
- it does not schedule recurring runs or start background daemons

If you want promoted memory after the run, do that explicitly:

```bash
python3 runtime/gateway/memory_decision.py \
  --action promote \
  --memory-candidate-id MEMCAND_ID \
  --reason "Approved for promoted retrieval" \
  --confidence-score 0.85
```

## Morning Handoff Pack

When you wake up and want the compact operator checkpoint first, run:

```bash
python3 scripts/operator_handoff_pack.py
```

This writes:

- `state/logs/operator_handoff_pack.json`
- `state/logs/operator_handoff_pack.md`

The handoff pack summarizes:

- recent task status
- recent candidate/promoted artifacts
- latest traces and replay evals
- pending review and approval items
- latest Ralph digest and memory candidate activity
- recommended next operator actions

## Operator UX goal

The operator should be able to understand what the system is doing without having to dive through raw logs unless something is broken.
