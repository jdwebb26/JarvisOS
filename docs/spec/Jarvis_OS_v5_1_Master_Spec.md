# Jarvis OS v5.1 Master Spec
## Clean full build/spec handoff

## 1. Purpose
Jarvis OS v5.1 is a tightening release built on the locked v5 foundation.

It does not reopen the core doctrine of v5.
It turns that doctrine into a cleaner, more buildable, more future-proof system by formalizing:
- provider-agnostic model routing
- candidate-first promotion
- demotion and revocation
- resumable approvals
- emergency controls
- provenance and replayability
- memory discipline
- subsystem contracts
- bounded multimodal control

This document is the single clean master spec.
It is meant to be handed to Codex, Claude, Qwen, or a future build agent.

---

## 2. North star
### 2.1 Product north star
Jarvis OS exists to convert **explicit operator intent** into **trustworthy, reviewable, high-leverage outputs** with minimal hidden state, minimal wasted context, and strong support for NQ / quant / Strategy Factory work.

### 2.2 Primary measurable north star
- **Time from explicit task creation to reviewed/promoted useful artifact**

### 2.3 Guardrails
The system should also track:
- false-promotion rate
- demotion / revocation rate
- memory-pollution rate
- operator intervention per completed task
- overnight Ralph useful-output-per-token
- overnight Ralph useful-output-per-dollar
- approval latency distribution
- replay-to-eval conversion count

---

## 3. Non-negotiable inherited v5 rules
These stay locked:
1. Conversation is not execution.
2. Task creation is explicit.
3. Chat state is not system state.
4. Long-form source material should be distilled once.
5. Risky outputs require review.
6. Deployment must catch obvious failures before runtime.
7. Jarvis remains the single public face and operator-facing identity.
8. Live trading remains highly restricted.
9. No silent model-family switching outside declared policy.

---

## 4. Core thesis
Jarvis remains the only primary public face and control plane.

Subsystem roles:
- **Hermes** = research daemon
- **autoresearch** = lab daemon
- **Ralph** = task runner + memory-consolidation engine
- **Archimedes** = code-review lane
- **Anton** = risk/final-review lane
- **Flowstate** = ingestion and distillation lane
- **voice** = first-class front door
- **browser automation** = first-class bounded action layer

All backend work enters the system as **candidate output**, not truth.
Promotion requires policy, review, and where appropriate evaluation evidence.

---

## 5. Release scope
### 5.1 In scope for initial v5.1
- provider-agnostic lane-based model routing
- Qwen-first as policy, not hardcoded architecture
- candidate-first promotion lifecycle
- demotion and revocation paths
- schema versioning rules
- token and cost budget framework
- prompt caching optimization policy
- emergency-control primitives
- resumable approvals
- dependency blocking rules
- Hermes adapter contract
- autoresearch Strategy Lab contract
- Ralph memory consolidation pass
- layered evaluation profiles
- replay-to-eval workflow
- memory typing + memory decay / contradiction policy
- skills portability policy
- skills vs plugins distinction
- A2A-aware daemon interfaces
- MCP policy with authorization/conformance gate
- security hardening additions
- RunTrace with OTel-aware naming
- promotion provenance / attestation-ready metadata
- status/heartbeat semantics
- Qwen routing refresh
- trajectory collection policy
- operator profile skeleton
- V1 dictation
- V2 conversational voice
- C2 bounded browser automation
- bootstrap / validation / smoke-test updates

### 5.2 Deferred to v5.2 unless explicitly pulled forward
- phone / SIP bridge
- general desktop automation
- supervised copilot mode
- full A2A adoption
- full OTel backend rollout
- MCP Apps / UI-native agent surfaces
- full cryptographic artifact attestation
- graph database adoption
- new orchestration frameworks
- Discord voice bot support beyond roadmap planning

---

## 6. Provider policy and model routing
### 6.1 Core rule
The architecture is **provider-agnostic**.
The default deployment policy is **Qwen-first**.

### 6.2 What that means
- Runtime code references **lanes**, not model names.
- Families are selected by policy/configuration.
- Switching from Qwen to Kimi, DeepSeek, or another family is a **config/policy change**, not a code rewrite.
- No silent cross-family fallback.

### 6.3 Lane model
Initial lanes:
- routing
n- general
- heavy_reasoning
- coder
- flowstate
- multimodal

