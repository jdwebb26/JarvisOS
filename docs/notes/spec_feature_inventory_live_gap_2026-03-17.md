# Spec-to-Live Feature Inventory — 2026-03-17

Generated from: v5 / v5.1 / v5.2 specs and live runtime evidence.
Source docs: `docs/spec/Jarvis_OS_v5_1_Master_Spec.md`, `docs/spec/JARVIS 5.2 MASTER SPEC.md`,
`docs/agent_roster.md`, `docs/source_owned_context_engine.md`, `docs/jarvis_5_2_migration_status.md`,
`runtime/core/agent_roster.py`, `runtime/gateway/source_owned_context_engine.py`,
`runtime/integrations/lane_activation.py`, `config/runtime_routing_policy.json`.

Status labels: **LIVE** | **PARTIAL** | **BLOCKED** | **NOT LIVE / DOC-ONLY** | **SCAFFOLD**

---

## 1. Control Plane / Routing

### 1.1 Multi-agent Discord channel bindings
- **Source**: `~/.openclaw/openclaw.json` bindings, `runtime/core/agent_roster.py`
- **Description**: Each Discord channel maps to a named agent (jarvis, hal, archimedes, anton, hermes, scout, qwen, kitt). Inbound messages routed to correct session/bootstrap.
- **Repo evidence**: `CANONICAL_AGENT_ROSTER` defines 10 agents; `openclaw.json` bindings section has 8 channels; `scan_all_specialist_channel_sessions()` in `runtime/integrations/openclaw_sessions.py`
- **Live evidence**: `verify_openclaw_bootstrap_runtime.py` shows 7/8 channels `ok`, 1 `no_session_yet` (jarvis main). Kitt session live.
- **Status**: **LIVE**
- **Next step**: N/A (working). Jarvis main channel session will create on first message.

### 1.2 Source-owned context engine — bounded working memory
- **Source**: `docs/source_owned_context_engine.md`, `runtime/gateway/source_owned_context_engine.py`
- **Description**: Raw working set bounded to last 6 user turns. Older turns distilled. Called as subprocess (`source_owned_context_engine_cli.py`) before every model send.
- **Repo evidence**: `build_context_packet()` in `source_owned_context_engine.py`; gateway bundle confirms `source_owned_visible_tools=True`, `filtered_skills_applied=True`
- **Live evidence**: Gateway bundle verified live; `workingMemoryMessages` replaces session history before model send
- **Status**: **LIVE**
- **Next step**: Monitor. Consider increasing turn window for long-running task sessions.

### 1.3 Context budget guard (safe 72%, hard 82%, emergency distill)
- **Source**: `docs/source_owned_context_engine.md`, `docs/notes/context-bloat-fix-20260316.md`
- **Description**: Budget estimated per category. Safe threshold triggers compaction. Hard threshold blocks send. Emergency distill pass fires when compacted window still over safe threshold.
- **Repo evidence**: `_build_prompt_budget()`, emergency distill block in `build_context_packet()`; fixed 2026-03-16 (integer estimation bug)
- **Live evidence**: Tests pass; prior Jarvis Discord session overflowed before fix (83KB session, March 16). Fix now live.
- **Status**: **LIVE**
- **Next step**: Monitor Scout 472KB session; consider turn-count ceiling for sessions that survive idle-reset.

### 1.4 Tool exposure filtering (chat-minimal / full / agent-scoped-full)
- **Source**: `docs/source_owned_context_engine.md`, `runtime/gateway/source_owned_context_engine.py`
- **Description**: Simple Discord chat → `chat-minimal` (no tools). Task/code/file prompts → `full` or `agent-scoped`. Applied per-turn, not per-session.
- **Repo evidence**: `_select_tool_exposure()`, `SIMPLE_CHAT_TOOL_RE` regex
- **Live evidence**: `test_source_owned_context_engine.py` all pass. Live turns confirmed via `systemPromptReport.toolExposure.mode`
- **Status**: **LIVE**
- **Next step**: N/A

### 1.5 Agent tool/skill allowlist enforcement (name-based, fail-closed)
- **Source**: `docs/STATUS_2026-03-15_agent_specialization_hardening.md`, `runtime/core/agent_roster.py`
- **Description**: `AGENT_TOOL_ALLOWLIST` and `AGENT_SKILL_ALLOWLIST` per agent. Unknown agents get 0 tools/skills. No Jarvis fallback for unknowns.
- **Repo evidence**: `filter_tools_for_agent()`, `filter_skills_prompt_for_agent()` in `agent_roster.py`
- **Live evidence**: Bundle checks `filtered_skills_applied=True`, `source_owned_visible_tools=True`. Verify script shows correct counts for all agents.
- **Status**: **LIVE**
- **Next step**: N/A

### 1.6 Runtime routing policy (config/runtime_routing_policy.json)
- **Source**: `docs/spec/JARVIS 5.2 MASTER SPEC.md`, `config/runtime_routing_policy.json`
- **Description**: Per-agent/workload model preferences, fallback chains, burst_allowed flags. Used as policy declaration; actual model selection is still openclaw.json assignment.
- **Repo evidence**: `config/runtime_routing_policy.json` has 9 agent policies; `build_agent_roster_summary()` reads it for `configured_routing_policy` field
- **Live evidence**: Policy file is read by verifier/roster summary but not enforced in the live model dispatch path (openclaw.json is authoritative for actual model selection)
- **Status**: **PARTIAL** — policy declared, not enforced in live dispatch
- **Next step**: Wire `decision_router.py` to actually query this policy before model selection (5.2 multi-model routing)

