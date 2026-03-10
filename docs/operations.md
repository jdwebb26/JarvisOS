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

## Checkpoint Action Pack

When you want copy-paste commands for the next manual checkpoint decisions, run:

```bash
python3 scripts/operator_checkpoint_action_pack.py
```

This writes:

- `state/logs/operator_checkpoint_action_pack.json`
- `state/logs/operator_checkpoint_action_pack.md`

The action pack includes:

- pending review commands
- pending approval commands
- memory promote/reject/supersede commands
- artifact inspection and follow-up commands where task state makes them relevant
- a recommended execution order

## One-Step Action Executor

When the checkpoint action pack already exists and you want to run one suggested action by stable id instead of copy-pasting the command, use:

```bash
python3 scripts/operator_action_executor.py --action-id ACTION_ID
```

For example, take an `action_id` from `recommended_execution_order` or one of the action sections in `state/logs/operator_checkpoint_action_pack.json`, then run it directly.

To resolve and log an action without executing it:

```bash
python3 scripts/operator_action_executor.py --action-id ACTION_ID --dry-run
```

To pin execution to a saved checkpoint action pack:

```bash
python3 scripts/operator_action_executor.py \
  --action-id ACTION_ID \
  --action-pack-path state/logs/operator_checkpoint_action_pack.json
```

Pinned-pack behavior:

- if the pinned pack is expired, malformed, or fingerprint-invalid, the executor fails clearly
- it does not silently swap to a rebuilt pack when `--action-pack-path` was requested
- execution records include the consumed `source_action_pack_id`, fingerprint, validation status, and resolution

Execution records are written to:

- `state/operator_action_executions/*.json`

To resume the latest failed or dry-run action for a task or category:

```bash
python3 scripts/operator_resume_action.py --task-id TASK_ID
python3 scripts/operator_resume_action.py --category pending_review
```

To explicitly replay the latest successful action:

```bash
python3 scripts/operator_resume_action.py --task-id TASK_ID --replay-success
```

To run the current recommended checkpoint actions as a bounded queue:

```bash
python3 scripts/operator_queue_runner.py
```

Useful filters:

```bash
python3 scripts/operator_queue_runner.py --task-id TASK_ID
python3 scripts/operator_queue_runner.py --category memory_candidate
python3 scripts/operator_queue_runner.py --max-actions 3 --dry-run
python3 scripts/operator_queue_runner.py --continue-on-failure
python3 scripts/operator_queue_runner.py --allow-category memory_candidate
python3 scripts/operator_queue_runner.py --allow-approval
python3 scripts/operator_queue_runner.py --deny-category pending_review
python3 scripts/operator_queue_runner.py --force
```

Queue-run records are written to:

- `state/operator_queue_runs/*.json`

To run a bounded bulk selection over the current action pack:

```bash
python3 scripts/operator_bulk_action_runner.py --category pending_review --dry-run
python3 scripts/operator_bulk_action_runner.py --task-id TASK_ID --action-id-prefix artifact:
python3 scripts/operator_bulk_action_runner.py --category artifact_followup --force
```

Bulk-run records are written to:

- `state/operator_bulk_runs/*.json`

To explain why a specific action executed, skipped, or refused:

```bash
python3 scripts/operator_action_explain.py --action-id ACTION_ID
python3 scripts/operator_action_explain.py --task-id TASK_ID
```

To inspect current action-pack freshness, expiry, and provenance quickly:

```bash
python3 scripts/operator_checkpoint_action_pack.py
python3 scripts/operator_handoff_pack.py
python3 -m json.tool state/logs/operator_checkpoint_action_pack.json
```

Look for:

- `action_pack_id`
- `action_pack_fingerprint`
- `recommended_ttl_seconds`
- `expires_at`
- `stale_after_reason`
- `source_action_pack_validation_status`
- `source_action_pack_resolution`
- `source_action_pack_rebuild_reason`

To generate an operator triage pack from durable control-plane ledgers:

```bash
python3 scripts/operator_triage_pack.py
python3 -m json.tool state/logs/operator_triage_pack.json
```

The triage pack highlights:

- highest-priority manual blockers
- per-task intervention summaries
- repeated stale/idempotency/pinned-pack failure patterns
- concrete next operator commands

To intervene on one task with the newest valid pack:

```bash
python3 scripts/operator_task_intervene.py --task-id TASK_ID --dry-run
python3 scripts/operator_task_intervene.py --task-id TASK_ID
```

To force a rerun after duplicate protection, or to use a pinned pack deliberately:

```bash
python3 scripts/operator_task_intervene.py --task-id TASK_ID --force
python3 scripts/operator_task_intervene.py --task-id TASK_ID --action-pack-path state/logs/operator_checkpoint_action_pack.json
```

Use the current pack when the ledger says an older pack is stale, expired, or missing actions.
Use pinned provenance only when you intentionally want to replay against the exact saved snapshot and are prepared for it to refuse if that snapshot is no longer valid.

