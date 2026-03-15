# TLA+ Approval Gate Follow-Ups

## Current runtime drift from `ApprovalGate.tla`

The runtime mostly enforces review/approval through explicit objects and task transitions:

- review requests live in [review_store.py](/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/review_store.py)
- approval requests and resumable checkpoints live in [approval_store.py](/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/approval_store.py)
- task status transitions live in [task_store.py](/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/task_store.py)
- `ready_to_ship` requires a promoted artifact in [task_runtime.py](/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/task_runtime.py)

The main semantic drift from the TLA+ model is this:

- the model treats review decisions as applying to produced work only
- the runtime tries to link reviews/approvals to artifacts via `linked_artifact_ids`
- but both `request_review(...)` and `request_approval(...)` still allow the link list to be empty when no candidate/promoted artifact is found

That means the control plane can create pending review/approval objects for work that is not yet artifact-bound, even though downstream promotion/shipping later requires a real promoted artifact.

## Are reviewer checks applied to produced artifacts/results or only the original request?

Best current answer: partially artifact-aware, but not artifact-strict.

Evidence:

- `request_review(...)` selects a task artifact when available, otherwise records an empty `linked_artifact_ids` list.
- `request_approval(...)` does the same.
- `record_review_verdict(...)` and `record_approval_decision(...)` try to resolve the linked artifact and demote/revoke it when present.
- `ready_to_ship_task(...)` refuses to move forward without a promoted artifact.

So the runtime is better than "reviewing only the original request text," but it still permits review / approval objects to exist before the produced artifact/result is definitely bound.

## Smallest future runtime fix

The smallest worthwhile fix is:

1. make review/approval request creation artifact-strict for task types that are supposed to produce promotable work
2. refuse `request_review(...)` / `request_approval(...)` when `linked_artifact_ids` would otherwise be empty
3. allow an explicit exception only for task classes that are terminal-result-only and do not participate in candidate promotion / shipping

That keeps the existing control-plane shape intact while moving the runtime closer to the `ApprovalGate.tla` rule that review decisions should apply to produced work, not only to the original request summary.
