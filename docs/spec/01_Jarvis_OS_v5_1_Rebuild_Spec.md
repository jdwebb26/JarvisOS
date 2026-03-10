# Jarvis OS v5.1 Rebuild Spec
## Rules-only implementation spec

## 1. Purpose
Jarvis OS v5.1 is a tightening release on top of the locked v5.0 build.

It does **not** reopen the core doctrine of v5.0.
It formalizes subsystem boundaries, candidate promotion, resumability, emergency controls, provenance, replayable evaluation, memory discipline, and scoped multimodal control so Jarvis can grow into a unified operator OS without drifting back into a loose swarm.

This document is the rules document only.
Rationale, external comparison, and tradeoffs belong in the Design Notes.
Sequencing belongs in the Roadmap.

## 2. North star
### 2.1 Product north star
Jarvis OS exists to convert **explicit operator intent** into **trustworthy, reviewable, high-leverage outputs** with minimal hidden state, minimal accidental autonomy, and strong support for NQ / quant / Strategy Factory work.

### 2.2 Primary measurable north star
Primary optimization target:
- **time from explicit task creation to reviewed/promoted useful artifact**

### 2.3 Guardrail metrics
The system must also track:
- false-promotion rate
- demotion/revocation rate
- memory-pollution rate
- operator-intervention-per-completed-task
- overnight Ralph useful-output-per-token and useful-output-per-dollar
- approval-latency distribution
- replay-to-eval conversion count for important failures

## 3. Core thesis
Jarvis remains the only primary public face and control plane.

Hermes becomes the research daemon.
autoresearch becomes the lab daemon.
Ralph becomes both a task runner and a memory-consolidation engine.
Voice is a first-class front door.
Browser automation is a first-class bounded action layer.

All backend work enters the system as candidates, not truth.
Promotion requires policy, review, and where appropriate evaluation evidence.

## 4. Non-negotiable inherited v5 rules
1. Conversation is not execution.
2. Task creation is explicit.
3. Chat state is not system state.
4. Long-form source material is distilled once.
5. Risky outputs require review.
6. Deployment must catch obvious failures before runtime.
7. Jarvis remains the primary operator-facing identity.
8. No silent model-family switching outside declared policy.

## 5. Initial v5.1 release scope
### 5.1 In-scope
The initial v5.1 release ships:
- explicit backend abstraction
- candidate-first promotion
- demotion and revocation paths
- schema versioning rules
- token and cost budget framework
- emergency-control primitives
- resumable approvals
- dependency blocking model
- Hermes integration contract
- autoresearch Strategy Lab contract
- Ralph memory consolidation pass
- layered evaluation profiles
- replay-to-eval workflow
- memory typing and memory decay policy
- skills portability policy
- skills vs plugins distinction
- A2A-aware daemon interfaces
- MCP policy with authorization/conformance gate
- security hardening additions
- RunTrace with OTel-aware naming
- promotion provenance metadata
- Qwen3.5 routing refresh
- trajectory collection policy
- notification adapter interface
- operator profile support
- V1 dictation
- V2 conversational voice
- C2 bounded browser automation

### 5.2 Deferred to v5.2 unless explicitly pulled forward later
- phone/SIP bridge
- general desktop automation
- supervised copilot mode
- full A2A adoption
- full OTel backend rollout
- MCP Apps / UI-native agent surfaces
- full cryptographic artifact attestation
- graph database adoption
- new orchestration frameworks
- Discord voice bot support beyond roadmap planning

## 6. Control plane, subsystems, and front doors
### 6.1 Control plane
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

### 6.2 Subsystems
- Hermes research daemon
- autoresearch lab daemon
- Flowstate distillation lane
- Archimedes code-review lane
- Anton risk / final-review lane
- voice subsystem
- browser automation subsystem
- notification subsystem

### 6.3 Front doors
- Discord text
- dashboard / web
- CLI
- voice session

All front doors must normalize into the same task, event, approval, review, artifact, and memory contracts.

## 7. De-v4-ification mandate
The implementation must continue removing v4-style swarm assumptions that conflict with the locked v5 direction.

Must phase out or isolate:
- implicit tiered swarm dispatch as the main control model
- persistent always-on persona sprawl where a service boundary would be clearer
- direct memory writes from arbitrary agent chains
- hidden reinject loops not reflected in structured task/event state
- chat-driven state inference
- direct execution from casual conversation
- setup/runtime language that still frames the system as a generic swarm

