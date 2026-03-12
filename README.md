## Jarvis OS v5.1 status

Jarvis OS v5.1 required bounded runtime scope is complete in the live repo.

This repo now includes the final bounded v5.1 runtime closures that were previously identified as concrete master-spec gaps:

- Hermes adapter hardening
- autoresearch adapter hardening
- autoresearch standard run output materialization
- bounded browser operator interrupt/cancel support

The current repo state should be understood as:

- **v5.1 required bounded runtime closure: complete**
- **documentation/tracker alignment: still being cleaned up**
- **future work after freeze: optional hardening, broader smoke coverage, and post-v5.1 features**

## What was closed in the final v5.1 passes

### 1. Hermes and autoresearch adapter contract hardening

The Hermes and autoresearch integration seams now fail closed instead of loosely accepting underspecified requests or malformed result payloads.

Hermes now enforces:

- objective required
- valid timeout required
- bounded sandbox class required
- explicit allowed tools required
- Qwen-only model policy required
- callback contract consistency required
- stricter response validation for:
  - model_name
  - status
  - citations
  - proposed_next_actions
  - token_usage

Autoresearch now enforces:

- objective required
- objective metrics required
- primary metric must be valid
- baseline_ref required
- benchmark_slice_ref required
- bounded sandbox class required
- sandbox_root required
- target_module required
- program_md_path required
- eval_command required
- task metadata required
- stricter result validation for:
  - hypothesis
  - metrics maps
  - token usage
  - recommendation shape
  - allowed success statuses

Both adapter paths now persist durable failure categorization and surface those categories through the existing status/read-model spine.

### 2. Standard autoresearch run outputs

The bounded autoresearch run path now materializes the standard run outputs required by the v5.1 master spec.

Per lab run, the repo now writes:

- `run_config.json`
- `baseline_metrics.json`
- `candidate_metrics.json`
- `delta_metrics.json`
- `candidate.patch`
- `experiment_log.md`
- `recommendation.json`

These are written under the bounded research workspace using the pattern:

`<repo_root>/<sandbox_root>/<run_id>/standard_run_outputs/`

The durable `LabRunResultRecord` continues to hold the canonical structured result fields, while the standard output directory provides the required materialized run artifacts.

### 3. Browser operator interrupt/cancel

The bounded browser path now supports operator cancellation for pending or accepted browser actions.

Added browser behavior:

- cancellable browser request/result state
- durable cancel metadata:
  - `cancelled_at`
  - `cancelled_by`
  - `cancel_reason`
- gateway cancel path
- browser cancellation task event emission
- reporting/read-model visibility for cancelled browser requests/results
- guard that prevents cancelled browser requests from executing later

Supported transitions now include:

- `pending_review -> cancelled`
- `accepted -> cancelled`

A cancelled browser request cannot later be completed into execution.

## Validation baseline actually proven in the live repo

The validated baseline currently proven in the live repo is:

- `python3 scripts/validate.py`
- `python3 runtime/core/run_runtime_regression_pack.py`
- `python3 tests/test_hermes_adapter.py`
- `python3 tests/test_autoresearch_adapter.py`
- `python3 tests/test_browser_gateway.py`

Do not describe the current validated baseline as "the full pytest suite" unless that full suite has been explicitly rerun and confirmed.

## Source of truth

For v5.1 completion state, use this precedence:

1. `docs/spec/Jarvis_OS_v5_1_Master_Spec.md`
2. live runtime code
3. focused validation/tests that prove the implemented behavior
4. tracker/checklist files

The rebuild checklist is a historical implementation tracker and may lag the actual repo state.

## Freeze posture

At this freeze point, no additional required bounded runtime pass is known to remain for v5.1.

Remaining work is in the category of:

- documentation alignment
- tracker cleanup
- optional broader validation
- future features beyond required bounded v5.1 closure

## Runtime posture: live vs 5.2 target

Current live runtime posture:
- Qwen-default / Qwen-first
- bounded provider-agnostic architecture
- explicit `task:` execution boundary
- no silent widening of execution authority

5.2 target posture:
- multi-model, policy-routed runtime
- richer backend health and accelerator visibility
- replay/scoring scaffolding expanded into deeper routing evaluation

This repo does not claim that the 5.2 target posture is already implemented. Current 5.2 work in this branch is scaffolding only unless a later routing-core ticket says otherwise.