### 6.4 Routing policy
The router must support:
- multiple families present in config
- `default_family`
- allowed family list
- optional `lane_overrides`
- temporary runtime overrides with expiry
- audit logging of overrides

Override scopes:
- global override
- lane-scoped override
- future session/task-scoped overrides may be added later

### 6.5 Capability matrix
Each model spec should declare capabilities rather than assuming interchangeability.
Recommended fields:
- family
- model_name
- provider
- supports_tool_calling
- supports_vision
- supports_structured_output
- supports_reasoning_mode
- max_context
- local_vs_hosted
- cost_class

### 6.6 Default Qwen-first routing direction
Default policy direction:
- routing/classification: `Qwen3.5-9B`
- general/multimodal worker: `Qwen3.5-35B-A3B`
- heavy reasoning / Anton / tool-heavy review: `Qwen3.5-122B-A10B`
- code lane: `Qwen3-Coder-Next`
- Flowstate distill / image-aware summarization: `Qwen3.5-35B-A3B`

### 6.7 Override rule
Family swaps must be:
- explicit
- logged
- scoped
- expiring where appropriate
- reversible

No silent fallback outside declared allowed families.

---

## 7. Control plane, subsystems, and front doors
### 7.1 Control plane
Jarvis core is the authoritative control plane and system of record.

Core services:
- gateway
- core
- auditor
- reporter
- review spine
- approval spine
- event spine
- artifact spine
- memory spine
- evaluation spine
- control spine

### 7.2 Subsystems
- Hermes research daemon
- autoresearch lab daemon
- Flowstate distillation lane
- Archimedes code-review lane
- Anton risk/final-review lane
- Ralph loop
- voice subsystem
- browser automation subsystem
- notification subsystem

### 7.3 Front doors
- Discord text
- dashboard / web
- CLI
- voice session

All front doors normalize into the same task/event/artifact/review/approval/memory contracts.

---

## 8. De-v4-ification mandate
The implementation must continue removing v4-style swarm assumptions.

Must phase out or isolate:
- implicit tiered swarm dispatch as main control model
- persistent persona sprawl where services would be clearer
- direct memory writes from arbitrary chains
- hidden reinject loops not reflected in durable state
- chat-driven state inference
- direct execution from casual conversation
- runtime/setup language still framing the system as a generic swarm

Preferred replacements:
- explicit service boundaries
- event-driven state transitions
- backend assignment records
- candidate-first promotion
- resumable approvals
- policy-visible retries/reruns
- versioned schemas
- trace-driven regression loops

---

## 9. Skills, plugins, MCP, and A2A
### 9.1 Skills portability
Reusable Jarvis skills and Hermes skills should follow the Agent Skills open standard where practical, using `SKILL.md` plus optional scripts/resources.

Rules:
- reusable skills should prefer the Agent Skills folder layout
- imported skills are disabled by default until approved
- skills must declare tools, permissions, and expected side effects

### 9.2 Plugins
Plugins are installable bundles that may package multiple skills, tools, hooks, prompts, and permissions.

Rules:
- plugin installation requires explicit operator approval
- plugin activation must pass the same security/permission checks as tools
- plugins must declare contained skills, tools, and permissions
- plugins are reversible and policy-scoped

### 9.3 MCP policy
MCP is the preferred standard interface for new external tool integrations where practical.

Rules:
- adopt MCP only when authorization and conformance standards are met
- do not install random MCP servers without review
- non-MCP adapters must still expose capability declaration, structured errors, cancellation behavior, progress events, and audit visibility

### 9.4 A2A-aware daemon interfaces
Jarvis-to-Hermes and future daemon interfaces should be A2A-aware even if Jarvis does not formally adopt full A2A in v5.1.

Interfaces should support:
- capability declaration
- task metadata
- status callback or equivalent contract
- timeout behavior
- cancellation behavior
- structured status transitions
- extension fields for future interoperability

---

## 10. Candidate-first promotion, demotion, and revocation
### 10.1 Rule
Candidate-first promotion is the first rule of v5.1.

Everything from Hermes, autoresearch, Flowstate, voice extraction, browser automation, and memory consolidation enters the system as a **candidate** unless policy explicitly states otherwise.

Nothing becomes truth merely because it exists.

### 10.2 Artifact states
Outputs move through these states when applicable:
- working
- candidate
- promoted
- demoted
- archived
- superseded