Preferred replacements:
- explicit service boundaries
- event-driven state transitions
- backend assignment records
- candidate artifact promotion
- resumable approvals
- policy-visible retries and reruns
- explicit subsystem adapters
- versioned schemas
- trace-driven regression loops

## 8. Skills, plugins, and tool interface policy
### 8.1 Skills portability
Reusable Jarvis skills and Hermes skills should follow the Agent Skills open standard where practical, using a `SKILL.md` manifest plus optional scripts and resources.

Rules:
- reusable skills should prefer the Agent Skills folder layout
- skills imported from external sources are disabled by default until approved
- skills must declare required tools, permissions, and expected side effects
- skill metadata must be specific enough for reliable discovery

### 8.2 Plugins
Plugins are installable bundles that may package multiple skills, tools, hooks, prompts, and permissions.

Rules:
- plugin installation requires explicit operator approval
- plugin activation must pass the same security and permission checks as tools
- plugins must declare contained skills, tools, and permissions
- plugins are policy-scoped, versioned, and reversible

### 8.3 MCP policy
MCP is the preferred standard interface for new external tool integrations unless a subsystem-specific exception is explicitly documented.

Rules:
- prefer MCP-compatible integrations where practical
- only adopt MCP SDKs/servers that meet the project’s conformance and authorization bar
- if MCP is deferred for a specific integration, the reason must be recorded in design notes
- non-MCP adapters must still expose capability declaration, structured errors, cancellation behavior, progress events, and audit visibility
- MCP-connected tools that access restricted resources must follow secure authorization practice and least privilege

### 8.4 A2A-aware daemon interfaces
Jarvis-to-Hermes and future daemon interfaces should be A2A-aware even if Jarvis does not formally adopt the full A2A protocol in v5.1.

Adapter requests and results must be able to express:
- capability_declaration
- task card or equivalent task metadata
- status callback or equivalent status contract
- timeout behavior
- cancellation behavior
- structured status transitions
- extension fields for future interoperability

## 9. Core doctrine additions
### 9.1 Candidate-first promotion
Candidate-first promotion is the first rule of v5.1.

Everything from Hermes, autoresearch, Flowstate, voice extraction, browser automation, and memory consolidation enters the system as a candidate unless policy explicitly states otherwise.

Nothing becomes truth merely because it exists.

### 9.2 Promotion states
Outputs move through these states when applicable:
- working
- candidate
- promoted
- demoted
- archived

### 9.3 Demotion and revocation
The system must support reversal, not only promotion.

Required actions:
- demote promoted artifact
- revoke promoted memory entry
- mark research claim superseded
- mark downstream artifacts as impacted by a superseded upstream source
- prevent superseded artifacts from being treated as active truth

### 9.4 Freedom with bounded execution
Jarvis should not feel overly constrained to the operator.
The system should constrain execution surfaces, not conversation quality.

This means:
- natural language requests stay broad and flexible
- execution is scoped by task envelopes, sandbox class, backend policy, and review requirements
- bounded autonomous mode is allowed inside declared boundaries
- step mode and suggest-only mode remain available at all times

## 10. Task envelopes, autonomy modes, and dependency blocking
### 10.1 TaskEnvelope
Every non-trivial task may carry a `TaskEnvelope`.

Fields:
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
- benchmark_slice_ref (optional)

### 10.2 Autonomy modes
Each task or session may run in one of these modes:
- suggest_only
- step_mode
- bounded_autonomous
- supervised_batch

Mode choice must be operator-visible.

### 10.3 Dependency blocking model
The system must define behavior for downstream tasks when upstream tasks await review or approval.

Rules:
- tasks that require approved upstream artifacts enter `blocked_dependency`
- speculative precompute is allowed only when policy marks the downstream step as `candidate_only`
- no downstream task may consume an unapproved upstream candidate as promoted truth
- blocked tasks must expose the specific upstream task/artifact causing the block
- approval walls must be explicit in status summaries and autonomy digests

## 11. EmergencyControl primitives
Emergency controls must live **outside** the agent reasoning path and must not require agent cooperation.

### 11.1 Global kill switch
The global kill switch halts all execution-bearing task steps and new backend launches.