### 1.7 Kitt missing from runtime_routing_policy.json
- **Source**: `runtime/core/agent_roster.py` (Kitt added 2026-03-17), `config/runtime_routing_policy.json`
- **Description**: Kitt has a full agent profile and live Discord channel, but no entry in `config/runtime_routing_policy.json`. Uses Kimi-K2.5 (nvidia), not Qwen.
- **Repo evidence**: Kitt not in `agent_policies` section of `runtime_routing_policy.json`. Kitt in `CANONICAL_AGENT_ROSTER` with `preferred_model: "Kimi-K2.5"`
- **Live evidence**: Missing entry means verifier/doctor shows no `configured_routing_policy` for Kitt
- **Status**: **PARTIAL** — agent live, routing policy registration absent
- **Next step**: Add Kitt entry to `config/runtime_routing_policy.json` with nvidia/kimi-k2-5 preferred, qwen fallback

### 1.8 Multi-node / burst worker routing (NIMO + Koolkidclub)
- **Source**: `docs/spec/JARVIS 5.2 MASTER SPEC.md` §1 "Persistent Core + Elastic Burst Runtime"
- **Description**: Node registration, worker heartbeat, task leasing, reroute on worker loss, node-aware scheduler
- **Repo evidence**: `node_registry.py`, `task_lease.py`, `heartbeat_reports.py` exist. `burst_allowed=false` in all `runtime_routing_policy.json` entries. `forbidden_host_roles: ["burst"]` everywhere.
- **Live evidence**: `_classify_runtime_host_from_url()` in `operator_discord_runtime_check.py` recognizes NIMO and KOOLKID by IP; no burst tasks have ever been dispatched.
- **Status**: **NOT LIVE / DOC-ONLY** — code scaffolded, burst routing disabled
- **Next step**: 5.2 work item; requires NIMO/Koolkidclub node registration and heartbeat wiring

### 1.9 ACP harness (HAL acp_ready)
- **Source**: `docs/agent_roster.md`, `docs/STATUS_2026-03-15_agent_specialization_hardening.md`
- **Description**: Long-running Claude Code subprocess handles HAL turns. Fully scaffolded; NOT active (`acp.enabled=false`). HAL is first designated candidate.
- **Repo evidence**: `AGENT_RUNTIME_TYPES["hal"] = "acp_ready"` in `agent_roster.py`; `acp_scaffold.enabled=false` in `runtime_routing_policy.json`; `runtime.type: "embedded"` in HAL's openclaw.json block
- **Live evidence**: All HAL turns still handled embedded. No ACP sessions observed.
- **Status**: **PARTIAL** — scaffolded, activation is a config change
- **Next step**: Set `acp.enabled=true` in openclaw.json, change HAL `runtime.type` to `"acp"`, add `"hal"` to `acp.allowedAgents`, validate with verifier. Requires confirming HAL actually succeeds on a real coding task first.

---

## 2. Agent System / Lane Specialization

### 2.1 Agent bootstrap specialization (per-agent files from ~/.openclaw/agents/<id>/)
- **Source**: `docs/agent_roster.md`, `docs/notes/hermes-bootstrap-gap-20260316.md`
- **Description**: Each agent loads AGENTS.md, SOUL.md, TOOLS.md, IDENTITY.md, USER.md, HEARTBEAT.md, BOOTSTRAP.md from its own agentDir. Generic workspace fallback only when file is absent.
- **Repo evidence**: `bootstrap-extra-files/handler.js` overlay verified: `agent_bootstrap_overlay_present=True`
- **Live evidence**: All agents (jarvis, hal, archimedes, anton, hermes, scout, qwen, kitt) confirmed loading from agent_dir or confirmed via `systemSent:true`. Verify script shows 7/7 basenames from agent_dir for kitt and hermes.
- **Status**: **LIVE**
- **Next step**: N/A

### 2.2 Kitt quant specialist lane
- **Source**: `~/.openclaw/openclaw.json` Kitt binding, `~/.openclaw/agents/kitt/`
- **Description**: Kitt = quantitative research/analyst specialist, no execution authority, Kimi-K2.5 model. Discord channel #kitt.
- **Repo evidence**: Kitt in `CANONICAL_AGENT_ROSTER`, `AGENT_TOOL_ALLOWLIST` (8 tools), `AGENT_SKILL_ALLOWLIST` (2 skills), `AGENT_RUNTIME_TYPES`
- **Live evidence**: All 7 bootstrap basenames resolve from agent_dir; channel binding ok; session `systemSent:true`; Allowed tools (8). Fixed 2026-03-17.
- **Status**: **LIVE**
- **Next step**: Add Kitt to `runtime_routing_policy.json` (see 1.7). First live turn needed to confirm tool/skill enforcement in prod.

### 2.3 Hermes live daemon integration
- **Source**: `docs/agent_roster.md`, `docs/jarvis_5_2_migration_status.md`
- **Description**: Hermes = deep research daemon. Jarvis-side adapter (`hermes_adapter.py`) hardened for fail-closed validation, failure_category persistence. External Hermes runtime required.
- **Repo evidence**: `runtime/integrations/hermes_adapter.py` (43KB). Contract hardening confirmed in `V5_1_FREEZE_NOTES.md`.
- **Live evidence**: Lane activation status: `not_run`. Hermes Discord session exists (embedded), but full research daemon path (hermes_bridge lane) never activated.
- **Status**: **BLOCKED** — adapter live, external runtime not configured
- **Next step**: Run `scripts/operator_activate_external_lanes.py` targeting `hermes_bridge`; confirm external Hermes service is running and accessible; record activation result.