To perform only the safest bounded wrapper-level interventions:

```bash
python3 scripts/operator_safe_autofix.py
python3 scripts/operator_safe_autofix.py --dry-run-top-action
python3 scripts/operator_safe_autofix.py --execute-safe-review
```

Safe autofix will:

- rebuild the current pack when it is expired or invalid
- explain top blocker items from durable ledgers
- optionally dry-run one safe review action
- optionally execute exactly one safe review approval

Safe autofix will not:

- approve pending approvals
- promote memory
- ship or publish artifacts
- bypass stale/idempotency/policy checks

Repeated-problem summaries appear in:

- `state/logs/operator_triage_pack.json`
- `state/logs/operator_handoff_pack.json`
- `state/logs/state_export.json`

To build the compact command-center view:

```bash
python3 scripts/operator_command_center.py
python3 -m json.tool state/logs/operator_command_center.json
```

Use command center when you want the shortest “what needs action now” view with ranked commands, deltas, and a green/yellow/red wrapper-health label.

To list current operator actions, tasks, or runs:

```bash
python3 scripts/operator_list_actions.py --category pending_review --only-safe
python3 scripts/operator_list_tasks.py --needs-review
python3 scripts/operator_list_runs.py --kind queue --failed-only
```

Use these list wrappers when you want compact filtered JSON instead of the full handoff or triage pack.

To build a cleaner printable next-step manifest:

```bash
python3 scripts/operator_decision_manifest.py
python3 -m json.tool state/logs/operator_decision_manifest.json
```

Use the decision manifest when you want a bounded “what should I do next / what should I avoid” artifact rather than the fuller triage pack.

To compare action packs or triage snapshots:

```bash
python3 scripts/operator_compare_packs.py --other-pack-path /tmp/older_pack.json
python3 scripts/operator_compare_triage.py --other-triage-path /tmp/older_triage.json
```

Use pack comparison when action ids or recommended order seem to have changed.
Use triage comparison when blocker counts or recommended interventions changed and you want the delta only.

To build the reply-ready decision inbox and tiny shortlist:

```bash
python3 scripts/operator_decision_inbox.py
python3 scripts/operator_decision_shortlist.py
```

Use the inbox when you want compact reply codes plus the full bounded item metadata.
Use the shortlist when you want the smallest phone/watch-style summary.

Reply-code meanings:

- `A1`: execute the primary safe approve/apply action for inbox item 1
- `R2`: execute the valid reject action for inbox item 2
- `P3`: execute the valid memory-promote action for inbox item 3
- `X4`: explain inbox item 4 only
- `B5`: rebuild or refresh first for inbox item 5
- `F6`: force-rerun inbox item 6 only if that item explicitly allows force

To plan, preview, or apply a compact reply:

```bash
python3 scripts/operator_reply_plan.py --reply "A1 X2"
python3 scripts/operator_reply_preview.py --reply "A1 X2"
python3 scripts/operator_apply_reply.py --reply "A1 X2" --dry-run
python3 scripts/operator_apply_reply.py --reply "A1"
```

Use reply plan when you want a durable non-executing plan.
Use preview when you want the exact execute/explain/rebuild breakdown.
Use apply when you want the reply string carried through existing wrapper guards.

To compare inbox snapshots:

```bash
python3 scripts/operator_compare_inbox.py --other-inbox-path /tmp/older_inbox.json
```

When deciding whether to use `--force`:

- use `--force` only when an action already succeeded and you explicitly want to override duplicate protection
- do not use `--force` to push through a stale action; stale actions should be explained or replaced with a fresh action from the newest pack
- use `F#` reply codes only when the inbox explicitly exposes them
- if the inbox does not expose `F#`, force is not valid for that item

When to use task intervene vs queue vs bulk:

- use `operator_task_intervene.py` when you want one task-centric bounded action with blocker inspection first
- use `operator_queue_runner.py` when you want recommended-order execution with policy and idempotency guards
- use `operator_bulk_action_runner.py` when you want explicit filtered batch selection across the current pack
- use the inbox/apply-reply path when you want the shortest deterministic operator reply grammar

How to interpret operator wrapper health:

- `green`: current pack is valid and there are no recent queue/bulk failures or repeated stale/pinned-pack problems
- `yellow`: the pack is valid, but there are still manual blockers like reviews, approvals, or memory decisions
- `red`: pack freshness is bad, queue/bulk failures exist, or repeated stale/pinned-pack failures are present

Reply-ready vs not-reply-ready:

- `reply-ready`: the current inbox was built from a valid pack and exposes reply-safe items
- `not reply-ready`: the current pack is invalid, the inbox is empty, or only explain/rebuild-style items remain

When rebuild-first is appropriate:

- use `B#` or rebuild the pack directly when the inbox item says pack refresh is required first
- rebuild-first is appropriate for expired, fingerprint-invalid, or missing-current-pack situations

## Operator UX goal

The operator should be able to understand what the system is doing without having to dive through raw logs unless something is broken.
