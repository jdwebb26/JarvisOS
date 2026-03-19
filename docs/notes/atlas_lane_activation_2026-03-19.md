# Atlas Lane Activation — 2026-03-19

## What changed

Atlas promoted from Jarvis-fallback quant service to a dedicated OpenClaw experiment lane.

### Live config (`~/.openclaw/openclaw.json`)
- Added `atlas` agent entry: model Qwen 3.5 35B, exec denied
- Rebound `#atlas` channel (`1483916149573025793`) from `jarvis` → `atlas`

### Agent bootstrap (`~/.openclaw/agents/atlas/`)
- `IDENTITY.md` — role, responsibilities, constraints, inputs/outputs
- `BOOTSTRAP.md` — startup, bounded execution path, key paths, constraints

### Roster (`runtime/core/agent_roster.py`)
- Added to `AGENT_SKILL_ALLOWLIST`: session-logs, model-usage
- Added to `AGENT_TOOL_ALLOWLIST`: read, process, memory_search, memory_get, message, session_status, sessions_list, sessions_history
- Added to `CANONICAL_AGENT_ROSTER`: full profile with role, responsibilities, routing intent, tool policies
- Added to `AGENT_RUNTIME_TYPES`: embedded
- Denied tool tokens: exec, shell, bash, write, edit, patch, clawhub, weather
- Denied categories: browser, engineering, maintenance, voice, creative

### Docs updated
- `docs/agent_roster.md` — Atlas section added, removed from fallback table
- `docs/channels.md` — updated quant lane channels note
- `docs/overview/OVERVIEW.md` — Atlas in agent roster table, removed from fallback table

## What did NOT change
- No strategy_factory edits
- No Kitt changes
- No Fish/Salmon changes
- No Sigma changes
- No OpenBB changes

## Atlas policy summary
- **Kind**: specialist (experiment design lane)
- **Runtime**: embedded
- **Exec**: denied
- **Write/edit**: denied (via denied_tool_name_tokens)
- **Allowed tools**: read, process, memory_search, memory_get, message, session_status, sessions_list, sessions_history
- **Model**: Qwen 3.5 35B (fallback: 9B)
- **Channel**: `#atlas` (`1483916149573025793`)
