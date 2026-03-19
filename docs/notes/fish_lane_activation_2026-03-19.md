# Fish Lane Activation — 2026-03-19

## Summary

Fish promoted from Jarvis-fallback quant service to a dedicated OpenClaw agent with its own identity, binding, and bootstrap.

## What changed

### Config (`~/.openclaw/openclaw.json`)
- Added Fish to `agents.list` — id: `fish`, model: Qwen3.5-35B primary / Qwen3.5-9B fallback, exec: denied
- Updated `#fish` channel binding from `agentId: "jarvis"` to `agentId: "fish"`

### Runtime (`runtime/core/agent_roster.py`)
- Added `fish` to `CANONICAL_AGENT_ROSTER` — role: scenario modeling/forecasting/calibration, kind: specialist, status: wired
- Added `fish` to `AGENT_TOOL_ALLOWLIST` — read, process, memory_search, memory_get, message, session_status, sessions_list, sessions_history
- Added `fish` to `AGENT_SKILL_ALLOWLIST` — session-logs, model-usage
- Added `fish` to `AGENT_RUNTIME_TYPES` — embedded

### Agent bootstrap (`~/.openclaw/agents/fish/`)
- Created `IDENTITY.md` — role, inputs, outputs, constraints, backend reference
- Created `BOOTSTRAP.md` — execution path, key paths, constraints

### Documentation
- `docs/agent_roster.md` — Fish moved from "Quant lane services (temporary fallback)" to canonical roster section, added to specialization matrix and runtime type table
- `docs/channels.md` — Updated quant lane note to reflect Fish promotion
- `docs/overview/OVERVIEW.md` — Fish added to Agent Roster table, removed from temporary fallback table

## Naming clarity

- **Fish** = the lane / agent / operator-facing identity
- **Salmon Adapter** = the quant_infra backend implementation (`workspace/quant_infra/salmon/adapter.py`)
- Salmon Adapter is NOT a lane, agent, or separate operator identity

## What did NOT change

- Fish scenario engine (`workspace/quant/fish/scenario_lane.py`) — untouched
- Salmon Adapter (`workspace/quant_infra/salmon/adapter.py`) — untouched
- Packet format and lane identity (`lane: "fish"`) — untouched
- Kitt, Atlas, Sigma, OpenBB, DuckDB — untouched
- Strategy Factory — untouched
- No runtime behavior changes — Fish was already producing packets; this wires the agent identity

## Permissions

Fish is deliberately constrained:
- exec: denied (in openclaw.json)
- write/edit/patch: denied (via denied_tool_name_tokens in agent_roster.py)
- Read/research/scenario only
