# JarvisOS 5.2 Master Spec (Repo-Aligned)

## Purpose

This document defines the **repo-aligned** 5.2 direction for JarvisOS.

It is intentionally written as a **migration and extension of the current JarvisOS repo**, not as a greenfield rewrite.

The goal is to make JarvisOS 5.2:

- multi-model
- policy-routed
- approval-aware
- evidence-backed
- mixed-hardware aware
- resilient to optional burst-worker loss
- operator-visible
- regression-gated
- compatible with the current repo structure

---

## Repo alignment rules

5.2 must preserve the current JarvisOS spine.

That means:

- keep the existing runtime structure
- extend live seams first
- avoid inventing parallel systems when a current file already owns the responsibility
- treat the current Qwen-default/Qwen-first runtime posture as a **5.1-era policy** to be migrated, not as a permanent architectural law

### Current spine to preserve

JarvisOS today is organized around:

- durable task state
- explicit task creation
- approval-aware execution
- artifact-first review
- provenance tracking
- validation-first deployment
- dashboard/operator visibility
- operator script entrypoints

### Existing seams to extend first

#### Core
- `runtime/core/models.py`
- `runtime/core/backend_assignments.py`
- `runtime/core/decision_router.py`
- `runtime/core/degradation_policy.py`
- `runtime/core/heartbeat_reports.py`
- `runtime/core/provenance_store.py`
- `runtime/core/approval_store.py`
- `runtime/core/artifact_store.py`
- `runtime/core/output_store.py`
- `runtime/core/promotion_governance.py`

#### Dashboard
- `runtime/dashboard/operator_snapshot.py`
- `runtime/dashboard/state_export.py`
- `runtime/dashboard/heartbeat_report.py`
- `runtime/dashboard/task_board.py`
- `runtime/dashboard/output_board.py`
- `runtime/dashboard/event_board.py`

#### Integrations
- `runtime/integrations/hermes_adapter.py`
- `runtime/integrations/autoresearch_adapter.py`

#### Evals
- `runtime/evals/trace_store.py`

#### Memory / research
- `runtime/memory/governance.py`
- `runtime/researchlab/runner.py`

#### Scripts
- `scripts/bootstrap.py`
- `scripts/validate.py`
- `scripts/smoke_test.py`
- `scripts/doctor.py`
- `scripts/operator_handoff_pack.py`
- `scripts/overnight_operator_run.py`
- `scripts/preflight_lib.py`

---

## Core 5.2 definition

JarvisOS 5.2 is:

> an approval-aware, policy-routed, multi-model operating system with an always-on durable primary node, optional burst workers, evidence-backed research, regression-gated skills, stronger operator visibility, and bounded self-improvement.

This is **not**:

- a greenfield multi-agent rewrite
- a replacement of the current dashboard with a third-party control plane
- a replacement of runtime truth with markdown notes
- uncontrolled autonomous self-rewriting
- a dependency on Koolkidclub being online

---

## 5.2 design invariants

These are non-negotiable.

1. Conversation is not execution.
2. `task:` remains the explicit task trigger.
3. Task state remains durable and visible.
4. Review and approval cannot be silently bypassed.
5. Model routing is explicit, logged, and policy-bound.
6. No silent downgrade for review-required or promotion-required work.
7. Validation-first deployment remains mandatory.
8. Research must produce evidence bundles, not just prose.
9. Burst workers may accelerate work but may not own irreplaceable state.
10. Self-improvement must be replayable and eval-gated.
11. Generated UI must remain declarative and trusted-component based.

---

## Cross-cutting infrastructure hardening requirements

These are not separate replacement packages. They are hardening requirements that sharpen the existing 5.2 packages.

### Persistent semantic memory and bounded recall
OpenClaw already documents semantic memory search over `MEMORY.md` and `memory/*.md`, including vector memory search and memory indexing/search commands. 5.2 should explicitly preserve a local-first, bounded, attributable memory model rather than relying on giant prompt replay. This requirement strengthens:
- Private Research + Evidence Package
- Compounding Skills Engine
- Knowledge OS / Intelligence Vault

### Automatic model routing and cost-aware dispatch
OpenClaw community and docs around ClawRouter show a strong pattern: analyze requests locally, route to the cheapest capable model, and avoid manual model switching. 5.2 should adopt that pattern natively inside `backend_assignments.py` and `decision_router.py`, but under Jarvis policy and approval constraints. This requirement strengthens:
- Mixed-Accelerator Multi-Model Runtime
- Persistent Core + Elastic Burst Runtime
- Eval Harness + Regression Gates

### Backup, restore, and safe-update discipline
OpenClaw’s migration and doctor docs emphasize backing up state/workspace before migrations, using doctor as a repair + migration tool, and validating config/state before committing changes. 5.2 should treat backup/recovery as a first-class operational requirement, not an afterthought. This requirement strengthens:
- Operator Cockpit / Mission Control Layer
- scripts/bootstrap.py
- scripts/doctor.py
- scripts/operator_handoff_pack.py

### Provider hygiene and API key resilience
OpenClaw’s provider docs already support API key rotation and multiple key sources for selected providers. 5.2 should make provider/key health visible in backend health, routing, and doctor outputs so model routing does not collapse into hidden config failures. This requirement strengthens:
- Mixed-Accelerator Multi-Model Runtime
- scripts/doctor.py
- runtime/core/backend_assignments.py

### Security-by-default posture
OpenClaw’s recent security guidance emphasizes the gateway as a critical boundary, including sandboxing controls, skills/tools/memory boundaries, and hardening against prompt-injection and exposed services. 5.2 should explicitly preserve a security-first posture: no silent authority widening, no hidden unsafe fallback, and operator-visible degraded modes. This requirement strengthens:
- runtime/core/degradation_policy.py
- runtime/core/promotion_governance.py
- runtime/dashboard/event_board.py

## 5.2 package split

## Must ship in 5.2

### 1) Persistent Core + Elastic Burst Runtime
NIMO is the durable primary node.
Koolkidclub is an opportunistic burst worker.

Responsibilities:
- node registration
- worker heartbeat
- leased burst work
- reroute on worker loss
- node-aware scheduler behavior
- operator-visible reroute events

### 2) Mixed-Accelerator Multi-Model Runtime
Replace the Qwen-only active deployment rule with a policy-routed multi-model layer.

Responsibilities:
- model registry
- routing policy
- backend assignment
- node/runtime/model selection
- latency/context/authority-aware dispatch
- legal fallback behavior

### 3) Private Research + Evidence Package
Make research durable and inspectable.

Responsibilities:
- research backend abstraction
- search backend integration
- normalized result schema
- evidence bundles
- provenance linkage
- backend health and degradation signaling

### 4) Eval Harness + Regression Gates
Make routing, fallback, and evidence behavior measurable.

Responsibilities:
- replayable traces
- routing regression tests
- downgrade regression tests
- reroute regression tests
- evidence completeness checks
- validation gate integration

### 5) Operator Cockpit / Mission Control Layer
Upgrade the current dashboard into a true operator control surface.

Responsibilities:
- node health visibility
- routing visibility
- degraded state visibility
- evidence visibility
- blocked review visibility
- event stream visibility

### 6) Compounding Skills Engine
Let Jarvis learn durable procedures without bypassing governance.

Responsibilities:
- skill candidates
- approved skills
- recurring skill execution
- bounded subagent scheduling
- memory-assisted reuse
- eval-gated promotion
- failure-driven skill discovery
- frontier tracking for top-performing variants
- prompt-plus-skill program versioning
- keep-or-revert improvement loops

---

## Strong 5.2 additions

### 7) Generative Operator Interfaces
Declarative operator cards/forms/panels built from trusted components.

### 8) Knowledge OS / Intelligence Vault
Markdown/Git/Obsidian-style knowledge sidecar for approved exports, briefs, syntheses, and searchable memory.

### 9) Specialist Persona Packs
Structured worker role cards with allowed tools, deliverables, and escalation rules.

### 10) Director Crew Builder / Night Shift Manager
Bounded overnight coordination with temporary crews and morning digests.

### 11) Self-Optimization Lab
Replay-gated propose → run → score → keep/revert loops.

EvoSkill should be treated as a direct pattern source here:
- treat an agent configuration as a versioned program
- use failures to propose targeted changes
- generate new skill files or prompt variants
- evaluate on held-out validation data
- keep only top-performing variants in a bounded frontier
- require Jarvis eval gates before promotion into approved runtime use

