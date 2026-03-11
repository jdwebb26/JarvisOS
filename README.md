# Jarvis / OpenClaw v5.1

Jarvis/OpenClaw v5.1 is a durable task, artifact, review, approval, provenance, replay, and control spine for Jarvis OS.
It is designed so the architecture stays provider-agnostic while the current live deployment remains Qwen-first.

## What this repo is

This repo is the live JarvisOS v5.1 codebase.

It contains:

- the core runtime and durable record models
- routing, candidate promotion, rollback, approval, replay, and memory governance
- bounded subsystem adapters such as Hermes, autoresearch, and Ralph
- operator-facing status, export, handoff, and validation scripts

It is not a fresh rebuild or a sidecar demo repo. It is the working in-place v5.1 system.

## Source vs runtime state

The repo keeps source and live runtime artifacts separate on purpose.

- Source code lives under `runtime/`, `scripts/`, `config/`, and `tests/`.
- Managed runtime state lives under `state/`.
- Operator/demo outputs live under `workspace/out/`.
- Scratch work products live under `workspace/work/`.

If you see stateful artifacts at repo root, treat them as legacy residue unless they are clearly documented source files.

## Current status

The repo is currently green for the intended Qwen-default deployment target.

The validated baseline includes:

- bootstrap
- validate
- smoke test
- doctor
- the runtime regression pack
- the full pytest suite

The runtime architecture is provider-agnostic, but the active deployment policy and tested default path remain Qwen/qwen-agent first.

## How to demo locally

For a clean local demo path, run:

```bash
python3 scripts/bootstrap.py
python3 scripts/validate.py
python3 scripts/smoke_test.py
python3 scripts/doctor.py
```

If those are green, inspect:

- `state/logs/operator_snapshot.json`
- `state/logs/state_export.json`
- `state/logs/operator_handoff_pack.json`

Then walk the next `ready_to_ship` or `shipped` task through the normal review/apply/publish flow.

## Active deployment policy

The current deployment policy is intentionally Qwen-default.

That means:

- Qwen/qwen-agent remains the preferred and validated runtime path
- provider/model/backend identity is still carried through durable routing and execution records
- future provider swaps should be policy/config changes, not core-spine rewrites
- no non-Qwen provider rollout is implied by this repo state

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
python3 scripts/bootstrap.py
python3 scripts/validate.py
python3 scripts/smoke_test.py
python3 scripts/doctor.py
```

What these cover:

- `bootstrap.py` creates the managed state/workspace folders and copies missing live config skeletons from the example files.
- `validate.py` checks repo shape, current config presence, active Qwen-only policy hints, writable operator paths, and key imports.
- `smoke_test.py` runs the repo-local preflight, the proven runtime regression pack, and rebuilds the operator/dashboard summary artifacts.
- `doctor.py` rolls the baseline into one operator-facing verdict with next actions.

After a green baseline, the practical next operator move is to inspect `state/logs/operator_snapshot.json` and push the next `ready_to_ship` or `shipped` task through apply/publish-complete. See [docs/runtime-regression-runbook.md](docs/runtime-regression-runbook.md), [docs/deployment.md](docs/deployment.md), and [docs/operations.md](docs/operations.md).

For the fastest first-live-use path, use [docs/operator-first-run.md](docs/operator-first-run.md).
