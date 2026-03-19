# Spec Verification Matrix — 2026-03-18

Feature-by-feature verification of v5 / v5.1 / v5.2 spec claims against live runtime evidence.

**Method**: Each row checked against live config, running services, state files, accepted commits, and test results. Status is what's proven, not what's claimed.

**Validate**: `python3 scripts/validate.py` — 395 pass, 0 fail

> See also: [CURRENT_TRUTH.md](CURRENT_TRUTH.md) (status/backlog), [live_runtime_watchboard.md](live_runtime_watchboard.md) (proof journal)

---

## 1. Control Plane & Routing

| # | Feature | Spec | Expected Behavior | Repo Evidence | Live Evidence | Status | Proof | Gap |
|---|---------|------|-------------------|---------------|---------------|--------|-------|-----|
| 1.1 | Multi-agent Discord bindings | v5.1 §7 | Each channel → named agent session | `openclaw.json` bindings (12 channels), `agent_channel_map.json` | Gateway resolves 12 channels at startup. All agent sessions active. | **LIVE** | Gateway log `channels resolved: +6` | — |
| 1.2 | Source-owned context engine | v5.1 §7 | Bounded 6-turn working memory, older turns distilled | `source_owned_context_engine.py`, `source_owned_context_engine_cli.py` | Called as subprocess before every model send. Budget guard at 72%/82%. Emergency distill fires when needed. | **LIVE** | 17/17 tests pass | — |
| 1.3 | Context budget guard | v5.1 §15 | Safe 72%, hard 82%, emergency distill | `_build_prompt_budget()`, emergency distill block | Hard threshold blocks send. Emergency distill fires when compacted window still over safe. Integer estimation bug fixed 2026-03-16. | **LIVE** | Tests pass; prior 83KB overflow caught | — |
| 1.4 | Tool exposure filtering | v5.1 §9 | chat-minimal / full / agent-scoped | `_select_tool_exposure()`, `SIMPLE_CHAT_TOOL_RE` | Simple chat gets no tools. Task/code prompts get full/scoped tools. Per-turn, not per-session. | **LIVE** | `systemPromptReport.toolExposure.mode` confirmed | — |
| 1.5 | Agent tool/skill allowlists | v5.1 §9 | Per-agent allowlists, fail-closed for unknowns | `AGENT_TOOL_ALLOWLIST`, `AGENT_SKILL_ALLOWLIST` in `agent_roster.py` | `filter_tools_for_agent()` / `filter_skills_prompt_for_agent()` confirmed via gateway bundle | **LIVE** | `filtered_skills_applied=True` | — |
| 1.6 | Lane-based model routing | v5.1 §6, v5.2 §2 | Policy-driven model selection per agent/workload | `runtime_routing_policy.json`, `routing.py`, `runtime_profiles.py` | `load_runtime_routing_policy()` applies active profile. 5 named profiles. `sync_routing_policy_to_openclaw.py` propagates to gateway. | **LIVE** | Jarvis on Kimi 2.5 proven (d864e47) | — |
| 1.7 | No silent cross-family switching | v5.1 §6 | Family swaps explicit, logged, scoped, expiring, reversible | Profile changes write `state/active_profile.json`, emit `profile_changed` Discord event | `show` command displays expected vs realized model with [ok]/[stale] match status | **LIVE** | dc3330a | — |
| 1.8 | Multi-node burst routing | v5.2 §1 | Node registration, heartbeat, lease, reroute on loss | `node_registry.py`, `task_lease.py`, `heartbeat_reports.py` exist. 3 nodes registered. `burst_allowed=false` everywhere. | No burst tasks ever dispatched. Heartbeat/lease modules importable but untested in production. | **DOC-ONLY** | — | Burst routing disabled. No real multi-node dispatch. |
| 1.9 | Capability matrix per model | v5.1 §6 | Each model declares family, tool support, vision, context, cost | `ACTIVE_QWEN_MODELS` in `routing.py`, `CAPABILITY_PROFILES` | 5 models registered with provider_id, model_family, priority_rank, workload_tags, capability_profile_ids | **LIVE** | — | Missing: vision, reasoning_mode, cost_class fields |

