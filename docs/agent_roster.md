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

## Files to trust

- `runtime/core/agent_roster.py`
- `config/runtime_routing_policy.json`
- `runtime/gateway/source_owned_context_engine.py`
- `runtime/core/decision_router.py`
- `runtime/core/status.py`
