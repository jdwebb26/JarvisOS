# JarvisOS Agent Roster

This file is the source-owned roster for the current JarvisOS branch.

It does not claim a second hidden orchestration mesh. It records the real repo-aligned specialization that exists today through:

- runtime routing policy
- source-owned context/tool exposure
- review and approval roles
- bounded subsystem adapters
- operator-visible status and snapshot summaries

## Authority

- Jarvis remains the public face and top-level control plane.
- Specialist agents are policy-backed roles and loadouts.
- Hermes, autoresearch, browser automation, and Ralph remain subsystem-bound and candidate-first.
- Jarvis/OpenClaw task, review, approval, session, and status records remain authoritative.

## Canonical roster

### Jarvis

- Role: primary user-facing AI OS / CEO / orchestrator
- Runtime truth: wired
- Owns:
  - user interaction
  - task routing
  - approval coordination
  - session/context handling
  - summaries/handoff
  - TTS / voice convenience
  - light operator status visibility
- Avoids by policy:
  - specialist research tools
  - browser automation tools
  - maintenance/junk stacks
- Routing intent:
  - preferred model `Qwen3.5-9B`

### HAL

- Role: primary coding / implementation agent
- Runtime truth: wired through routing/context policy, not a separate daemon
- Owns:
  - code changes
  - patching
  - local engineering execution
  - tests/build loops
- Routing intent:
  - preferred model `Qwen3.5-35B`

### Archimedes

- Role: technical reviewer / architecture critic
- Runtime truth: wired
- Owns:
  - code review
  - architecture review
  - bug/risk finding
  - second-pass critique
- Routing intent:
  - preferred model `Qwen3.5-122B`
- Review alignment:
  - default reviewer for code/runtime work

### Anton

- Role: supreme reviewer / high-stakes final brain
- Runtime truth: wired
- Owns:
  - high-stakes review
  - final judgment
  - strategic critique
  - difficult approval decisions
- Routing intent:
  - preferred model `Qwen3.5-122B`
- Review alignment:
  - default reviewer for deploy/quant/high-stakes lanes

### Hermes

- Role: deep research daemon
- Runtime truth: implemented on the Jarvis side, still external-runtime dependent
- Owns:
  - deep research
  - evidence gathering
  - research synthesis
- Routing intent:
  - preferred model `Qwen3.5-122B`
  - primary backend `hermes_adapter`

### Scout

- Role: web scout / reconnaissance / collection
- Runtime truth: wired
- Owns:
  - browsing/search/collection
  - source gathering
  - lead generation for Hermes/research tasks
- Routing intent:
  - preferred model `Qwen3.5-35B`

### Bowser

- Role: browser automation specialist
- Runtime truth: scaffold-only
- Owns:
  - browser actions
  - tab/workflow operations
- Current limitation:
  - browser bridge remains bounded/scaffolded, not a fully live external lane

### Muse

- Role: creative writing / ideation specialist
- Runtime truth: policy-backed
- Owns:
  - creative writing
  - ideation
  - naming/copy
- Current limitation:
  - no dedicated higher-temperature runtime daemon; specialization is policy/loadout-level

### Ralph

- Role: overflow / maintenance / consolidation worker
- Runtime truth: implemented on the Jarvis side, still external-runtime dependent for the fuller loop
- Owns:
  - low-priority chores
  - queue draining
  - maintenance-ish work
  - memory consolidation intent

## Review hierarchy

- HAL builds
- Archimedes reviews technically
- Anton handles supreme / high-stakes review

This matches:

- [review-policy.md](/home/rollan/.openclaw/workspace/jarvis-v5/docs/review-policy.md)
- `runtime/core/decision_router.py`

## Tool / skill specialization

The current repo does not have a separate general-purpose subagent runtime for each name in the roster.

What is real today:

- `runtime/core/agent_roster.py` defines the canonical agent responsibilities and tool/skill intent
- `config/runtime_routing_policy.json` maps the full roster to routing intent
- `runtime/gateway/source_owned_context_engine.py` now scopes visible tools by agent role
- `runtime/core/status.py`, `runtime/dashboard/operator_snapshot.py`, and `runtime/dashboard/state_export.py` surface the roster for operators