## 2. Agent System & Specialization

| # | Feature | Spec | Expected Behavior | Repo Evidence | Live Evidence | Status | Proof | Gap |
|---|---------|------|-------------------|---------------|---------------|--------|-------|-----|
| 2.1 | Jarvis orchestrator | v5.1 §4 | Single public face, control plane, task routing | `openclaw.json` agent config, `AGENTS.md`/`SOUL.md`/`IDENTITY.md` bootstrap files | Real turns proven via `openclaw agent --agent jarvis`. Orchestrates task routing, review delegation. | **LIVE** | d864e47 | — |
| 2.2 | HAL builder + ACP | v5.1 §4, §7 | Code execution via ACP subprocess | `acp.enabled=true`, `backend=acpx`, `allowedAgents=["hal"]` in `openclaw.json` | `openclaw-acp` + `acpx` sessions live in gateway process tree. Per-turn ACP telemetry to `hal_acp.jsonl`. | **LIVE** | Watchboard §J | — |
| 2.3 | Archimedes reviewer | v5.1 §4 | Code review lane | Agent config + bootstrap files. Session active. | Reviews recorded in `state/reviews/` (26 records). Review events route to Discord. | **LIVE** | bbe7132 | — |
| 2.4 | Anton supreme reviewer | v5.1 §4 | Risk/final review lane | Agent config + bootstrap. Uses Qwen3.5-122B (or 35B fallback). | Approval records in `state/approvals/`. Probe confirmed live response. | **LIVE** | Probe results | — |
| 2.5 | Scout recon | v5.1 §4 | Web search via SearXNG | Agent config. SearXNG integration via `searxng_client.py`. | Probe: 10 results for NQ E-mini query. Status file shows live actions. | **LIVE** | Probe results | — |
| 2.6 | Kitt quant specialist | v5.1 §4 | Quant research with Kimi 2.5 | `kitt_quant` in `BACKEND_ADAPTERS`. `kitt_quant_workflow.py` wires SearXNG → Bowser → Kimi → artifact. | Dispatch proven: brief artifact + backend result + agent status + Discord event. | **LIVE** | f026883 | — |
| 2.7 | Bowser browser bridge | v5.1 §26 | Bounded browser automation via PinchTab | `bowser_adapter.py`, PinchTab at `127.0.0.1:9867` | Navigate, snapshot, screenshot, DOM text extraction (4000 char). Status file shows live actions. | **LIVE** | Watchboard §F | — |
| 2.8 | Ralph task runner | v5.1 §20 | Task runner + memory consolidation | `runtime/ralph/agent_loop.py`, `scripts/run_ralph_v1.py` | Full operator-usable loop: claim → HAL → auto-review → approval → completion. CLI: `--status`, `--approve`, `--reject`, `--retry`. Rejected reviews fail cleanly. Stale recovery. Idle clears error state. E2E proven with real task. Systemd timer live (10 min). Gateway health gate has 1-retry backoff. | **LIVE** | f815910 | No memory consolidation. |
| 2.9 | Hermes research daemon | v5.1 §21 | Long-form research, source gathering, synthesis | `hermes_adapter.py` (43KB). `hermes_transport.py` calls LM Studio directly. `hermes_adapter` in `backend_dispatch.py` BACKEND_ADAPTERS + Ralph ELIGIBLE_BACKENDS. | Real execution proven 2026-03-18: task `task_7b4905b3005f` → `bres_7b10e9081a58` (qwen3.5-35b-a3b, 1284 tokens) → artifact `art_bf1920942594` (3342 chars). 6 transport tests + 20 adapter tests pass. | **LIVE** | b70a8b4 | Requires LM Studio running. No external daemon needed — transport calls LM Studio API directly. |
| 2.10 | Muse creative | v5.1 §4 | Creative specialist | Agent config + gateway binding (channel 1483133844663304272). Model: lmstudio/qwen3.5-35b-a3b. Webhook + bot delivery live. | Agent turns via gateway proven (3 turns). Bot delivers replies to #muse Discord channel. Session file created/updated. Event routing + outbox + worklog mirror working. No channel collisions (11 bindings). Config structurally identical to Jarvis (proven Discord ingress). | **LIVE** | 527ede7 | Discord user-message ingress untested (gateway `allowFrom` requires operator to type in #muse). Ralph muse_creative backend path untested under timer. |
| 2.11a | Cadence — wake-word command layer | v5.1 §25 | Wake detection → VAD → STT → command routing → TTS response | Full pipeline in `runtime/voice/`: `cadence_daemon.py` (two-phase loop), `live_listener.py` (OWW + Silero + faster-whisper subprocess), `cadence_ingress.py` (routing), `tts_piper.py`/`tts_coqui_render.py` (TTS), `cues.py`/`feedback.py` (earcons). Daemon active (`cadence-voice-daemon.service`, 596 MB). | Daemon running. Transcript routing proven. TTS proven. Mic blocked: RDPSource unavailable in WSL2. No live end-to-end wake-to-command proof. | **PARTIAL** | Watchboard §7.3 | Mic blocked on WSL2. One-shot command routing works if audio is provided; live mic capture does not. |
| 2.11b | Cadence — PersonaPlex conversation layer | v5.1 §25 | Persistent conversational AI with workspace/context awareness — multi-turn copilot, not one-shot commands | Does not exist. No code, no design, no session state beyond the single-utterance voice session record used by the command layer. | — | **MISSING** | — | Entire layer needs to be designed and built. Requires: persistent conversation memory, live runtime state access, dialogue management, intent distinction (command vs conversation). |
| 2.12 | Flowstate distillation | v5.1 §4 | Ingestion and distillation lane | `runtime/flowstate/` — source_store, distill_store, promotion_store, index_builder. Operator CLI: `scripts/flowstate.py`. State in `state/flowstate_sources/`. | Full ingest→extract→distill lifecycle proven with real input. Source records, extraction artifacts, distillation artifacts stored on disk with provenance. Promotion is explicit (approval-gated, not auto-promoted). 2 sources, 2 distillations in live state. | **LIVE** | This commit | No daemon. No Discord #flowstate channel wiring. No LLM-powered auto-distillation. |

