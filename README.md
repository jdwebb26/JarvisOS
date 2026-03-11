# Jarvis / OpenClaw v5

Jarvis/OpenClaw v5 is a chat-first operator system built around durable events, explicit task creation, approval-aware execution, Flowstate distillation, and artifact-first review. The runtime architecture is provider-agnostic, but the active deployment policy remains Qwen-only.

## Core rules

1. Conversation is not execution.
2. Ordinary chat in `#jarvis` must not silently enqueue work.
3. Jarvis stays conversational and useful in `#jarvis`.
4. Explicit task creation remains supported.
5. Task state must be durable and visible.
6. Flowstate promotion is gated by approval.
7. Code and risky work require review.
8. Deployment is validation-first.
9. No silent switching away from the Qwen 3.5 family.

## Accepted explicit task trigger

Initial supported task trigger in `#jarvis`:

- `task: ...`

## Operational spine

Discord ingest -> events.db -> enrich_worker -> router -> outputs/tasks -> executor -> dashboard

v5 preserves and hardens this spine rather than replacing it.

## Main lanes

- `#jarvis` — chat, planning, orchestration, status, explicit task creation only
- `#tasks` — durable task lifecycle visibility
- `#outputs` — approved final artifacts
- `#review` — concise approval decisions
- `#audit` — risky / high-stakes review summaries
- `#code-review` — code-review output
- `#flowstate` — ingest / distill / propose lane

## Review policy

- **Archimedes** reviews code and production-facing implementation changes
- **Anton** reviews risky, deploy/ship, trading/quant, and other high-stakes work

## Flowstate policy

Flowstate outputs do not automatically become tasks, memory, or global assumptions.
Promotion requires explicit approval.

## Implementation order

1. Contracts and docs
2. Bootstrap / validate / doctor
3. Minimum durable runtime
4. Review and approval system
5. Flowstate lane
6. Qwen-native specialization
7. Dashboard / operator visibility
8. Migration / packaging / hardening
9. Only then expand autonomy loops

## Current status

The repo now has a proven runtime regression pack in `runtime/core/` covering intake, review/approval routing, `ready_to_ship`, ship, publish-complete, and output creation.

Rerun command:

```bash
python3 runtime/core/run_runtime_regression_pack.py
```

Current green meaning: `ok: true`, `total: 5`, `passed: 5`, `failed: 0`.

Deployment/operator baseline:

```bash
python3 scripts/validate.py
python3 scripts/smoke_test.py
python3 scripts/doctor.py
```

What these cover:

- `validate.py` checks repo shape, current config presence, active Qwen-only policy hints, writable operator paths, and key imports.
- `smoke_test.py` runs the repo-local preflight and then the proven runtime regression pack.
- `doctor.py` rolls the baseline into one operator-facing verdict with next actions.

After a green baseline, the practical next operator move is to inspect `state/logs/operator_snapshot.json` and push the next `ready_to_ship` or `shipped` task through apply/publish-complete. See [docs/runtime-regression-runbook.md](docs/runtime-regression-runbook.md), [docs/deployment.md](docs/deployment.md), and [docs/operations.md](docs/operations.md).

For the fastest first-live-use path, use [docs/operator-first-run.md](docs/operator-first-run.md).