This means Jarvis no longer needs to behave like it must preload every specialist tool family by default, even though the repo still uses one bounded runtime spine.

### Per-agent specialization matrix

Enforcement is **name-based allowlist only** — `AGENT_TOOL_ALLOWLIST` and `AGENT_SKILL_ALLOWLIST` in `runtime/core/agent_roster.py` are the single source of truth. Categories are metadata only.

Verify current state with: `python3 scripts/verify_openclaw_bootstrap_runtime.py --agent <id>`

| Agent | Runtime type | Allowed tools (exact names) | Allowed skills (exact names) |
| --- | --- | --- | --- |
| **jarvis** | embedded | `agents_list`, `gateway`, `memory_get`, `memory_search`, `message`, `read`, `session_status`, `sessions_history`, `sessions_list`, `sessions_send`, `sessions_spawn`, `sessions_yield`, `tts` | `discord`, `model-usage`, `session-logs`, `sherpa-onnx-tts`, `voice-call` |
| **hal** | acp_ready | `cron`, `edit`, `exec`, `gateway`, `memory_get`, `memory_search`, `message`, `process`, `read`, `session_status`, `sessions_history`, `sessions_list`, `sessions_send`, `sessions_spawn`, `sessions_yield`, `subagents`, `write` | `coding-agent`, `gh-issues`, `github`, `model-usage`, `session-logs` |
| **archimedes** | embedded | `memory_get`, `memory_search`, `read`, `session_status`, `sessions_history`, `sessions_list` | `model-usage`, `session-logs` |
| **anton** | embedded | `memory_get`, `memory_search`, `message`, `read`, `session_status`, `sessions_history`, `sessions_list` | `model-usage`, `session-logs` |
| **hermes** | embedded | `gateway`, `memory_get`, `memory_search`, `message`, `process`, `read`, `session_status`, `sessions_history`, `sessions_list`, `sessions_send`, `sessions_spawn`, `sessions_yield` | `blogwatcher`, `goplaces`, `model-usage`, `session-logs`, `summarize` |
| **scout** | embedded | `image`, `process`, `read`, `session_status`, `sessions_history`, `sessions_list`, `sessions_send`, `sessions_spawn`, `sessions_yield`, `web_fetch`, `web_search` | `blogwatcher`, `goplaces`, `session-logs`, `summarize`, `xurl` |
| **bowser** | embedded | `browser`, `browser_navigate`, `process`, `session_status`, `sessions_history`, `sessions_list`, `sessions_send`, `sessions_spawn`, `sessions_yield` | `session-logs` |
| **muse** | embedded | `image`, `message`, `read`, `tts` | `sag`, `session-logs`, `songsee`, `summarize` |
| **ralph** | embedded | `cron`, `memory_get`, `memory_search`, `process`, `session_status`, `sessions_history`, `sessions_list`, `sessions_send`, `sessions_spawn`, `sessions_yield` | `ordercli`, `session-logs` |

**Delegation**: jarvis → hal (implementation), hal → archimedes (review), archimedes → anton (supreme review)<br>
**Denied globally**: `clawhub`, `weather`, `gog` (in `COMMON_DENIED_SKILL_NAMES`)

What is now real in the live prompt/bootstrap path:

- the source-owned context bridge filters skill blocks per agent before the final OpenClaw system prompt is assembled
- Jarvis no longer receives the full installed skill inventory by default
- the live `agent:bootstrap` hook now overlays agent-specific bootstrap files by basename from `~/.openclaw/agents/<id>/`
- the persisted `systemPromptReport` now records, for active runs:
  - loaded skill count and names
  - visible tool count, names, and categories
  - agent/runtime model and provider intent

To keep each lane focused, Jarvis and the specialist agents now explicitly deny `clawhub` and `weather` tokens when the runtime builds the per-agent skill prompt (see `runtime/core/agent_roster.py`), so those skills/tools never make it into an agent that does not need them.

Active bootstrap sources:

