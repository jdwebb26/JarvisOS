# Jarvis v5 Review Policy

Jarvis v5 is approval-aware. Review is not optional for risky classes of work.

## Reviewer roles

### Archimedes

Use Archimedes for:
- code tasks
- code review tasks
- production-facing implementation changes
- patches that modify runtime behavior

### Anton

Use Anton for:
- risky tasks
- deploy / ship tasks
- trading / quant tasks
- high-stakes outputs
- changes that could affect operator trust or external behavior

---

## Approval requirements

Approval is required before finalization for:
- code changes
- deploy / ship actions
- Flowstate promotion
- trading / quant outputs marked high-stakes
- other tasks flagged risky by policy

---

## Minimum approval object

Each approval request should capture:
- approval ID
- related task ID
- approval type
- requested action
- requester
- requested reviewer
- timestamp
- current status
- linked artifact(s)
- linked review verdict(s)

---

## Review outputs should be structured

At minimum, review artifacts should answer:
- what was reviewed
- what looks good
- what is risky or incomplete
- recommended decision
- blocking issues, if any

---

## Decision states

Suggested durable statuses:
- `pending_review`
- `in_review`
- `changes_requested`
- `approved`
- `rejected`
- `expired`

---

## Concise approval UX

The `#review` lane should support short replies like:
- `yes`
- `no`
- `1`
- `2`
- `A`
- `B`

These should map cleanly onto approval objects.

---

## Policy guardrails

- no silent approval inference from casual chat
- no code finalization without required review
- no deploy finalization without required review
- no Flowstate promotion without required approval