### 10.3 Demotion / revocation
The system must support:
- demote promoted artifact
- revoke promoted memory entry
- mark research claim superseded
- mark downstream artifacts as impacted by upstream revocation
- prevent superseded outputs from being treated as active truth

---

## 11. Task envelopes, autonomy modes, and dependency blocking
### 11.1 TaskEnvelope
Every non-trivial task may carry a `TaskEnvelope`.

Suggested fields:
- allowed_apps
- allowed_sites
- allowed_paths
- blocked_apps
- blocked_sites
- blocked_paths
- max_runtime_minutes
- max_cost_budget
- max_tool_calls
- requires_checkpoints
- requires_confirmation_for
- forbidden_actions
- rollback_strategy
- benchmark_slice_ref

### 11.2 Autonomy modes
Each task or session may run in one of these modes:
- suggest_only
- step_mode
- bounded_autonomous
- supervised_batch

Mode choice must be operator-visible.

### 11.3 Dependency blocking
Rules:
- if a parent task is blocked on approval, dependent tasks enter blocked state unless explicitly marked speculative
- speculative downstream work may proceed only in candidate state
- no blocked approval wall may be bypassed by implicit execution
- blocked reason must be operator-visible
- downstream promoted artifacts may not bypass upstream approval requirements

---

## 12. Durable records and schema versioning
All execution-bearing durable records must carry an explicit `schema_version`.

### 12.1 Required durable records
At minimum:
- TaskRecord
- ArtifactRecord
- TaskEvent
- ApprovalRecord
- ReviewVerdict
- BackendAssignment
- PromotionProvenance / PromotionAttestation
- HermesTaskRequest
- HermesTaskResult
- LabRunRequest
- LabRunResult
- TokenBudget
- EmergencyControlState
- DegradationPolicy
- RunTrace
- HeartbeatReport
- EvalProfile
- EvalOutcome
- MemoryEntry
- VoiceSession
- BrowserControlAllowlist
- optional TrajectoryRecord

### 12.2 Schema versioning rule
- New fields added in later versions must default to `null` or a declared safe default.
- Records created under older schema versions remain valid under newer schemas unless explicitly migrated.
- Validation must fail loudly if a required record type has no declared schema version.

---

## 13. Resumable approvals
Any step awaiting approval or review must write a resumable checkpoint.

Approval results:
- approve
- reject
- rerun
- escalate
- defer

Phone-safe / voice-safe responses should exist for simple approvals:
- yes/no
- approve/reject
- option numbers
- rerun

Rules:
- approval decisions resume from saved structured state, not reconstructed chat context
- approval walls must be visible in status reports
- approval latency must be measurable

---

## 14. EmergencyControl and kill behavior
This is mandatory.

### 14.1 Three layers
1. **global kill switch**
2. **per-subsystem circuit breakers**
3. **rate governors / auto-pause**

### 14.2 Core rules
- kill switch must live outside model reasoning
- kill switch must not require agent cooperation
- hard-stop budget thresholds must auto-pause, not just alert
- kill/circuit state must be checked before every meaningful task step
- kill-switch tests should run regularly

### 14.3 In-flight behavior
When a global kill or subsystem breaker fires:
- in-flight tasks must checkpoint current state if possible
- in-flight tasks enter `killed` or `paused_by_control` status
- they do **not** resume automatically when the kill switch is lifted
- operator must explicitly re-queue or resume them

### 14.4 Subsystem breakers
Must independently disable at least:
- Hermes
- autoresearch
- Ralph
- browser automation
- voice execution if needed

---

## 15. Token/cost budgets and prompt caching
### 15.1 TokenBudget
Fields:
- scope
- max_tokens_per_task
- max_tokens_per_cycle
- max_cost_usd_per_cycle
- current_usage
- alert_threshold
- hard_stop_threshold

### 15.2 Hard-stop rule
When hard stop hits:
- auto-pause
- emit operator-visible event
- do not silently continue

### 15.3 Prompt caching policy
Where providers support prompt caching, the system should structure prompts to maximize cache hit rates.

Rules:
- stable prompt prefixes should be separated from variable content
- system prompts, review templates, and Strategy Lab program files should be structured for reuse
- cost optimization is a policy concern, not an afterthought

---

## 16. Degradation policy
`DegradationPolicy` fields:
- subsystem
- degradation_mode
- fallback_action
- requires_operator_notification
- auto_recover
- retry_policy