## 3. Task Lifecycle & Execution

| # | Feature | Spec | Expected Behavior | Repo Evidence | Live Evidence | Status | Proof | Gap |
|---|---------|------|-------------------|---------------|---------------|--------|-------|-----|
| 3.1 | Explicit task creation | v5.1 §3 | `task:` trigger, no implicit execution from chat | `task_runtime.py`, `intake.py` | Tasks created via `create_task_from_message()`. Status transitions emit events. | **LIVE** | — | — |
| 3.2 | Task lifecycle events | v5.1 §12 | created → started → progress → completed/failed | `emit_event()` wired to all status transitions in `task_runtime.py` | Events route to Discord with emoji format. Outbox entries for each transition. | **LIVE** | Watchboard §I | — |
| 3.3 | Backend dispatch | v5.2 §2 | Map tasks to legal backends | `backend_dispatch.py` with `BACKEND_ADAPTERS`: nvidia_executor, openai_executor, browser_backend, kitt_quant, hermes_adapter | `dispatch_to_backend()` dispatches to correct adapter. Backend execution request/result records written. | **LIVE** | f026883, b70a8b4, 490e83f | qwen_executor/planner handled by gateway, not Python dispatch |
| 3.4 | Resumable approvals | v5.1 §13 | Checkpoint with approve/reject/rerun/escalate/defer | `approval_store.py` (27KB), `approval_sessions.py` (10KB) | Approval records in `state/approvals/`. Review/approval events emit to Discord. | **LIVE** | 011f733 (Ralph proof) | — |
| 3.5 | Review hierarchy | v5.1 §4 | HAL → Archimedes → Anton | `review_store.py`, `decision_router.py` | Full chain proven: HAL code → Archimedes review → Anton/operator approval. 26 review records. | **LIVE** | bbe7132 | — |
| 3.6 | Task envelopes | v5.1 §11 | Per-task autonomy constraints, allowed apps/sites/paths | TaskEnvelope fields defined in spec | No TaskEnvelope enforcement in live dispatch path. Tasks execute without per-task sandbox constraints. | **DOC-ONLY** | — | Not implemented as runtime enforcement. |
| 3.7 | Autonomy modes | v5.1 §11 | suggest_only, step_mode, bounded_autonomous, supervised_batch | Spec-defined. Ralph uses bounded_autonomous pattern. | Ralph v1 is effectively bounded_autonomous. No formal autonomy mode field on tasks. | **PARTIAL** | — | No formal mode field. Pattern exists but not enforced by contract. |

