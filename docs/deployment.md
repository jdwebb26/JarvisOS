# Jarvis v5 Deployment Policy

Jarvis v5 deployment must be validation-first.

## Required order

1. install
2. configure
3. validate
4. smoke test
5. doctor
6. only then start services

## Current Commands

```bash
python3 scripts/validate.py
python3 scripts/validate.py --json
python3 scripts/smoke_test.py
python3 scripts/doctor.py
python3 runtime/core/run_runtime_regression_pack.py
```

Use them in that order for the current repo-local deployment baseline.

If you are the next operator/session picking this up cold, start with [docs/operator-first-run.md](docs/operator-first-run.md).

## Required deployment artifacts

The workspace should contain and maintain:

- `scripts/install.sh`
- `scripts/bootstrap.py`
- `scripts/generate_config.py`
- `scripts/validate.py`
- `scripts/doctor.py`
- `scripts/smoke_test.py`
- example config files
- service/unit files

## Deployment goals

Deployment should:
- fail early
- fail clearly
- catch Discord/config/path/model issues before runtime
- avoid hidden environment drift
- be boring on a fresh machine

## Minimum validation scope

Validation should check:
- required directories
- required files
- live and example config presence
- placeholder/config drift
- model config family restrictions
- writable `state/logs` and `workspace/out`
- Python import readiness for the proven runtime path
- runtime regression-pack entrypoint presence

## Current Validate Behavior

`python3 scripts/validate.py` is the practical preflight for this repo. It reports:

- pass / warn / fail findings
- exact remediation text for blocking failures
- repo-derived deployment path readiness
- Qwen-only config checks
- operator/runtime prerequisites

It also writes `state/logs/validate_report.json`.

## Doctor scope

Doctor should help diagnose:
- missing or placeholder configs
- permission/path problems in repo-local writable areas
- import/runtime drift in the proven lifecycle
- stale or missing operator-facing logs
- whether the regression pack is still green

## Current Doctor Behavior

`python3 scripts/doctor.py` reuses the validate layer, inspects current runtime/operator artifacts, reruns the regression pack, and returns one verdict:

- `healthy`
- `healthy_with_warnings`
- `blocked`

It writes `state/logs/doctor_report.json`.

## Smoke Test

`python3 scripts/smoke_test.py` is the lightweight repo-local smoke. It:

- runs the validate preflight
- stops immediately if validate has blocking failures
- runs `python3 runtime/core/run_runtime_regression_pack.py`
- prints a compact success/failure summary
- writes `state/logs/smoke_test_report.json`

## First Live Use

After the baseline is green:

1. inspect `state/logs/operator_snapshot.json`
2. inspect `state/logs/state_export.json`
3. clear pending review/approval work
4. move `ready_to_ship` tasks through apply
5. move `shipped` tasks with linked artifacts through publish-complete

See [docs/operator-first-run.md](docs/operator-first-run.md) for the compact checklist.

## Hard rule

Do not rely on runtime crashes to reveal setup problems that could have been caught during validation.
