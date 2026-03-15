# Source-Owned Context Engine

Date: 2026-03-14

This branch now contains a source-owned bounded-context engine for Discord/OpenClaw-style sessions in:

- `runtime/gateway/source_owned_context_engine.py`

It replaces the hotfix-only logic with a repo-owned policy layer that can be inspected, tested, and reused.

## Working Memory Model

- Raw working set is bounded by user-turn recency, not full transcript replay.
- Default raw window: `6` user turns.
- Older turns are not carried forward verbatim.
- Before prompt assembly, stale metadata wrappers and stale tool-result blobs are distilled.
- The active working set reports:
  - `rawUserTurnWindow`
  - `userTurnsInSession`
  - `recentMessageCount`

## Rolling Summary Model

- Each session gets a rolling summary artifact in `workspace/vault/session_context/`.
- The summary is indexed through `runtime/memory/vault_index.py`.
- The summary is built with `runtime/memory/brief_builder.py`, not a parallel summary system.
- It preserves:
  - current objective
  - unresolved questions
  - active constraints
  - recent decisions
  - tool findings worth carrying forward
  - operator preferences

## Retrieval Policy

- Retrieval reuses `runtime/memory/governance.py`.
- `retrieve_memory_for_context(...)` performs bounded context retrieval.
- Retrieval is split into:
  - episodic memory: recent observations, prior run outcomes, tool findings
  - semantic memory: stable facts, operator preferences, durable constraints
- Retrieval is bounded by:
  - token budget
  - episodic count limit
  - semantic count limit
- Retrieval accounting is persisted through `MemoryRetrievalRecord`.

## Budget Policy

- Prompt budget categories:
  - `systemPrompt`
  - `recentConversationTurns`
  - `toolSchemas`
  - `retrievedMemory`
  - `rawToolOutputs`
  - `metadataWrappers`
  - `rollingSessionSummary`
- Safe threshold: `72%` of context window.
- Hard threshold: `82%` of context window.
- If safe threshold is exceeded:
  - the engine compacts by tightening the working set and retrieval footprint
- If hard threshold is still exceeded:
  - the call is blocked before send

## Tool Exposure Policy

- Tool exposure is selected from turn characteristics.
- `chat-minimal`:
  - simple Discord chat
  - no full tool surface attached
- `full`:
  - code/file/shell/research/task-looking turns
- Operator-visible fields remain aligned with the OpenClaw report shape:
  - `toolExposure.mode`
  - `toolExposure.reason`
  - `beforeCount`
  - `afterCount`

## Forgetting / Distillation Policy

- Distillation happens before model send.
- Old metadata wrappers are stripped down to the user-authored body.
- Old tool-result blobs are replaced with compact state records that retain:
  - tool name
  - omitted size
  - top path-like refs when present
- Important state is preserved through:
  - rolling summary
  - bounded episodic retrieval
  - bounded semantic retrieval

## What Is Proven Here

- Source-owned policy logic exists in the repo.
- The policy is exercised by unit tests, including a synthetic long-thread regression.
- Operator-facing budget and tool-exposure fields remain compatible with the existing reporting shape.

## What Still Depends On External Runtime Wiring

- The installed OpenClaw runtime still needs to call this source-owned engine for live Discord turns.
- This slice removes logic ownership from the dist-bundle hotfix, but does not replace the external runtime binary by itself.