- `~/.openclaw/agents/<id>/BOOTSTRAP.md`
- `~/.openclaw/agents/<id>/TOOLS.md`
- `~/.openclaw/agents/<id>/IDENTITY.md`
- `~/.openclaw/agents/<id>/SOUL.md` when present
- fallback for missing basenames:
  - `~/.openclaw/agents/<id>/agent/AGENTS.md`
  - `~/.openclaw/agents/<id>/agent/SOUL.md`
  - `~/.openclaw/agents/<id>/agent/USER.md`
  - `~/.openclaw/agents/<id>/agent/HEARTBEAT.md`

#### Live bootstrap path

Today the runtime's `agentDir` entries (see `~/.openclaw/openclaw.json`) point directly at `~/.openclaw/agents/<id>/`. The files that previously lived under `.../agent/` have been merged up and the old subfolders renamed to `agent_legacy_20260315`, so the bootstrap precedence order is now unambiguous and the live path you should edit is the top-level agent folder.

Supplemental only:

- the shared repo workspace bootstrap files remain the default fallback when an agent-specific basename is absent
- top-level agent folders are not the discovery registry; `~/.openclaw/openclaw.json` `agents.list` remains the live registry source

Review lane truth:

- `review` is the primary concise review/approval lane
- `code_review` is the Archimedes technical review lane
- `audit` is the Anton high-stakes/final review lane

These are backed by:

- `config/channels.yaml`
- `config/policies.yaml`
- `runtime/core/decision_router.py`

## Honest gaps

### Already implemented

- Jarvis public/control-plane role
- Archimedes and Anton review alignment
- Hermes adapter seam
- Scout routing identity
- voice subsystem
- browser bounded policy seam
- Ralph memory/maintenance intent in specs and summaries

### Partially implemented

- HAL as explicit coding specialist
- Muse as explicit creative specialist
- agent-specific tool/skill loadout policy
- full operator-facing roster visibility

### Blocked by external runtime

- Hermes live daemon availability
- Ralph full autonomy/consolidation loop
- Bowser/browser bridge live lane

## Embedded vs ACP runtime

All agents run **embedded** by default — their turns are handled inline inside the OpenClaw process during Discord / task sessions.

**ACP (Agent Control Protocol)** is a separate harness mode where a long-running Claude Code process handles the agent's turns. It is fully scaffolded but **not active** (`acp.enabled=false` in `openclaw.json`).

### Runtime type labels

| Agent      | runtime_type | Notes |
|------------|-------------|-------|
| jarvis     | embedded    | Must stay embedded — front door and control plane for all Discord sessions |
| hal        | acp_ready   | First ACP candidate; designated but NOT active until `acp.enabled=true` |
| archimedes | embedded    | |
| anton      | embedded    | |
| hermes     | embedded    | Second ACP candidate; not flipped until HAL is validated end-to-end |
| scout      | embedded    | |
| bowser     | embedded    | |
| muse       | embedded    | |
| ralph      | embedded    | |

### Why Jarvis stays embedded

Jarvis is the front door for all inbound Discord messages. Embedding it in the process gives sub-100ms turn latency and keeps session/context management inside the same process boundary. Externalising Jarvis to ACP would add process-spawn overhead on every Discord turn and complicate the session state hand-off.

### Why HAL is the first ACP candidate

HAL is the implementation builder — it receives delegated coding tasks from Jarvis, not direct Discord turns. Its work is naturally async and long-running, making the ACP harness model a good fit. It has no latency requirement from Discord response times.

### How to activate ACP for HAL (when ready)

1. Set `acp.enabled = true` and populate `acp.backend` / `acp.runtime.installCommand` in `openclaw.json`.
2. Change HAL's `runtime.type` from `"acp_ready"` to `"acp"` in `openclaw.json`.
3. Add `"hal"` to `acp.allowedAgents`.
4. Verify with `scripts/verify_openclaw_bootstrap_runtime.py --agent hal`.

### How to add Hermes as a second ACP agent (future)

Follow the same steps as HAL. Update `AGENT_RUNTIME_TYPES["hermes"]` in `agent_roster.py` from `"embedded"` to `"acp_ready"` once HAL is validated.

## Files to trust

- `runtime/core/agent_roster.py`
- `config/runtime_routing_policy.json`
- `runtime/gateway/source_owned_context_engine.py`
- `runtime/core/decision_router.py`
- `runtime/core/status.py`