### 2.4 SearXNG web search backend
- **Source**: `docs/jarvis_5_2_migration_status.md`, `runtime/integrations/searxng_client.py`
- **Description**: Scout/Hermes use SearXNG for web search. Integration code exists; requires external SearXNG service healthcheck to go green.
- **Repo evidence**: `runtime/integrations/searxng_client.py`, `runtime/integrations/search_normalizer.py`
- **Live evidence**: Lane activation: `not_run`. Scout's `web_search`/`web_fetch` tools are in its allowlist but it's unclear if they currently hit SearXNG or another backend.
- **Status**: **BLOCKED** — client exists, external healthcheck not confirmed
- **Next step**: Check if SearXNG is running locally; if yes, run activation script; if not, decide whether to stand it up or confirm Scout is using a different search backend.

### 2.5 Ralph autonomous maintenance loop
- **Source**: `docs/agent_roster.md`, `runtime/core/agent_roster.py`
- **Description**: Ralph = overflow/maintenance worker. Memory consolidation, queue draining, low-priority chores. Full autonomy loop needs external runtime.
- **Repo evidence**: Ralph in `CANONICAL_AGENT_ROSTER` (`implemented_but_blocked_by_external_runtime`). `AGENT_TOOL_ALLOWLIST` has 10 tools including `cron`, `memory_search`, `memory_get`.
- **Live evidence**: No Ralph Discord session. Sessions run cron (Sunday 2AM memory compaction) but Ralph agent loop itself not live.
- **Status**: **BLOCKED** — policy backed, full loop requires external runtime or ACP
- **Next step**: Ralph could run as a second ACP candidate after HAL validation. Or: wire Ralph to execute a bounded consolidation pass as a cron-triggered subprocess.

### 2.6 Bowser browser bridge
- **Source**: `docs/agent_roster.md`, `docs/jarvis_5_2_migration_status.md`
- **Description**: Browser automation specialist. `browser` tool in allowlist. Browser bridge lane: `scaffold_only`.
- **Repo evidence**: Bowser in `CANONICAL_AGENT_ROSTER`; `browser_bridge` in `TARGET_LANES` in `lane_activation.py`; browser cancel path added in v5.1.
- **Live evidence**: Lane activation: `not_run`. Host does not pass `browser` tool in live sessions yet.
- **Status**: **SCAFFOLD** — policy and cancel path exist, no live automation
- **Next step**: Not a high priority. Bowser needs browser tool to be passed by the gateway host.

### 2.7 Muse creative specialist
- **Source**: `docs/agent_roster.md`
- **Description**: Creative writing, ideation, naming. Policy-backed specialization; no dedicated daemon. Discord channel not confirmed bound.
- **Repo evidence**: Muse in `CANONICAL_AGENT_ROSTER` (`policy_backed`); `AGENT_TOOL_ALLOWLIST` has 4 tools (image, message, read, tts).
- **Live evidence**: No Muse Discord session in scan. No channel binding found in `openclaw.json` for Muse.
- **Status**: **PARTIAL** — policy exists, no live Discord channel
- **Next step**: If Muse is needed, add a channel binding in `openclaw.json` and Muse-specific bootstrap files in `~/.openclaw/agents/muse/`.

---

## 3. Runtime Memory / Context / Prompt Management

### 3.1 Rolling session summary (vault/session_context/)
- **Source**: `docs/source_owned_context_engine.md`, `runtime/memory/vault_index.py`
- **Description**: Per-session rolling summary built from distilled messages. Persisted to `workspace/vault/session_context/`. Preserves objective, questions, constraints, decisions, tool findings, operator preferences.
- **Repo evidence**: `_build_summary_from_messages()`, `save_session_context_summary()`, `load_session_context_summary()` in `source_owned_context_engine.py`; `runtime/memory/vault_index.py`
- **Live evidence**: `workspace/vault/session_context/` exists in live workspace. Called on every turn.
- **Status**: **LIVE**
- **Next step**: N/A

### 3.2 Memory retrieval for context (episodic + semantic)
- **Source**: `docs/source_owned_context_engine.md`, `runtime/memory/governance.py`
- **Description**: Before each prompt assembly, retrieve bounded episodic and semantic memories. Budget: 1200 tokens, 4 episodic, 4 semantic. Uses `retrieve_memory_for_context()`.
- **Repo evidence**: `runtime/memory/governance.py`, called in `build_context_packet()`. `MemoryRetrievalRecord` persisted.
- **Live evidence**: Called every turn. Whether useful memory entries exist depends on memory being written. Memory spine for Jarvis sessions is active per tests.
- **Status**: **LIVE** (infrastructure), **PARTIAL** (utility — depends on memory entries being saved proactively)
- **Next step**: Ensure memory entries are actually written for significant decisions/findings. Currently retrieval infrastructure is live but there may be few entries to retrieve.