## 4. Memory & Context

| # | Feature | Spec | Expected Behavior | Repo Evidence | Live Evidence | Status | Proof | Gap |
|---|---------|------|-------------------|---------------|---------------|--------|-------|-----|
| 4.1 | Memory typing | v5.1 §19 | episodic, semantic, procedural with confidence decay | `write_session_memory_entry()` with memory_class, structural_type, confidence_score, confidence_decay_days | Memory entries in `state/memory_entries/`. Dual write paths (episodic + semantic). Retrieval returns ranked entries. | **LIVE** | Watchboard §L | — |
| 4.2 | Memory write points | v5.1 §19 | Task outcomes, review verdicts, approval decisions, routing decisions → memory | Wired in `task_runtime.py`, `review_store.py`, `approval_store.py`, `decision_router.py` | Proven: task complete, review approved, approval approved all write memory entries. Retrieval confirmed. | **LIVE** | Watchboard §L, §M | — |
| 4.3 | Learnings ledger | extension | Durable lessons from failures, rejections, corrections | `learnings_store.py`. JSONL-backed. Writes from failures/rejections/corrections. | Global + per-agent ledgers. `compile_learnings_digest()` injects into context packets. | **LIVE** | d762a98 | — |
| 4.4 | Rolling session summary | v5.1 §7 | Distill older turns into summary for continuity | `rolling_summary` in `source_owned_context_engine.py` | Written to `workspace/vault/session_context/`. Carries across session resets. Noise filtering live (§K). | **LIVE** | Watchboard §K | — |
| 4.5 | Session hygiene / rotation | extension | Auto-rotate oversized sessions before context builds | `session_hygiene.py`, `pre_context_build_hygiene()` | Fires before every context build. Rotates stale main sessions for jarvis/hal/archimedes. | **LIVE** | 671cf15 | — |
| 4.6 | Memory consolidation | v5.1 §20 | Ralph merges redundant memories, identifies stale ones | Spec-defined as Ralph responsibility. Ralph loop exists but doesn't run consolidation. | No memory consolidation runs observed. Ralph bounded loop focuses on task execution. | **DOC-ONLY** | — | Not implemented. |

## 5. Provider & Model Management

| # | Feature | Spec | Expected Behavior | Repo Evidence | Live Evidence | Status | Proof | Gap |
|---|---------|------|-------------------|---------------|---------------|--------|-------|-----|
| 5.1 | Runtime profiles | extension | Named provider/model presets: local_only, hybrid, cloud_fast, cloud_smart, degraded | `runtime_profiles.py`. 5 profiles. `set`/`show`/`list`/`status`/`post` CLI. | `set hybrid` → sync → gateway restart → Jarvis on Kimi 2.5. `show` displays realized vs expected. | **LIVE** | 4240dcf, d864e47 | — |
| 5.2 | Profile ↔ gateway sync | extension | Sync script propagates active profile to openclaw.json | `sync_routing_policy_to_openclaw.py` reads active profile, applies changes, backs up | 5 changes applied when switching hybrid ↔ local_only. Gateway restart picks up new config. | **LIVE** | 369bf6f | — |
| 5.3 | Realized model visibility | extension | Operator sees what model actually ran | `model-snapshot` in gateway session files. `show` reads last realized model per agent. | Jarvis `[ok]` when profile matches, `[stale]` when mismatched. Turn telemetry with profile name. | **LIVE** | d864e47 | — |
| 5.4 | Qwen-first as policy | v5.1 §6, §35 | Qwen default, switchable to Kimi/Claude without code surgery | `local_only` profile uses all Qwen. `hybrid`/`cloud_*` switch to Kimi. Restore is clean. | Switched Jarvis to Kimi 2.5 and back without code changes. Profile switch + sync + restart. | **LIVE** | 4240dcf | — |
| 5.5 | Token/cost budgets | v5.1 §15 | Per-task/cycle token limits, hard-stop auto-pause | `token_budget.py` wired into `execution_contracts.py` (pre-check + post-usage). Ralph `_track_usage()` calls `apply_budget_usage()` after every HAL/Archimedes call. | Global budget created (`budget_f8f98e529db0`), 841 tokens tracked from live proof. Hard-stop blocks task + raises ValueError. | **LIVE** | see commit | Global budget enforced. USD cost tracking wired but local LLMs report $0. |

