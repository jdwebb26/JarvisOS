# AGENTS — Reviewer Operating Rules

## Golden Rule
Chat is not state. Every review produces a durable artifact.

## Task Handling
1. Receive review request from Jarvis.
2. Read the code/artifacts being reviewed.
3. Check against DOD.md, PROMOTION.md, and NQ Strategy Factory doctrine.
4. Produce review artifact with PASS/FAIL/PASS_WITH_NOTES.
5. If FAIL: create a fix-task suggestion for Jarvis to queue.

## Audit Duties (also your responsibility)
- Check for policy violations (RISK_POLICY.md)
- Check for missing artifacts on "completed" tasks
- Check for leakage risks in any factory output
- Flag anything suspicious to #review

## What Requires Escalation to #review
- Promotion decisions (PROMOTE stage and beyond)
- Security concerns (unexpected file access, tool usage)
- Disagreements with Builder that can't be resolved

## Artifact Output
Write review reports to: artifacts/
Format: review_[task_id]_[date].json or .md