### 3.3 Memory typing (episodic / semantic / procedural) with confidence decay
- **Source**: `docs/spec/Jarvis_OS_v5_1_Master_Spec.md`, `runtime/core/models.py`
- **Description**: Three memory types. Episodic: recent observations, bounded decay. Semantic: stable facts, operator preferences. Procedural: approved skills.
- **Repo evidence**: `MemoryEntryRecord` in `models.py`, `runtime/memory/governance.py`; `save_memory_entry()`, `retrieve_memory_for_context()`
- **Live evidence**: Framework live. Memory spine in tests uses episodic + semantic. Unclear how much is written in practice during live Discord sessions.
- **Status**: **PARTIAL** — framework live, active memory population unclear
- **Next step**: Audit whether Jarvis/agents are actively calling `save_memory_entry()` during live sessions. If not, identify 2–3 high-value memory write points to add.

### 3.4 Token/cost budget tracking
- **Source**: `docs/spec/Jarvis_OS_v5_1_Master_Spec.md`, `runtime/core/token_budget.py`
- **Description**: Hard-stop auto-pause on token/cost budget overflow. Budget tracking per task/session.
- **Repo evidence**: `runtime/core/token_budget.py` (11KB)
- **Live evidence**: Not confirmed as wired to live model call path. Context engine does prompt-budget estimation but that's for context window, not cost tracking.
- **Status**: **PARTIAL** — module exists, not confirmed live in model dispatch
- **Next step**: Verify whether token_budget.py is called during live model sends. If not, wire it.

### 3.5 Session reset policy (daily/idle)
- **Source**: `~/.openclaw/openclaw.json`
- **Description**: `mode: "daily"`, `atHour: 4`, `idleMinutes: 120`. Sessions idle for 2h or spanning 4AM reset.
- **Repo evidence**: `openclaw.json` `session.reset` config; documented in context-bloat fix notes
- **Live evidence**: Sessions that run continuously (24h+) have overflowed before fix. Post-fix emergency distill handles it, but long continuous sessions remain a risk.
- **Status**: **LIVE** (policy configured), **PARTIAL** (sessions can still grow if they survive without idling)
- **Next step**: Consider adding a hard turn-count ceiling in `source_owned_context_engine.py` (e.g., reset if `total_user_turns > 50`).

---

## 4. Hermes / Research / Execution Integration

### 4.1 Hermes adapter contract hardening (v5.1 closure)
- **Source**: `docs/spec/V5_1_FREEZE_NOTES.md`
- **Description**: Hermes request/result validation blocks on malformed contracts. `failure_category` persisted durably. Summary surfaces expose failure counts.
- **Repo evidence**: `runtime/integrations/hermes_adapter.py` (43KB). Test: `tests/test_hermes_adapter.py`
- **Live evidence**: Code and tests confirmed. Hermes adapter is hardened; the external daemon is what's missing.
- **Status**: **LIVE** (code), **BLOCKED** (end-to-end — external daemon not running)
- **Next step**: External daemon activation (see 2.3)

### 4.2 Autoresearch adapter + standard run outputs (v5.1 closure)
- **Source**: `docs/spec/V5_1_FREEZE_NOTES.md`
- **Description**: Autoresearch request/result validation. Standard output files (run_config.json, candidate.patch, experiment_log.md, recommendation.json, etc.) written under sandbox_root/run_id/standard_run_outputs/.
- **Repo evidence**: `runtime/integrations/autoresearch_adapter.py` (68KB). Test: `tests/test_autoresearch_adapter.py`
- **Live evidence**: Code and tests confirmed. External autoresearch upstream never activated (`not_run`).
- **Status**: **LIVE** (code), **BLOCKED** (end-to-end — external runtime not running)
- **Next step**: External runtime activation required

### 4.3 ShadowBroker OSINT sidecar
- **Source**: `docs/shadowbroker_deployment.md`, `docs/jarvis_5_2_migration_status.md`
- **Description**: External OSINT/intel sidecar. Integration adapter exists. Status: `implemented_but_blocked_by_external_runtime` unless service is configured and healthy.
- **Repo evidence**: `runtime/integrations/shadowbroker_adapter.py` (25KB); `runtime/world_ops/` models, store, collector, normalizer, summary
- **Live evidence**: Lane activation: `not_run`. World-ops is `deprecated_alias`.
- **Status**: **BLOCKED**
- **Next step**: Activate only if OSINT sidecar service is actually available. Low priority unless research capability is a current bottleneck.

### 4.4 Adaptation lab (Unsloth fine-tuning)
- **Source**: `docs/jarvis_5_2_migration_status.md`, `runtime/adaptation_lab/`
- **Description**: Narrow adapter fine-tuning. Status: `implemented_but_blocked_by_external_runtime` unless Unsloth installed and a bounded proof run completed.
- **Repo evidence**: `runtime/adaptation_lab/runner.py`, `evaluator.py`, `promotion_policy.py`
- **Live evidence**: Lane activation: `not_run`
- **Status**: **BLOCKED** — Unsloth not proven installed/running
- **Next step**: Not a current priority unless model fine-tuning is needed.

### 4.5 DSPy optimizer
- **Source**: `docs/jarvis_5_2_migration_status.md`, `runtime/optimizer/`
- **Description**: DSPy-based prompt optimization. Status: `implemented_but_blocked_by_external_runtime` unless DSPy installed and a bounded proof run completed.
- **Repo evidence**: `runtime/optimizer/dspy_runner.py`, `variant_store.py`, `eval_gate.py`
- **Live evidence**: Lane activation: `not_run`
- **Status**: **BLOCKED**
- **Next step**: Not a current priority.