## 6. Discord & Operator Visibility

| # | Feature | Spec | Expected Behavior | Repo Evidence | Live Evidence | Status | Proof | Gap |
|---|---------|------|-------------------|---------------|---------------|--------|-------|-----|
| 6.1 | Discord webhook delivery | v5.1 §7 | Events → outbox → webhook → Discord channels | `discord_event_router.py`, `discord_outbox_sender.py`. 12 channel→webhook mappings. | All 12 webhooks HTTP 200. 249+ messages delivered. Timer fires every 60s. | **LIVE** | 369bf6f | — |
| 6.2 | Emoji-first message format | extension | Purpose-separated, phone-scannable messages | `_render_status_text()` with `_EMOJI` map, `_clean_detail()`, `_extract_error_summary()` | 28 event kinds rendered with emoji prefix. Internal noise stripped (tab hashes, cycle IDs, exceptions). | **LIVE** | 0f686d4 | — |
| 6.3 | Event routing (owner + worklog + jarvis forward) | extension | Events route to owner channel + mirror to worklog + escalate to jarvis | `agent_channel_map.json` with `worklog_mirror_event_kinds`, `jarvis_forward_event_kinds` | Owner + worklog + jarvis_forward confirmed for browser_result, task_failed, approval_requested. | **LIVE** | Watchboard §D | — |
| 6.4 | Operator cockpit + Discord | v5.2 §5 | Single-command live system view, Discord delivery | `scripts/operator_cockpit.py`. Parallel service health, agent table, blocker detection. `--discord` posts to #jarvis. | Cockpit renders live status. `--discord` posts emoji-formatted cockpit to Discord via event router. Live delivery confirmed. | **LIVE** | cockpit_status event | — |
| 6.5 | Profile status in Discord | extension | Operator sees active profile and model status in Discord | `post_models_status_to_discord()`, `format_discord_status()` | `set` auto-posts `profile_changed` event to #jarvis. `post` sends full model status table. | **LIVE** | dc3330a | — |
| 6.6 | Validate suite | v5.1 §30 | Config, routing, state dirs, schema, security checks | `scripts/validate.py`, `scripts/preflight_lib.py` | 395 checks pass, 0 fail. Covers config, routing, state dirs, backend health, modality contracts. | **LIVE** | — | — |

## 7. Safety, Controls & Governance

| # | Feature | Spec | Expected Behavior | Repo Evidence | Live Evidence | Status | Proof | Gap |
|---|---------|------|-------------------|---------------|---------------|--------|-------|-----|
| 7.1 | Emergency controls | v5.1 §14 | Global kill, per-subsystem breakers, rate governors | `runtime/controls/control_store.py`. `get_effective_control_state()` with emergency_flags. `assert_control_allows()`. | Returns structured state: `effective_status=active, safety_mode=normal`. All flags false (system healthy). Imported by `routing.py`. | **LIVE** | — | Kill switch testing not confirmed as regular practice. |
| 7.2 | Degradation policy | v5.1 §16 | Fallback without security reduction, operator notification | `degradation_policy.py` (25KB). `list_active_degradation_modes()`, `can_fallback()`. | Module integrated into routing. No active degradation modes (system healthy). Operator event emission confirmed. | **LIVE** | — | — |
| 7.3 | Candidate-first promotion | v5.1 §10 | Everything enters as candidate; promotion requires review | `promotion_governance.py`. Artifact states defined. `auto_promote.py` wired into Ralph completion. | Strategy factory uses candidate pipeline. Review/approval gates exist. Auto-promotion fires after task completion (review-only or review+approval path) — creates candidate → promotes → publishes. Idempotent. Manual `promote_output.py` still works. Proven 2026-03-18. | **LIVE** | 6d64953 | — |
| 7.4 | Promotion provenance | v5.1 §17 | Promoted artifacts carry source_task_id, reviewer, model_lane | `provenance_store.py`. `save_routing_provenance()`. RoutingProvenanceRecord. | Routing provenance saved for task routing decisions. Module importable. | **PARTIAL** | — | Not all promoted artifacts carry full provenance chain. |
| 7.5 | Schema versioning | v5.1 §12 | All durable records carry schema_version | `schema_version` field on TaskRecord and other models. | TaskRecord has schema_version parameter. Records in state/ carry versions. | **LIVE** | — | — |
| 7.6 | Live trading restriction | v5.1 §3 | Live trading requires human approval; never auto-executed | RISK_POLICY.md, PROMOTION.md. Approval gate in promotion_governance. | No live trades executed. Paper trading gate requires Discord `#review` emoji. | **LIVE** | — | — |

