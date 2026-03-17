# Hermes Bootstrap Gap — 2026-03-16

## Problem
Hermes was reading Jarvis's identity from the shared workspace root (`jarvis-v5/IDENTITY.md`). All agents configured with `workspace: jarvis-v5` share the same workspace-root bootstrap files (IDENTITY.md, SOUL.md, etc.). Hermes had no per-agent identity, causing generic/confused behavior.

Additionally, all 6 per-agent bootstrap files in `~/.openclaw/agents/hermes/` were empty (0 bytes), meaning Hermes had no identity grounding from either location.

## Root Cause
OpenClaw loads bootstrap files from `workspaceDir` (the configured `workspace` field in openclaw.json). For Hermes, this was the shared `jarvis-v5/` root which contains Jarvis's IDENTITY.md etc. The `agentDir` (`~/.openclaw/agents/hermes/`) is used only for auth profiles and model config, NOT for bootstrap/system prompt loading.

## Fix
1. **Hermes workspace reassigned**: Changed `workspace` in openclaw.json from `jarvis-v5` to `jarvis-v5/agents/hermes` — giving Hermes its own bootstrap directory while keeping the jarvis-v5 codebase as the repo context.
2. **Bootstrap files written**: All 6 files written to both `workspace/jarvis-v5/agents/hermes/` (live workspace) and `~/.openclaw/agents/hermes/` (agentDir reference copy):
   - `IDENTITY.md`: Hermes role as deep research/runtime integration daemon
   - `SOUL.md`: Evidence-first, structured-output operating principles
   - `TOOLS.md`: Tool policy with absolute parent workspace paths
   - `AGENTS.md`: Delegation position in the agent mesh
   - `BOOTSTRAP.md`: Startup orientation
   - `HEARTBEAT.md`: Idle-time maintenance protocol with absolute workspace paths
3. **Session reset**: Cleared `systemSent` flag in the Hermes session to force bootstrap re-injection on next message.
4. **Gateway restarted**: Picked up new workspace config.

## Verification
After the fix, Hermes's `workspaceDir` will resolve to `jarvis-v5/agents/hermes` and its system prompt will contain Hermes-specific IDENTITY.md ("You are Hermes, the deep research and runtime integration daemon.") rather than Jarvis's identity.

File reads requiring parent workspace access should use absolute paths (`/home/rollan/.openclaw/workspace/jarvis-v5/...`).