Requirements:
- externally enforced
- operator-visible
- phone-friendly access path
- checked before every task step and autonomy cycle
- regularly testable

### 11.2 Subsystem circuit breakers
Per-subsystem breakers may independently disable:
- Hermes
- autoresearch
- Ralph
- voice
- browser automation
- notification dispatch

### 11.3 Rate governor
Budget hard-stop thresholds must auto-pause, not merely alert.

### 11.4 Control states
- enabled
- paused
- hard_stopped
- degraded
- maintenance

## 12. Schema versioning and record defaults
### 12.1 Versioning rule
All core records must carry `schema_version`.

### 12.2 Forward-compatibility rule
New fields introduced in later versions must default to `null` or a declared safe default so older records remain valid.

### 12.3 Migration rule
Old records remain readable under the new schema contract unless explicitly marked unsupported by a later migration note.

## 13. Core records
### 13.1 TaskRecord
Fields:
- task_id
- schema_version
- operator_id
- title
- objective
- task_type
- status
- priority
- risk
- execution_backend
- autonomy_mode
- task_envelope_ref
- parent_task_id
- dependency_refs
- review_policy_ref
- approval_policy_ref
- budget_ref
- eval_profile_ref
- created_at
- updated_at

### 13.2 TaskEvent
Fields:
- event_id
- schema_version
- task_id
- event_type
- status_before
- status_after
- backend_name
- summary
- blocker_ref
- run_trace_ref
- created_at

### 13.3 ArtifactRecord
Fields:
- artifact_id
- schema_version
- task_id
- artifact_type
- lifecycle_state
- source_backend
- source_run_id
- provenance_ref
- eval_refs
- review_refs
- superseded_by
- created_at
- updated_at

### 13.4 ReviewVerdict
Fields:
- verdict_id
- schema_version
- task_id
- reviewer
- findings
- required_changes
- optional_suggestions
- decision
- created_at

### 13.5 ApprovalRecord
Fields:
- approval_id
- schema_version
- task_id
- operator_id
- approval_type
- status
- requested_action
- timeout_at
- checkpoint_ref
- created_at
- updated_at

### 13.6 TokenBudget
Fields:
- budget_id
- scope
- max_tokens_per_task
- max_tokens_per_cycle
- max_cost_usd_per_cycle
- current_usage
- alert_threshold
- hard_stop_threshold
- auto_pause_on_hard_stop

### 13.7 DegradationPolicy
Fields:
- policy_id
- subsystem
- degradation_mode
- fallback_action
- requires_operator_notification
- auto_recover
- retry_policy

### 13.8 RunTrace
Fields:
- run_id
- task_id
- backend_name
- model_lane
- provider_name
- tool_calls
- handoffs
- artifacts_created
- reviews_triggered
- approvals_requested
- failure_summary
- timestamps
- retention_class
- query_tags
- token_usage
- cost_usage

RunTrace fields should align with OpenTelemetry GenAI semantic conventions where practical.
Run traces must be queryable by `task_id`, `backend_name`, `status`, and time range.

### 13.9 PromotionProvenance
Fields:
- provenance_id
- source_task_id
- source_backend
- source_run_id
- model_lane
- input_refs
- eval_refs
- review_refs
- promoter_id
- promoted_at
- attestation_ready_metadata

### 13.10 CandidateArtifact
Fields:
- candidate_id
- parent_task_id
- artifact_type
- source_backend
- baseline_reference
- eval_reference
- review_required
- promotion_status

## 14. Hermes adapter records
### 14.1 HermesTaskRequest
Fields:
- task_id
- objective
- sandbox_class
- allowed_tools
- capability_declaration
- model_override_policy
- timeout_seconds
- max_tokens
- return_format
- status_callback_url_or_contract

### 14.2 HermesTaskResult
Fields:
- task_id
- run_id
- status
- artifacts
- checkpoint_summary
- citations
- proposed_next_actions
- token_usage
- error_summary

## 15. Lab adapter records
### 15.1 LabRunRequest
Fields:
- task_id
- target_module
- program_md_path
- eval_command
- baseline_ref
- benchmark_slice_ref
- budget_minutes
- sandbox_root