Rules:
- if Hermes is unavailable, local fallback only if policy allows
- if reviewer/auditor unavailable, review-required outputs must not auto-promote
- fallback must not silently reduce security posture
- every degradation event becomes an operator-visible event

Concrete timeout rule example:
- if Hermes times out, the task enters failed or timed_out status with explicit error category
- retry follows DegradationPolicy
- local fallback is permitted only if policy says so

---

## 17. Provenance / attestation-ready promotion
Every promoted artifact must carry provenance metadata.

Required fields:
- source_task_id
- source_backend
- model_lane
- input_refs
- eval_refs
- reviewer
- promoter
- promoted_at
- build_or_run_ref

V5.1 does not require full cryptographic attestations, but the schema should be attestation-ready.

No promoted artifact without lineage.

---

## 18. RunTrace, heartbeat, and replay-to-eval
### 18.1 RunTrace
Suggested fields:
- run_id
- task_id
- backend_name
- model_lane
- tool_calls
- handoffs
- artifacts_created
- reviews_triggered
- approvals_requested
- failure_summary
- timestamps
- retention_class
- query_tags

RunTrace naming should align with OpenTelemetry GenAI semantic conventions where practical.

### 18.2 HeartbeatReport
Every subsystem should emit a common heartbeat shape.

Suggested fields:
- subsystem_name
- status (`healthy`, `degraded`, `stopped`, `unreachable`)
- last_active_at
- current_task_count
- error_summary
- budget_remaining

### 18.3 Replay-to-eval
Important failures should not just become lore.

Rules:
- traces from significant failures may be promoted into replay cases
- replay cases may become permanent eval/regression cases
- this applies especially to Hermes failures, browser-control failures, voice failures, autoresearch false positives, and promotion mistakes

---

## 19. Memory doctrine
Memory must be selective, artifact-linked, reversible where practical, and promotion-gated.

### 19.1 Memory content classes
- operator_preference_memory
- decision_memory
- artifact_memory
- research_claim_memory
- risk_memory

### 19.2 Structural memory types
Cross-tag each entry with:
- episodic
- semantic
- procedural

Retrieval guidance:
- episodic: prefer time / run context
- semantic: prefer similarity / grounding
- procedural: prefer task pattern / applicability

### 19.3 Required memory fields
- memory_id
- memory_class
- structural_type
- source_refs
- approval_requirement
- confidence_score
- confidence_decay_days
- last_retrieved_at
- contradiction_check
- superseded_by
- review_state

### 19.4 Memory rules
- store insights, not transcripts
- raw transcripts and daemon chatter do not promote by default
- every promoted memory must encode a claim, preference, decision, or procedure
- memory must be materially more compressed than its source
- memories never retrieved may decay
- memories contradicted by newer promoted artifacts should be flagged for review/demotion
- periodic consolidation should merge redundant low-value memories into stronger summaries

---

## 20. Ralph loop
Ralph is not just a task runner.
Ralph is also the system’s memory-consolidation engine during autonomy windows.

Ralph may:
- progress queued work within policy
- rewrite checkpoint summaries into tighter learned context
- pre-digest Flowstate artifacts
- merge redundant research notes into compressed dossiers
- update Strategy Lab baseline summaries
- identify stale/contradictory memories for review

Ralph outputs are candidates until promoted by policy.

---

## 21. Hermes integration contract
Hermes is the research daemon, not the product identity.

Hermes may:
- perform long-form research
- gather/rank sources
- run delegated synthesis
- maintain bounded research continuity
- produce candidate plans, research notes, summaries, digests

Hermes may not:
- become the authoritative task store
- promote artifacts directly
- write permanent Jarvis memory directly without approval
- bypass Jarvis approvals
- silently change model-family policy

Hermes working memory may exist for Hermes-local continuity, but promoted memory must re-enter Jarvis through candidate/promotion rules.

### 21.1 HermesTaskRequest
Suggested fields:
- task_id
- objective
- sandbox_class
- allowed_tools
- model_override_policy
- timeout_seconds
- max_tokens
- return_format
- capability_declaration
- status_callback_url or callback contract

### 21.2 HermesTaskResult
Suggested fields:
- task_id
- run_id
- status
- artifacts
- checkpoint_summary
- citations
- proposed_next_actions
- token_usage
- error_summary