### 12) Fine-Tuning Factory / Model Adaptation Lab
A practical lab for narrow adapters and model candidates, never auto-promoted into runtime.

---

## Later / sidecar / lab

- Degraded Local Survival Lane
- Low-VRAM Inference Lane
- Shadow Model Evaluation Lane
- NVIDIA Performance Lab
- World-State Ops Map
- Live Event Market Reactor
- Hybrid MoE Inference Lab

---

## Runtime model

The runtime loop should remain:

1. user conversation or operator action occurs
2. explicit task is created or recognized
3. task is classified
4. policy determines what models/backends are legal
5. router chooses node + backend + model
6. if routed to burst worker, task is leased
7. task executes
8. outputs/artifacts/provenance are written
9. dashboard and operator surfaces update
10. review/eval/publish logic proceeds

This is an extension of the current Jarvis spine, not a replacement.

---

## File-by-file ownership model

## `runtime/core/models.py`

### Purpose
The shared vocabulary for runtime state.

### Add
Enums:
- `ModelFamily`
- `ModelTier`
- `BackendRuntime`
- `NodeRole`
- `NodeStatus`
- `TaskClass`
- `AuthorityClass`
- `RoutingReason`
- `DegradationMode`

Records:
- `ModelProfile`
- `BackendProfile`
- `NodeProfile`
- `RoutingDecision`
- `EvidenceBundleRef`
- `TaskLeaseRecord`

### How it works
All routing, dashboard, doctor, validate, provenance, and skill code should import these shapes.
This avoids drift and duplicate local schemas.

---

## `runtime/core/backend_assignments.py`

### Purpose
The legal-assignment rule table.

### Add functions
- `load_model_policy(...)`
- `get_allowed_models_for_task(...)`
- `get_min_tier_for_authority(...)`
- `get_fallback_chain(...)`
- `is_shadow_eligible(...)`
- `is_route_allowed(...)`
- `assert_no_forbidden_downgrade(...)`

### How it works
This file answers:
- which model families are allowed
- what minimum tier is required
- which node roles are preferred
- whether fallback is legal
- whether shadow routing is legal

This file defines legality, not final choice.

---

## `runtime/core/decision_router.py`

### Purpose
The final explainable chooser.

### Add functions
- `route_task(...)`
- `collect_candidate_routes(...)`
- `score_candidate_route(...)`
- `select_best_route(...)`
- `persist_routing_decision(...)`
- `explain_routing_decision(...)`

### How it works
1. receive task + task class + authority class
2. ask `backend_assignments.py` what is legal
3. check node health, backend health, queue depth, latency, context, degraded state
4. score candidates
5. choose the best legal route
6. persist a routing decision record
7. hand off to executor path

This file answers “what got chosen, and why.”

---

## `runtime/core/degradation_policy.py`

### Purpose
Single source of truth for degraded behavior.

### Add functions
- `load_degradation_policies(...)`
- `get_active_degradation_modes(...)`
- `can_fallback(...)`
- `record_degradation_event(...)`
- `should_notify_operator(...)`
- `get_retry_policy(...)`
- `is_authority_downgrade_forbidden(...)`

### Add degradation modes
- `BURST_WORKER_OFFLINE`
- `RESEARCH_BACKEND_DOWN`
- `NVIDIA_LANE_DOWN`
- `AMD_LANE_DOWN`
- `FALLBACK_SUMMARY_ONLY`

### How it works
When a node/backend fails, router does not improvise.
It asks degradation policy:
- what fallback is legal
- whether operator notification is required
- whether authority class forbids downgrade
- whether retry should happen

This preserves the current approval-aware safety posture while making fallback explicit.

---

## `runtime/core/heartbeat_reports.py`

### Purpose
Live node/worker liveness seam.

### Add functions
- `write_heartbeat(...)`
- `read_heartbeat(...)`
- `heartbeat_is_stale(...)`
- `summarize_node_health(...)`
- `list_online_nodes()`

### How it works
Heartbeats should carry:
- node id
- node role
- last seen
- queue depth
- loaded models
- loaded backends
- hardware summary
- runtime health summary

Router and dashboard both use this.
If heartbeat goes stale, degradation + lease logic take over.

---

## `runtime/core/task_lease.py` (new)

### Purpose
Safe leasing for burst-worker tasks.

### Add functions
- `create_lease(...)`
- `renew_lease(...)`
- `expire_stale_leases(...)`
- `requeue_expired_lease(...)`
- `get_active_lease(...)`

### How it works
Every task sent to Koolkidclub gets a lease.
Koolkidclub refreshes while working.
If it disappears, the lease expires and task is rerouted.

This makes burst workers acceleration-only, not critical-path.

---

## `runtime/core/node_registry.py` (new)

### Purpose
Durable node metadata.

### Add functions
- `register_node(...)`
- `get_node(...)`
- `list_nodes()`
- `update_node_status(...)`
- `get_node_capabilities(...)`

### How it works
Heartbeat is live pulse.
Node registry is durable node identity/capability state.

---

## `runtime/core/provenance_store.py`

### Purpose
Home for evidence bundles and research provenance.

### Add functions
- `write_evidence_bundle(...)`
- `read_evidence_bundle(...)`
- `attach_evidence_to_artifact(...)`
- `get_artifact_evidence(...)`
- `summarize_provenance_for_output(...)`

### How it works
Research backends produce normalized results.
Those become evidence bundles.
Artifacts/outputs point to those bundles.
Dashboard and review can inspect provenance directly.

---

## `runtime/integrations/hermes_adapter.py`

### Purpose
Bounded Hermes-style long-form agent adapter.

This adapter should also be able to feed failure cases into the EvoSkill-style improvement loop instead of only emitting prose or ad hoc suggestions.

### Add functions
- `run_research_task(...)`
- `get_research_backend(...)`
- `build_evidence_bundle(...)`
- `create_skill_candidate_from_failure(...)`

### How it works
Hermes-style capabilities are allowed to:
- research
- synthesize
- propose skill candidates
- use shared research backend abstraction

They are not allowed to bypass:
- routing policy
- provenance
- review
- approval

---

## `runtime/integrations/autoresearch_adapter.py`

### Purpose
Bounded research worker.

### Add functions
- `run_autoresearch_experiment(...)`
- `normalize_sources(...)`
- `persist_experiment_trace(...)`
- `publish_research_artifact(...)`

### How it works
Runs research tasks through normalized backends.
Publishes evidence-backed artifacts.
Feeds evals and provenance, not a private disconnected pipeline.

---

## `runtime/integrations/research_backends.py` (new)

### Purpose
Backend abstraction for research/search/doc retrieval.

### Add
- `ResearchBackend` protocol
- `get_backend(...)`
- `list_backends()`
- `healthcheck_backend(...)`

### How it works
Hermes/autoresearch ask this file for a backend.
Backend health becomes visible to router, doctor, and dashboard.

---

## `runtime/integrations/searxng_client.py` (new)

### Purpose
Concrete SearXNG backend implementation.

### Add functions
- `search(...)`
- `healthcheck()`

### How it works
One backend implementation for private metasearch.
Returns raw results.
Normalization happens downstream.

---

## `runtime/integrations/search_normalizer.py` (new)

### Purpose
Uniform result schema.

### Add functions
- `normalize_search_results(...)`
- `dedupe_results(...)`
- `build_source_records(...)`

### How it works
This makes search provenance consistent regardless of backend.
Provenance/evals/dashboard do not need provider-specific logic.

---

## `runtime/evals/trace_store.py`

### Purpose
Durable trace store.

### Add functions
- `write_trace(...)`
- `load_trace(...)`
- `list_traces(...)`

### How it works
Router runs, research runs, skill runs, and fallback events emit traces.
Replay and regression suites use them later.

---

## `runtime/evals/replay_runner.py` (new)

### Purpose
Replay traces through new router/policy behavior.

This file should also support replaying skill-candidate and prompt-variant experiments so the EvoSkill-style loop can be measured on saved failure cases, not just live guesses.

### Add functions
- `replay_trace(...)`
- `replay_router_decision(...)`
- `compare_expected_vs_actual(...)`

### How it works
Saved traces are re-run against updated policy/router code.
Differences are measured before shipping changes.

---

## `runtime/evals/scorers.py` (new)

