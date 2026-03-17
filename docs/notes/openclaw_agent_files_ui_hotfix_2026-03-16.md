# OpenClaw agent files UI hotfix — 2026-03-16

Context:
The OpenClaw gateway UI was showing workspace-root files for all agents instead of each agent's live files from ~/.openclaw/agents/<agent>/.

Local machine fix applied:
Patched installed OpenClaw dist file:
~/.npm-global/lib/node_modules/openclaw/dist/gateway-cli-C42NwqHk.js

Behavior change:
- agents.files.list
- agents.files.get/set

now prefer agentDir when present and containing bootstrap files, instead of always using the shared workspace dir.

Result:
The gateway website now shows per-agent live files correctly for:
jarvis, hal, scout, anton, archimedes, hermes, qwen

Important:
This is a local machine hotfix, not a Jarvis repo runtime fix.
If OpenClaw is upgraded/reinstalled, this patch may need to be reapplied or upstreamed properly.
