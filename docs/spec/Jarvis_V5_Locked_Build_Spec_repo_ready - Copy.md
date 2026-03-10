# Jarvis v5 Locked Build Spec

## Purpose

This document converts the v5 discussion into a concrete build target. The goal is to build the full
v5 system while sequencing implementation so it stays runnable and does not become another
architecture-only exercise. This spec reflects:

- the current Jarvis v4 lessons
- the Snowglobe clean-install pain pattern
- preferences
- the decision to keep Qwen-native functionality central
- the decision to make deployment less manual

## Core product definition

Jarvis v5 is a Qwen-first operator system for:

- orchestrating work

- banging out tasks quickly
- quant / NQ / prop-account research
- media ingest and idea extraction
- code generation and review gated execution
- artifact creation and auditability

## Primary product goal

The most important day-one use case is:

1. NQ prop account work
2. quant research
3. rapid execution with review and visibility

## Non-negotiable v5 rules

### Rule 1 - conversation is not execution

A normal message in #jarvis must never create work automatically.

### Rule 2 - task creation must be explicit

Supported task triggers in #jarvis:

- !task ...
- task: ...
- task ... if parsing is reliable enough

### Rule 3 - chat state is not system state

Task state must live in durable records, not chat scrollback.

### Rule 4 - long-form source material should be distilled once

Videos, audio, links, and other heavy materials should be ingested and distilled into reusable a
future tasks do not repeatedly burn context/tokens on the raw source.

### Rule 5 - risky outputs require review

Anton and/or Archimedes should gate the right classes of work before completion.

### Rule 6 - deployment should catch obvious failures before runtime

Validation and doctor tooling must catch config, permission, model, and filesystem issues early.

## Channel map

### #jarvis

Purpose: conversation, orchestration, planning, status, updates

Rules: - chat only

- no automatic task creation from ordinary conversation
- accepts explicit task triggers
- should respond fast and clearly
- should behave like an operator sidekick, not a background work queue

### #tasks

Purpose: explicit task creation and task progress

Rules: - formal task requests go here

- active task progress can be posted here
- task transitions can be visible here

### #outputs

Purpose: final artifacts and completed useful outputs

### #review

Purpose: approvals and final human decisions

Rules: - optimized for simple reaction-based approvals first

- can expand later to richer UI

### #alerts

Purpose: important failures, blocked tasks, operational notices

### #code-review

Purpose: Archimedes code-review verdicts and code-focused feedback

### #audit

Purpose: Anton summaries, higher-level review, oversight, integrity checks

### #flowstate

Purpose: ingest / transcribe / distill / idea extraction lane

Rules: - drop media, links, clips,
source material

- system ingests and extracts meaning
- output claims, ideas, actions, timestamps
- nothing becomes a task or memory unless approved

### #crew

v5.0 default: removed unless the new tar proves it is still necessary

## Lane model

Jarvis v5 has three main lanes.

### 1. Chat lane

Primary surface: #jarvis

Responsibilities: - answer status questions

- coordinate work
- plan next steps
- explain what is happening
- accept explicit task creation commands

### 2. Task lane

Primary surfaces:

- #tasks

- #outputs
- #review
- #alerts
- #code-review
- #audit

Responsibilities: - run explicit task lifecycle
- produce artifacts
- run reviews
- route for approvals
- surface failures and completions

### 3. Flowstate lane

Primary surface: #flowstate

Responsibilities: - ingest long-form source material

- transcribe / summarize
- extract ideas and possibilities
- present compressed knowledge for approval

## Role map

### Jarvis

operator-facing orchestrator fast chat/status/planning layer may do light planning/reasoning should
not be relied on for brittle live tool execution unless intentionally designed for it

### Worker

default execution role for normal tasks

### Scout

retrieval, search, context gathering, research support

### Kitt

trading / quant specialist lane

### HAL

implementation / code production lane

### Archimedes

specialized code reviewer reviews completed code tasks behaves like a professional code-review layer

### Anton

final reviewer / risk gate / synthesis reviewer used for risky, high-value, or final-pass work

### Out of v5.0 scope

Muse Herald Gatekeeper Council personas as permanent operational roles

## Review policy

### Non-code tasks

normal safe task: no heavy review unless needed high-risk / high-value / publish-worthy task: Anton

### Code tasks

completed code task: Archimedes required risky / deploymenty-related / production-facing code: Archimedes
first, Anton final gate small safe code tasks: Archimedes only

### Trading / quant tasks

research/setup/simulation/draft outputs: policy-controlled, usually Anton before promotion if high
importance actual placement or live action: explicit restricted pathway + approval gate required
Data contracts The v5 runtime should revolve around explicit structured records. Task record schema
Every task record should include at least: - task_id

- created_at
- updated_at
- source_lane
- source_channel
- source_message_id
- source_user
- trigger_type
- raw_request
- normalized_request
- task_type
- priority
- risk_level
- status
- assigned_role
- assigned_model -

review_required -

approval_required -

parent_task_id

- related_artifact_ids
- related_approval_ids
- checkpoint_summary
- error_count
- last_error
- final_outcome Task event schema Every task event should include at least: - event_id
- task_id
- timestamp
- event_type
- from_status
- to_status
- actor
- lane
- summary
- details
- artifact_ids
- approval_id
- error Artifact schema Every artifact should include at least: - artifact_id
- created_at
- updated_at
- task_id
- artifact_type
- title
- summary
- path
- source_refs
- generator_role
- generator_model
- review_status
- approval_status
- tags
- metadata

Flowstate source schema Every Flowstate source record should include at least: - source_id

- created_at
- submitted_by
- source_kind -

source_url -

source_path -

source_title -

source_author

- source_duration
- ingest_status
- transcript_artifact_id
- distilled_artifact_id
- promotion_status
- notes Review verdict schema Every Archimedes or Anton verdict should include at least: - verdict_id
- task_id
- artifact_id
- reviewer
- review_model
- review_type
- timestamp
- decision
- severity
- summary
- findings
- required_changes
- optional_suggestions
- approved_for_promotion Approval policy v5.0 approval UX Start simple. Supported initially: - reaction-based yes/no
- minimal follow-up prompts when clarification is a required Approval object fields approval_id task_id artifact_id created_at requested_by route title summary options recommended_option risk_note status timeout_at response responded_by responded_at approval_id task_id title summary options recommended option

risk note timeout route Supported actions approve reject rerun escalate choose option 1/2/3 when
applicable Status vocabulary To keep the system debuggable, status values should be constrained.
Task statuses received classified planned queued running awaiting_review awaiting_approval approved
rejected completed failed archived Review statuses not_required pending in_review changes_requested
approved rejected Approval statuses not_required pending approved rejected

expired cancelled Artifact types summary plan report code_patch code_review audit transcript
flowstate_distillation research_note trading_setup simulation_result draft_order final_output
Flowstate spec #flowstate is a first-class lane, not a side feature. Intended user behavior User
drops: - video links

- uploads
- audio clips
- source docs
- external explanations / walkthroughs System behavior
1. capture source metadata
2. fetch or open source when allowed
3. transcribe / extract
4. distill into compact artifact
5. present summary + ideas + actions
6. wait for approval before promotion into tasks or memory Distilled artifact should include concise summary key claims key ideas candidate action items notable timestamps / sections important caveats

Why it exists reduce repeated token/context burn turn raw long-form material into reusable
structured knowledge let you approve what matters before it spreads into the rest of the system
Config contracts The config layer should be split by purpose so failures are easier to isolate.
app.yaml Should include: - app name

- environment name
- workspace root
- state root
- log root
- event backend mode
- default task retention rules
- feature flags channels.yaml Should include: - guild/server identifier -

jarvis_channel_id -

tasks_channel_id

- outputs_channel_id
- review_channel_id
- alerts_channel_id
- code_review_channel_id
- audit_channel_id
- flowstate_channel_id
- allow_task_creation_in_jarvis
- accepted task trigger patterns models.yaml Should include: - routing model
- general worker model
- anton model
- coder model
- flow provider identifiers
- endpoint base URLs
- timeout rules
- retry rules
- fallback rules within model family policies.yaml Should include: - task creation rules
- review rules
- approval rules
- trading guardrail rules
- access rules
- memory writeback rules
- Flowstate promotion rules .env Secrets only: - Discord token
- provider/API keys
- database or event-backend credentials if u private integration secrets Model routing Core model assignments Qwen3.5-9B
- routing / classification / light triage Qwen3.5-35B
- general work / planning / summaries / flowstate distillation / research

Qwen3.5-122B

- Anton / hardest reviews / high-stakes reasoning Coding lane Evaluate use of Qwen coder model for: - HAL implementation work
- possibly Archimedes co depending on actual quality in practice Routing principles never silently switch model families report model failures explicitly degrade gracefully preserve configured provider behavior Context and memory policy Context budget strategy The system should be designed around bounded context, not expanding context. Per-step principle

Each step should receive only: - the current objective
- the minimum relevant task state
- relevant retrieved context
- links/paths to artifacts instead of full raw material whenever possible Checkpoint principle

After each major phase, create a checkpoint summary containing: - what was done
- what r decisions
- important artifacts
- blockers This checkpoint becomes the default future context instead of the full history.

Retrieval principle

Prefer retrieval of: - prior summaries
- verdicts
- artifacts
- task metadata Avoid retrieval of: - entire raw transcripts
- entire chat logs
- repeated large blobs unles requested Escalation principle

If a task grows too large for comfortable bounded context: - split it into sub-tasks
- writ artifacts
- route a compressed dossier to Anton/Archimedes rather than raw sprawl

Context failure modes to defend against raw transcript re-injection over and over long Discord
history stuffing repeating whole prior plans in every prompt code review over full noisy logs
instead of targeted diffs final review over uncompressed work history Context and memory policy The
system must not rely on giant prompt accumulation. Four context layers

1. live working context for current step only
2. durable task record
3. retrieval memory
4. artifact references Rules do not keep appending entire conversation histories summarize checkpoints after major phases store decisions in structured fields retrieve only relevant prior material keep raw source outside the live prompt when possible use distilled artifacts instead of full source whenever possible Flowstate interaction with context Flowstate should produce compressed artifacts that later tasks can use instead of the full orig audio/doc. Runtime architecture target We are building toward the full v5 system, but implementation should stay sane. Full target architecture gateway core runtime auditor reporter configs validators

deploymenty/bootstrap layer flowstate ingest pipeline review/approval lane artifact/task state layer v5.0
implementation constraint At first, keep runtime pieces compact enough to debug. Recommended initial
service grouping: - gateway

