# Migration from v4 to v5

This document records what v5 preserves, what it hardens, and what it intentionally changes from older OpenClaw/Jarvis behavior.

## What v5 preserves

- the operational spine:
  Discord ingest -> events.db -> enrich_worker -> router -> outputs/tasks -> executor -> dashboard
- the usefulness of Jarvis as an operator assistant
- explicit task creation
- artifact-oriented work output
- review lanes and approval-aware execution
- Flowstate as a meaningful source-material lane

## What v5 hardens

- ordinary chat in `#jarvis` does not silently become queued work
- task lifecycle becomes durable and visible
- approvals become structured objects
- Flowstate promotion becomes explicitly gated
- deployment becomes validation-first
- model-family policy becomes explicit and enforced

## What v5 intentionally avoids

- vague swarm magic as the first implementation layer
- silent side effects from casual chat
- hidden automatic promotion from Flowstate
- invisible task creation
- drifting model-family assumptions
- deployment-by-debugging

## Migration stance for existing v4-era pieces

Older components may still contain useful logic, but they should be treated as migration material, not as permission to violate v5 policy.

Keep useful pieces.
Do not re-import unwanted behavior.

## Immediate migration rule

When reusing older code:
1. preserve chat-first behavior
2. preserve explicit task creation
3. preserve durable task visibility
4. preserve review policy
5. preserve Flowstate gating
6. preserve Qwen-only model policy
