# Qwen Scope Policy

This policy defines which tasks are allowed for the initial Qwen lane in the Jarvis workspace.

## Allowed Task Patterns

Tasks are **allowed** when they exhibit these signals:

1. **Strategy-factory workflow**: Tasks follow the `NQ SF P{phase}.{step}` naming convention (e.g., "NQ SF P1.3 implement synthetic data + sim early-exit")
2. **Structured phase/step naming**: Clear phase and step identifiers in the title
3. **Implementation-oriented titles**: Titles describe concrete implementation work, not generic testing or stubs
4. **Sufficient priority**: Priority >= 9 for strategy-factory tasks; priority >= 5 for other implementation tasks
5. **Valid status**: Status is `done` (not `blocked`)
6. **Payload path present**: Task has a valid payload_path pointing to result artifacts

## Disallowed Task Patterns

Tasks are **rejected** when they exhibit these signals:

1. **Priority too low**: Priority < 5 for non-strategy-factory tasks; priority < 9 for strategy-factory tasks
2. **Generic helper/stub tasks**: Tasks titled as "helper", "stub", or generic smoke tests without implementation direction
3. **Missing structured implementation signals**: No phase/step naming, no clear implementation description
4. **Unexpected status=blocked**: Task status is `blocked` rather than `done`
5. **No payload_path present**: Missing result artifact path in task metadata
6. **Generic smoke tests without strong implementation signals**: Smoke test tasks that don't describe concrete implementation work

## Minimum Priority Rule

- **Strategy-factory workflow tasks** (NQ SF P{phase}.{step}): minimum priority 9
- **Other implementation tasks**: minimum priority 5
- Tasks below these thresholds are rejected unless they have exceptional positive signals

## Why Task 67 is Allowed While Task 72 is Not

### Task 67 (Allowed)
```
Title: NQ SF P1.3 implement synthetic data + sim early-exit + smoke test RETRY
Priority: 10
Signals:
  - strategy-factory workflow ✓
  - structured phase/step naming (P1.3) ✓
  - implementation-oriented title ✓
```
**Decision**: Allowed because it follows the strategy-factory pattern with high priority and clear implementation direction.

### Task 72 (Rejected)
```
Title: manual slash helper smoke test
Priority: 1
Signals:
  - generic helper/stub task ✗
  - generic smoke test without strong implementation signals ✗
  - missing structured implementation signals ✗
  - priority too low (1) ✗
```
**Decision**: Rejected because it is a low-priority generic helper stub with no structured implementation signals or clear work direction.

---
*Policy derived from workspace scope tools and review bundle analysis.*