### Purpose
Turn replay into pass/fail signals.

This file should support frontier-style ranking of candidate variants, not only binary pass/fail, so Jarvis can keep a bounded top-N set of strong skill/prompt variants while still requiring explicit approval before production promotion.

### Add functions
- `score_routing_correctness(...)`
- `score_no_silent_downgrade(...)`
- `score_evidence_completeness(...)`
- `score_reroute_behavior(...)`

### How it works
These scorers protect 5.2 from turning into vibes.
`validate.py` should use them to fail bad migrations.

---

## `runtime/dashboard/operator_snapshot.py`

### Purpose
Human-readable system summary.

### Add functions
- `build_operator_snapshot()`
- `summarize_nodes()`
- `summarize_active_degradations()`
- `summarize_recent_reroutes()`
- `summarize_blocked_reviews()`

### How it works
This should answer:
- which nodes are online
- which routes/models are active
- what degraded modes are active
- what is blocked in review
- what got rerouted recently

---

## `runtime/dashboard/state_export.py`

### Purpose
Machine-readable state export.

### Add functions
- `export_routing_state()`
- `export_node_state()`
- `export_backend_health()`
- `export_evidence_state()`
- `export_review_state()`

### How it works
Dashboard, handoff pack, and tools consume the same exported state.
No separate ad hoc status formats.

---

## `runtime/dashboard/heartbeat_report.py`

### Purpose
Node/worker health panel.

### Add functions
- `build_heartbeat_report()`
- `summarize_backend_latency()`
- `summarize_loaded_models()`

### How it works
Lets operator instantly see whether Koolkidclub is really usable.

---

## `runtime/dashboard/task_board.py`

### Purpose
Task-level operator board.

### Add functions
- `attach_routing_metadata(...)`
- `attach_evidence_flags(...)`

### How it works
Each task row should show:
- assigned node
- assigned model
- authority class
- degraded marker
- evidence marker

---

## `runtime/dashboard/output_board.py`

### Purpose
Output-level operator board.

### Add functions
- `attach_producer_metadata(...)`
- `attach_provenance_status(...)`

### How it works
Each output should show:
- producing model/backend
- degraded-mode marker
- evidence/provenance marker

---

## `runtime/dashboard/event_board.py`

### Purpose
System event stream.

### Add helpers
- `emit_routing_event(...)`
- `emit_reroute_event(...)`
- `emit_backend_degraded_event(...)`
- `emit_worker_offline_event(...)`

### How it works
One place to watch routing changes, backend failures, reroutes, and fallback activity.

---

## `scripts/bootstrap.py`

### Purpose
Initialize the 5.2 runtime environment.

### Add functions
- `bootstrap_model_registry(...)`
- `bootstrap_node_registry(...)`
- `bootstrap_backend_health(...)`
- `bootstrap_research_backends(...)`

### How it works
Before runtime starts:
- load policy
- load models
- seed state dirs
- probe backends
- register nodes

---

## `scripts/validate.py`

### Purpose
Hard gate for policy and routing changes.

### Add functions
- `validate_model_policy(...)`
- `validate_no_forbidden_downgrades(...)`
- `validate_required_state_dirs(...)`
- `run_regression_suites(...)`

### How it works
Multi-model routing does not ship unless:
- policy is coherent
- forbidden downgrades are blocked
- regression suites pass

---

## `scripts/smoke_test.py`

### Purpose
Quick sanity tests for runtime basics.

### Add functions
- `smoke_route_safe_task(...)`
- `smoke_burst_worker_loss(...)`
- `smoke_evidence_bundle_write(...)`
- `smoke_forbidden_downgrade_block(...)`

### How it works
Fast checks that the new routing/evidence/lease behavior works at all.

---

## `scripts/doctor.py`

### Purpose
Explain why a lane or backend is unavailable.

### Add functions
- `doctor_nodes(...)`
- `doctor_backends(...)`
- `doctor_policy_consistency(...)`
- `doctor_research_backends(...)`

### How it works
Doctor should explain:
- why Koolkidclub is not available
- why a runtime is unhealthy
- why a policy path is invalid
- why a research backend is unreachable

---

## `scripts/operator_handoff_pack.py`

### Purpose
Portable operational summary.

### Add functions
- `build_handoff_pack(...)`
- `include_active_nodes(...)`
- `include_routing_policy_summary(...)`
- `include_recent_reroutes(...)`
- `include_evidence_backend_summary(...)`

### How it works
Another operator or model should be able to continue work from this file alone.

---

## `scripts/preflight_lib.py`

### Purpose
Shared preflight helpers.

### Add functions
- `check_model_policy_file(...)`
- `check_node_registry(...)`
- `check_backend_probe(...)`
- `ensure_state_dirs(...)`

---

## `scripts/overnight_operator_run.py`

### Purpose
Phase B overnight behavior.

This is the natural place for bounded EvoSkill-style overnight improvement runs on approved datasets, with strict replay/eval gates and no automatic promotion of new variants.

### Add later
- `run_approved_scheduled_skills(...)`
- `build_morning_digest(...)`
- `summarize_overnight_reroutes(...)`

### How it works
Only approved skills run overnight.
No widening of authority.
Morning digest summarizes what happened.

---

## New state directories

Create:
- `state/nodes/`
- `state/worker_heartbeats/`
- `state/task_leases/`
- `state/backend_health/`
- `state/accelerators/`
- `state/research_queries/`
- `state/evidence_bundles/`
- `state/eval_runs/`
- `state/eval_results/`
- `state/skills/`
- `state/skill_candidates/`
- `state/ui_views/`
- `state/logs/routing_decisions/`

These should remain additive to the current `state/` layer, not replacements for existing durable stores.

---

## Phase A implementation order

1. docs/policy migration
2. `runtime/core/models.py`
3. `runtime/core/backend_assignments.py`
4. `runtime/core/decision_router.py`
5. `runtime/core/degradation_policy.py`
6. `runtime/core/heartbeat_reports.py`
7. `runtime/core/task_lease.py`
8. `runtime/core/provenance_store.py`
9. `runtime/integrations/*` research additions
10. `runtime/evals/*`
11. `runtime/dashboard/*`
12. `scripts/*`

This order minimizes confusion and keeps the implementation aligned with the current repo spine.

---

## Integration cleanliness rules

These rules exist to keep 5.2 cohesive inside JarvisOS.

### 1) Extend existing seams before adding new ones
If a live repo file already owns a responsibility, 5.2 extends that file first.
Examples:
- routing logic extends `runtime/core/backend_assignments.py` and `runtime/core/decision_router.py`
- degraded behavior extends `runtime/core/degradation_policy.py`
- provenance extends `runtime/core/provenance_store.py`
- operator visibility extends `runtime/dashboard/*`
- operational entrypoints remain under `scripts/*`

### 2) New files must be narrow and clearly owned
A new file is only allowed when there is no clean existing owner.
Examples of acceptable new files:
- `runtime/core/task_lease.py`
- `runtime/core/node_registry.py`
- `runtime/integrations/research_backends.py`
- `runtime/integrations/searxng_client.py`
- `runtime/integrations/search_normalizer.py`
- `runtime/evals/replay_runner.py`
- `runtime/evals/scorers.py`

### 3) External projects contribute patterns, not replacement control planes
Borrow useful ideas, but keep JarvisOS in charge.
- Mission Control contributes dashboard/operator patterns
- Hermes contributes skills/memory/automation patterns
- EvoSkill contributes failure-driven skill improvement and frontier evaluation patterns
- SearXNG contributes private search backend behavior
- A2UI contributes declarative trusted UI patterns
- COG / Khoj contribute knowledge-vault and second-brain patterns
- Unsloth contributes fine-tuning lab patterns

No external project should become the new source of truth for:
- task routing
- approval policy
- degraded behavior
- operator authority
- durable runtime state

### 4) Keep core, extension, and sidecar boundaries explicit

#### Core runtime
Owns:
- task classification
- routing
- model/backend selection
- degraded fallback policy
- leases
- review/approval gates
- provenance
- dashboard exports

Core runtime lives in:
- `runtime/core/*`
- `runtime/dashboard/*`
- `runtime/evals/*`
- `scripts/bootstrap.py`
- `scripts/validate.py`
- `scripts/doctor.py`
- `scripts/smoke_test.py`

