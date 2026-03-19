# Jarvis v5 Channel Policy

This file defines the intended channel behavior for Jarvis/OpenClaw v5.

## Primary rule

A normal message in `#jarvis` is conversation, not execution.

Jarvis may answer, plan, clarify, summarize, and discuss in `#jarvis`, but it must not silently convert ordinary chat into queued work.

---

## Supported channels

### `#jarvis`

Purpose:
- conversation
- planning
- orchestration
- status
- explicit task creation

Allowed:
- normal chat
- status questions
- planning discussion
- explicit task trigger like `task: ...`

Not allowed:
- silent enqueue of ordinary chat
- silent Flowstate promotion
- hidden side effects that create durable work from casual conversation

---

### `#tasks`

Purpose:
- durable task lifecycle visibility

Allowed:
- task created
- task assigned
- task blocked
- task awaiting review
- task awaiting approval
- task completed
- task failed
- task resumed

Expected behavior:
- every durable task should have a visible task ID
- state changes should be reflected here or through dashboard/state surfaces

---

### `#outputs`

Purpose:
- final approved artifacts

Allowed:
- final writeups
- approved deliverables
- approved summaries
- approved implementation artifacts

---

### `#review`

Purpose:
- concise approval decisions

Allowed:
- yes/no approvals
- numbered or lettered option replies
- short review requests
- approval object references

Design requirement:
- responses should be short enough to handle from a phone/watch approval lane

---

### `#audit`

Purpose:
- risky / high-stakes / final-review summaries

Expected reviewer:
- Anton

---

### `#code-review`

Purpose:
- code review summaries and verdicts

Expected reviewer:
- Archimedes

---

### `#flowstate`

Purpose:
- ingest
- transcript/extraction
- distillation
- promotion proposal

Important:
- Flowstate outputs do not become tasks or memory automatically
- promotion requires explicit approval

---

### Agent-per-channel model (live)

The live system uses one Discord channel per agent. Each channel has:
- An outbound webhook (for the outbox sender to post events)
- A gateway allowlist entry (so the bot listens)
- A binding to an agent (for inbound message routing)

The canonical mapping is in `config/agent_channel_map.json`. The gateway bindings are in `~/.openclaw/openclaw.json`.

**Quant lane channels** (sigma, atlas, pulse) have outbound webhooks and gateway allowlist entries, but their inbound binding routes to **jarvis as a temporary fallback** — they do not have dedicated OpenClaw agent definitions. Fish has been promoted to a full agent with its own binding and identity (see agent_roster.md).

See `config/agent_channel_map.json` and `runtime/core/discord_outbox_sender.py` for the live channel→webhook→env var mapping.

---

## Explicit task trigger

Only this trigger is supported for durable task creation in `#jarvis`:

- `task: ...`

Examples:
- `task: build the minimum durable runtime spine`
- `task: patch the intake code path for gateway routing`
- `task: deploy the new jarvis v5 gateway service wiring`

Non-examples:
- `task build the runtime spine`
- `hey jarvis build the runtime spine`

Those must remain conversation unless the explicit `task:` prefix is used.