### 4.6 Research backend abstraction (5.2 evidence bundles)
- **Source**: `docs/spec/JARVIS 5.2 MASTER SPEC.md` §3
- **Description**: Research backends produce normalized results → evidence bundles → provenance linkage to artifacts. Dashboard can inspect provenance.
- **Repo evidence**: `runtime/integrations/research_backends.py`, `runtime/core/provenance_store.py`; autoresearch adapter materializes standard outputs. Evidence bundle shape spec'd in 5.2.
- **Live evidence**: No live research runs observed. Autoresearch standard outputs are written to disk but only when autoresearch upstream runs.
- **Status**: **PARTIAL** — provenance store and backend abstraction exist, no live research runs producing bundles
- **Next step**: Depends on external research runtime activation (4.1, 4.2)

---

## 5. Dashboards / Operator Visibility

### 5.1 Bootstrap verification script
- **Source**: `scripts/verify_openclaw_bootstrap_runtime.py`
- **Description**: Verifies live agent bootstrap files, policy allowlists, session snapshot vs policy. Live-usable operator tool.
- **Repo evidence**: Full implementation, `--agent` flag, `--json` output, channel audit section
- **Live evidence**: Run in this session successfully; all 8 agents verified.
- **Status**: **LIVE**
- **Next step**: N/A