## 8. External Integrations

| # | Feature | Spec | Expected Behavior | Repo Evidence | Live Evidence | Status | Proof | Gap |
|---|---------|------|-------------------|---------------|---------------|--------|-------|-----|
| 8.1 | SearXNG web search | v5.2 §3 | Pluggable search backend for research | `searxng_client.py`, `search_normalizer.py` | Live at `localhost:8888`. Lane activation: `status=completed, healthy=true`. Used by Scout and Kitt. | **LIVE** | — | — |
| 8.2 | PinchTab browser backend | v5.1 §26 | Browser automation service | `bowser_adapter.py`, PinchTab systemd service | Live at `127.0.0.1:9867`. Navigate, snapshot, screenshot, DOM extraction proven. | **LIVE** | — | — |
| 8.3 | NVIDIA / Kimi K2.5 | v5.1 §6 | Cloud model provider for quant/orchestration | `nvidia_executor.py`. Provider config in `openclaw.json`. | NVIDIA_API_KEY set. Real API calls proven (HTTP 200). Used by Kitt (default) and Jarvis (via profile). | **LIVE** | d864e47 | — |
| 8.4 | LM Studio / Qwen | v5.1 §6 | Local model provider | `openclaw.json` lmstudio provider. 5 models configured. | Live at `100.70.114.34:1234`. 11 models loaded. All local agents use Qwen via LM Studio. | **LIVE** | — | — |
| 8.5 | ShadowBroker OSINT | v5.2 | OSINT sidecar for research | Module referenced. No live service. | External service not present. | **DOC-ONLY** | — | Not implemented or deployed. |
| 8.6 | Autoresearch / Strategy Lab | v5.1 §22 | Bounded experiment loops in sandbox | `autoresearch_adapter.py` importable. Strategy factory pipeline exists. | Strategy factory cron scheduled (Sunday 2AM batch). No autoresearch lab runs confirmed. | **PARTIAL** | — | Adapter exists. Strategy factory active. No lab experiment runs. |
| 8.7 | A2A protocol | v5.2 | Agent-to-agent communication | `a2a_policy.py` importable. Scaffold only. | Agent comms happen via Discord channels / `sessions_send` tool, not A2A protocol. | **DOC-ONLY** | — | Scaffold. Not used in practice. |
| 8.8 | Anthropic / Claude | v5.1 §6 | Cloud provider option | Provider config in `openclaw.json`. `claude-sonnet-4-6` configured. `ModelFamily.CLAUDE` enum exists. | `ANTHROPIC_API_KEY=REPLACE_ME`. No Python-track adapter (`claude_executor.py`) exists — gateway config only. No real API calls possible. | **BLOCKED** | — | User must set real API key. No Python dispatch adapter — only gateway-level config. |
| 8.8b | OpenAI / GPT | v5.1 §6 | Cloud provider option | `openai_executor.py` adapter. `openai_executor` in `BACKEND_ADAPTERS`. Model registry entry `gpt-4.1-mini`. Capability profile `cap_general_gpt`. Provider in `openclaw.json`. `BackendRuntime.OPENAI_EXECUTOR` enum. 26 tests. | Adapter wired, dispatch registered, model+profile registered. Current `OPENAI_API_KEY` returns 401 (unfunded). `gpt` family not in any agent's `allowed_families` — routing never selects it without explicit opt-in. | **WIRED (inactive)** | 490e83f | Requires funded OpenAI API key. ChatGPT subscription does NOT fund API usage. Must add `gpt` to agent `allowed_families` to enable routing. |
| 8.9 | TradingView adapter | v5.2 | Market data integration | `tradingview_adapter.py` (1.6KB) | Not confirmed in active use. | **DOC-ONLY** | — | Adapter exists but unused. |
| 8.10 | Mission control | v5.2 §5 | Gateway mode ops, mission sync | `scripts/mission_control_sync.py` | Scaffold only. | **DOC-ONLY** | — | Not implemented. |

