# Hermes Bootstrap Verification — 2026-03-16

## What Was Inspected

1. `sessions.json` — session record for `agent:hermes:discord:channel:1483131437292191945`
2. All 7 bootstrap files in `jarvis-v5/agents/hermes/` (workspace/repo copy)
3. All 7 bootstrap files in `~/.openclaw/agents/hermes/` (agentDir/runtime copy)
4. Session JSONL `3800543c-fb6b-4431-8261-850a86cf4cd0.jsonl` — live turn evidence
5. `verify_openclaw_bootstrap_runtime.py --agent hermes` output

## Evidence Found

### Live Turn Analysis (JSONL session log)
A live turn occurred. Hermes responded with:

> "I am Hermes, your intelligent assistant within the Jarvis OS ecosystem. I help coordinate tasks, manage workflows, and support you with information and automation across your digital environment."

This is generic assistant language. It does NOT reflect the daemon voice defined in IDENTITY.md/SOUL.md:
- "intelligent assistant" vs correct "deep research and runtime integration daemon"
- "coordinate tasks, manage workflows" vs correct "synthesize evidence, produce structured artifacts, check orchestration health"
- No mention of being NOT the front door, NOT the executor

**Root diagnosis**: The live turn occurred before the session system prompt was injected (`systemSent: false` still in sessions.json after the turn). The JSONL shows `promptChars=0 | toolEntries=0`, meaning the system prompt bootstrap had not been delivered when the model responded. The model fell back to generic LLM behavior.

### Verification Script Output
`verify_openclaw_bootstrap_runtime.py --agent hermes` confirmed:
- `active` bootstrap files are from `agent_dir` (`~/.openclaw/agents/hermes/`) — this is the runtime source
- `used_directly_at_runtime=False` for workspace versions (`jarvis-v5/agents/hermes/`) — workspace files are repo reference only
- Precedence: `top_level_agent_root → agent_dir → workspace_base`
- Session: `EXISTS but no tool data — policy comparison not available`

### File Comparison (before fix)
The agentDir runtime files had a behavior gap vs the workspace reference copies:

| File | Gap |
|------|-----|
| `TOOLS.md` | Missing `## Parent workspace` section; relative `research/` path instead of absolute `/home/rollan/.openclaw/workspace/jarvis-v5/research/` |
| `HEARTBEAT.md` | Used relative paths (`TASKS.jsonl`, `research/`, `artifacts/`) instead of absolute paths; missing workspace root header |

All other files (IDENTITY.md, SOUL.md, BOOTSTRAP.md, AGENTS.md) were already identical between agentDir and workspace copies.

## Gap Identified

1. **Relative paths in runtime TOOLS.md and HEARTBEAT.md** — when Hermes uses these files to guide tool calls, relative paths would fail or produce wrong lookups because the cwd (`jarvis-v5/agents/hermes/`) is the workspace root, not the research/artifacts/ parent.

2. **No live proof of correct bootstrap injection yet** — the `systemSent: false` flag means the proper system prompt (with IDENTITY.md, SOUL.md, etc.) has not been delivered to the model in any turn. The one live turn that occurred had `promptChars=0`, meaning the model responded without a system prompt.

## What Was Fixed

Updated `~/.openclaw/agents/hermes/TOOLS.md` (the active runtime file):
- Added `## Parent workspace` section with absolute path `/home/rollan/.openclaw/workspace/jarvis-v5/`
- Changed research output path from relative `research/[topic]_[YYYY-MM-DD].md` to absolute `/home/rollan/.openclaw/workspace/jarvis-v5/research/[topic]_[YYYY-MM-DD].md`
- Updated `read` tool description to specify absolute paths

Updated `~/.openclaw/agents/hermes/HEARTBEAT.md` (the active runtime file):
- Added `Workspace root:` header with absolute path
- Changed `TASKS.jsonl` to `/home/rollan/.openclaw/workspace/TASKS.jsonl`
- Changed `research/` to `/home/rollan/.openclaw/workspace/jarvis-v5/research/`
- Changed `artifacts/strategy_factory/` to `/home/rollan/.openclaw/workspace/jarvis-v5/artifacts/strategy_factory/`

Post-fix diff confirmed: agentDir files are now identical to workspace reference copies.

## Files Changed

- `/home/rollan/.openclaw/agents/hermes/TOOLS.md` — added absolute paths (runtime fix)
- `/home/rollan/.openclaw/agents/hermes/HEARTBEAT.md` — added absolute paths (runtime fix)
- `/home/rollan/.openclaw/workspace/jarvis-v5/agents/hermes/TOOLS.md` — no change (was already correct)
- `/home/rollan/.openclaw/workspace/jarvis-v5/agents/hermes/HEARTBEAT.md` — no change (was already correct)

## What Remains

1. **Bootstrap injection not yet confirmed** — `systemSent` is still `false`. The next message to Hermes's Discord channel will trigger system prompt injection. Once that occurs, the session JSONL should show `promptChars > 0` and the response should reflect the daemon voice.

2. **Tone verification** — after next live turn with system prompt injected, verify response no longer uses "intelligent assistant" / "coordinate tasks" language and instead reflects evidence-first daemon behavior.

3. **agentDir files are NOT git-tracked** — the fixes to `~/.openclaw/agents/hermes/TOOLS.md` and `HEARTBEAT.md` are runtime state, not versioned. The canonical reference copies in `jarvis-v5/agents/hermes/` are what git tracks. If the agentDir is ever regenerated from the workspace copy, the correct files will be used.