### 15.2 LabRunResult
Fields:
- task_id
- run_id
- candidate_patch_path
- baseline_metrics
- candidate_metrics
- delta_metrics
- experiment_log_path
- recommendation
- token_usage

## 16. Evaluation records
### 16.1 EvalProfile
Fields:
- profile_id
- schema_version
- task_type
- eval_command
- veto_checks
- quality_metrics
- promotion_thresholds
- hard_fail_conditions
- reproducibility_requirements

Eval profiles must separate hard vetoes from scored quality judgments.
Examples:
- leakage failure: veto
- schema mismatch: veto
- weak OOS improvement: quality metric
- research clarity: quality metric

### 16.2 EvalOutcome
Fields:
- eval_id
- task_id
- profile_id
- veto_results
- quality_scores
- pass_fail
- notes

Pass/fail must be derived from veto outcomes plus declared promotion thresholds rather than used as the only signal.

## 17. Memory doctrine
### 17.1 Content classes
Memory classes:
- operator_preference
- decision
- artifact
- research_claim
- risk

### 17.2 Structural memory types
Every memory entry must also carry one structural type:
- episodic
- semantic
- procedural

Retrieval should be type-aware where practical:
- episodic retrieval may prefer time and run context
- semantic retrieval may prefer similarity and source grounding
- procedural retrieval may prefer task pattern and applicability conditions

### 17.3 MemoryEntry
Fields:
- memory_id
- schema_version
- content_class
- structural_type
- source_artifact_ref
- source_task_ref
- summary
- confidence_score
- confidence_decay_days
- last_retrieved_at
- contradiction_check
- superseded_by
- review_state
- approved_by
- created_at
- updated_at

### 17.4 Memory matrix
Every memory class must define:
- allowed writers
- allowed readers
- whether approval is required
- whether contradiction checks apply
- whether decay applies
- whether demotion/revocation is allowed

### 17.5 Compression gate
Every promoted memory must be materially more compressed than its source and must encode a:
- claim
- preference
- decision
- procedure

Raw records, raw transcripts, and raw daemon chatter must not be promoted as memory by default.

### 17.6 Decay and contradiction
Rules:
- memories that are never retrieved may decay in confidence over time
- memories contradicted by newer promoted artifacts must be flagged for review or demotion
- raw transcripts should not be promoted when a higher-value distilled memory exists
- consolidation should merge redundant low-value memories into stronger promoted summaries

## 18. Ralph loop refinement
The Ralph loop is not just a task runner.
It is also the system’s memory-consolidation engine during autonomy windows.

### 18.1 Ralph consolidation pass
During approved autonomy windows, after progressing queued work, Ralph may run a memory consolidation pass that:
- rewrites checkpoint summaries into tighter learned context
- pre-digests Flowstate artifacts likely to matter in future queries
- merges redundant research notes into compressed dossiers
- updates Strategy Lab baseline summaries and experiment digests
- identifies stale, contradictory, or low-value memories for review or decay

Ralph consolidation outputs are candidate memories or candidate artifacts until promoted by policy.

## 19. Review, approval, resumability, and model overrides
### 19.1 Resumable approvals
Any step awaiting approval or review must write a resumable checkpoint.
A later approval, rejection, rerun, or escalate action must resume from structured saved state rather than rebuilding context from chat history.

### 19.2 Reviewer outages
If a reviewer subsystem is unavailable, review-required outputs must not auto-promote.
A policy-visible degraded state must be emitted.

### 19.3 Model override exception path
Jarvis remains Qwen-first.
If a task class genuinely requires a model override, the system must record:
- who requested the override
- why the override is needed
- which component is affected
- what approval was granted
- when the override expires

No silent override is permitted.

## 20. Hermes integration rules
Hermes working memory may be used for Hermes-local continuity, but any memory promoted back into Jarvis must go through Jarvis candidate and promotion policy.

Hermes may:
- perform long-form research
- gather and rank sources
- run delegated synthesis
- maintain bounded research continuity
- produce candidate plans, research notes, summaries, and digests

Hermes may not:
- become the authoritative task store
- promote artifacts directly
- write permanent Jarvis memory directly without policy approval
- bypass Jarvis approvals
- silently change model family policy

Hermes adapter behavior must be explicit:
- Hermes requests use `HermesTaskRequest`
- Hermes responses use `HermesTaskResult`
- timeout, retry, and unreachable-backend behavior must follow `DegradationPolicy`
- Hermes completion must be reflected as structured task events rather than inferred from chat or logs
- Hermes browser/terminal capabilities must map to sandbox classes by policy

