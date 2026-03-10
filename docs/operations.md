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

## Operator UX goal

The operator should be able to understand what the system is doing without having to dive through raw logs unless something is broken.