- core
- auditor
- reporter Where core covers most director/executor behavior early on. Deployment requirements Deployment design principle Deployment should be boring. That means a first-time setup should fail early, clearly, and specifically
- not appear healthy unravel through runtime surprises. Deployment output contract A successful deploymentyment process should end with: - validated config files
- validated secrets validated Discord connectivity and permissions
- validated model endpoint reachability
- validated w runtime/state directories
- at least one successful smoke-test result
- clear instructions for sta restarting services Common failure classes v5 must detect invalid/missing channel IDs bot lacks view/send permission in one or more channels wrong guild/server binding bad or missing token/env values model endpoint unreachable configured model name invalid required directories missing or not writable service file points to wrong working directory or wrong python interpreter Deployment requirements The Snowglobe clean-install pain should directly shape v5 deploymentyment.

Primary goal A deploymentyment should be much closer to: - install

- configure
- validate
- run than to: - install
- fail mysteriously
- patch manually for hours
- discover permission problems later Required deploymentyment artifacts install.sh generate_config.py validate.py doctor.py example config files service/unit files or equivalent runtime launcher files smoke-test script validate.py must check secrets/config presence channel existence Discord access and permissions model endpoint availability configured model responses writable directories event/state layer readiness alerts route task lifecycle smoke test ability doctor.py must do rerunnable diagnostics explicit pass/fail output exact remediation steps visible health summary Security and guardrails The user prefers visibility, but guardrails are still necessary. Must protect API keys privileged actions filesystem scope live trading actions

dangerous tool execution Minimum guardrails least-privilege tool routing no direct live action from
casual chat restricted path for live trading actions explicit review/approval for risky execution
logging/audit trail on sensitive operations Jarvis response contract #jarvis should behave
consistently enough that the user learns what to expect. Status request response shape When the user
asks for status, Jarvis should try to answer in this order:

1. what is runn what is blocked
3. what is waiting on approval
4. what finished recently
5. what th recommended move is Task creation acknowledgement shape When the user creates a task explicitly, Jarvis should return: - task ID
- short normalized su status
- where progress will appear
- whether review/approval is likely expected Failure response shape When something fails, Jarvis should return: - what failed
- which lane/service failed
- whether r whether user action is required
- where more detail was logged Flowstate response shape When a source is dropped into #flowstate , the first acknowledgment should include: - source receipt confirmation
- source type
- ingest status
- whether transcription/extraction started
- whether app be needed before promotion Repo / output structure target This is the target structure we should build toward, even if some pieces are stubbed first. /home/rollan/.openclaw/workspace/jarvis-v5/ docs/ architecture.md deploymentyment.md

channels.md review-policy.md flowstate.md migration-from-v4.md config/ app.example.yaml
channels.example.yaml models.example.yaml policies.example.yaml scripts/ install.sh
generate_config.py validate.py doctor.py smoke_test.py runtime/ gateway/ core/ auditor/ reporter/
flowstate/ state/ tasks/ artifacts/ approvals/ logs/ systemd/ jarvis-v5-gateway.service
jarvis-v5-core.service jarvis-v5-auditor.service jarvis-v5-reporter.service This is a build target,
not a demand that every file be fully implemented before anything runs. Build phases Phase 1

- lock contracts and deploymentyment layer Deliverables: - final design decisions
- channel policy doc
- review policy doc
- flowstate doc - .env.example
- install.sh
- generate_config.py
- validate.py
- doctor.py Exit condition A fresh install can be validated before runtime with clear pass/fail results.

Phase 2

- core runtime skeleton Deliverables: - gateway skeleton
- core runtime skeleton
- task record schema
- task lifecycle explicit task creation parsing
- status reporting in #jarvis Exit condition User can chat in #jarvis , create a task explicitly, and see state tracked durably. Phase 3
- flowstate lane Deliverables: - media ingest path
- transcript/extraction path
- distilled artifact schema
- approval/promotion path Exit condition User can drop source material in #flowstate and receive a structured distillation artifact. Phase 4
- review lanes Deliverables: - Archimedes code-review flow
- Anton review flow
- approval objects and reaction handling Exit condition Completed code tasks and risky tasks route through the proper reviewers. Phase 5
- Qwen-native worker specialization Deliverables: - routing model integration
- general worker model integration
- Anton high-stakes integration
- coder lane evaluation/integration Exit condition The right Qwen models are doing the right kinds of work with clear routing behavior. Phase 6
- deploymentyment hardening and migration support Deliverables: - fresh-machine smoke test improvements
- migration notes from v4
- better s packaging
- better ops reporting Exit condition Deployment becomes boring enough that the system can be set up with minimal pos improvisation.

Acceptance criteria by phase Phase 1 acceptance criteria all core config files exist .env.example
covers every required secret/config input validate.py can run without starting the runtime doctor.py
produces explicit pass/fail results and remediation text channel policy is documented in one place
review policy is documented in one place flowstate policy is documented in one place Phase 2
acceptance criteria #jarvis replies conversationally without auto-enqueueing work explicit task
creation via !task works explicit task creation via task: works a task record is written durably
task state transitions are visible and consistent a basic status request in #jarvis can summarize
current system state Phase 3 acceptance criteria a source dropped in #flowstate creates a source
record transcript/extraction output is stored as an artifact distilled artifact contains summary,
ideas, actions, and caveats promotion into tasks or memory requires explicit approval Phase 4
acceptance criteria completed code tasks route to Archimedes risky non-code tasks can route to Anton
reaction-based approval can approve/reject/rerun review verdicts are stored with the task/artifact
Phase 5 acceptance criteria routing/model selection is explicit and logged configured Qwen models
are reachable and testable model failures are reported without silent family switching coder lane
can be enabled independently of the general worker lane

Phase 6 acceptance criteria fresh-machine setup can reach a validated baseline with minimal manual
steps common Discord permission/config problems are caught before runtime migration notes from v4
are preserved service launch and health checks are documented and repeatable Success criteria Jarvis
v5 is a success if: - #jarvis feels clean and conversational

- work never auto-enqueues from casual chat
- tasks can be created explicitly and tracked clearly
- Flowstate turns heavy source useful approved artifacts
- code tasks get properly reviewed
- risky tasks get properly reviewed
- headache is much lower than v4
- context does not explode from repeated raw-material stuffing native capabilities are actually present where they matter Open questions to resolve after the new tar These items should be finalized after examining the next working v4 tar and the stabilized d lessons. exact working channel IDs and final channel naming exact service launch order that proved reliable whether #crew remains necessary for any legacy path which provider/model mappings proved best in practice exact live file paths and service unit paths on Snowglobe final set of manual post-deploymenty fixes that still existed whether Redis should be enabled by default or left optional which coder model actually performs best for HAL/Archimedes in your environment Future-facing extensions These are important but should not delay the first runnable v5. Multimodal extensions screenshot-based debugging chart/image analysis for trading workflows visual approval aids visual artifact inspection Trading action extensions restricted execution lane for live orders policy-driven size/risk caps

dry-run/sim-first toggles signed audit trail for live actions Operator experience extensions richer
dashboard watch/phone-friendly approval shortcuts better artifact browsing/search weekly digest
generation Example configuration files These examples are intentionally explicit so v5 can be
bootstrapped with less guessing. config/app.example.yaml app_name: jarvis-v5 environment: production
workspace_root: /home/rollan/.openclaw/workspace/jarvis-v5 state_root:
/home/rollan/.openclaw/workspace/jarvis-v5/state log_root:
/home/rollan/.openclaw/workspace/jarvis-v5/state/logs timezone: America/Chicago event_backend: mode:
sqlite sqlite_path: /home/rollan/.openclaw/workspace/jarvis-v5/state/events.db feature_flags:
enable_flowstate: true enable_multimodal: true enable_live_trading: false retention: keep_task_days:
90 keep_artifact_days: 180 keep_log_days: 30 config/channels.example.yaml guild_name: Snowglobe
jarvis_channel_id: "REPLACE_ME" tasks_channel_id: "REPLACE_ME" outputs_channel_id: "REPLACE_ME"
review_channel_id: "REPLACE_ME" alerts_channel_id: "REPLACE_ME" code_review_channel_id: "REPLACE_ME"
audit_channel_id: "REPLACE_ME" flowstate_channel_id: "REPLACE_ME"

allow_task_creation_in_jarvis: true task_triggers: - "!task " - "task:" - "task "
config/models.example.yaml providers: routing: provider: openai_compatible base_url: "REPLACE_ME"
api_env: QWEN_ROUTING_API_KEY general: provider: openai_compatible base_url: "REPLACE_ME" api_env:
QWEN_GENERAL_API_KEY anton: provider: openai_compatible base_url: "REPLACE_ME" api_env:
QWEN_ANTON_API_KEY coder: provider: openai_compatible base_url: "REPLACE_ME" api_env:
QWEN_CODER_API_KEY models: routing_model: Qwen3.5-9B general_model: Qwen3.5-35B anton_model:
Qwen3.5-122B coder_model: Qwen3-Coder flowstate_model: Qwen3.5-35B timeouts: routing_seconds: 20
general_seconds: 90 anton_seconds: 180 coder_seconds: 180 retries: max_attempts: 2 backoff_seconds:
3 fallbacks: allow_same_family_fallbacks: true routing_fallbacks: [Qwen3.5-9B] general_fallbacks:
[Qwen3.5-35B] anton_fallbacks: [Qwen3.5-122B] coder_fallbacks: [Qwen3-Coder]

config/policies.example.yaml task_creation: auto_enqueue_from_chat: false explicit_triggers_only:
true review: archimedes_reviews_all_completed_code: true anton_reviews_risky_non_code: true
anton_reviews_deploymenty_code: true approval: reaction_based_enabled: true default_timeout_minutes: 240
flowstate: requires_approval_for_promotion: true auto_write_memory: false trading:
live_trading_enabled: false require_anton_for_live_actions: true default_mode: research_only
filesystem: restrict_to_workspace_root: true allow_shell_exec: false memory:
auto_write_on_completion: false require_review_for_high_impact_entries: true .env.example
DISCORD_BOT_TOKEN=REPLACE_ME QWEN_ROUTING_API_KEY=REPLACE_ME QWEN_GENERAL_API_KEY=REPLACE_ME
QWEN_ANTON_API_KEY=REPLACE_ME QWEN_CODER_API_KEY=REPLACE_ME Example JSON records Example task record
{ "task_id": "task_20260305_001", "created_at": "2026-03-05T22:10:00-06:00", "updated_at":
"2026-03-05T22:12:14-06:00", "source_lane": "chat", "source_channel": "jarvis",

"source_message_id": "192817261", "source_user": "Rollan", "trigger_type": "!task", "raw_request":
"!task research nq prop account rules and common failure points", "normalized_request": "Research NQ
prop account rules and common failure points.", "task_type": "research", "priority": "high",
"risk_level": "medium", "status": "running", "assigned_role": "Scout", "assigned_model":
"Qwen3.5-35B", "review_required": true, "approval_required": false, "parent_task_id": null,
"related_artifact_ids": ["artifact_20260305_014"], "related_approval_ids": [], "checkpoint_summary":
"Initial research sources gathered; drafting structured findings next.", "error_count": 0,
"last_error": null, "final_outcome": null } Example task event { "event_id": "evt_20260305_105",
"task_id": "task_20260305_001", "timestamp": "2026-03-05T22:12:14-06:00", "event_type":
"status_transition", "from_status": "queued", "to_status": "running", "actor": "core", "lane":
"task", "summary": "Task execution started.", "details": { "assigned_role": "Scout",
"assigned_model": "Qwen3.5-35B" }, "artifact_ids": [], "approval_id": null, "error": null }