## 21. Strategy Lab and autoresearch rules
### 21.1 General rules
autoresearch integration must preserve the fixed-budget experiment pattern by default.
Standard lab runs should use a short default budget unless a later policy explicitly defines a multi-round sequence.

Lab control behavior must be explicit:
- Jarvis starts a run with `LabRunRequest`
- the lab backend returns `LabRunResult`
- completion, failure, and recommendation must be recorded as structured task events

autoresearch may not:
- modify the production repo directly
- touch live trading code paths
- alter review/approval logic
- alter split integrity or leakage-guard code without explicit elevated review
- become a public chat-facing agent

### 21.2 Strategy Lab goals
- improve feature transforms
- improve ranking and scoring logic
- improve diagnostics and stress evaluation helpers
- tune objective functions within declared bounds
- produce reproducible candidate results suitable for review

### 21.3 Program files
Every lab run must reference a program file that defines:
- objective
- constraints
- forbidden edits
- success metrics
- failure vetoes
- dataset or benchmark assumptions
- expected output format

### 21.4 Required outputs
Every lab run must write:
- run_config.json
- baseline_metrics.json
- candidate_metrics.json
- delta_metrics.json
- candidate.patch
- experiment_log.md
- recommendation.json

### 21.5 Diversity map
Strategy Lab should maintain a candidate diversity map across behavioral dimensions such as:
- strategy type
- regime sensitivity
- turnover characteristics
- drawdown profile
- holding-pattern / trade-frequency profile

Promotion decisions should consider both metric improvement and behavioral diversity relative to existing promoted strategies.

## 22. Qwen policy and model routing
### 22.1 Qwen-first policy
Jarvis remains Qwen-first.
Qwen3.5 is the default multimodal family for routing, reasoning, Flowstate, screenshot interpretation, and image-aware task support.
Qwen3-Coder-Next is the preferred coding lane.

### 22.2 Initial v5.1 routing table
- routing / classification: Qwen3.5-9B
- general worker: Qwen3.5-35B-A3B
- Anton / heavy review / tool-heavy reasoning: Qwen3.5-122B-A10B
- coder lane: Qwen3-Coder-Next
- Flowstate distill / image-aware summarization: Qwen3.5-35B-A3B

### 22.3 Tool-calling compatibility
Tool-calling backends must be validated against Qwen3.5 parser requirements before production use.
Hermes-Qwen integration must be explicitly compatibility-tested.

## 23. Voice subsystem
### 23.1 Scope
Initial v5.1 scope includes:
- V1 dictation
- V2 conversational voice

Phone calling is deferred.

### 23.2 VoiceSession
Fields:
- voice_session_id
- channel_type
- caller_identity
- transcript_ref
- active_task_id
- barge_in_supported
- escalation_state
- consent_state
- lifecycle_state

Lifecycle states:
- initializing
- active
- paused
- summarizing
- closed

### 23.3 Voice rules
- speech transcripts are not system state by themselves
- explicit task confirmation is still required for task creation
- every voice session must persist transcript and event summaries
- every important voice action must have a text summary fallback
- approvals must be readable and answerable with simple phone-safe responses later

### 23.4 Voice eval split
Voice evaluation must distinguish:
- STT fidelity
- intent accuracy
- interruption handling
- response quality
- TTS clarity
- end-to-end task extraction success

## 24. Browser automation subsystem
### 24.1 Scope
Initial v5.1 scope includes bounded browser automation only.
Desktop-wide automation is deferred.

### 24.2 Browser run rules
- all browser actions must run under a sandbox class or allowlist
- sensitive actions require explicit confirmation
- every execution run must create a RunTrace
- screenshots before and after major actions should be captured when practical
- the operator must be able to interrupt or cancel at any time
- browser control should prefer explicit browser automation and tool APIs over blind clicking where possible

### 24.3 Browser eval split
Browser evaluation must distinguish:
- navigation success
- task completion
- recovery from page changes or errors
- sensitive-action confirmation compliance
- trace/screenshot completeness

## 25. Notification subsystem and operator profiles
### 25.1 Notification adapter interface
v5.1 must define a notification adapter interface so approvals and alerts can later route to multiple surfaces without rewriting approval logic.