#### Extensions
Add capability but do not replace core decisions.
Extensions include:
- skills
- knowledge vault export
- generative operator interfaces
- research backends
- persona packs
- night shift manager

Extensions live in:
- `runtime/integrations/*`
- `runtime/memory/*`
- `runtime/researchlab/*`
- `runtime/skills/*`
- `runtime/ui/*`
- `runtime/personas/*`

#### Sidecars/labs
Useful, but never authoritative for core execution.
Examples:
- world-state ops map
- live event market reactor
- fine-tuning factory
- low-VRAM inference lane
- hybrid MoE experiments
- NVIDIA performance lab

These must remain isolated from approval and promotion authority unless explicitly promoted through core policy.

### 5) Approval and promotion authority always stay centralized
No skill, sidecar, adapter, or burst worker may silently gain authority.
Authority remains governed by core policy files and review stores.

### 6) Memory is helpful, but not authoritative runtime truth
Vaults, semantic memory, and second-brain systems are support layers.
They can inform routing, research, and skills, but they do not replace:
- task state
- review state
- approval state
- degradation state
- provenance state

### 7) Operator visibility is mandatory for all dynamic behavior
If the system reroutes, degrades, falls back, creates a skill candidate, or loses a burst worker, that change must become visible through:
- `runtime/dashboard/operator_snapshot.py`
- `runtime/dashboard/state_export.py`
- `runtime/dashboard/event_board.py`
- `scripts/operator_handoff_pack.py`

### 8) Multi-model does not mean unbounded model freedom
The 5.2 migration removes the Qwen-only runtime posture, but replaces it with policy-routed multi-model behavior.
All model use must still be:
- allowlisted by task class
- tier-bounded by authority class
- logged in routing decisions
- visible in outputs/artifacts
- blocked from forbidden downgrades

### 9) Burst workers are acceleration only
Burst workers may speed up work, but must not become the only holder of:
- critical task state
- review state
- approval state
- irreplaceable artifacts

### 10) Every compounding mechanism must be eval-gated
This includes:
- new skill candidates
- prompt variants
- frontier winners
- model candidates
- routing policy changes

Nothing compounds directly into production without replay/eval evidence and core approval.

## Clean package ownership map

### Core packages
- Persistent Core + Elastic Burst Runtime -> `runtime/core/*`, `runtime/dashboard/*`, `scripts/*`
- Mixed-Accelerator Multi-Model Runtime -> `runtime/core/models.py`, `backend_assignments.py`, `decision_router.py`, `degradation_policy.py`
- Private Research + Evidence -> `runtime/integrations/*`, `runtime/core/provenance_store.py`, `runtime/researchlab/*`
- Eval Harness + Regression Gates -> `runtime/evals/*`, `scripts/validate.py`, `scripts/smoke_test.py`
- Operator Cockpit -> `runtime/dashboard/*`, `scripts/operator_handoff_pack.py`
- Compounding Skills Engine -> `runtime/skills/*`, `runtime/memory/*`, `runtime/evals/*`, `scripts/overnight_operator_run.py`

### Extension packages
- Generative Operator Interfaces -> `runtime/ui/*`, `runtime/dashboard/*`
- Knowledge OS / Intelligence Vault -> `runtime/memory/*`, `workspace/vault/*`
- Specialist Persona Packs -> `runtime/personas/*`
- Director Crew Builder / Night Shift Manager -> `runtime/crew/*`, `scripts/overnight_operator_run.py`
- Self-Optimization Lab -> `runtime/researchlab/*`, `runtime/evals/*`, `state/experiments/*`
- Fine-Tuning Factory / Model Adaptation Lab -> `labs/fine_tuning/*`, `runtime/evals/*`

### Sidecars / labs
- World-State Ops Map -> isolated sidecar feeding research/evidence only
- Live Event Market Reactor -> isolated trading sidecar supervised by Jarvis
- Low-VRAM Inference Lane -> optional fallback/portability lane under degradation policy
- Shadow Model Evaluation Lane -> eval-only path
- NVIDIA Performance Lab -> lab only
- Hybrid MoE Inference Lab -> lab only

### Fit test for any new idea
Before adding a new package or repo-inspired feature, require five yes answers:
1. Does it extend an existing Jarvis seam cleanly?
2. Does it preserve core authority boundaries?
3. Does it keep runtime truth in Jarvis state?
4. Is its dynamic behavior operator-visible?
5. Can it be evaluated or replayed before promotion?

If any answer is no, the idea stays a lab or is rejected.

## Phase A implementation tickets (grouped by dependency order)

These tickets are written to be executed in order.
Each ticket should preserve the current repo structure and extend existing seams first.

### Ticket A0 — 5.2 policy migration and docs

#### Files
- `README.md`
- `Jarvis_OS_v5_1_Master_Spec.md`
- `docs/jarvis_5_2_runtime_migration.md` (new)

#### Goals
- replace the current Qwen-default / Qwen-first runtime wording with 5.2 multi-model, policy-routed wording
- preserve approval-aware, validation-first, durable-state invariants
- document that multi-model support is a controlled migration, not free-for-all model use

#### Acceptance criteria
- README no longer describes active runtime policy as Qwen-only
- 5.2 delta is clearly documented
- migration notes explain what changed and what did not change

---

### Ticket A1 — shared runtime types in `runtime/core/models.py`

#### Files
- `runtime/core/models.py`

#### Add
Enums:
- `ModelFamily`
- `ModelTier`
- `BackendRuntime`
- `NodeRole`
- `NodeStatus`
- `TaskClass`
- `AuthorityClass`
- `RoutingReason`
- `DegradationMode`

Records:
- `ModelProfile`
- `BackendProfile`
- `NodeProfile`
- `RoutingDecision`
- `EvidenceBundleRef`
- `TaskLeaseRecord`

#### Goals
- make `models.py` the canonical vocabulary for routing, nodes, evidence, leases, and degraded modes
- remove the need for ad hoc duplicate shapes in downstream files

#### Acceptance criteria
- downstream modules can import these types without defining local alternatives
- types are expressive enough to describe multi-model routing and burst-worker state

---

### Ticket A2 — policy-backed assignment rules in `runtime/core/backend_assignments.py`

#### Files
- `runtime/core/backend_assignments.py`
- `config/model_policy.json` (new)
- `runtime/core/model_policy.py` (optional helper only if needed)

#### Add
Functions:
- `load_model_policy(...)`
- `get_allowed_models_for_task(...)`
- `get_min_tier_for_authority(...)`
- `get_fallback_chain(...)`
- `is_shadow_eligible(...)`
- `is_route_allowed(...)`
- `assert_no_forbidden_downgrade(...)`

#### Goals
- encode model/task/authority legality in one place
- keep assignment policy data-driven
- support multi-model routing without relaxing safety boundaries

#### Acceptance criteria
- policy file can express allowlists, minimum tiers, fallback chains, and forbidden downgrades
- review-required work cannot be legally routed into forbidden weak lanes
- safe summaries can legally use cheaper/fallback lanes if policy allows

---

### Ticket A3 — explainable routing in `runtime/core/decision_router.py`

#### Files
- `runtime/core/decision_router.py`
- `runtime/core/model_router.py` (optional helper only if needed)
- `state/logs/routing_decisions/` (new dir)

#### Add
Functions:
- `route_task(...)`
- `collect_candidate_routes(...)`
- `score_candidate_route(...)`
- `select_best_route(...)`
- `persist_routing_decision(...)`
- `explain_routing_decision(...)`

#### Goals
- choose node + backend + model using task class, authority class, health, queue depth, context, and degradation state
- persist every final routing decision
- make routing behavior visible and replayable

#### Acceptance criteria
- every routed task produces a durable routing decision record
- routing decision includes reasons and selected node/backend/model
- same task can route differently under different health/load conditions while staying policy-legal

---

### Ticket A4 — degraded behavior hardening in `runtime/core/degradation_policy.py`

#### Files
- `runtime/core/degradation_policy.py`
- `state/degradation_policies/` (existing or confirm)
- `state/degradation_events/` (existing or confirm)

#### Add
Functions:
- `load_degradation_policies(...)`
- `get_active_degradation_modes(...)`
- `can_fallback(...)`
- `record_degradation_event(...)`
- `should_notify_operator(...)`
- `get_retry_policy(...)`
- `is_authority_downgrade_forbidden(...)`

