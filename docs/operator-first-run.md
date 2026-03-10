# Operator First Run

This is the shortest practical path from repo checkout to first live operator use.

## First-Live Checklist

1. Confirm config files exist:
   - `config/app.yaml`
   - `config/channels.yaml`
   - `config/models.yaml`
   - `config/policies.yaml`
2. Run the baseline commands:

```bash
python3 scripts/validate.py
python3 scripts/smoke_test.py
python3 scripts/doctor.py
python3 runtime/core/run_runtime_regression_pack.py
```

3. Treat this baseline as green when:
   - `scripts/validate.py` passes
   - `scripts/smoke_test.py` passes
   - `scripts/doctor.py` returns `healthy` or `healthy_with_warnings`
   - `runtime/core/run_runtime_regression_pack.py` returns `ok: true`

## What `healthy_with_warnings` Means Here

Current expected warnings are non-blocking:

- missing `.git` metadata can be ignored in this source-export setup
- `REPLACE_ME` values in live Discord config still need to be filled before a real Discord deployment

Treat `healthy_with_warnings` as usable for local/operator validation. Treat it as not fully live-ready until the placeholder config values are replaced.

## Service / Startup Checklist

1. Fill in real Discord IDs and any environment-specific values in:
   - `config/app.yaml`
   - `config/channels.yaml`
2. Re-run:

```bash
python3 scripts/validate.py
python3 scripts/doctor.py
```

3. Confirm these logs exist and look current:
   - `state/logs/validate_report.json`
   - `state/logs/smoke_test_report.json`
   - `state/logs/doctor_report.json`
   - `state/logs/operator_snapshot.json`
   - `state/logs/state_export.json`
4. Only after the baseline is green should you start any surrounding service/process wrapper for Discord or workers.

## Discord / Channel Wiring Checklist

Fill these channel mappings in `config/channels.yaml`:

- `jarvis`
- `tasks`
- `outputs`
- `review`
- `audit`
- `code_review`
- `flowstate`

Expected usage:

- `#jarvis`: chat, status, explicit `task:` creation only
- `#tasks`: task lifecycle visibility
- `#outputs`: final artifacts / completed useful outputs
- `#review`: review and approval handoff
- `#audit`: high-stakes summaries
- `#code-review`: code review output
- `#flowstate`: ingest / distill / promotion candidates

## Green Baseline -> What Do I Do Next?

After the baseline is green:

1. Inspect:
   - `state/logs/operator_snapshot.json`
   - `state/logs/state_export.json`
   - `state/logs/task_board.json`
   - `state/logs/review_inbox.json`
2. Clear pending review or approval work first.
3. If a task is `ready_to_ship` and marked `candidate_ready_for_live_apply`, use the apply path.
4. If a task is already `shipped` and has a linked artifact, use publish-complete.

## Apply vs Publish-Complete

Use apply when:

- the task is `ready_to_ship`
- the candidate is approved for live apply
- the operator wants to move the task through the live-apply handoff

Use publish-complete when:

- the task is already `shipped`
- a linked artifact exists
- the operator wants the task to land in `completed`

## Most Likely First-Run Problems

- `validate.py` fails on missing files or directories
  Fix: restore the missing repo file or rerun bootstrap/config generation.
- `doctor.py` says `healthy_with_warnings`
  Fix: read the warning text. In this repo, missing `.git` is ignorable in source-export mode; `REPLACE_ME` config values are not ignorable for live Discord use.
- `smoke_test.py` fails at validate
  Fix: resolve the blocking preflight issue first.
- regression pack is not green
  Fix: do not start live use. Repair the failing smoke before proceeding.
- operator logs are stale or missing
  Fix: rerun the baseline commands and then inspect `state/logs/`.