Minimum supported concept fields:
- notification_type
- audience
- channel
- priority
- requires_acknowledgement
- task_or_approval_ref

### 25.2 Operator profiles
v5.1 remains effectively single-operator in practice, but must be structurally multi-operator-ready.

At minimum:
- `operator_id` must exist on task creation
- `operator_id` must exist on approvals
- notification and control actions must record the acting operator

## 26. Trajectory collection policy
Trajectory collection is allowed for future fine-tuning and evaluation work, but must be deliberate.

Rules:
- collect trajectories only from approved execution surfaces
- trajectories must be linkable to task ID, backend, and outcome class
- unsafe or privacy-sensitive traces must be redactable before export
- trajectory collection must not weaken memory or promotion policy

## 27. Observability and replay-to-eval
### 27.1 OTel-aware naming
RunTrace fields should align with OpenTelemetry GenAI semantic conventions where practical to enable future export to standard observability backends.

### 27.2 Replay-to-eval
Any important failure may be promoted into a replayable regression case.

Required loop:
1. capture trace
2. replay failure in sandbox
3. turn replay into an eval case or regression fixture
4. prevent silent recurrence in CI or validation flows where practical

## 28. Security and trustworthiness validation
### 28.1 Security hardening additions
- all local gateways must bind to localhost by default unless the operator explicitly opts into remote exposure
- any remote exposure must produce a prominent warning and explicit acknowledgement
- skills and tools from external sources require explicit approval before installation or activation
- auto-discovery from untrusted repositories is disabled by default
- subsystem OAuth and API tokens should be scoped to the minimum practical permissions
- tokens should have explicit expiry where supported

### 28.2 Trustworthiness validation layer
Validation should include checks for:
- prompt injection / indirect injection handling where applicable
- unsafe tool output handling
- exfiltration risk in external-content processing paths
- unsafe fallback or degradation behavior
- MCP server authorization posture
- memory-pollution risk and uncompressed memory writes
- browser automation handling of sensitive actions

## 29. Deployment and validate.py expectations
validate.py and doctor.py should explicitly check:
- current Qwen model names resolve
- configured endpoints are reachable
- emergency controls are available
- Discord permission splits are handled where relevant
- gateway bind posture is safe
- budgets and degradation policies exist
- approval/review-required paths cannot auto-promote during outages

## 30. Status semantics
Jarvis should always be able to answer:
- what is running
- what backend is running it
- what the system is waiting on
- what review gate is blocking promotion
- what changed since the last checkpoint
- what can be safely approved right now
- whether any subsystem is degraded or circuit-broken

This status contract must be available in text, dashboard, and voice-safe form.

## 31. Acceptance gates
### 31.1 Structural gates
- every execution-bearing task carries backend metadata
- candidate-first promotion is enforced everywhere
- all core records are versioned
- kill switch and circuit breakers are externally enforceable

### 31.2 Hermes gates
- Hermes cannot become system-of-record
- Hermes outputs land as candidates
- Hermes timeouts and failures create structured events
- Hermes uses approved Qwen endpoints and passes compatibility tests

### 31.3 Strategy Lab gates
- no direct production writes
- baseline refs are explicit
- benchmark slice refs are explicit
- evals include veto checks and quality metrics
- diversity map is populated for promoted strategies

### 31.4 Memory gates
- promoted memories pass the compression/type gate
- Ralph consolidation produces candidates, not direct truth
- contradiction and decay fields exist
- retrieval remains artifact-linked and reversible

### 31.5 Voice/browser gates
- voice cannot silently create risky work
- browser actions are scoped by task envelope
- sensitive actions require confirmation
- traces and screenshots exist for major runs

### 31.6 Hardening gates
- validate.py catches config, model, permission, and gateway issues
- doctor.py reports degradation, budgets, and controls
- emergency controls are testable
- replay-to-eval can create at least one permanent regression case

## 32. Explicit non-goals
- replacing Jarvis with Hermes as product identity
- making autoresearch a general public-facing bot
- letting casual voice chat silently create risky work
- allowing daemon outputs to bypass review
- weakening live trading restrictions
- reopening already locked v5.0 doctrine without a concrete operational reason
- adopting new orchestration frameworks for their own sake