Modes:
- `BURST_WORKER_OFFLINE`
- `RESEARCH_BACKEND_DOWN`
- `NVIDIA_LANE_DOWN`
- `AMD_LANE_DOWN`
- `FALLBACK_SUMMARY_ONLY`

#### Goals
- keep all degraded/fallback logic centralized
- prevent silent authority widening or weak-lane substitution for sensitive work
- make degraded events durable and operator-visible

#### Acceptance criteria
- burst-worker loss becomes a visible degradation event
- sensitive work cannot silently fall to disallowed tiers/runtimes
- degraded safe-summary paths remain functional when policy allows

---

### Ticket A5 — node liveness and burst-worker state in `runtime/core/heartbeat_reports.py`

#### Files
- `runtime/core/heartbeat_reports.py`
- `runtime/core/node_registry.py` (new)
- `state/nodes/` (new dir)
- `state/worker_heartbeats/` (new dir)

#### Add
Heartbeat functions:
- `write_heartbeat(...)`
- `read_heartbeat(...)`
- `heartbeat_is_stale(...)`
- `summarize_node_health(...)`
- `list_online_nodes()`

Node registry functions:
- `register_node(...)`
- `get_node(...)`
- `list_nodes()`
- `update_node_status(...)`
- `get_node_capabilities(...)`

#### Goals
- separate live pulse from durable node identity/capabilities
- let router and dashboard understand whether Koolkidclub is actually usable
- expose hardware/runtime/model availability per node

#### Acceptance criteria
- NIMO can be represented as primary node
- Koolkidclub can be represented as burst node
- stale heartbeat is detectable and actionable
- node registry + heartbeat together are sufficient for routing decisions

---

### Ticket A6 — leased burst work in `runtime/core/task_lease.py`

#### Files
- `runtime/core/task_lease.py` (new)
- `state/task_leases/` (new dir)

#### Add
Functions:
- `create_lease(...)`
- `renew_lease(...)`
- `expire_stale_leases(...)`
- `requeue_expired_lease(...)`
- `get_active_lease(...)`

#### Goals
- ensure every burst-worker task is reclaimable
- make Koolkidclub acceleration-only, not critical-path
- support checkpoints and reroute reasons

#### Acceptance criteria
- every task assigned to burst worker has a lease record
- expired leases can be requeued automatically
- rerouted burst work is visible in state/events

---

### Ticket A7 — backend and accelerator health records

#### Files
- `state/backend_health/` (new dir)
- `state/accelerators/` (new dir)
- `scripts/preflight_lib.py`
- `scripts/bootstrap.py`
- `scripts/doctor.py`

#### Goals
- persist runtime/backend reachability, health, and basic performance snapshots
- persist node accelerator summaries for routing and visibility
- give doctor/bootstrap enough state to explain why lanes are unavailable

#### Acceptance criteria
- backend health files exist for active runtimes
- accelerator summaries exist per node
- doctor can explain missing/failed lanes instead of only reporting generic failure

---

### Ticket A8 — research backend abstraction and evidence bundle plumbing

#### Files
- `runtime/integrations/hermes_adapter.py`
- `runtime/integrations/autoresearch_adapter.py`
- `runtime/integrations/research_backends.py` (new)
- `runtime/integrations/searxng_client.py` (new)
- `runtime/integrations/search_normalizer.py` (new)
- `runtime/core/provenance_store.py`
- `runtime/researchlab/evidence_bundle.py` (new)
- `state/research_queries/` (new dir)
- `state/evidence_bundles/` (new dir)

#### Add
Backend interface:
- `ResearchBackend` protocol
- `get_backend(...)`
- `list_backends()`
- `healthcheck_backend(...)`

SearXNG client:
- `search(...)`
- `healthcheck()`

Normalizer:
- `normalize_search_results(...)`
- `dedupe_results(...)`
- `build_source_records(...)`

Provenance functions:
- `write_evidence_bundle(...)`
- `read_evidence_bundle(...)`
- `attach_evidence_to_artifact(...)`
- `get_artifact_evidence(...)`
- `summarize_provenance_for_output(...)`

#### Goals
- make research backends swappable
- ensure research outputs become evidence-backed artifacts
- keep provenance attached to current core provenance seam

#### Acceptance criteria
- research query can produce normalized results and an evidence bundle
- artifacts can point to evidence bundles
- backend outage becomes visible degradation instead of fake evidence

---

### Ticket A9 — trace replay and scoring in `runtime/evals/*`

#### Files
- `runtime/evals/trace_store.py`
- `runtime/evals/replay_runner.py` (new)
- `runtime/evals/scorers.py` (new)
- `runtime/evals/regression_suites/` (new dir)
- `state/eval_runs/` (new dir)
- `state/eval_results/` (new dir)

#### Add
Trace functions:
- `write_trace(...)`
- `load_trace(...)`
- `list_traces(...)`

Replay functions:
- `replay_trace(...)`
- `replay_router_decision(...)`
- `compare_expected_vs_actual(...)`

Scorers:
- `score_routing_correctness(...)`
- `score_no_silent_downgrade(...)`
- `score_evidence_completeness(...)`
- `score_reroute_behavior(...)`

#### Seed regression suites
- routing correctness
- no-silent-downgrade
- burst-worker reroute
- evidence completeness
- degradation correctness

#### Goals
- make 5.2 routing and fallback behavior replayable and measurable
- prevent unsafe migration drift

#### Acceptance criteria
- validate can run critical regression pack
- router and fallback changes can fail fast on regressions
- evidence completeness is scoreable

---

### Ticket A10 — operator cockpit upgrades in `runtime/dashboard/*`

#### Files
- `runtime/dashboard/operator_snapshot.py`
- `runtime/dashboard/state_export.py`
- `runtime/dashboard/heartbeat_report.py`
- `runtime/dashboard/task_board.py`
- `runtime/dashboard/output_board.py`
- `runtime/dashboard/event_board.py`
- `runtime/dashboard/node_board.py` (optional)
- `runtime/dashboard/research_board.py` (optional)

#### Add
Operator snapshot:
- `build_operator_snapshot()`
- `summarize_nodes()`
- `summarize_active_degradations()`
- `summarize_recent_reroutes()`
- `summarize_blocked_reviews()`

State export:
- `export_routing_state()`
- `export_node_state()`
- `export_backend_health()`
- `export_evidence_state()`
- `export_review_state()`

Heartbeat report:
- `build_heartbeat_report()`
- `summarize_backend_latency()`
- `summarize_loaded_models()`

Task board:
- `attach_routing_metadata(...)`
- `attach_evidence_flags(...)`

Output board:
- `attach_producer_metadata(...)`
- `attach_provenance_status(...)`

Event board:
- `emit_routing_event(...)`
- `emit_reroute_event(...)`
- `emit_backend_degraded_event(...)`
- `emit_worker_offline_event(...)`

#### Goals
- make node/model/backend/degradation/evidence state operator-visible in one coherent surface
- upgrade current dashboard instead of replacing it

#### Acceptance criteria
- operator can tell whether Koolkidclub is online and usable
- outputs/tasks visibly show model/backend and evidence status
- reroutes and degraded events appear in event stream

---

### Ticket A11 — operational entrypoint upgrades in `scripts/*`

#### Files
- `scripts/bootstrap.py`
- `scripts/validate.py`
- `scripts/smoke_test.py`
- `scripts/doctor.py`
- `scripts/operator_handoff_pack.py`
- `scripts/preflight_lib.py`
- `scripts/overnight_operator_run.py` (Phase B portion only)

#### Add to `bootstrap.py`
- `bootstrap_model_registry(...)`
- `bootstrap_node_registry(...)`
- `bootstrap_backend_health(...)`
- `bootstrap_research_backends(...)`

#### Add to `validate.py`
- `validate_model_policy(...)`
- `validate_no_forbidden_downgrades(...)`
- `validate_required_state_dirs(...)`
- `run_regression_suites(...)`

#### Add to `smoke_test.py`
- `smoke_route_safe_task(...)`
- `smoke_burst_worker_loss(...)`
- `smoke_evidence_bundle_write(...)`
- `smoke_forbidden_downgrade_block(...)`

#### Add to `doctor.py`
- `doctor_nodes(...)`
- `doctor_backends(...)`
- `doctor_policy_consistency(...)`
- `doctor_research_backends(...)`