Example artifact record { "artifact_id": "artifact_20260305_014", "created_at":
"2026-03-05T22:18:42-06:00", "updated_at": "2026-03-05T22:18:42-06:00", "task_id":
"task_20260305_001", "artifact_type": "research_note", "title": "NQ prop account rules and failure
patterns", "summary": "Structured research note covering common prop firm rules, evaluation
pitfalls, and risk management implications.", "path":
"/home/rollan/.openclaw/workspace/jarvis-v5/state/artifacts/ task_20260305_001/research_note.md",
"source_refs": ["web_search", "flowstate_distillation"], "generator_role": "Scout",
"generator_model": "Qwen3.5-35B", "review_status": "pending", "approval_status": "not_required",
"tags": ["nq", "prop", "research"], "metadata": { "word_count": 1280, "format": "markdown" } }
Example Flowstate source record { "source_id": "src_20260305_007", "created_at":
"2026-03-05T22:25:00-06:00", "submitted_by": "Rollan", "source_kind": "video_link", "source_url":
"https://example.com/openclaw-update-video", "source_path": null, "source_title": "OpenClaw Update
Walkthrough", "source_author": "Example Creator", "source_duration": 1260, "ingest_status":
"distilled", "transcript_artifact_id": "artifact_20260305_021", "distilled_artifact_id":
"artifact_20260305_022", "promotion_status": "awaiting_approval", "notes": "Potential ideas for
deploymentyment automation and Flowstate improvements." }

Example approval record { "approval_id": "approval_20260305_002", "task_id": "task_20260305_001",
"artifact_id": "artifact_20260305_014", "created_at": "2026-03-05T22:20:00-06:00", "requested_by":
"Anton", "route": "review", "title": "Approve promotion of research findings", "summary": "Research
note is complete and ready for promotion into outputs.", "options": ["approve", "reject", "rerun"],
"recommended_option": "approve", "risk_note": "Low operational risk; no live actions.", "status":
"pending", "timeout_at": "2026-03-06T02:20:00-06:00", "response": null, "responded_by": null,
"responded_at": null } Example review verdict { "verdict_id": "verdict_20260305_003", "task_id":
"task_20260305_099", "artifact_id": "artifact_20260305_044", "reviewer": "Archimedes",
"review_model": "Qwen3-Coder", "review_type": "code_review", "timestamp":
"2026-03-05T23:01:11-06:00", "decision": "changes_requested", "severity": "medium", "summary": "Code
is structurally solid but needs better error handling around Discord permission failures.",
"findings": [ "Permission failures are not surfaced clearly to the operator.", "Channel lookup code
should fail early with a clearer message." ], "required_changes": [ "Add explicit permission
diagnostics before attempting send operations.", "Return structured errors for missing or
inaccessible channels." ], "optional_suggestions": [ "Add a small preflight helper for channel
validation." ],

"approved_for_promotion": false } Script behavior specifications The deploymentyment and validation
scripts should be explicit, boring, and easy to rerun. scripts/install.sh Purpose: bootstrap a
first-time v5 installation on the host machine. Responsibilities verify required system tools are
present verify Python version is acceptable create required directory structure create virtual
environment if missing install Python dependencies copy example config files into real config
locations if missing generate a starter .env if missing set executable bits on helper scripts create
state/log/artifact directories optionally generate systemd unit files from templates run validate.py
at the end print concise success/failure summary Output expectations must clearly distinguish
between: completed successfully completed with warnings failed and requires action must print exact
file paths when something is created or missing must never silently skip a critical prerequisite
Failure handling fail fast on missing Python or broken venv creation fail clearly on dependency
install failure warn but continue for optional features only scripts/generate_config.py Purpose:
generate working config stubs from examples and known defaults.

Responsibilities create real config files from *.example.yaml if they do not exist support
interactive mode for first-time setup support non-interactive mode for automation preserve
user-edited files unless explicitly told to overwrite validate that channel/model/policy sections
are structurally complete optionally import known good values from prior v4 deploymentyment notes later
Output expectations report which files were created report which files were left untouched report
which required values are still placeholders scripts/validate.py Purpose: run preflight validation
before runtime startup. Responsibilities load .env and config files verify config files parse
correctly verify required secrets are present verify referenced directories exist and are writable
verify Discord token is valid verify guild/server binding is correct verify each configured channel
exists verify view/send permissions for each required channel verify model endpoints are reachable
verify configured model names respond successfully verify event backend is writable/reachable verify
artifact/state directories are writable verify optional Flowstate dependencies when enabled Output
expectations produce machine-readable JSON result option produce human-readable summary by default
group failures by category: config Discord models filesystem event backend optional features

Exit behavior exit non-zero on blocking failures exit zero with warnings only when the system can
still start safely scripts/doctor.py Purpose: rerunnable diagnostics and remediation assistant for a
deploymentyed system. Responsibilities rerun validation checks against the current environment inspect
service health if service files are in use inspect recent logs for known failure patterns summarize
current lane/channel readiness summarize model/provider readiness summarize common permission
problems provide exact next-step remediation text highlight mismatches between config and runtime
reality Output expectations clearly separate: passing checks warnings blocking failures each failure
should include: what failed where it failed likely cause exact next action Example failure classes
doctor should recognize invalid channel ID inaccessible channel due to permissions wrong working
directory in service file wrong interpreter path in service file model endpoint timeout invalid
model name unwritable state directory missing env var scripts/smoke_test.py Purpose: verify the
runtime can perform a minimal end-to-end baseline flow.

Responsibilities create a minimal synthetic task record move it through a basic lifecycle write at
least one artifact verify artifact path creation verify optional review object creation when enabled
verify basic status summary generation optionally test Flowstate source ingestion with a lightweight
dummy input Output expectations must clearly say what passed must clearly say the first failing step
if something breaks must not require a real production task to run Suggested command flow A clean
first-time setup should ideally look like: cd /home/rollan/.openclaw/workspace/jarvis-v5 bash
scripts/install.sh python3 scripts/generate_config.py python3 scripts/validate.py python3
scripts/smoke_test.py python3 scripts/doctor.py Future enhancements for the script layer
test_fresh_install.sh for clean-machine validation systemd unit generation from config values import
helper for stable v4 channel/config values redaction-safe diagnostics bundle for troubleshooting
Runtime service responsibilities The runtime should be divided by responsibility, not just by file
name. gateway Purpose: operator-facing intake and outward messaging boundary. Responsibilities
receive Discord messages and events

identify lane/channel origin enforce channel policy before work creation parse explicit task
triggers create intake envelopes for downstream processing send acknowledgements back to the
appropriate channel post status summaries, failures, and routed outputs never own long-running task
execution logic Inputs Discord messages reaction events approval responses service health/status
requests Outputs intake envelope records user-facing acknowledgements approval responses routed into
task state status requests routed to core/reporter Must not do long-running execution hidden task
creation from casual chat deep review logic direct live trading action core Purpose: main
orchestrator and execution spine for v5.0. Responsibilities normalize requests into task records
classify task type and risk assign role/model routing manage task lifecycle state transitions
execute normal task steps create artifacts checkpoint progress summaries request reviews/approvals
when policy requires emit task events for every meaningful transition maintain the current system
truth for active tasks

Inputs intake envelopes from gateway approved Flowstate promotions approval outcomes retry/rerun
requests config/policy settings Outputs task records task events artifacts review requests approval
requests status summaries for gateway/reporter Must not do bypass review/approval policy silently
change model families treat chat history as authoritative state directly own Discord transport
details outside defined interfaces auditor Purpose: review, verification, and risk gating.
Responsibilities run Archimedes code reviews run Anton higher-level final reviews apply review
policies consistently produce structured verdict records mark whether changes are required approve
or block promotion according to policy surface review rationale clearly Inputs review requests from
core artifacts to inspect task summaries/checkpoints policy/config rules

Outputs review verdict records review events approval requests when needed review summaries for
code-review/audit lanes Must not do execute the original task itself mutate task inputs silently
post incomplete/unstructured verdicts reporter Purpose: health, observability, summaries, and
operator visibility. Responsibilities summarize current task states summarize failures and blockers
summarize pending approvals/reviews emit heartbeat/ops health messages expose simple status views
for the operator surface queue depth / stalled task patterns collect structured logs and metrics
Inputs task events review events approval events service health checks validation/doctor outputs
Outputs status summaries health summaries alert summaries digest-style operational snapshots Must
not do become the source of truth for task state perform task execution invent state that is not
backed by records/events

flowstate Purpose: ingest-heavy lane for long-form source material. Responsibilities accept
media/source submissions fetch/open/process source when allowed create source records generate
transcript or extracted representation create distilled artifacts propose candidate actions/ideas
request approval before promotion into tasks or memory preserve reusable compressed outputs for
later retrieval Inputs links uploads text-heavy sources media metadata flowstate policy settings
Outputs source records transcript artifacts Flowstate distillation artifacts optional promotion
proposals Must not do automatically promote extracted ideas without approval dump raw large material
into every future context bypass source tracking Interface boundaries To avoid v4-style drift,
interfaces between services should be narrow and explicit. Gateway → Core Should pass: - lane

- source channel
- source user
- trigger type
- raw content
- referenced
- request timestamp Should not pass: - giant pre-expanded history by default
- hidden inferred task state

Core → Auditor Should pass: - task ID

- artifact ID
- review type
- compact checkpoint summary
- relevant the minimum required supporting context Should not pass: - whole noisy chat logs unless explicitly necessary Core/Flowstate → Reporter Should pass: - event summaries
- status snapshots
- failure details
- approval/review counts Should not pass: - raw unstructured dumps when a compact event exists Runtime anti-patterns to avoid chat handling mixed with execution logic in one giant file module imports that assume symbol names without compatibility checks task state inferred from message scrollback raw transcript stuffing into review prompts reviewers also serving as primary executors silent fallback to different providers/model families Suggested runtime file layout runtime/ gateway/ __init__.py discord_intake.py acknowledgements.py approval_reactions.py core/ __init__.py intake.py task_store.py task_events.py routing.py execution.py checkpoints.py status.py auditor/ __init__.py archimedes.py anton.py verdicts.py reporter/

__init__.py health.py digests.py alerts.py status_views.py flowstate/ __init__.py ingest.py
transcript.py distill.py promotion.py Operational sequence examples Example: explicit task from
#jarvis

1. gateway receives !task ...
2. gateway validates channel policy
3. gateway creates intake envelope
4. core creates task record core emits received → classified → queued
5. 6. core begins execution
7. artifacts are created
8. review/approval invoked if policy requires
9. reporter surfaces progress and result Example: Flowstate source
1. gateway or Flowstate intake receives source
2. Flowstate creates source record
3. transcript/extraction artifact is created
4. distillation artifact is created
5. promotion proposal is created
6. approval is required before new tasks/memory entries are created Example: completed code task
1. core marks task ready for review
2. auditor routes to Archimedes
3. verdict record produced
4. if deploymenty-risk/high-risk, Anton final pass runs
5. final approval/promotion decision recorded Draft docs content These drafts define the intended content for the initial docs/ files.

docs/channels.md # Jarvis v5 Channel Policy ## Purpose This document defines what each Discord
channel is for and what behavior is allowed there. ## Core rule Conversation is not execution. A
normal message in `#jarvis` must never create work automatically. ## Channels ### `#jarvis` Purpose:
conversation, orchestration, status, planning, quick updates. Allowed: - ordinary chat

- status questions
- planning questions
- explicit task creation via `!task ...`, `task: ...`, or `task ...` if enabled Not allowed: - automatic task creation from ordinary conversation
- long-running execution logic
- posting noisy work logs by default ### `#tasks` Purpose: explicit task intake and task progress. Allowed: - formal work requests
- task progress updates
- task lifecycle notices Not allowed: - general chat that obscures work state ### `#outputs` Purpose: final deliverables and useful artifacts. Allowed: - completed reports
- summaries
- final plans

- approved artifacts Not allowed: - noisy intermediate logs ### `#review`

Purpose: approval decisions. Allowed: - approval prompts

- reaction-based decisions
- short clarification prompts when needed ### `#alerts` Purpose: important failures, blocked states, operational notices. Allowed: - blocking failures
- warnings requiring operator attention
- service-health alerts ### `#code-review` Purpose: Archimedes code-review outputs. Allowed: - structured code-review verdicts
- required changes
- code risk notes ### `#audit` Purpose: Anton summaries, higher-level review, integrity notes. Allowed: - final review summaries
- higher-level audit notes
- operator-facing oversight output ### `#flowstate` Purpose: ingest/transcribe/distill/idea extraction lane. Allowed: - source material drops
- transcription notices
- distillation results
- promotion proposals requiring approval Not allowed: - automatic promotion of ideas into tasks or memory without approval

## Task creation rules Task creation is explicit. Accepted task triggers in `#jarvis`: - `!task ...` - `task: ...` - `task ...` when enabled and reliably parsed ## Status behavior When asked for status in `#jarvis`, Jarvis should summarize:

###

1. what is running

###

2. what is blocked

###

3. what is awaiting approval

###

4. what finished recently

###

5. the next recommended move

docs/review-policy.md # Jarvis v5 Review Policy ## Purpose This document defines when Archimedes or
Anton must review work and what their roles are. ## Reviewer roles ### Archimedes Archimedes is the
specialized code reviewer. Responsibilities:

- review completed code tasks
- identify bugs, weak assumptions, missing checks, and risky changes
- provide structured verdicts with required changes and optional suggestions ### Anton Anton is the broader final reviewer and risk gate.

Responsibilities:

- review risky or high-value work
- provide final synthesis review
- gate promotion of sensitive outputs
- act as a higher-level operator-facing reviewer ## Review rules

### Non-code tasks

- safe/low-risk tasks do not always require heavy review
- risky, publish-worthy, high-value, or sensitive non-code tasks should route to

### Anton

### Code tasks

- all completed code tasks route to Archimedes
- deploymenty-related, production-facing, or otherwise risky code can route to Anton after Archimedes ### Trading / quant tasks
- research and setup outputs may be reviewed based on policy and importance
- live-action pathways require stricter approval and review ## Verdict structure Every review should produce a structured verdict containing: - summary
- findings
- required changes
- optional suggestions
- approval decision or promotion decision ## Promotion rule No risky output should be promoted just because a task finished. Review policy decides whether it is actually ready. docs/flowstate.md # Jarvis v5 Flowstate Policy ## Purpose Flowstate is the ingest-heavy lane for source material that should be processed once and reused efficiently. ## Why Flowstate exists Long videos, audio clips, links, and large source material should not be repeatedly stuffed into model context. Flowstate solves this by: - ingesting the source once
- creating transcript/extraction artifacts once
- creating a distilled artifact once
- letting future work use the distilled artifact instead of the raw source ## Typical Flowstate flow

###

1. user drops a source

###

2. system records source metadata

###

3. system transcribes or extracts content

###

4. system distills the content into a compact artifact

###

5. system proposes ideas/actions

###

6. user approves promotion before it becomes a task or memory

## Distilled artifact should include

- concise summary
- key claims
- key ideas
- candidate action items
- notable sections/timestamps
- caveats or uncertainties ## Promotion rule Flowstate outputs do not automatically become tasks, memory, or system-wide assumptions. Promotion requires explicit approval. ## Context rule Future tasks should prefer the distilled artifact over the raw transcript or raw source whenever possible. docs/deploymentyment.md # Jarvis v5 Deployment Guide ## Goal Deployment should be boring, explicit, and diagnosable. ## First-time setup flow

###

1. create or unpack the repo in the intended workspace path

###

2. run `bash scripts/install.sh`

###

3. run `python3 scripts/generate_config.py`

###

4. fill in required secrets and real config values

###

5. run `python3 scripts/validate.py`

###

6. run `python3 scripts/smoke_test.py`

###

7. run `python3 scripts/doctor.py`

###

8. start services only after the validation baseline passes

## Deployment contract A healthy deploymentyment should confirm: - config files parse

- required secrets are present

- directories are writable
- Discord channel bindings are valid
- Discord permissions are sufficient
- model endpoints are reachable
- configured model names work
- state/event backend is usable
- a basic smoke test passes ## Failure philosophy Fail early and specifically. The system should not appear healthy while critical prerequisites are broken. ## Common classes of deploymentyment failure
- missing env vars
- invalid channel IDs
- inaccessible channels
- wrong guild binding
- wrong working directory in service file
- wrong interpreter path in service file
- unreachable model endpoint
- invalid configured model name
- unwritable state directories ## Doctor workflow `doctor.py` should be rerunnable at any time and provide: - pass/fail summary
- warnings
- blocking failures
- exact remediation steps docs/migration-from-v4.md # Jarvis v5 Migration from v4 ## Purpose This document records what v4 taught us and how those lessons map into v5. ## What v4 got right
- strong operator identity for Jarvis
- clear need for Anton and Archimedes as separate reviewer roles
- useful Discord-first workflow
- strong need for approval gates
- useful idea behind Flowstate/media distillation ## What v4 got wrong or handled weakly

- chat and execution were too entangled
- ordinary conversation could enqueue work unintentionally
- module responsibilities blurred together
- post-deploymenty issues were discovered too late
- deploymentyment required too many manual fixes
- context could grow in messy ways ## v5 responses to those lessons - `#jarvis` is chat-only by default
- task creation is explicit
- task state is durable and structured
- review policy is clearer
- Flowstate is a first-class lane
- validation and doctor tooling are part of the deploymentyment contract
- artifacts and summaries are preferred over repeated raw-source stuffing ## Migration notes to preserve from the final v4 tar This section should be updated after the stabilized v4 tar is available. Capture: - final working channel layout
- final service launch order
- final model/provider mappings
- all manual post-deploymenty fixes that were required
- Discord permission lessons
- any runtime path or interpreter issues discovered on Snowglobe Validator check catalog validate.py should check grouped requirements in a deterministic order. Group 1
- config integrity Checks: - required config files exist
- YAML parses successfully
- required top-level sections placeholder values are detected and flagged
- config values agree on key paths where required Blocking failures: - missing config file
- invalid YAML
- required section missing Warnings: - optional section missing
- placeholder values still present in optional fields Group 2
- secrets and environment Checks: - .env exists when required
- required secret names are present
- secret values are no workspace root / state root environment assumptions are consistent Blocking failures: - missing Discord token
- missing required provider/API key for enabled model path

Warnings: - optional integration secret missing Group 3

- filesystem Checks: - workspace root exists
- state root exists or can be created
- logs/artifacts/app directories exist or can be created
- configured paths are writable
- configured runtime pat obviously inconsistent Blocking failures: - unwritable state root
- invalid configured path
- artifact/log/task directories ca created Group 4
- Discord connectivity Checks: - bot token authenticates
- configured guild/server is reachable
- each required channel I
- each required channel is visible to the bot
- each required channel is sendable by the bo message history access exists where needed
- reaction permission exists where review flow requires it Blocking failures: - invalid bot token
- missing required channel
- inaccessible required channel send permission in required outbound channel Warnings: - optional channel inaccessible
- reaction permission missing where fallback interaction exists Group 5
- model/provider readiness Checks: - configured provider base URLs are reachable
- configured model names accept a m request
- timeouts are sane
- fallback policy stays within allowed family
- enabled coder/anton models are testable Blocking failures: - primary routing/general/anton model unavailable
- configured model name inva provider endpoint unreachable for required lane Warnings: - optional model unavailable
- fallback list missing for non-critical lane Group 6
- event/state backend Checks: - configured backend mode is supported
- SQLite file or Redis backend is reachable writable
- a tiny write/read/delete cycle succeeds Blocking failures: - backend unreachable
- backend not writable
- backend mode unsupported Group 7
- optional feature readiness Checks: - Flowstate dependencies when Flowstate is enabled
- multimodal tool path when multi enabled
- service unit paths if systemd mode is enabled

Warnings by default unless feature is marked required. Doctor output contract doctor.py should be
optimized for fast operator triage. Output sections

1. overall health verdict
2. passing checks
3. warnings
4. blocking failures
5. recommended next actions
6. recent known-failure patterns if logs are available Overall verdict values healthy healthy_with_warnings degraded blocked Per-issue structure Each issue should include: - severity
- category
- title
- what_failed
- likely_cause
- where
- recommended_fix
- is_blocking Human-readable example OVERALL: blocked Blocking failures: - Discord / Missing send permission / #review Cause: bot can view channel but cannot send messages Fix: grant Send Messages permission to the bot role in #review Warnings: - Models / Coder lane unavailable Cause: Qwen3-Coder test request timed out Fix: check coder endpoint or disable coder lane temporarily Next actions:

###

1. Fix #review permissions

###

2. Re-run validate.py

###

3. Re-run doctor.py

Machine-readable mode Doctor should support JSON output so later dashboards or scripts can consume
the results. Task lifecycle transitions Task status changes should follow explicit allowed
transitions. Allowed transitions received -> classified classified -> planned classified -> queued
planned -> queued queued -> running running -> awaiting_review running -> awaiting_approval running
-> completed running -> failed awaiting_review -> awaiting_approval awaiting_review -> completed
awaiting_review -> failed awaiting_review -> queued (when changes are required and rerun is
appropriate) awaiting_approval -> approved awaiting_approval -> rejected approved -> completed
rejected -> queued (if rerun/rework is chosen) rejected -> archived completed -> archived failed ->
queued (retry path) failed -> archived Illegal transitions to reject Examples: - received ->
completed

- queued -> approved
- completed -> running
- archived -> anything unless explicitly restored by an admin/operator tool later Lifecycle rules every transition must emit a task event every transition should update updated_at failed must record last_error completed should record final_outcome checkpoint summaries should be updated at major phase boundaries

Approval interaction rules Approvals should be simple, deterministic, and reaction-friendly in v5.0.
Initial approval interaction model Primary path: - message posted in #review

- user reacts with predefined approval emoji or rejection emoji Supported initial outcomes approve reject rerun escalate Reaction mapping Suggested mapping: - ✅ approve - ❌ reject - 🔁 rerun - ⬆️ escalate This can be changed later, but the mapping should be documented and stable. Approval message requirements Every approval prompt should include: - task ID
- short title
- short summary
- option recommended option
- risk note if relevant
- timeout if relevant Approval timeout behavior When timeout is reached: - mark approval status as expired
- emit approval/task event
- do not silently auto-approve
- route to reporter/alerts if the approval was blocking Approval safety rules only authorized users/reactions count duplicate conflicting reactions should resolve to the first valid decisive reaction unless policy says otherwise reaction removal should not silently undo an already-recorded approval outcome approval outcomes should be written durably before downstream action continues Escalation behavior If escalated: - keep task blocked from promotion
- create an escalation note/event
- surface in #review summary

Review routing rules Code review routing When task type is code-related and status reaches review
phase: - route to Archimedes

- c request record
- wait for verdict
- if verdict is changes_requested , route back to queue/rerun path
- if verdict is approved and task is high-risk/deploymenty-related, optionally route to Anton final pass Anton routing Anton should be triggered when: - task is marked high-risk
- task involves sensitive outputs
- facing or publish-facing
- policy explicitly requires Anton for the task category Non-review completion Low-risk tasks that do not require review may complete directly, but should still produce artifa normally. Artifact promotion rules Artifacts should not all be treated the same. Promotion policy determines what becomes visible, or durable beyond the current task. Promotion levels task_local
- only relevant to the current task review_ready
- ready for reviewer inspection output_ready
- ready to appear in #outputs memory_candidate
- suitable for possible long-term memory writeback archival
- preserve for audit/history only Default promotion guidance by artifact type summary -> task_local or output_ready depending on quality and purpose plan -> task_local unless explicitly approved for wider reuse report -> review_ready then output_ready code_patch -> review_ready code_review -> archival and optionally output_ready in #code-review audit -> archival and optionally output_ready in #audit transcript -> archival by default flowstate_distillation -> review_ready , then memory_candidate or task-promotion candidate on approval research_note -> review_ready then output_ready trading_setup -> review_ready ; promotion depends on trading policy simulation_result -> review_ready then output_ready if meaningful draft_order -> review_ready only, never auto-promote to live action

final_output -> output_ready Promotion rules transcripts should not be treated as final outputs by
default raw source artifacts should usually remain archival/reference only reviewer verdicts should
influence promotion level approval-required artifacts must not promote automatically risky artifacts
must not become memory entries without policy approval Output posting rule Before an artifact is
posted to #outputs , the system should verify: - artifact exists and path is va artifact summary is
present

- review/approval requirements have been satisfied
- the artifact superseded by a newer version Memory writeback policy Memory should be selective, structured, and reversible where possible. What memory is for Memory is for durable lessons, reusable facts about workflows, stable preferences, and approved knowledge
- not for dumping every task result. Good memory candidates stable operator preferences durable workflow rules validated deploymentyment lessons approved Flowstate distillations with reusable value recurring task heuristics that proved useful long-lived system constraints Poor memory candidates raw transcripts temporary debugging state one-off noisy failures without lessons extracted speculative claims not yet approved incomplete task outputs redundant summaries of already-archived artifacts Memory writeback rules memory writeback should be off by default for high-impact categories unless approved writebacks should store compact structured summaries, not raw blobs

each memory write should link back to source task/artifact IDs memory entries should carry
confidence/approval metadata memory entries derived from Flowstate should require promotion approval
first Suggested memory entry fields memory_id created_at source_task_id source_artifact_id
memory_type title summary tags confidence approved_by notes Task classification taxonomy Task
classification should be constrained so routing is predictable. Primary task categories status
planning research flowstate_ingest code code_review audit trading_research trading_setup simulation
draft_order deploymentyment ops memory_update Risk levels low medium high restricted

Priority levels low normal high urgent Classification rules explicit task trigger text should
influence classification strongly lane/channel origin should influence classification but not
override explicit content blindly Flowstate submissions should default to flowstate_ingest code
changes should default to code deploymentyment/config fixes should default to deploymentyment or ops anything
proposing live market action should not remain a generic task class Error taxonomy A consistent
error taxonomy makes logs, doctor output, and retry behavior far easier to manage. Error categories
config_error env_error filesystem_error discord_auth_error discord_permission_error
discord_channel_error model_connection_error model_timeout_error model_response_error
event_backend_error artifact_error review_error approval_error flowstate_ingest_error
flowstate_transcript_error flowstate_distill_error routing_error policy_violation unknown_error
Error severity levels info warning error

critical Retry guidance by error class model_timeout_error -> retryable in many cases
model_connection_error -> retryable after short backoff discord_permission_error -> not retryable
until fixed config_error -> not retryable until fixed policy_violation -> not retryable without
operator/policy change filesystem_error -> depends on cause; usually requires remediation first
review_error -> retryable if caused by transient model/provider issue Suggested structured error
record error_id timestamp task_id artifact_id service category severity message details retryable
recommended_action Logging and metrics policy Logs should support both debugging and operational
summaries. Logging rules use structured logs where practical include task IDs and artifact IDs
whenever relevant avoid logging raw secrets avoid logging huge blobs when a path/reference is enough
prefer concise event-style records over giant freeform prints Minimum important log fields timestamp
service lane task_id event_type status message

error_category Metrics to track early tasks created per lane tasks completed tasks failed average
task duration by category number of pending approvals number of pending reviews Flowstate sources
processed model timeout count Discord permission/channel failures Promotion and completion policy
Task completion should not imply broad promotion automatically. Completion rule A task can be marked
completed when its defined objective is met. Promotion rule A completed artifact/result can only be
promoted to broader visibility or memory when: - requi has passed

- required approval has passed
- policy allows promotion for that artifact/task type Archive rule Everything important should remain traceable even if it is not promoted. Artifacts, verdicts, approvals, and key events should be archivable even when they are not output-ready. Policy matrices Policy matrices make routing and enforcement deterministic. Task → Reviewer matrix Task Type

### Archimedes

### Anton

Notes code required optional Anton only if deploymenty or high risk code_review required no already
code-review lane deploymentyment optional required infra risk

Task Type

### Archimedes

### Anton

Notes research no optional Anton if publication quality trading_research no optional Anton if
strategy impact trading_setup optional required strategy gate simulation no optional review if
unusual results draft_order optional required must never auto-promote ops optional optional
depending on severity Task → Approval matrix Task Type Approval Required Notes research no unless
publish/promotion code sometimes if deploymenty-related trading_setup yes operator gate draft_order yes
never auto execute deploymentyment yes production risk memory_update yes prevents memory pollution
Artifact → Promotion matrix Artifact Type Promote to Outputs Promote to Memory Notes summary yes no
ephemeral by default report yes optional if reusable knowledge code_patch no no review lane only
code_review optional no archival mostly flowstate_distillation optional yes after approval
research_note yes optional if reusable simulation_result optional no unless insight transcript no no
archival only State storage design The system should separate structured state, artifacts, and logs.

State categories

1. task state
2. approval state
3. review state
4. artifact metadata
5. memory entries Storage guidance State Type Storage task records SQLite / structured JSON approval records SQLite review verdicts SQLite + artifact link artifact metadata SQLite artifacts filesystem logs log files / structured logs Artifact directory pattern state/ artifacts/ <task_id>/ artifact_1.md artifact_2.json File naming guidance use task_id prefixes avoid spaces prefer deterministic naming Example: T1234_summary.md T1234_simulation_results.json Versioning rule If an artifact is regenerated:

T1234_summary_v2.md Previous versions should not be silently overwritten. Provider and model routing
rules v5 uses only Qwen family models as requested. Routing lanes Lane Model routing Qwen3.5‑9B
general Qwen3.5‑35B heavy reasoning Qwen3.5‑122B code analysis Qwen coder model flowstate distill
Qwen3.5‑35B Routing policy routing model decides classification and routing general model handles
most execution tasks 122B reserved for difficult reasoning or Anton coder model used by Archimedes
Fallback rules Fallbacks must stay within the Qwen family. Example fallback chain: 122B → 35B → 9B
Fallback events should be logged clearly. Provider abstraction Providers may include: local
inference (NiMo) hosted inference

The system should log: provider model name request duration Flowstate ingestion rules Flowstate is
designed for large or media-heavy inputs. Accepted source types YouTube links audio clips uploaded
video long documents research threads Ingestion steps

1. source metadata capture
2. download or fetch content
3. transcript extraction
4. content segmentation
5. distillation pass
6. idea extraction Size constraints To avoid runaway processing: extremely long videos should be chunked transcripts should be segmented Distillation structure Flowstate distillation artifacts should include: concise summary key ideas actionable insights notable timestamps potential tasks Promotion rule Distillations do not automatically create tasks.

User approval is required before promotion. Event system specification The event system is the
coordination backbone of v5.

## Purpose

The event system exists so services communicate through durable, structured events instead of
implicit state. Core event principles every meaningful state change emits an event events are
append-only events are timestamped events are linked to task IDs and artifact IDs when relevant
events should be compact summaries, not giant raw dumps downstream services should consume events
rather than infer state from chat history Event record fields Minimum fields: - event_id

- timestamp
- service
- lane
- event_type
- task_id
- artifact_id
- approval_id
- source_id
- severity
- summary
- payload Event types Suggested core event types: - task_created
- task_classified
- task_planned
- task_queued
- task_started
- task_checkpoint
- task_completed
- task_failed
- review_requested
- review_completed
- approval_requested
- approval_recorded
- artifact_created
- artifact_promoted -

artifact_archived -

flowstate_source_received

- flowstate_transcript_created
- flowstate_distilled
- doctor_run
- validation_run
- service_health Event consumption guidance gateway consumes status-oriented events core consumes intake, approval, and rerun events auditor consumes review-request events reporter consumes nearly all event categories for summaries/health views flowstate consumes source-ingest events and emits transcript/distill events Event backend modes Supported backend modes should be: - sqlite
- redis (optional)

Event retention guidance keep recent events queryable for fast operator status archive older events
rather than deleting immediately when possible allow summary compaction later if event volume grows
Concurrency and workload policy v5 should avoid uncontrolled parallelism. Core concurrency
principles default to safe bounded concurrency never let Flowstate ingestion starve interactive
Jarvis status/help never let low-priority work block approvals or alerts reserve capacity for urgent
operator-driven tasks Suggested initial concurrency limits routing/classification tasks: up to 4
concurrent lightweight operations general execution tasks: 1-2 concurrent by default Anton reviews:
1 at a time by default Archimedes code reviews: 1 at a time by default Flowstate ingest jobs: 1
active heavy ingest by default approval handling: effectively immediate / lightweight Priority
preemption guidance Urgent user-driven work should preempt background low-priority work where
feasible. Suggested priority order:

1. approval handling
2. alerts / blocking failures
3. direct operator requests
4. active code/review tasks
5. background Flowstate ingestion
6. low-priority autonomy tasks Retry/backoff guidance model timeouts: short exponential backoff provider connection failures: short retry then degrade/warn permission/config failures: do not hot-loop retries Flowstate fetch failures: bounded retries with clear logging Workload safety rules do not launch unlimited retries do not flood the same model/provider with duplicate concurrent work unnecessarily do not start a second heavy Flowstate ingest unless policy/concurrency allows it do not let autonomy loops continuously regenerate the same failed task without a rerun policy

Autonomy and Ralph loop specification The autonomy layer should act like a disciplined night-shift
operator, not an uncontrolled agent swarm.

## Purpose

The Ralph loop exists to advance queued work, research, and follow-up processing during auto windows
while staying bounded by policy, review gates, and approvals. Core autonomy principles autonomy is
for progressing work, not bypassing oversight autonomy should prefer unfinished queued tasks over
inventing busywork autonomy should create artifacts/checkpoints, not hide what it did autonomy must
respect review and approval boundaries autonomy should stop escalating itself when blocked Suggested
autonomy window Initial target window: - approximately 2:00 AM to 3:00 PM America/Chicago This
should be configurable. Autonomy responsibilities During active window, the loop may: - inspect
queued tasks

- resume retryable failed tasks
- running research tasks
- process approved Flowstate promotions
- generate checkpoint summar prepare review-ready artifacts
- queue approval requests when policy requires
- produce ops/status for the operator Autonomy must not do bypass required approvals auto-promote risky outputs place live trading actions without the dedicated restricted path and policy approval endlessly re-run the same failing task without a retry policy spam channels with noisy intermediate chatter Suggested Ralph loop cycle
1. read current system state
2. identify eligible tasks
3. rank by priority, age, and policy eligibility
4. pick next bounded unit of work
5. execute one chunk
6. write checkpoint/event/artifact

7. request review/approval if needed
8. emit digest/health update if appropriate
9. sleep/backoff before next cycle Eligible task criteria A task is eligible for autonomous work if: - it is in queued or retryable failed
- required dependencies are available
- it is not blocked on approval or review
- it is within policy and time-window rules Autonomy scoring hints When ranking eligible work, consider: - priority
- age/staleness
- user importance tags
- trad importance
- whether the task is close to completion
- whether Flowstate-derived ideas have alr approved Suggested autonomy outputs checkpoint summaries ready-for-review artifacts morning or periodic ops digest concise statement of what changed during the loop Digest and reporting policy for autonomy Autonomy should leave a visible paper trail. Digest cadence guidance send a concise startup summary when autonomy begins if useful send periodic summaries only when meaningful work changed send a stronger summary at the end of a major autonomy block or at window end Digest contents A useful autonomy digest should include: - tasks advanced
- tasks blocked
- approvals now n artifacts produced
- notable failures
- recommended next human action Noise control rules do not post a digest if nothing meaningful changed combine repeated similar failures into one summary prefer one concise digest over many tiny updates Idle behavior policy When no eligible task exists, autonomy should not invent random work blindly.

Preferred idle actions generate a concise health/status summary inspect pending approvals/reviews
surface stale blocked tasks look for approved Flowstate promotions waiting to become tasks perform
low-risk housekeeping only if explicitly enabled Disallowed idle behavior creating speculative tasks
without grounded source material or policy basis spamming “nothing to do” messages repeatedly
polling external services too aggressively Security policy matrix Security in v5 should be
practical, visible, and policy-driven. Core security principles secrets should never be
unnecessarily exposed to model context risky actions must go through explicit restricted pathways
approvals should only count from authorized operators chat should never directly execute sensitive
actions logs should preserve diagnostics without leaking secrets Approval authority matrix Action
Type Who Can Approve Notes low-risk artifact promotion authorized operator reaction-based approval
allowed memory writeback authorized operator prevents memory pollution deploymentyment change promotion
authorized operator higher scrutiny trading setup promotion authorized operator strategy gate draft
order approval authorized operator still not live execution live trading action restricted operator
path only never casual-chat approval Tool sensitivity matrix Tool / Capability Sensitivity Default
Policy Discord message send medium allowed through gateway/runtime only filesystem write inside
workspace medium allowed by policy

Tool / Capability Sensitivity Default Policy filesystem write outside workspace high blocked by
default shell exec high blocked by default external fetch/download medium allowlisted by policy
model/provider API calls medium allowed via configured paths live trading execution restricted
disabled by default memory writeback medium controlled by policy Secrets handling rules secrets live
in .env or protected runtime environment secrets should not be printed in logs secrets should not be
written into artifacts model prompts should not include raw API keys or tokens diagnostics should
redact sensitive values by default Discord security rules bot token validity should be validated
early required permissions should be checked before runtime action where feasible only authorized
users should count for approvals or sensitive triggers channel misconfiguration should block startup
for required channels Live trading guardrails live trading must be disabled by default live trading
requires dedicated restricted mode/tool path live trading approval cannot be satisfied by casual
conversation alone live trading actions should produce explicit audit records draft orders must
remain non-executable until promoted through the correct path Policy violation handling When a
requested action violates policy: - block the action

- emit a policy_violation error/event
- explain why it was blocked
- suggest the correct approval or routing path if one exists Task chunking and planning policy Large tasks should be broken into bounded, reviewable units of work. Chunking principles one task should not become an unbounded prompt blob

chunking should preserve traceability between parent and child work each chunk should end with a
checkpoint summary or artifact when meaningful chunk boundaries should align with actual phases of
work When to split a task A task should be considered for chunking when: - it spans multiple
distinct phases

- it req different roles/models
- it is likely to exceed comfortable context limits
- it produces multiple m
- it has been retried multiple times without clean progress Suggested chunk types research chunk synthesis chunk implementation chunk review-prep chunk review chunk approval-prep chunk Flowstate extraction chunk Parent/child task rules parent tasks may spawn child tasks when chunking is needed child tasks should reference parent_task_id parent task should not be considered complete until required child tasks are resolved child outcomes should roll up into the parent checkpoint summary Planning granularity rules A plan should be detailed enough to guide execution, but not so detailed that it becomes stale immediately. Good plan structure:
1. objective
2. constraints
3. phases
4. expected artifacts
5. likely review/approval points Checkpoint rules After each major chunk, write a checkpoint summary containing: - what was completed
- what artifacts produced
- blockers
- next recommended chunk Retry and escalation policy one transient failure does not require full replanning repeated identical failures should trigger escalation or replanning after a bounded number of retries, the task should surface as blocked rather than hot-looping

Suggested retry guidance transient provider/model issues: 1-2 retries Flowstate fetch/transcript
issues: bounded retries with backoff policy/config/permission failures: do not retry without
intervention repeated review failures: requeue with explicit required-changes summary Chunk
completion rule A chunk can be considered done when: - its intended artifact or summary exists

- required sta written
- next step is clear
- any required review handoff is prepared Planning anti-patterns to avoid giant single-shot tasks with no checkpoints repeatedly re-summarizing the entire task history spawning child tasks without linking them back to a parent re-running the exact same failing chunk without new information forcing Anton/Archimedes to review raw sprawl instead of targeted outputs Dashboard and operator view specification The operator surface should emphasize fast situational awareness, not clutter. Core dashboard principles show current truth, not speculative state prioritize blocked work and approvals over vanity metrics keep the most actionable information visible first make it easy to drill from summary -> task -> artifact -> review/approval reflect the three main lanes: chat/task/flowstate Suggested primary views

###

1. Health view

Purpose: answer “is the system healthy right now?” Should show: - overall health verdict

- gateway/core/auditor/reporter/flowstate service status
- current backend status
- model/provider readiness summary
- latest doctor/validate result summary
- critical/warning failures

###

2. Tasks view

Purpose: answer “what work exists and what state is it in?”

Should show: - active tasks

- queued tasks
- failed tasks
- blocked tasks
- completed recently type, priority, risk, lane Each task row/card should expose at least: - task ID
- normalized title/request
- status
- assigned role/model
- latest checkpoint summary
- last updated time

###

3. Approvals view

Purpose: answer “what is waiting on me?” Should show: - pending approvals

- timeout windows
- recommended option
- related task/artifact risk note

###

4. Review view

Purpose: answer “what is under review and what changed is required?” Should show: - pending code reviews

- Anton reviews
- recent verdicts
- decisions: approved requested / rejected

###

5. Outputs view

Purpose: answer “what useful artifacts exist?” Should show: - recent reports

- final outputs
- research notes
- simulation outputs
- promot distillations

###

6. Flowstate view

Purpose: answer “what sources have been ingested and what ideas came out of them?” Should show: -
recent sources

- ingest status
- transcript presence
- distillation presence
- promo candidate actions

###

7. Alerts / Failures view

Purpose: answer “what needs attention because something is wrong?” Should show: - current blocking failures

- degraded subsystems
- repeated retry failures
- rec violations
- direct links to relevant task/service context

###

8. Autonomy / Ralph view

Purpose: answer “what did the night shift do?”

Should show: - active autonomy window status

- tasks advanced autonomously
- tasks autonomously
- approvals generated
- artifacts generated
- last digest summary Operator drill-down expectations From any task or artifact summary, the operator should be able to reach: - latest checkpo artifacts
- related approvals
- latest review verdict
- recent failure history Minimal v5.0 implementation guidance v5.0 does not need a huge custom dashboard to satisfy this spec. A compact status/reporting is acceptable so long as these questions can be answered quickly. Testing and evaluation matrix Testing should verify both correctness and operator usability. Testing principles test the deploymentyment path, not just isolated code test policy enforcement, not just happy-path execution test lane separation explicitly test failure reporting quality, not just failure occurrence include synthetic end-to-end scenarios before trusting live workflows Test layers Unit tests Target: - config parsing
- task classification
- lifecycle transition validation
- approval reaction promotion rule evaluation
- policy violation detection
- error taxonomy mapping Integration tests Target: - gateway -> core intake flow
- core -> auditor review flow
- core -> reporter event ingest -> transcript -> distill flow
- approval recording -> task continuation flow Smoke tests Target: - fresh install baseline
- config generation baseline
- validate/doctor baseline
- minimal syn lifecycle
- minimal synthetic Flowstate ingestion

Policy enforcement tests Target: - casual chat in #jarvis does not enqueue work

- explicit task trigger does enqueue wo restricted actions are blocked without approval
- memory writeback is blocked when policy approval
- transcript artifacts do not auto-promote Reliability tests Target: - model timeout handling
- provider unavailability handling
- Discord permission failure ha invalid channel/config detection
- repeated retry escalation behavior Operator UX tests Target: - status request produces concise useful answer
- approval prompt includes required fields output gives actionable remediation
- autonomy digest is concise and useful Acceptance scenarios before deploymenty Before calling a v5 build deploymentyable, it should pass scenarios like:
1. #jarvis status message produces no task creation
2. !task ... creates a durable task record
3. a code task routes to Archimedes review
4. a high-risk non-code task can route to Anton
5. a Flowstate source produces transcript + distillation artifacts
6. a required approval blocks promotion until operator response
7. a Discord permission issue is caught by validate/doctor with clear remediation
8. a missing model/provider is surfaced clearly without silent family switch
9. a failed task does not hot-loop endlessly
10. a completed artifact can be promoted only when policy allows Suggested release gates A build should not be considered ready for normal use unless: - validation passes with no blo smoke test passes
- lane separation tests pass
- policy enforcement tests pass
- at least one run passes
- at least one Flowstate run passes Future evaluation extensions Later, add: - regression test suite for common deploymentyment pain points
- benchmark tasks for q research quality
- benchmark tasks for code review quality
- autonomy productivity metrics over cycle Migration and compatibility strategy The v5 build should learn from v4 without inheriting v4's ambiguity.

Migration goals preserve useful working configuration where possible preserve deploymentyment lessons
explicitly avoid blindly porting broken assumptions make v4 -> v5 mapping visible and auditable What
to import from the stabilized v4 tar When the next validated v4 tar is available, inspect and map: -
final working channel names final service launch order

- final working provider/base URL settings
- final environment variable n requirements
- any hardcoded paths that proved necessary on Snowglobe
- any post-deploymenty manu that were still required
- any Discord permission lessons
- any watchdog/reporting logic that prov any real Flowstate/media handling improvements Migration categories Category 1
- carry forward directly Items that should likely port with minimal change: - channel IDs and naming that proved corre endpoints that proved stable
- required environment variable names
- service path corrections th verified on Snowglobe Category 2
- carry forward with adaptation Items that may port but need reshaping: - task/review logic
- watchdog/heartbeat reporting p current Flowstate handling
- memory/artifact directory organization Category 3
- do not carry forward blindly Items likely to require redesign or strict review: - chat/execution entanglement
- CrewAI-heavy orche assumptions
- module interfaces that drifted without contracts
- manual deploymentyment steps that become scripted Migration record format Each imported lesson from v4 should be recorded with: - lesson_id
- category
- source_file_or_service
- what_worked
- what_failed
- v5_action
- notes Compatibility principle v5 may preserve useful external behavior while changing the internal structure. For example: - same Discord channels
- improved internal routing
- same provider settings
- im event/state model

Migration anti-patterns to avoid copying old files forward just because they exist preserving
confusing naming without documenting it importing manual post-deploymenty steps as tribal knowledge
instead of automation treating a workaround as a design principle Release roadmap and milestone plan
The roadmap should move v5 from specification -> bootstrap -> runnable core -> reviewed outputs.
Milestone 0

- freeze design inputs Goal: stop architecture churn and collect operational truth. Deliverables: - stabilized v5 spec
- deploymentyment lessons document from v4
- final v4 tar comparison
- list of open migration questions Exit criteria: - major design decisions are no longer being re-litigated
- known v4 pain documented clearly Milestone 1
- bootstrap and contracts Goal: make the deploymentyment layer and file contracts real. Deliverables: - actual docs files
- actual example config files - .env.example
- install.sh skeleton
- generate_config.py skeleton
- validate.py skeleton
- doctor.py skeleton
- task/event/artifact/ approval/verdict model stubs Exit criteria: - repo skeleton exists
- config and script contracts are materialized
- validation log to run in partial form Milestone 2
- runtime intake and task spine Goal: get a minimal but durable task system working. Deliverables: - gateway intake path
- explicit task parsing in #jarvis
- task store
- task event emission
- status summary path
- initial reporter summaries Exit criteria: - casual #jarvis chat does not create work
- explicit task creation creates durable event records
- status reporting reflects real records Milestone 3
- review and approval spine Goal: make the system safe and reviewable.

Deliverables: - Archimedes review path

- Anton review path
- approval record handling
- reactio handling
- review/approval summaries in reporter Exit criteria: - code tasks can route to Archimedes
- risky tasks can route to Anton
- appro allow promotion Milestone 4
- Flowstate lane Goal: make ingest/transcribe/distill/approve real. Deliverables: - source intake record creation
- transcript/extraction path
- distillation artifact crea promotion proposal flow
- Flowstate status/reporting view Exit criteria: - a source dropped into Flowstate creates source + artifact records
- promotion memory remains approval-gated Milestone 5
- Qwen-native specialization Goal: wire in the intended Qwen model lanes cleanly. Deliverables: - routing model integration
- general worker model integration
- Anton model inte coder model integration/evaluation
- logged fallback behavior within Qwen family Exit criteria: - model routing is explicit, testable, and logged
- no silent non-Qwen family switching occurs Milestone 6
- autonomy / Ralph loop Goal: allow bounded autonomous progress during configured windows. Deliverables: - eligible task selection logic
- autonomy cycle runner
- checkpoint/digest genera bounded retry behavior
- autonomy reporting surface Exit criteria: - the system can progress eligible queued work autonomously without violating autonomy leaves a clear paper trail Milestone 7
- deploymentyment hardening and migration closeout Goal: make deploymentyment boring and migration lessons permanent. Deliverables: - polished validate/doctor/smoke-test behavior
- migrated stable config values from where appropriate
- fresh-machine deploymentyment checklist
- migration notes finalized
- release gate checklist Exit criteria: - deploymentyment pain is materially reduced compared to v4
- common misconfiguratio caught before runtime
- the migration from v4 is documented and reproducible

Dependency guidance between milestones Milestone 1 should come before any serious runtime coding
Milestone 2 should precede Milestone 4 because Flowstate needs the task/event/artifact spine
Milestone 3 should precede any risky promotion behavior Milestone 5 can start in partial form once
Milestone 2 is stable Milestone 6 should not bypass Milestones 3 and 5 Milestone 7 should be
ongoing, but only finalized after the others are coherent Suggested near-term execution order

1. finish Milestone 0 inputs
2. materialize Milestone 1 files
3. build Milestone 2 minimal runnable core
4. add Milestone 3 review/approval safety
5. add Milestone 4 Flowstate lane
6. wire Milestone 5 Qwen specialization
7. enable Milestone 6 autonomy carefully
8. harden with Milestone 7 Definition of “push for v5” Pushing for v5 should mean advancing the next milestone with real files and runnable beha reopening already-locked architectural debates. Message templates and output formatting rules Operator-facing messages should be concise, structured, and predictable. General formatting principles lead with the most important fact first include IDs when they are actionable avoid giant walls of text in Discord channels prefer one compact structured message over many tiny fragments clearly distinguish status, warning, failure, approval, and review messages Status message templates #jarvis quick status reply Template shape: - current top-line status
- running tasks count or names
- blocked tasks coun pending approvals count
- recent completion summary
- next recommended move

Example: 🟢 Jarvis status Running: 2 tasks (NQ prop research, deploymentyment validation) Blocked: 1 task
(awaiting approval) Pending approvals: 1 Finished recently: Flowstate distillation for OpenClaw
update video Next best move: approve the research note promotion in #review Task creation
acknowledgment Template shape: - confirmation

- task ID
- normalized short description
- initial status
- where appear
- likely review/approval note Example: 📋 Task created: T1234 Summary: Research NQ prop account rules and common failure points. Status: queued Progress: #tasks Review: Anton may review before promotion if the findings are high impact. Approval message templates Approval prompt Template shape: - title
- task/artifact ID
- short summary
- options
- recommended option timeout note if relevant Example: 🟡 Approval needed Task: T1234 Artifact: A204 Summary: Research note is complete and ready for promotion to #outputs. Options: ✅ approve | ❌ reject | 🔁 rerun | ⬆️ escalate Recommended: ✅ approve Risk: low operational risk Timeout: 4 hours

Approval result acknowledgment Example: ✅ Approval recorded Task: T1234 Decision: approve Next:
artifact will be promoted to #outputs Review message templates Archimedes review summary Template
shape: - reviewer name

- task/artifact ID
- decision
- severity
- short summary
- req count Example: 🧠 Archimedes review Task: T2091 Artifact: A991 Decision: changes requested Severity: medium Summary: Code is structurally solid but missing explicit Discord permission diagnostics. Required changes: 2 Anton review summary Example: 🛡️ Anton review Task: T3301 Decision: approved for promotion Summary: Findings are coherent and risk is acceptable for output posting. Failure message templates Blocking failure Template shape: - what failed
- category/service
- likely cause
- immediate next action

Example: ❌ Blocking failure Service: gateway Category: discord_permission_error Issue: bot cannot
send messages in #review Likely cause: missing Send Messages permission Next action: fix channel
permissions, then rerun validate.py Retryable failure Example: ⚠️ Retryable failure Service: core
Category: model_timeout_error Issue: general model timed out during execution Next action: automatic
retry with backoff Flowstate message templates Flowstate receipt acknowledgment Example: 📥 Flowstate
source received Source: video link Status: ingest started Next: transcript/extraction will run
before distillation Promotion: approval required before ideas become tasks or memory Flowstate
distillation summary Example: 🧾 Flowstate distillation ready Source: OpenClaw update walkthrough
Summary: 6 major ideas extracted, 2 deploymentyment improvements suggested Artifacts: transcript +
distillation created Next: review and approve promotion candidates

Digest formats Daily / autonomy digest Template sections: - work advanced

- tasks blocked
- approvals now needed
- artifacts produced failures
- recommended next move Example: 🌙 Ralph loop digest Advanced: 3 tasks Blocked: 1 (awaiting approval) Approvals needed: 2 Artifacts produced: 4 Notable failure: one model timeout in Flowstate distillation Next move: approve the NQ research note and review the code patch verdict Minimal no-change digest rule If nothing meaningful changed, prefer silence or one short statement: ℹ️ No major changes since the last digest. Service health output format Health summary structure A health summary should include: - overall verdict
- services healthy/degraded/blocked
- model r summary
- event backend status
- pending approvals/reviews count
- latest critical issue Example: 🩺 System health: degraded Services: gateway ✅ | core ✅ | auditor ⚠️ | reporter ✅ | flowstate ✅ Models: routing ✅ | general ✅ | anton ⚠️ | coder ✅ Event backend: sqlite ✅ Pending approvals: 1 Pending reviews: 2 Critical issue: Anton model timed out during final review

Service-specific health entry Example fields: - service name

- status
- last heartbeat
- last error
- current load/count Channel message rules

### #jarvis

keep messages concise prioritize operator awareness avoid dumping raw logs status replies should be
readable in one screen when possible

### #tasks

emphasize task IDs, status, and latest checkpoint avoid noisy token-by-token chatter

### #review

approval prompts must be compact and reaction-ready avoid mixing unrelated tasks in one message

### #code-review

show verdict summary first link or reference the full artifact/details if needed

### #audit

emphasize risk, integrity, and final disposition keep higher-level than code-review lane

### #alerts

reserve for actionable failures or warnings avoid spammy informational messages

### #flowstate

focus on source receipt, ingest status, distillation readiness, and promotion proposals avoid
posting raw giant transcript chunks by default Directory-by-directory file plan This section defines
the intended responsibility of each major file so implementation stays aligned architecture.

docs/ docs/architecture.md Purpose: - high-level overview of lanes, services, and data flow

- explain how gateway/core/ reporter/flowstate fit together docs/deploymentyment.md Purpose: - first-time install flow
- validation/doctor workflow
- common deploymentyment failure handling docs/channels.md Purpose: - Discord channel contracts
- allowed behavior by lane
- task creation rules docs/review-policy.md Purpose: - Archimedes and Anton rules
- review triggers
- approval interplay docs/flowstate.md Purpose: - source ingest workflow
- transcript/distill/promotion policy
- Flowstate-specific constraints docs/migration-from-v4.md Purpose: - carry forward lessons from stabilized v4
- preserve Snowglobe deploymentyment truth
- what should/should not migrate docs/v4_deploymentyment_lessons.md Purpose: - raw lesson log from active v4 stabilization
- source material for migration automation config/ config/app.example.yaml Purpose: - global runtime settings
- workspace/state/log roots
- feature flags
- event backend mode config/channels.example.yaml Purpose: - guild and channel mappings
- task trigger patterns
- lane/channel policy bindings config/models.example.yaml Purpose: - Qwen provider and model routing
- timeout/retry/fallback rules

config/policies.example.yaml Purpose: - review/approval/trading/filesystem/memory/Flowstate policy
defaults scripts/ scripts/install.sh Purpose: - bootstrap directories, venv, dependencies, starter
configs scripts/generate_config.py Purpose: - create or update real config files from examples

- detect placeholders scripts/validate.py Purpose: - preflight checks before runtime start scripts/doctor.py Purpose: - rerunnable triage and remediation summary scripts/smoke_test.py Purpose: - minimal end-to-end sanity checks scripts/test_fresh_install.sh (future) Purpose: - clean-machine verification path runtime/gateway/ runtime/gateway/discord_intake.py Purpose: - listen for Discord messages/events
- build intake envelopes
- enforce channel policy at ingress runtime/gateway/acknowledgements.py Purpose: - standardize status, task-created, failure, and Flowstate acknowledgments runtime/gateway/approval_reactions.py Purpose: - map reactions to approval outcomes
- validate authorized approvers

runtime/core/ runtime/core/intake.py Purpose: - normalize gateway input into task requests/source
requests runtime/core/task_store.py Purpose: - create/update/read task records and related metadata
runtime/core/task_events.py Purpose: - write/read structured task events

- enforce event schema/retention rules runtime/core/routing.py Purpose: - classify tasks
- assign role/model lanes
- apply routing policy runtime/core/execution.py Purpose: - run bounded units of work
- emit checkpoints/artifacts/events runtime/core/checkpoints.py Purpose: - summarize progress after chunks/phases
- prepare compact future context runtime/core/status.py Purpose: - generate concise operator-facing status summaries from real state runtime/auditor/ runtime/auditor/archimedes.py Purpose: - code review lane
- produce structured code-review verdicts runtime/auditor/anton.py Purpose: - higher-level review and risk gate lane runtime/auditor/verdicts.py Purpose: - common verdict schemas, formatting, and persistence helpers

runtime/reporter/ runtime/reporter/health.py Purpose: - service/model/event-backend health summaries
runtime/reporter/digests.py Purpose: - autonomy digests and periodic concise summaries
runtime/reporter/alerts.py Purpose: - failure/warning routing with noise control
runtime/reporter/status_views.py Purpose: - task/approval/review/output/flowstate summaries for
operator surfaces runtime/flowstate/ runtime/flowstate/ingest.py Purpose: - source record creation
and metadata capture runtime/flowstate/transcript.py Purpose: - transcript/extraction generation

- segmentation handling runtime/flowstate/distill.py Purpose: - summary/idea/action extraction from source material runtime/flowstate/promotion.py Purpose: - approval-gated promotion of Flowstate outputs into tasks/memory/artifacts state/ state/tasks/ Purpose: - optional exported task records / snapshots state/artifacts/ Purpose: - persistent artifact files by task/source

state/approvals/ Purpose: - optional exported approval snapshots state/logs/ Purpose: - structured
log output and health/error history systemd/ systemd/jarvis-v5-gateway.service Purpose: - launch
gateway process with correct working directory/interpreter systemd/jarvis-v5-core.service Purpose: -
launch core runtime systemd/jarvis-v5-auditor.service Purpose: - launch review/risk gate service
systemd/jarvis-v5-reporter.service Purpose: - launch reporter/health/digest service Build handoff
pack This section is the concise starting packet for future sessions, reviewers, or collaborators.
Project summary Jarvis v5 is a Qwen-first operator system built around: - chat-only Jarvis
orchestration

- exp creation
- durable task/event/artifact state
- Archimedes code review
- Anton risk/final review
- ingest/transcribe/distill/approve lane
- strong deploymentyment validation and doctor tooling
- bound autonomy via the Ralph loop Most important locked decisions #jarvis must never auto-enqueue ordinary chat task creation in #jarvis is explicit: !task ... , task: ... , optionally task ... Flowstate is its own ingest/distill/promotion lane Qwen-only model family for v5 task/review/approval/artifact/event records should be structured deploymentyment pain must be attacked with install/validate/doctor/smoke-test flow autonomy must stay bounded and leave a paper trail

Current recommended model lanes routing: Qwen3.5-9B general: Qwen3.5-35B Anton/heavy reasoning:
Qwen3.5-122B code lane: Qwen coder model Flowstate distill: Qwen3.5-35B Immediate build priorities

1. preserve stabilized v4 deploymentyment lessons
2. materialize Milestone 1 files
3. build Milestone 2 task/event spine
4. add review/approval safety
5. add Flowstate lane
6. wire Qwen specialization
7. harden deploymentyment and autonomy What future sessions should ask first has the new stabilized v4 tar been uploaded yet? what new deploymentyment lessons came out of Snowglobe clean install? are any locked v5 decisions being intentionally changed, or should they be preserved? What not to do do not reintroduce accidental task creation from casual Jarvis chat do not silently switch outside the Qwen family do not rebuild huge runtime complexity before Milestones 1-2 are real do not treat transcripts or raw logs as final outputs by default do not bypass Anton/Archimedes/approval policy for risky work Handoff checklist A future session should quickly verify: - latest v5 spec exists and is current
- latest v4 lessons are captured
- milestone target for the current work session is explicit
- no conflic architecture rewrite is happening elsewhere Schema class plan The runtime should use explicit structured models so data stays consistent across services. Core schema modules runtime/core/models.py Purpose: - define core task/event/artifact/error models used across the runtime

Suggested classes: -

TaskRecord -

TaskEvent -

ArtifactRecord -

ErrorRecord

- CheckpointSummary runtime/auditor/models.py Purpose: - define review and approval-related models Suggested classes: - ReviewVerdict
- ApprovalRecord
- ApprovalOutcome runtime/flowstate/models.py Purpose: - define Flowstate-specific records Suggested classes: - FlowstateSource
- FlowstateDistillation
- PromotionProposal runtime/reporter/models.py Purpose: - define operator-facing summary models Suggested classes: - HealthSummary
- TaskStatusSummary
- ApprovalQueueSummary
- AutonomyDigest Suggested model field rules use explicit enums for statuses, risk, priority, and verdict decisions include created_at / updated_at timestamps where relevant include source traceability fields include optional version field for forward compatibility where useful validate IDs and status transitions at the model layer where practical Example enum families Task status enum received classified planned queued running awaiting_review awaiting_approval approved rejected completed failed archived

Risk enum low medium high restricted Priority enum low normal high urgent Review decision enum
approved changes_requested rejected Approval outcome enum approve reject rerun escalate Validation
philosophy reject impossible state combinations early reject invalid lifecycle transitions where the
model layer can catch them allow partial objects only when explicitly modeled for in-progress
creation prefer strong defaults over hidden assumptions Operator doctrine This section defines how
the operator should use the system day to day so the lanes remain clean. Core operator principles
use the right lane for the right kind of work keep #jarvis conversational and strategic use explicit
task creation when you want real work queued use #flowstate for source ingestion and idea extraction
use #review for approvals, not debate trust the lanes to keep clutter down

When to use #jarvis Use #jarvis for: - asking what is going on

- planning work
- checking status
- deciding wh issuing explicit task requests with !task ... or task: ... Do not use #jarvis for: - dumping raw source material for ingestion
- expecting ordinary conversa create work automatically
- browsing noisy logs When to use #tasks Use #tasks for: - formal work intake
- checking task progress
- seeing task state transitions When to use #flowstate Use #flowstate for: - videos
- links
- audio clips
- long docs
- update walkthroughs
- anyt transcribed, distilled, and converted into reusable ideas When to use #review Use #review for: - approvals
- rejections
- reruns
- escalations Keep it short and decision-focused. When to use #code-review Use #code-review to inspect: - Archimedes verdicts
- code issues
- required changes When to use #audit Use #audit to inspect: - Anton summaries
- higher-level integrity/risk notes
- final disposition of work When to use #outputs Use #outputs to find: - final artifacts
- promoted research notes
- approved summaries/reports finished deliverables Best practices for the operator phrase real work requests explicitly ask for status in #jarvis when you want a concise operating picture approve only what you actually want promoted use Flowstate to compress large source material before turning it into tasks prefer one grounded task over many vague speculative ones

Anti-patterns for the operator expecting a casual greeting to trigger work mixing approval decisions
into random channels using Flowstate as a general chat lane promoting ideas or memory entries
without reviewing what they actually say letting blocked tasks accumulate without checking why they
are blocked Immediate next build targets The next practical build outputs should be:

1. v5 decisions summary
2. channel policy doc review policy doc
4. flowstate doc
5. config schema
6. install/validate/doctor skeletons These are the highest-ROI files to prepare before the new tar arrives.