### 5.2 Discord runtime check script
- **Source**: `scripts/operator_discord_runtime_check.py`
- **Description**: Checks Discord session state, provider health, model routing, tool exposure, rolling summaries. References `build_status()` for full read-model.
- **Repo evidence**: 50+ line script using `build_status()` and `openclaw_sessions.py`
- **Live evidence**: Script exists and can be run. Not run in this session.
- **Status**: **LIVE** (script), **PARTIAL** (how regularly it's used is unclear)
- **Next step**: Could be run periodically or wired to a cron/heartbeat check.

### 5.3 Operator command center (90+ scripts)
- **Source**: `scripts/operator_*.py` (90+ files)
- **Description**: Full lifecycle CLI: task management, checkpoint, bridge cycles, transport, recovery, remediation, incident detection, doctor, triage. Designed for operator-driven debugging and approvals.
- **Repo evidence**: 90+ scripts in `scripts/`
- **Live evidence**: Scripts exist but usage in live operation is not confirmed. No evidence of active task/approval cycles running.
- **Status**: **PARTIAL** — scripts exist, unclear how actively the task/approval lifecycle is being used
- **Next step**: Audit which operator scripts are actually being called. The task queue (TASKS.jsonl) and strategy registry may be the active surfaces.

### 5.4 Dashboard (operator_snapshot, state_export, task_board, event_board)
- **Source**: `runtime/dashboard/`, `docs/spec/JARVIS 5.2 MASTER SPEC.md` §5
- **Description**: Operator cockpit. Read-model surfaces for status, tasks, outputs, events, heartbeat.
- **Repo evidence**: `runtime/dashboard/operator_snapshot.py`, `state_export.py`, `task_board.py`, `output_board.py`, `event_board.py`, `rebuild_all.py`
- **Live evidence**: Dashboard rebuild scripts exist but no confirmed live rendering surface. Dashboard is a read-model, not a live web UI.
- **Status**: **PARTIAL** — read-model exists, no live rendering confirmed
- **Next step**: Run `scripts/doctor.py` and `scripts/validate.py` to verify dashboard rebuild works end-to-end.

### 5.5 Lane activation status tracking
- **Source**: `runtime/integrations/lane_activation.py`
- **Description**: Tracks activation attempts for 6 external lanes (shadowbroker, searxng, hermes_bridge, autoresearch_upstream_bridge, adaptation_lab_unsloth, optimizer_dspy). Per-lane result files in `state/lane_activation/`.
- **Repo evidence**: `lane_activation.py`, `summarize_lane_activation()` function
- **Live evidence**: All 6 lanes: `not_run`. `state/lane_activation/` is empty.
- **Status**: **PARTIAL** — framework live, no activations ever attempted
- **Next step**: Run lane activation for lanes where the external service might already be available (e.g., check if SearXNG is accessible).

### 5.6 Jarvis/agent channel status (no #jarvis session)
- **Source**: `verify_openclaw_bootstrap_runtime.py` output
- **Description**: Jarvis main Discord channel binding (1478178050133987400) has no session yet.
- **Live evidence**: `status: no_session_yet` in channel audit. Jarvis will create it on first inbound message.
- **Status**: **PARTIAL** — will auto-create
- **Next step**: Send a message to #jarvis on Discord to initialize the session.

---

## 6. Approvals / Governance / Degradation

### 6.1 Review hierarchy (HAL → Archimedes → Anton)
- **Source**: `docs/agent_roster.md`, `runtime/core/decision_router.py`
- **Description**: HAL builds → Archimedes technical review → Anton supreme/high-stakes review. Wired via `decision_router.py` which posts completed work to reviewer channels.
- **Repo evidence**: `REVIEW_HIERARCHY`, `DELEGATION_WIRING` in `agent_roster.py`; `decision_router.py` (15KB)
- **Live evidence**: Policy backed. No confirmed end-to-end review cycle observed. Archimedes, Anton, Hermes have no live sessions yet.
- **Status**: **PARTIAL** — routing logic exists, no confirmed live review cycles
- **Next step**: Confirm a real HAL → Archimedes review cycle has completed at least once. Check if decision_router posts to Archimedes/Anton channels correctly.

### 6.2 Approval store / resumable approvals
- **Source**: `docs/spec/Jarvis_OS_v5_1_Master_Spec.md`, `runtime/core/approval_store.py`
- **Description**: Approval checkpoints with resumable sessions. Discord `#review` emoji reactions trigger approvals.
- **Repo evidence**: `runtime/core/approval_store.py` (27KB), `runtime/core/approval_sessions.py` (10KB)
- **Live evidence**: Code exists. No confirmed live approval cycles observed for code/strategy work.
- **Status**: **PARTIAL** — code live, not confirmed in regular use
- **Next step**: Test an approval cycle. Requires HAL to produce an artifact that needs review.

### 6.3 Degradation policy
- **Source**: `docs/spec/Jarvis_OS_v5_1_Master_Spec.md`, `docs/notes/degradation_policy.md`, `runtime/core/degradation_policy.py`
- **Description**: System degradation response. Fallback without security reduction. `BURST_WORKER_OFFLINE`, `RESEARCH_BACKEND_DOWN`, etc. Operator notification required for some modes.
- **Repo evidence**: `runtime/core/degradation_policy.py` (25KB); `docs/notes/degradation_policy.md`
- **Live evidence**: Module exists. Not confirmed as wired to live model dispatch or routing.
- **Status**: **PARTIAL** — module exists, not confirmed live in dispatch path
- **Next step**: Verify `decision_router.py` calls `degradation_policy.py` before model selection.

### 6.4 Promotion governance (strategy lifecycle gates)
- **Source**: `docs/spec/Jarvis_OS_v5_1_Master_Spec.md`, `runtime/core/promotion_governance.py`
- **Description**: Strategy promotion gates (IDEA → CANDIDATE → BACKTESTED → PROMOTED → PAPER_TRADING → LIVE). Live execution requires human approval.
- **Repo evidence**: `runtime/core/promotion_governance.py` (13KB)
- **Live evidence**: Strategy factory in `workspace/strategy_factory/` is the live surface. Promotion gates connected to factory pipeline.
- **Status**: **PARTIAL** — governance code exists, live strategy pipeline is the active surface
- **Next step**: N/A unless strategies are being promoted

### 6.5 Emergency controls (global kill, subsystem breakers, rate governors)
- **Source**: `docs/spec/Jarvis_OS_v5_1_Master_Spec.md`
- **Description**: Three-layer emergency control: global kill switch, per-subsystem circuit breakers, per-agent rate governors.
- **Repo evidence**: Referenced in master spec. `degradation_policy.py` has related logic. No separate emergency_controls.py found.
- **Live evidence**: Not confirmed as a live seam
- **Status**: **PARTIAL / DOC-ONLY** — degradation policy covers some cases, no dedicated emergency control seam confirmed
- **Next step**: Verify `degradation_policy.py` has all three layers or determine if global kill / rate governors are missing.

---

## 7. External Integrations / Mission Control / World-Ops

### 7.1 Mission control adapter
- **Source**: `docs/mission_control_gateway_mode.md`, `docs/jarvis_5_2_migration_status.md`
- **Description**: Gateway mode operations, mission control sync.
- **Repo evidence**: `scripts/mission_control_sync.py`; `docs/mission_control_gateway_mode.md`
- **Live evidence**: `scaffold_only` per migration status
- **Status**: **SCAFFOLD**
- **Next step**: Not a current priority

### 7.2 A2A (agent-to-agent) protocol
- **Source**: `docs/jarvis_5_2_migration_status.md`, `runtime/core/a2a_policy.py`
- **Description**: Direct agent-to-agent communication protocol, distinct from Discord channel routing.
- **Repo evidence**: `runtime/core/a2a_policy.py` (7KB); `scaffold_only` per migration status
- **Live evidence**: Not active. Agent communication happens via Discord channels / `sessions_send` tool.
- **Status**: **SCAFFOLD**
- **Next step**: Not a current priority

### 7.3 Voice subsystem
- **Source**: `docs/spec/Jarvis_OS_v5_1_Master_Spec.md`, `runtime/integrations/voice_gateway.py`
- **Description**: First-class voice ingress/egress. V1: dictation. V2: conversational. TTS in Jarvis allowlist.
- **Repo evidence**: `runtime/integrations/voice_gateway.py`, `runtime/core/voice_sessions.py`, `runtime/core/spoken_approval.py`; `tts` in Jarvis/Muse/Qwen tool allowlists; `sherpa-onnx-tts` in Jarvis skill allowlist
- **Live evidence**: TTS tools present in Jarvis loadout. Voice gateway file exists. Not confirmed as active.
- **Status**: **PARTIAL** — bounded framework exists, live use not confirmed
- **Next step**: Test voice channel if hardware is available. TTS skill is in Jarvis allowlist.

### 7.4 TradingView adapter
- **Source**: `runtime/integrations/tradingview_adapter.py`
- **Description**: TradingView data integration for quant research.
- **Repo evidence**: `tradingview_adapter.py` (1.6KB)
- **Live evidence**: Not confirmed as actively used
- **Status**: **PARTIAL** — adapter exists, active use unclear
- **Next step**: If Kitt/quant pipeline needs live market data, wire this into Kitt's tool surface.

### 7.5 Notification adapter
- **Source**: `runtime/integrations/notification_adapter.py`
- **Description**: Notification service for operator alerts.
- **Repo evidence**: `notification_adapter.py` (2.7KB)
- **Live evidence**: Not confirmed
- **Status**: **PARTIAL**
- **Next step**: Audit whether Discord messages from agents serve as the live notification surface.

---

## 8. Quant / Kitt / Trading-Related

### 8.1 Strategy factory pipeline
- **Source**: `~/.openclaw/workspace/strategy_factory/`, CLAUDE.md
- **Description**: Full NQ backtesting pipeline: data pull, feature gen, candidate gen, simulation, gates, robustness, diversity, scoring, promotion gate, paper trading. Cron-scheduled.
- **Repo evidence**: `workspace/strategy_factory/` (separate from jarvis-v5). TASKS.jsonl, STRATEGIES.jsonl, EXPERIMENTS.jsonl in workspace root.
- **Live evidence**: Cron jobs scheduled (daily 4AM data pull, weekly Sunday factory batch). Active per CLAUDE.md.
- **Status**: **LIVE**
- **Next step**: N/A (monitoring)

### 8.2 Kitt quant specialist lane
- See 2.2 above. **LIVE** as of 2026-03-17.

### 8.3 Kitt missing from runtime_routing_policy.json
- See 1.7 above. **PARTIAL** (trivial fix).

### 8.4 Quant evidence bundles / research provenance for strategies
- **Source**: `docs/spec/JARVIS 5.2 MASTER SPEC.md` §3, `workspace/artifacts/`
- **Description**: Strategy research producing normalized evidence bundles, provenance linkage to artifacts. Currently strategy factory outputs are JSON artifacts but not connected to the evidence bundle framework.
- **Repo evidence**: `workspace/artifacts/strategy_factory/` (output directory). `provenance_store.py` exists but not confirmed wired to strategy factory.
- **Live evidence**: Strategy factory artifacts exist in `workspace/artifacts/`. Evidence bundle framework in `provenance_store.py` is not confirmed connected.
- **Status**: **PARTIAL** — artifacts exist, evidence bundle provenance chain not confirmed
- **Next step**: Wire strategy factory outputs to `provenance_store.py` evidence bundle writes.

### 8.5 Paper trading / live trading approval gate
- **Source**: `docs/spec/Jarvis_OS_v5_1_Master_Spec.md`, `~/.openclaw/workspace/PROMOTION.md`
- **Description**: Live execution always requires human approval via Discord #review emoji reaction. Never auto-executed.
- **Repo evidence**: `runtime/core/promotion_governance.py`, `approval_store.py`, PROMOTION.md
- **Live evidence**: Policy is live (no strategies currently at paper or live trading stage per known state). Approval gate code exists.
- **Status**: **LIVE** (as policy/code gate), **PARTIAL** (no active strategies requiring this gate currently)
- **Next step**: N/A

### 8.6 DURABLE task queue / strategy registry / experiment registry
- **Source**: CLAUDE.md, `~/.openclaw/workspace/`
- **Description**: TASKS.jsonl (durable task queue), STRATEGIES.jsonl (strategy registry), EXPERIMENTS.jsonl (experiment run configs).
- **Live evidence**: Files exist in `~/.openclaw/workspace/`. Actively maintained per cron schedule.
- **Status**: **LIVE**
- **Next step**: N/A

---

## Priority Top 10 (by runtime impact × usefulness × difficulty × dependency order)

| # | Feature | Impact | Usefulness | Difficulty | Status | Dependency |
|---|---------|--------|------------|------------|--------|------------|
| 1 | Kitt routing policy registration (1.7) | Low-medium | Medium | Trivial (1 file) | PARTIAL | None |
| 2 | SearXNG activation check + lane activation (2.4) | High | High | Low if running | BLOCKED | External service |
| 3 | Memory entry write points audit (3.3) | High | High | Medium | PARTIAL | None |
| 4 | ACP harness activation for HAL (1.9) | High | High | Low (config change) | PARTIAL | HAL task validation |
| 5 | Hermes external daemon activation (2.3) | High | High | Medium-High | BLOCKED | External service |
| 6 | Review cycle confirmation (6.1) | High | High | Low (test run) | PARTIAL | HAL working task |
| 7 | Hard turn-count ceiling in context engine (3.5) | Medium | Medium | Low (1 function) | PARTIAL | None |
| 8 | Multi-model routing enforcement in decision_router (1.6) | High | Medium | High | PARTIAL | 5.2 work |
| 9 | Degradation policy live wiring (6.3) | Medium | Medium | Medium | PARTIAL | decision_router |
| 10 | TradingView → Kitt tool surface (7.4) | Medium | High (quant) | Low-medium | PARTIAL | Kitt live |

---

## Next 3 Live-Runtime Targets

### Target 1 — Kitt routing policy registration
**Why it matters**: Kitt has a live Discord channel and a full roster profile, but no entry in `config/runtime_routing_policy.json`. Verifier shows `configured_routing_policy: {}` for Kitt. When the 5.2 policy router queries routing policy, Kitt will fall through to defaults (Qwen-only). Kitt uses Kimi-K2.5 (nvidia), which is a different provider family entirely.

**Exact live seam to touch**: `config/runtime_routing_policy.json`, `agent_policies` section.

**Files involved**:
- `config/runtime_routing_policy.json` — add Kitt entry with `nvidia` preferred provider, `moonshotai/kimi-k2-5` preferred model, `qwen3.5` family as fallback

**Proof it is live**: Running `verify_openclaw_bootstrap_runtime.py --agent kitt` shows non-empty `configured_routing_policy`. Running `build_agent_roster_summary()` shows `routing_policy_present: True` for Kitt.

---

### Target 2 — Memory write points: confirm or add active save_memory_entry() calls
**Why it matters**: The memory retrieval infrastructure (episodic + semantic) is live and called every turn, but if agents are not writing memory entries during sessions, retrieval returns nothing useful. The context engine wastes retrieval budget on empty results. This means sessions effectively have no persistent cross-session learning.

**Exact live seam to touch**: Confirm whether `save_memory_entry()` is called during live Jarvis/Scout/Hermes/Kitt Discord sessions. If not, add 2–3 high-value write points: (a) after a task decision is made, (b) after a research result is returned, (c) when an operator preference is stated.

**Files involved**:
- `runtime/memory/governance.py` — `save_memory_entry()` already exists
- Look in `runtime/core/decision_router.py`, `runtime/core/task_store.py`, `scripts/source_owned_context_engine_cli.py` for where to add write calls
- Check `~/.openclaw/workspace/jarvis-v5/workspace/` for any existing memory files

**Proof it is live**: After a live Discord conversation with a decision or finding, running `retrieve_memory_for_context()` returns non-empty results. `MemoryRetrievalRecord` shows `episodic_result_count > 0` or `semantic_result_count > 0`.

---

### Target 3 — SearXNG lane activation check (Scout web search)
**Why it matters**: Scout has `web_search` and `web_fetch` in its tool allowlist and is the primary web reconnaissance agent. The SearXNG client code exists. If SearXNG is not running, Scout's research capability is absent or falling back to an untracked backend. Activating this lane unblocks Scout and indirectly Hermes.

**Exact live seam to touch**:
1. Check if SearXNG is accessible (local docker container or remote endpoint)
2. If accessible: run `scripts/operator_activate_external_lanes.py` or call `record_lane_activation_result()` directly with `lane="searxng"`, `configured=True`, `healthy=True`
3. If not accessible: stand up SearXNG container or document that Scout uses a different search backend

**Files involved**:
- `runtime/integrations/searxng_client.py` — check `base_url` configuration
- `runtime/integrations/lane_activation.py` — record activation result
- `scripts/operator_activate_external_lanes.py` — activation script
- `state/lane_activation/searxng.json` — result file after activation

**Proof it is live**: `lane_activation/searxng.json` shows `configured=True, healthy=True, status="completed"`. Scout can run `web_search` tool and return actual search results from SearXNG.
## 2026-03-17 — Post-merge live validation update

Merged branch `audit/parallel-runs-2026-03-17` into `main` and pushed to `origin/main`.

### Repo state
- **Branch**: `main`
- **Merge commit**: `1afda5a`
- **Status at validation time**: clean working tree before inventory-only edits

### Live gateway state
- **Gateway service**: `openclaw-gateway.service` active/running
- **Health endpoint**: `http://127.0.0.1:18789/health` returned `{"ok":true,"status":"live"}`
- **Discord**: logged in as Jarvis and channels resolved successfully after restart/reconnect

### Kitt runtime validation
- **Status**: LIVE
- **Proof**: `openclaw agent --agent kitt --message "Reply with exactly: KITT_LIVE_OK" --json`
- **Observed provider/model**: `nvidia` / `moonshotai/kimi-k2.5`
- **Observed response**: `KITT_LIVE_OK`

### SearXNG web search validation
- **Status**: LIVE
- **Backend**: local SearXNG at `http://localhost:8888`
- **Direct backend proof**: `/search?q=VIX+index&format=json` returned Yahoo Finance VIX result
- **Agent proof**: `openclaw agent --agent kitt --message "Use web_search and tell me one result for VIX index. Keep it to one line." --json`
- **Observed result**: Kitt returned Yahoo Finance VIX result in one line
- **Interpretation**: patched multi-bundle SearXNG path is functioning live through agent web_search

### HAL runtime validation
- **Status**: LIVE for normal agent execution
- **Proof**: `openclaw agent --agent hal --message "Reply with exactly: HAL_LIVE_OK" --json`
- **Observed provider/model**: `lmstudio` / `qwen3.5-35b-a3b`
- **Observed response**: `HAL_LIVE_OK`

### HAL ACP validation
- **Status**: PARTIAL / DIRECT ACP PROOF ONLY
- **Direct ACP proof**:
  - wrapper server script launched `openclaw acp --session agent:hal:main`
  - `openclaw acp client` returned `ACP_DIRECT_OK`
  - ACP client showed `[end_turn]`
- **Interpretation**: ACP path is reachable and completes a direct session
- **Remaining gap**: gateway journal did not emit strong ACP/acpx session evidence for the direct proof, and Discord-initiated HAL ACP dispatch is still not conclusively evidenced from logs

### Inventory of merged work now on main
- context engine session turn ceiling + memory flush
- operator checkpoint cadence + provenance freshness
- preflight drift + backend dependency checks
- SearXNG patch verification hardening
- Kitt NVIDIA/Kimi routing + executor wiring
- backend dispatch + HAL handoff
- operator gateway inbound seam + status lookup fix

### Current confidence summary
- **Kitt on NVIDIA/Kimi**: confirmed live
- **Kitt web_search via SearXNG**: confirmed live
- **HAL normal execution on LM Studio**: confirmed live
- **HAL ACP direct session**: confirmed in bounded direct-client proof
- **HAL ACP via Discord/gateway-originated production path**: still needs cleaner proof/telemetry

### Recommended next proof target
Capture one unambiguous HAL ACP production-path proof with either:
1. Discord-initiated HAL turn that shows ACP/acpx session evidence in logs, or
2. explicit gateway-side ACP telemetry added to make the dispatch path operator-visible.