#### Add to `operator_handoff_pack.py`
- `build_handoff_pack(...)`
- `include_active_nodes(...)`
- `include_routing_policy_summary(...)`
- `include_recent_reroutes(...)`
- `include_evidence_backend_summary(...)`

#### Add to `preflight_lib.py`
- `check_model_policy_file(...)`
- `check_node_registry(...)`
- `check_backend_probe(...)`
- `ensure_state_dirs(...)`

#### Goals
- keep bootstrap/validate/doctor/smoke/handoff as the operational spine for 5.2
- make the new runtime legible to operators and other sessions

#### Acceptance criteria
- bootstrap can initialize the new state and config surfaces
- validate can block unsafe routing changes
- doctor can explain lane/backend failures
- handoff pack captures nodes, models, degraded state, and evidence backend summary

---

### Ticket B1 — Compounding Skills Engine foundation

#### Files
- `runtime/skills/registry.py` (new)
- `runtime/skills/skill_store.py` (new)
- `runtime/skills/skill_candidate.py` (new)
- `runtime/skills/skill_scheduler.py` (new)
- `runtime/memory/governance.py`
- `runtime/evals/*`
- `state/skills/` (new dir)
- `state/skill_candidates/` (new dir)

#### Goals
- support approved skills and candidate skills as durable records
- support failure-driven skill discovery
- support eval-gated promotion

#### Acceptance criteria
- repeated failures can produce skill candidates
- skills can be evaluated before approval
- approved skills are searchable and schedulable

---

### Ticket B2 — Overnight approved-skill execution

#### Files
- `scripts/overnight_operator_run.py`

#### Add
- `run_approved_scheduled_skills(...)`
- `build_morning_digest(...)`
- `summarize_overnight_reroutes(...)`

#### Goals
- run only approved recurring skills overnight
- summarize overnight activity without widening authority

#### Acceptance criteria
- no unapproved skills run automatically
- morning digest captures reroutes, failures, and completed skill runs

---

### Ticket B3 — Generative Operator Interfaces

#### Files
- `runtime/ui/a2ui_schema.py` (new)
- `runtime/ui/component_catalog.py` (new)
- `runtime/dashboard/renderers/a2ui_renderer.py` (new)
- `state/ui_views/` (new dir)

#### Goals
- allow declarative trusted UI views for approvals, task controls, and research panes

#### Acceptance criteria
- generated UI stays declarative
- renderer only accepts catalog-listed components
- no executable arbitrary UI code path is introduced

---

### Ticket B4 — Knowledge vault export

#### Files
- `runtime/memory/vault_export.py` (new)
- `runtime/memory/vault_index.py` (new)
- `runtime/memory/brief_builder.py` (new)
- `workspace/vault/`

#### Goals
- export approved artifacts and briefs into a searchable knowledge sidecar
- keep runtime truth separate from memory/exported notes

#### Acceptance criteria
- vault exports do not replace core task/review/approval/provenance state
- approved summaries and artifacts can be exported cleanly

---

### Ticket B5 — Self-Optimization Lab / EvoSkill-style frontier loop

#### Files
- `runtime/researchlab/optimizer.py` (new)
- `runtime/researchlab/experiment_store.py` (new)
- `runtime/evals/*`
- `state/experiments/` (new dir)

#### Goals
- support bounded prompt/skill variant experiments
- support keep-or-revert behavior based on replay/eval
- support bounded frontier ranking of top variants

#### Acceptance criteria
- variant experiments are replayable and scored
- candidates do not auto-promote into production
- frontier winners still require approval/eval gates before live use

---

## Suggested command-of-work order

1. Ticket A0
2. Ticket A1
3. Ticket A2
4. Ticket A3
5. Ticket A4
6. Ticket A5
7. Ticket A6
8. Ticket A7
9. Ticket A8
10. Ticket A9
11. Ticket A10
12. Ticket A11
13. Ticket B1
14. Ticket B2
15. Ticket B3
16. Ticket B4
17. Ticket B5

This order keeps the migration clean:
- policy first
- routing core next
- degraded/liveness/burst safety next
- research provenance next
- eval gates next
- visibility and operations next
- compounding intelligence later

## Copy-paste coder prompts by ticket

These prompts are designed to be handed to another coding model or operator one at a time.
They assume the current JarvisOS repo structure should be preserved.
They explicitly forbid greenfield rewrites and require extending existing seams first.

### Prompt for Ticket A0 — 5.2 policy migration and docs

Read `README.md` and `Jarvis_OS_v5_1_Master_Spec.md` first.
Do not change repo structure.
Do not invent new runtime packages.

Task:
- update the docs from the current Qwen-default / Qwen-first runtime posture to a 5.2 multi-model, policy-routed posture
- preserve all existing approval-aware, explicit-task, durable-state, and validation-first guarantees
- add a new doc `docs/jarvis_5_2_runtime_migration.md`

Required outputs:
- updated `README.md`
- updated `Jarvis_OS_v5_1_Master_Spec.md` with a clear 5.2 delta section
- new `docs/jarvis_5_2_runtime_migration.md`

Requirements:
- do not imply that 5.2 is already implemented if it is not
- explain that multi-model support is controlled by routing policy, not free-for-all model use
- keep the rules “conversation is not execution” and “task: remains explicit” intact

Validation:
- docs should be internally consistent
- there should be no remaining text that says the active runtime policy is still Qwen-only unless it is explicitly labeled as historical 5.1 behavior

---

### Prompt for Ticket A1 — shared runtime types in `runtime/core/models.py`

Read `runtime/core/models.py` first.
Extend existing types; do not fork a second type system.

Task:
Add the shared 5.2 routing/runtime vocabulary into `runtime/core/models.py`.

Add enums for:
- `ModelFamily`
- `ModelTier`
- `BackendRuntime`
- `NodeRole`
- `NodeStatus`
- `TaskClass`
- `AuthorityClass`
- `RoutingReason`
- `DegradationMode`

Add records/dataclasses (or the repo’s existing preferred type style) for:
- `ModelProfile`
- `BackendProfile`
- `NodeProfile`
- `RoutingDecision`
- `EvidenceBundleRef`
- `TaskLeaseRecord`

Requirements:
- keep the style consistent with the existing file
- do not break existing imports or current runtime behavior
- add concise docstrings/comments explaining intended 5.2 usage

Validation:
- file imports cleanly
- types are sufficient for multi-model routing, burst-worker state, provenance refs, and degraded modes

---

### Prompt for Ticket A2 — policy-backed assignment rules in `runtime/core/backend_assignments.py`

Read:
- `runtime/core/backend_assignments.py`
- `runtime/core/models.py`

Task:
Extend `backend_assignments.py` so it becomes the policy-backed assignment layer for 5.2.
Create `config/model_policy.json` if it does not exist.
Only add `runtime/core/model_policy.py` if a helper is clearly needed.

Implement functions for:
- loading model policy
- allowed models by task class
- minimum tier by authority class
- fallback chain lookup
- shadow/eval eligibility
- route legality checks
- forbidden downgrade assertions

Requirements:
- do not make routing decisions here; only determine legality/policy
- keep policy data-driven as much as possible
- preserve existing safety posture for review/promotion-sensitive work

Validation:
- policy file can express allowlists, min tiers, fallback chains, and forbidden downgrades
- sensitive work cannot be legally assigned to weak forbidden lanes

---

### Prompt for Ticket A3 — explainable routing in `runtime/core/decision_router.py`

Read:
- `runtime/core/decision_router.py`
- `runtime/core/backend_assignments.py`
- `runtime/core/models.py`

Task:
Turn `decision_router.py` into the final explainable route chooser.
Add helper `runtime/core/model_router.py` only if needed.
Create durable routing decision records under `state/logs/routing_decisions/`.

Implement functions for:
- route selection entrypoint
- candidate collection
- candidate scoring
- best-route selection
- routing decision persistence
- routing explanation

Router inputs must consider:
- task class
- authority class
- context estimate
- latency preference
- node health
- backend health
- queue depth
- degraded mode
- policy legality

Requirements:
- every routed task must produce a durable routing record
- routing decisions must be explainable
- do not hardcode one model family as the only valid route
- do not break existing router flow if current behavior still depends on legacy assumptions

Validation:
- routing record includes selected node/backend/model and reasons
- same task can route differently under different health/load states while remaining policy-legal

---

### Prompt for Ticket A4 — degraded behavior hardening in `runtime/core/degradation_policy.py`