## 9. Strategy Factory & Quant

| # | Feature | Spec | Expected Behavior | Repo Evidence | Live Evidence | Status | Proof | Gap |
|---|---------|------|-------------------|---------------|---------------|--------|-------|-----|
| 9.1 | Strategy factory pipeline | MISSION.md | Data → features → candidates → simulation → gates → scoring → promotion | `workspace/strategy_factory/`. Cron: daily 4AM OHLCV+VIX, Sunday batch. | Pipeline code present. Cron scheduled. OHLCV + VIX data pulls running. | **LIVE** | — | No strategy has reached PF ≥ 1.5 promotion gate yet. |
| 9.2 | Durable task/strategy queues | v5.1 §12 | TASKS.jsonl, STRATEGIES.jsonl, EXPERIMENTS.jsonl | Files exist in workspace root. | TASKS.jsonl exists (0 lines — queue empty/drained). Strategy registry present. | **LIVE** | — | — |
| 9.3 | Strategy diversity | v5.1 §23 | Maintain candidate diversity across type, regime, turnover, drawdown | Spec-defined. Strategy factory scoring includes diversity. | Not confirmed with real promoted strategies (none exist yet). | **PARTIAL** | — | No promoted strategies to verify diversity against. |

## 10. Eval & Regression

| # | Feature | Spec | Expected Behavior | Repo Evidence | Live Evidence | Status | Proof | Gap |
|---|---------|------|-------------------|---------------|---------------|--------|-------|-----|
| 10.1 | Trace store | v5.2 §4 | Durable execution traces for replay | `runtime/evals/trace_store.py`. Ralph records traces via `_record_execution_trace()` after every HAL/Archimedes call. | 35+ traces in `state/run_traces/` (31 browser + 4 Ralph). | **LIVE** | see commit | — |
| 10.2 | Replay runner | v5.2 §4 | Replay traces and compare expected vs actual | `runtime/evals/replay_runner.py` + `scripts/run_regression.py` — operator CLI. | `run_regression.py` scored 4 Ralph traces, detected model drift when expected-model changed. Eval runs saved to `state/eval_runs/`. | **LIVE** | see commit | — |
| 10.3 | Regression scorers | v5.2 §4 | Score output completeness, model match, token efficiency, routing correctness | `runtime/evals/scorers.py` — 4 live scorers replacing stubs. | 4/4 scorers proven: completeness catches truncation, model_match catches drift, token_efficiency flags high usage, routing_correctness checks lane/backend. 15 unit tests pass. | **LIVE** | see commit | Not yet in CI/gate (manual CLI). |
| 10.4 | Layered eval profiles | v5.1 §24 | EvalProfile with vetoes, quality metrics, promotion thresholds | Spec-defined. No EvalProfile implementation found in runtime. | Not implemented as runtime module. Strategy factory has its own eval gates. | **DOC-ONLY** | — | Spec-defined, not runtime-implemented. |

## 11. v5.2 Advanced Features