Hermes adapter must be tested against the chosen family’s tool-calling/parser requirements rather than assumed generic.

---

## 22. autoresearch / Strategy Lab contract
autoresearch is the lab daemon, not a public chat bot.

It may:
- run bounded experiment loops
- edit allowlisted files in sandbox
- compare candidate results vs baseline
- emit candidate patches, experiment logs, metric deltas

It may not:
- modify production repo directly
- touch live trading paths
- alter review/approval logic
- become a public chat-facing agent
- bypass Strategy Lab policy

### 22.1 LabRunRequest
Suggested fields:
- task_id
- target_module
- program_md_path
- eval_command
- baseline_ref
- benchmark_slice_ref
- budget_minutes
- sandbox_root

### 22.2 LabRunResult
Suggested fields:
- task_id
- run_id
- candidate_patch_path
- baseline_metrics
- candidate_metrics
- delta_metrics
- experiment_log_path
- recommendation
- token_usage

### 22.3 Standard run outputs
- run_config.json
- baseline_metrics.json
- candidate_metrics.json
- delta_metrics.json
- candidate.patch
- experiment_log.md
- recommendation.json

---

## 23. Strategy Lab diversity and protected zones
Strategy Lab should not optimize only for one metric.
It should maintain a candidate diversity map across behavioral dimensions such as:
- strategy type
- regime sensitivity
- turnover characteristics
- drawdown profile
- style niche

Promotion should consider:
- metric quality
- hard vetoes
- behavioral diversity relative to existing promoted strategies

Protected zones:
- fold generation / split integrity
- leakage guards
- live execution paths
- promotion logic
- authoritative dataset builders

---

## 24. Layered evals
Evals should be layered, not binary.

### 24.1 EvalProfile
Suggested fields:
- profile_id
- task_type
- eval_command
- veto_checks
- quality_metrics
- hard_fail_conditions
- reproducibility_requirements
- promotion_thresholds
- schema_version

### 24.2 EvalOutcome
Suggested fields:
- eval_id
- task_id
- profile_id
- veto_results
- quality_scores
- pass_fail
- metrics
- notes

### 24.3 Eval rules
- hard vetoes immediately reject
- quality metrics inform promotion
- pass/fail is derived, not the only signal
- if no eval exists, task must explicitly declare `review_only`, `no_eval_required_by_policy`, or `operator_defined_eval_pending`
- eval profiles should be versioned independently and changes should be operator/policy controlled for promoted task types

---

## 25. Voice subsystem
Voice is a first-class ingress/egress lane, not a hidden parallel system.

### 25.1 Initial v5.1 scope
- V1 dictation
- V2 conversational voice

Deferred:
- phone / SIP
- advanced autonomous voice tasking unless explicit task confirmation is preserved

### 25.2 VoiceSession
Suggested fields:
- voice_session_id
- channel_type
- caller_identity
- transcript_ref
- active_task_id
- barge_in_supported
- escalation_state
- consent_state

### 25.3 Voice rules
- transcripts are not system state by themselves
- important voice actions still require explicit confirmation where needed
- every voice session persists transcript + summary artifacts
- fallback text summary should exist for important sessions
- approvals must be answerable by simple voice-safe responses

Voice evals should consider:
- STT quality
- intent extraction
- interruption handling
- response usefulness
- TTS clarity where applicable

---

## 26. Browser automation / computer control
Computer control is not chat. It is an action subsystem.

### 26.1 Initial v5.1 scope
- C2 bounded browser automation
- light suggest-only behavior may exist

Deferred:
- full desktop automation
- full operator copilot

### 26.2 Computer control rules
- all actions must run under sandbox/allowlist rules
- sensitive actions require explicit confirmation
- every run must create RunTrace
- screenshots before/after major actions when practical
- operator can interrupt/cancel
- prefer browser automation or explicit tool APIs over blind clicking

### 26.3 BrowserControlAllowlist
Suggested fields:
- allowed_apps
- allowed_sites
- allowed_paths
- blocked_apps
- blocked_sites
- blocked_paths
- destructive_actions_require_confirmation
- secret_entry_requires_manual_control

---

## 27. Security / trustworthiness validation
Add a named validation layer for:
- prompt injection / indirect injection
- unsafe tool output handling
- excessive agency
- exfiltration paths
- insecure degradation/fallback behavior
- MCP server auth posture
- malicious skill/plugin install behavior
- memory pollution risks