Read:
- `runtime/core/degradation_policy.py`
- `runtime/core/models.py`
- `runtime/core/backend_assignments.py`

Task:
Extend degradation policy to cover 5.2 multi-model + burst-worker behavior.
Reuse existing degradation state/files if present.

Implement:
- policy loading helpers
- active degradation mode lookup
- fallback legality checks
- degradation event recording
- operator-notify decision helpers
- retry policy helpers
- forbidden authority-downgrade checks

Add/handle modes like:
- `BURST_WORKER_OFFLINE`
- `RESEARCH_BACKEND_DOWN`
- `NVIDIA_LANE_DOWN`
- `AMD_LANE_DOWN`
- `FALLBACK_SUMMARY_ONLY`

Requirements:
- all fallback behavior must stay centralized here
- no silent downgrade for review/promotion-sensitive work
- safe summary fallback may remain available if policy allows

Validation:
- burst-worker loss creates visible degradation event
- forbidden downgrade cases are blocked
- allowed degraded summary paths still function

---

### Prompt for Ticket A5 — node liveness and burst-worker state

Read:
- `runtime/core/heartbeat_reports.py`
- `runtime/core/models.py`

Task:
Extend heartbeat reporting and add durable node registry support.
Create `runtime/core/node_registry.py`.
Create state dirs `state/nodes/` and `state/worker_heartbeats/`.

Implement in heartbeat layer:
- write heartbeat
- read heartbeat
- stale heartbeat detection
- node health summary
- online node listing

Implement in node registry:
- register node
- get node
- list nodes
- update node status
- get node capabilities

Requirements:
- heartbeat is live pulse
- node registry is durable metadata
- support NIMO as primary and Koolkidclub as burst worker
- do not make burst worker a required dependency

Validation:
- stale heartbeat is detectable
- node data is sufficient for routing and dashboard visibility

---

### Prompt for Ticket A6 — leased burst work in `runtime/core/task_lease.py`

Read:
- `runtime/core/models.py`
- `runtime/core/heartbeat_reports.py`
- `runtime/core/degradation_policy.py`

Task:
Create `runtime/core/task_lease.py` and `state/task_leases/`.
Implement safe leasing for burst-worker tasks.

Implement functions for:
- create lease
- renew lease
- expire stale leases
- requeue expired lease
- get active lease

Requirements:
- every burst-worker task must have a lease
- lease expiry must trigger safe reroute/requeue
- include checkpoint ref/progress fields if practical

Validation:
- burst-worker tasks are reclaimable
- lease expiry produces visible reroute behavior

---

### Prompt for Ticket A7 — backend and accelerator health records

Read:
- `scripts/bootstrap.py`
- `scripts/doctor.py`
- `scripts/preflight_lib.py`

Task:
Add backend health and accelerator summary state support.
Create `state/backend_health/` and `state/accelerators/`.
Use the existing script spine; do not add a new top-level operational entrypoint.

Implement:
- backend health snapshot writing/reading
- accelerator summary writing/reading
- doctor helpers for failed lanes
- bootstrap/preflight hooks for initializing these state surfaces

Requirements:
- keep health state simple and inspectable
- support both AMD and NVIDIA reporting where available
- doctor must explain lane/backend unavailability rather than fail vaguely

Validation:
- backend health files exist for active runtimes
- accelerator summary files exist per node
- doctor output becomes more specific

---

### Prompt for Ticket A8 — research backend abstraction and evidence bundles

Read:
- `runtime/integrations/hermes_adapter.py`
- `runtime/integrations/autoresearch_adapter.py`
- `runtime/core/provenance_store.py`
- `runtime/researchlab/runner.py`

Task:
Add a swappable research backend abstraction, a SearXNG client, normalization, and evidence bundle plumbing.
Create:
- `runtime/integrations/research_backends.py`
- `runtime/integrations/searxng_client.py`
- `runtime/integrations/search_normalizer.py`
- `runtime/researchlab/evidence_bundle.py`
- `state/research_queries/`
- `state/evidence_bundles/`

Extend current files rather than bypassing them.

Implement:
- `ResearchBackend` interface/protocol
- backend lookup/list/healthcheck
- SearXNG search + healthcheck
- search-result normalization/dedup/source record building
- provenance functions for evidence bundle write/read/attach/summarize

Requirements:
- research output must become evidence-backed
- provenance stays in the current provenance seam
- backend outage must become visible degraded state, not fake success

Validation:
- research query can produce normalized results and evidence bundle
- artifacts can point to evidence bundles

---

### Prompt for Ticket A9 — replay and scoring in `runtime/evals/*`

Read:
- `runtime/evals/trace_store.py`
- `scripts/validate.py`
- `scripts/smoke_test.py`

Task:
Extend evals for 5.2 replay/regression behavior.
Create:
- `runtime/evals/replay_runner.py`
- `runtime/evals/scorers.py`
- `runtime/evals/regression_suites/`
- `state/eval_runs/`
- `state/eval_results/`

Extend `trace_store.py` with durable trace helpers.

Implement:
- trace write/load/list
- replay of saved traces
- router decision replay
- expected vs actual comparison
- scorers for routing correctness, no silent downgrade, evidence completeness, reroute behavior

Seed regression suites for:
- routing correctness
- no-silent-downgrade
- burst-worker reroute
- evidence completeness
- degradation correctness

Requirements:
- validate should be able to run critical suites
- replay should be usable for router/fallback policy changes

Validation:
- regression pack can fail bad changes
- trace format is durable and readable

---

### Prompt for Ticket A10 — operator cockpit upgrades in `runtime/dashboard/*`

Read:
- `runtime/dashboard/operator_snapshot.py`
- `runtime/dashboard/state_export.py`
- `runtime/dashboard/heartbeat_report.py`
- `runtime/dashboard/task_board.py`
- `runtime/dashboard/output_board.py`
- `runtime/dashboard/event_board.py`

Task:
Upgrade the current dashboard/operator surface instead of replacing it.
Only add `node_board.py` or `research_board.py` if necessary.

Implement:
- operator snapshot node/reroute/degradation/review summaries
- state export for routing/node/backend/evidence/review state
- heartbeat report node/model/backend summaries
- task board routing/evidence metadata
- output board producer/provenance metadata
- event board routing/reroute/backend-degraded/worker-offline events

Requirements:
- keep the current dashboard as the operator truth surface
- do not build a second control plane
- dynamic behavior must become operator-visible

Validation:
- operator can see whether Koolkidclub is online and usable
- tasks/outputs show model/backend/evidence/degraded state
- reroutes and degraded events appear in event stream

---

### Prompt for Ticket A11 — operational entrypoint upgrades in `scripts/*`

Read:
- `scripts/bootstrap.py`
- `scripts/validate.py`
- `scripts/smoke_test.py`
- `scripts/doctor.py`
- `scripts/operator_handoff_pack.py`
- `scripts/preflight_lib.py`
- `scripts/overnight_operator_run.py`

Task:
Extend the existing script spine for 5.2.
Do not add a new top-level operator entrypoint.

Implement in `bootstrap.py`:
- model registry bootstrap
- node registry bootstrap
- backend health bootstrap
- research backend bootstrap

Implement in `validate.py`:
- model policy validation
- forbidden downgrade validation
- required state dir validation
- regression suite execution

Implement in `smoke_test.py`:
- safe task route smoke
- burst-worker loss smoke
- evidence bundle write smoke
- forbidden downgrade smoke

Implement in `doctor.py`:
- node diagnosis
- backend diagnosis
- policy consistency diagnosis
- research backend diagnosis

Implement in `operator_handoff_pack.py`:
- routing policy summary
- active nodes/backends/models
- degraded state summary
- recent reroutes
- evidence backend summary

Implement in `preflight_lib.py`:
- model policy check
- node registry check
- backend probe check
- required state dir ensure/check

Requirements:
- preserve script entrypoint roles
- make 5.2 operational state understandable to humans and other models

Validation:
- bootstrap initializes the 5.2 surfaces
- validate can block unsafe routing changes
- doctor explains lane/backend failures
- handoff pack captures enough state for continuity

---

### Prompt for Ticket B1 — Compounding Skills Engine foundation

Read:
- `runtime/memory/governance.py`
- `runtime/evals/trace_store.py`
- `scripts/overnight_operator_run.py`

