# Qwen Next Integration Step

Recommendation for the next safe step after completing the read-only scope analysis lane.

## Recommended Next Task: Task 68

**Title**: NQ SF P2.1 implement gates + regimes + tests RETRY
**Priority**: 10
**Status**: done (from scope scan)

### Rationale

1. **In-scope task**: Confirmed allowed by `workspace_scope_candidates` with positive signals for strategy-factory workflow and structured phase/step naming
2. **High priority**: Priority 10 meets the minimum threshold for strategy-factory tasks (≥9)
3. **Retry variant**: The RETRY designation suggests prior work exists that can be inspected before continuing
4. **Sequential progression**: Follows P1.x tasks (63-67) in the strategy-factory workflow, moving to P2.x phase

## Safe Execution Steps

### Step 1: Inspect Existing Work (Read-Only)
Before any edits, read and summarize:
- `workspace_read_file` on task result: `/home/rollan/.openclaw/workspace/tasks/results/68.md`
- Review files written by related P1.x tasks in the strategy-factory workspace
- Check if P2.1 implementation already exists or needs to be created from scratch

### Step 2: Verify Scope Before Editing
Confirm the task remains in scope:
- `workspace_scope_check` for task_id=68
- Ensure no new disallowed patterns have emerged (blocked status, missing payload_path)

### Step 3: Propose Smallest Safe Change First
When ready to edit:
- Start with one file or one function change
- Explain the smallest safe next change before implementing
- Prefer reading files and summarizing before proposing edits

## Alternative Path: Implementation-Oriented Work

If strategy-factory workflow is complete, consider:
- **Task 60/61**: "implement real ops report from task 17 outline" (priority 5)
- These are allowed but lower priority than P2.x tasks
- Still require file inspection before proposing edits

## Constraints to Maintain

1. **Never infer file contents from filenames alone** - always read files first
2. **Do not claim work is done unless you inspected the relevant files**
3. **Do not invent missing runtime pieces** - say when something is only a skeleton
4. **Use narrow searches for file listing** before broad exploration
5. **Stay inside the allowed workspace** defined by scope tools

---
*Recommendation based on workspace_scope_candidates and review bundle analysis.*