| # | Feature | Spec | Expected Behavior | Repo Evidence | Live Evidence | Status | Proof | Gap |
|---|---------|------|-------------------|---------------|---------------|--------|-------|-----|
| 11.1 | Compounding skills engine | v5.2 §6 | Skill candidates from failures, eval-gated promotion | `runtime/skills/skill_store.py`. 0 skills registered. | Scaffold. No skills created or promoted. | **DOC-ONLY** | — | Not implemented beyond scaffold. |
| 11.2 | Generative operator UI | v5.2 §7 | Declarative UI from trusted components | Not implemented. | Not present. | **DOC-ONLY** | — | Future feature. |
| 11.3 | Knowledge vault | v5.2 §8 | Markdown/Git searchable knowledge sidecar | Not implemented. | Not present. | **DOC-ONLY** | — | Future feature. |
| 11.4 | Director / night shift | v5.2 §10 | Bounded overnight coordination | Not implemented. | Not present. | **DOC-ONLY** | — | Future feature. |
| 11.5 | Self-optimization lab | v5.2 §11 | EvoSkill-style propose→run→score→keep/revert | Not implemented. | Not present. | **DOC-ONLY** | — | Future feature. |
| 11.6 | Fine-tuning factory | v5.2 §12 | Unsloth/DSPy model adaptation lab | Not implemented. DSPy/Unsloth not installed. | Not present. | **DOC-ONLY** | — | Future feature. |

---

## Summary

### Fully Verified (LIVE) — 40 features

| Area | Count | Features |
|------|-------|----------|
| Control plane | 8 | Discord bindings, context engine, budget guard, tool filtering, allowlists, lane routing, no-silent-switch, capability matrix |
| Agents | 9 | Jarvis, HAL+ACP, Archimedes, Anton, Scout, Kitt, Bowser, Ralph, Hermes |
| Task lifecycle | 5 | Explicit tasks, lifecycle events, backend dispatch, resumable approvals, review hierarchy |
| Memory | 5 | Memory typing, write points, learnings ledger, rolling summary, session hygiene |
| Provider mgmt | 4 | Runtime profiles, profile sync, realized visibility, Qwen-first policy |
| Discord/operator | 6 | Webhook delivery, emoji format, event routing, cockpit, profile status, validate suite |
| Safety | 5 | Emergency controls, degradation policy, candidate-first, schema versioning, live trading restriction |
| Integrations | 4 | SearXNG, PinchTab, NVIDIA/Kimi, LM Studio |
| Strategy | 2 | Factory pipeline, durable queues |

### Partially Verified — 5 features

| # | Feature | What Works | What's Missing |
|---|---------|-----------|----------------|
| 2.11a | Cadence wake-word command layer | Daemon running, pipeline built (OWW + Silero + whisper + Piper), transcript routing + TTS proven | Mic blocked (WSL2 RDPSource). No live end-to-end proof. |
| 3.7 | Autonomy modes | Ralph uses bounded pattern | No formal mode field on tasks |
| 7.4 | Promotion provenance | Module exists, routing provenance saves | Not all artifacts carry full chain |
| 8.6 | Autoresearch | Adapter + strategy factory exist | No lab experiment runs confirmed |
| 9.3 | Strategy diversity | Factory scoring exists | No promoted strategies to verify |

### Wired but Inactive — 1 feature

| Feature | Status | Blocker |
|---------|--------|---------|
| 8.8b OpenAI/GPT provider | Adapter + dispatch + model registry + tests all wired | Requires funded API key (current key returns 401). `gpt` family not in any agent's `allowed_families`. ChatGPT subscription does NOT fund API. |

### Still Blocked — 2 features

| Feature | Blocker |
|---------|---------|
| 8.8 Anthropic/Claude provider | `ANTHROPIC_API_KEY=REPLACE_ME`. No Python-track adapter exists (gateway config only). |
| 2.11b Cadence PersonaPlex conversation layer | Does not exist. Entire persistent conversational AI / copilot layer needs to be designed and built. Current Cadence is one-shot command routing only. |

### DOC-ONLY (spec-defined, not runtime-implemented) — 9 features

1.8 Multi-node burst, 3.6 Task envelopes, 4.6 Memory consolidation, 8.5 ShadowBroker, 8.7 A2A protocol, 8.9 TradingView, 8.10 Mission control, 10.4 Layered eval profiles, 11.1–11.6 v5.2 advanced features (skills engine, generative UI, knowledge vault, director, self-optimization, fine-tuning).
