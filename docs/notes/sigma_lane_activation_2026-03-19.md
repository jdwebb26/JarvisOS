# Sigma Lane Activation — 2026-03-19

## What changed

Sigma promoted from Jarvis-fallback quant service to a dedicated OpenClaw agent.

### Live config (`~/.openclaw/openclaw.json`)
- Added `sigma` agent entry: model Qwen 3.5 35B, exec denied
- Rebound `#sigma` channel (`1483916191046041811`) from `jarvis` → `sigma`

### Agent bootstrap (`~/.openclaw/agents/sigma/`)
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
- `docs/agent_roster.md` — Sigma section added, removed from fallback table
- `docs/channels.md` — updated quant lane channels note
- `docs/overview/OVERVIEW.md` — Sigma in agent roster table, removed from fallback table

## What did NOT change
- No strategy_factory edits
- No Kitt paper loop changes
- No Fish/Salmon changes
- No OpenBB changes
- No `openclaw.json` structural changes beyond sigma agent + binding

## Verification
- `openclaw doctor`: config valid
- Gateway restarted cleanly, no sigma/error/denied log lines
- `#sigma` channel binding confirmed: agentId = sigma
- Sigma in roster: True (runtime_type=embedded, status=wired)
- Preflight: CLEAR (0 fail)
- Postdeploy: CLEAN (0 fail)
- Smoke test: PASS (5/5 regression green)

## Sigma policy summary
- **Kind**: specialist (validation lane)
- **Runtime**: embedded
- **Exec**: denied
- **Write/edit**: denied (via denied_tool_name_tokens)
- **Allowed tools**: read, process, memory_search, memory_get, message, session_status, sessions_list, sessions_history
- **Model**: Qwen 3.5 35B (fallback: 9B)
- **Channel**: `#sigma` (`1483916191046041811`)