Security additions:
- local gateways bind localhost by default
- remote exposure requires explicit opt-in and clear warning
- external skills/tools require explicit approval before activation
- tokens should be least-privilege and expiring where possible

---

## 28. Status semantics
Jarvis should always be able to answer:
- what is running
- what backend is running it
- what is blocked and why
- what is waiting on approval
- what was finished recently
- what changed since the last checkpoint
- what can be safely approved now
- what the recommended next move is

Every subsystem should report in this shape:
- local core
- Hermes
- autoresearch
- Ralph
- browser automation
- voice
- review/auditor lanes

---

## 29. Trajectory collection and operator profiles
### 29.1 Trajectory collection
Jarvis may preserve structured trajectories for later tuning/analysis when policy allows.

Suggested fields:
- prompt class
- task type
- backend
- tools used
- outcome quality
- review result
- replay/eval linkage

No raw sensitive collection by default.
Trajectory collection remains policy-controlled.

### 29.2 Operator profiles
V5.1 only needs a minimal structure.

Suggested fields:
- operator_id
- notification_preference_refs
- approval_surface_preference
- verbosity_style
- escalation_rules_ref

---

## 30. Bootstrap, validation, and smoke testing
V5.1 extends the v5 bootstrap and validation doctrine.

Expected operator flow:
1. install / sync repo
2. generate or review config
3. validate
4. smoke test
5. doctor / status check
6. start services

`validate.py` should eventually check at minimum:
- config presence and parsing
- model routing and lane resolution
- expected state directories
- emergency control state accessibility
- schema version availability
- Hermes adapter reachability when enabled
- autoresearch sandbox writability when enabled
- voice STT/TTS endpoint availability when enabled
- browser automation backend health when enabled
- current Discord permission requirements when relevant
- basic security posture reminders

`smoke_test.py` should verify the foundation slice, including:
- schema instantiation/serialization
- candidate lifecycle
- memory typing and decay
- token budget thresholds
- eval profile structure
- routing resolves lanes
- override flow (Qwen -> Kimi -> revert)
- emergency control lifecycle

---

## 31. On-disk artifact and state expectations
Promoted and candidate artifacts must be distinguishable in durable state and on disk or in metadata indexing.

Recommended baseline:
- `state/artifacts/<task_id>/...`
- artifact metadata must include promotion state, provenance, and revocation/supersession metadata
- candidates must not be confused with promoted outputs in dashboards or APIs

---

## 32. Implementation priorities
### P0
- provider-agnostic lane router
- schema versioning
- execution_backend on TaskRecord/core records
- candidate-first promotion lifecycle
- consistent status semantics
- north star section in docs and reporting

### P1
- Hermes adapter contract
- token/cost budgets
- resumable approvals
- EmergencyControl
- promotion provenance
- degradation policies
- de-v4 cleanup boundaries
- heartbeat contract

### P2
- autoresearch Strategy Lab adapter
- sandbox enforcement
- eval lifecycle hardening
- Ralph memory consolidation
- memory typing/decay
- voice V1/V2

### P3
- bounded browser automation polish
- replay-to-eval hardening
- OTel export later
- deferred v5.2 planning

---

## 33. Build order
Recommended build order:
1. foundation layer: core models, routing, emergency control, validate, smoke test
2. task/event persistence with lifecycle enforcement
3. status reporter and heartbeat plumbing
4. Hermes adapter and candidate promotion path
5. resumable approvals
6. Strategy Lab/autoresearch adapter
7. Ralph consolidation
8. voice V1/V2
9. bounded browser automation

Each slice should be independently testable.
Do not do a giant rewrite.

---

## 34. Non-goals
Do not do these in v5.1:
- replace Jarvis with Hermes
- make autoresearch a public bot
- adopt a new orchestration framework
- add graph DBs
- add Letta/MemGPT as infra
- weaken live trading restrictions
- let casual voice chat silently create risky work
- adopt full A2A or marketplace behavior prematurely

---

## 35. Final build rule
Build with the Qwen stack now.
Future-proof by keeping Qwen-first as a **policy**, not an architectural assumption.

Jarvis should be able to run Qwen by default, switch a lane or family to Kimi for a day, and revert cleanly without code surgery.

That is the correct v5.1 shape.