Task:
Add the initial skills layer.
Create:
- `runtime/skills/registry.py`
- `runtime/skills/skill_store.py`
- `runtime/skills/skill_candidate.py`
- `runtime/skills/skill_scheduler.py`
- `state/skills/`
- `state/skill_candidates/`

Implement:
- approved skill records
- skill candidate records
- failure-driven candidate creation helpers
- searchable approved skill registry
- schedulable approved skills only

Requirements:
- do not auto-promote skill candidates
- skill approval must remain eval-gated and review-aware
- keep style consistent with current repo governance patterns

Validation:
- repeated failures can produce candidates
- approved skills are searchable and schedulable

---

### Prompt for Ticket B2 — overnight approved-skill execution

Read:
- `scripts/overnight_operator_run.py`
- `runtime/skills/*`

Task:
Extend overnight operator run to support approved recurring skills only.

Implement:
- approved scheduled skill execution
- morning digest builder
- overnight reroute summary

Requirements:
- no unapproved skill may run automatically
- overnight behavior must not widen authority

Validation:
- morning digest clearly summarizes skill runs, reroutes, and failures

---

### Prompt for Ticket B3 — Generative Operator Interfaces

Read:
- `runtime/dashboard/*`

Task:
Add a declarative trusted UI layer.
Create:
- `runtime/ui/a2ui_schema.py`
- `runtime/ui/component_catalog.py`
- `runtime/dashboard/renderers/a2ui_renderer.py`
- `state/ui_views/`

Implement:
- view schema
- trusted component catalog
- renderer for declarative views

Requirements:
- no arbitrary executable UI generation
- stay integrated with current dashboard surfaces

Validation:
- generated views are declarative and render only trusted components

---

### Prompt for Ticket B4 — knowledge vault export

Read:
- `runtime/memory/governance.py`
- `runtime/core/provenance_store.py`

Task:
Add governed export into a knowledge sidecar.
Create:
- `runtime/memory/vault_export.py`
- `runtime/memory/vault_index.py`
- `runtime/memory/brief_builder.py`
- `workspace/vault/`

Implement:
- export of approved artifacts/summaries
- simple index/update helpers
- brief builder for daily/weekly summaries

Requirements:
- vault must not become runtime truth
- exports should be traceable back to approved artifacts/provenance

Validation:
- approved artifacts can be exported cleanly
- runtime truth remains in Jarvis state

---

### Prompt for Ticket B5 — Self-Optimization Lab / EvoSkill-style frontier loop

Read:
- `runtime/researchlab/runner.py`
- `runtime/evals/*`
- `runtime/skills/*`

Task:
Add a bounded experiment loop for prompt/skill variants.
Create:
- `runtime/researchlab/optimizer.py`
- `runtime/researchlab/experiment_store.py`
- `state/experiments/`

Implement:
- proposal of candidate variants
- replay/eval of variants
- keep-or-revert behavior
- bounded frontier of top-performing candidates

Requirements:
- no automatic production promotion
- all winners still require eval/review gates
- experiments must be reproducible and inspectable

Validation:
- candidate variants are scored and stored
- bounded frontier is maintained
- promotion remains explicitly gated

---

## Safe-first execution lanes

This section splits the tickets into:
- safe first tickets
- tickets that should be reviewed immediately after patching
- tickets that should stay human-led or tightly supervised

The goal is to reduce the chance that a coding model touches the most sensitive control-plane files too early.

### Lane 1 — Safe first tickets
These are the best starting tickets because they are additive, relatively bounded, and unlikely to destabilize core execution if done carefully.

#### Safe first
- **A0 — 5.2 policy migration and docs**
- **A7 — backend and accelerator health records**
- **A8 — research backend abstraction and evidence bundles**
- **A9 — replay and scoring in `runtime/evals/*`**
- **A10 — operator cockpit upgrades in `runtime/dashboard/*`**
- **A11 — operational entrypoint upgrades in `scripts/*`**
- **B3 — Generative Operator Interfaces**
- **B4 — knowledge vault export**

#### Why these are safe first
They are mostly:
- additive
- visibility-improving
- validation-improving
- side-effect-light compared with core routing logic

Even when they touch important files, they usually do not directly decide execution authority.

#### Recommended order inside safe first
1. A0
2. A7
3. A9
4. A10
5. A11
6. A8
7. B4
8. B3

---

### Lane 2 — Patch, then review immediately
These are core-runtime tickets that are necessary, but should always be reviewed right after patching before moving on.

#### Patch then review
- **A1 — shared runtime types in `runtime/core/models.py`**
- **A2 — policy-backed assignment rules in `runtime/core/backend_assignments.py`**
- **A3 — explainable routing in `runtime/core/decision_router.py`**
- **A4 — degraded behavior hardening in `runtime/core/degradation_policy.py`**
- **A5 — node liveness and burst-worker state**
- **A6 — leased burst work in `runtime/core/task_lease.py`**
- **B1 — Compounding Skills Engine foundation**

#### Why these need immediate review
These files influence:
- routing
- authority boundaries
- degraded behavior
- node selection
- promotion of reusable behaviors

A coding model can work on them, but you should inspect the patch before continuing, especially for:
- hidden assumption changes
- broad refactors
- duplicated logic
- silent widening of authority
- breaking old call sites

#### Review checklist after patching
- Did the patch preserve the current repo structure?
- Did it extend an existing seam instead of inventing a parallel system?
- Did it accidentally hardcode a model family or backend?
- Did it weaken approval/review/downgrade protections?
- Did it introduce unbounded autonomous behavior?
- Did it change public behavior without writing durable state or dashboard visibility?

---

### Lane 3 — Human-led or tightly supervised tickets
These are the tickets most likely to introduce subtle control-plane drift or autonomy creep if handed off too casually.

#### Human-led / tightly supervised
- **B2 — overnight approved-skill execution**
- **B5 — Self-Optimization Lab / EvoSkill-style frontier loop**

#### Why these are highest risk
They directly touch:
- recurring autonomous behavior
- compounding improvement loops
- overnight activity
- candidate promotion logic
- replay/eval/approval boundaries

These should not be early “fire and forget” coding-model tickets.
They should be implemented only after the routing, degradation, provenance, eval, and operator visibility layers are stable.

---

## Recommended staged execution plan

### Stage 1 — visibility and safety scaffolding first
Run these before touching routing core:
1. A0
2. A7
3. A9
4. A10
5. A11

This gives you:
- better docs
- better health state
- better eval scaffolding
- better dashboard visibility
- better operational tooling

### Stage 2 — core runtime migration
Then do these one at a time with immediate review:
6. A1
7. A2
8. A3
9. A4
10. A5
11. A6

This is the actual heart of 5.2.
Each patch here should be reviewed before the next one begins.

### Stage 3 — research + provenance tightening
12. A8

This can move earlier if you want private research sooner, but it is cleaner after the policy/routing vocabulary is in place.

### Stage 4 — compounding capability foundations
13. B1
14. B4
15. B3

These are safe once the runtime core is stable.

### Stage 5 — tightly supervised autonomy growth
16. B2
17. B5

These should be last because they increase autonomous and compounding behavior.

---

## Fastest low-risk starting bundle

If you want the safest first bundle to hand off immediately, use this group:
- A0
- A7
- A9
- A10
- A11

This bundle gives you:
- updated policy/docs
- backend/accelerator visibility
- regression harness scaffolding
- dashboard/operator visibility
- stronger bootstrap/validate/doctor/handoff behavior

It improves the system a lot without yet modifying the deepest routing and degradation logic.

---

## Highest-value but highest-attention bundle

If you want the real 5.2 heart, but handled carefully, use this group one-by-one:
- A1
- A2
- A3
- A4
- A5
- A6

This bundle changes the actual control plane.
It should never be handed off as one giant unattended patch.

---

## Non-goals

5.2 must not:

- replace the current dashboard with a third-party control plane
- replace runtime truth with markdown files
- let Hermes-style learning bypass review/evals
- make Koolkidclub part of the critical path
- allow silent fallback from review-required work into weak lanes
- treat generated UI as executable code
- allow arbitrary uncontrolled model use

---

## Short definition for handoff

JarvisOS 5.2 is a repo-aligned migration from a Qwen-default/Qwen-first runtime to a policy-routed multi-model runtime that preserves durable task state, explicit tasking, approval-aware execution, evidence-backed research, validation-first deployment, and the existing operator/dashboard/script spine.

