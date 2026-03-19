# Jarvis v5.1 Operating Guide

## Overview

Jarvis v5.1 is a bounded operator-supervised runtime for task execution, approvals, browser actions, voice routing, Hermes-assisted candidate generation, and autoresearch / Strategy Lab style experimentation.

This guide is the practical operator manual for the live v5.1 repo state. It is written for day-to-day use, not as a replacement for the master spec.

**What this guide is for**

* starting and validating the runtime
* understanding the major subsystems
* running common operator workflows
* knowing where state is written
* understanding review, approval, cancellation, and bounded execution behavior
* troubleshooting normal failures without guessing

**What this guide is not**

* not the authority over the master spec
* not a historical design log
* not a promise of post-v5.1 features that are not yet implemented

---

---

## Live Operator Loop

Everything below describes what is **actually running right now** and how to operate it. For architecture details, see sections further down.

### What is live

| Component | Unit / Script | Interval | What it does |
|-----------|--------------|----------|--------------|
| Gateway | `openclaw-gateway.service` | persistent | Node.js bot, Discord WebSocket, agent session routing |
| Inbound server | `openclaw-inbound-server.service` | persistent | HTTP API on :18790 for operator replies and approvals |
| Ralph | `openclaw-ralph.timer` | 10 min | Picks one queued task, dispatches to HAL, requests review |
| Review poller | `openclaw-review-poller.timer` | 30s | Polls Discord #review for `approve apr_xxx` / `reject apr_xxx` |
| Todo poller | `lobster-todo-intake.timer` | 2 min | Polls Discord #todo, calls `submit_todo()` for each human message |
| Outbox sender | `openclaw-discord-outbox.timer` | 60s | Delivers pending Discord outbox entries via webhooks |
| Operator status | `openclaw-operator-status.timer` | 5 min | Posts action summary to #jarvis when approvals/failures exist |
| Dashboard | `openclaw-dashboard.service` | persistent | Browser UI at **http://127.0.0.1:18793/** — health, approvals, queue, next action |
| Hermes | on-demand (via Ralph or gateway) | per-task | Deep research via LM Studio Qwen — produces artifacts and evidence bundles |
| Auto-promotion | wired into task completion | per-task | Promotes completed outputs through lifecycle gates |

### LLM provider status

| Provider | Backend | Status | Notes |
|----------|---------|--------|-------|
| LM Studio / Qwen | `qwen_executor`, `qwen_planner` (gateway) | **LIVE** | Primary. All local agents use Qwen via LM Studio |
| NVIDIA / Kimi K2.5 | `nvidia_executor` | **LIVE** | Used by Kitt (default), Jarvis (via hybrid profile) |
| OpenAI / GPT | `openai_executor` | **WIRED (inactive)** | Adapter + dispatch + model registry wired. Requires `OPENAI_API_KEY` with funded billing. **A ChatGPT subscription does NOT fund API usage.** Check: `python3 scripts/check_openai_provider.py` |
| Anthropic / Claude | gateway config only | **BLOCKED** | `ANTHROPIC_API_KEY=REPLACE_ME`. No Python-track adapter exists — gateway config only |

### Daily operator commands

Open the dashboard in a browser:

```
http://127.0.0.1:18793/
```

Check what needs attention (terminal):

```bash
python3 scripts/operator_status.py
```

Verify the runtime is healthy:

```bash
python3 scripts/runtime_doctor.py
```

See Ralph's owned tasks and what's pending:

```bash
python3 scripts/run_ralph_v1.py --status
```

Approve a pending task:

```bash
python3 scripts/run_ralph_v1.py --approve task_XXXX
# or in Discord #review: type "approve apr_XXXX"
```

Reject a pending task:

```bash
python3 scripts/run_ralph_v1.py --reject task_XXXX --reason "needs rework"
# or in Discord #review: type "reject apr_XXXX needs rework"
```

Retry a failed task:

```bash
python3 scripts/run_ralph_v1.py --retry task_XXXX
```

Clean up stale/orphaned approvals:

```bash
python3 scripts/reconcile_approvals.py          # dry-run report
python3 scripts/reconcile_approvals.py --apply   # fix them
```

Post status summary to Discord:

```bash
python3 scripts/operator_status.py --discord
```

### Discord lanes

| Channel | What happens | Ingress mechanism |
|---------|-------------|-------------------|
| **#todo** (`#✅todo`) | Human messages become tasks. Low-risk tasks go straight to Ralph. | `discord_todo_poller.py` polls via REST API every 2 min |
| **#review** (`#archimedes`) | Approval requests appear here. Operator types `approve apr_xxx` or adds ✅ emoji. | `discord_review_poller.py` polls via REST API every 30s |
| **#muse** | Creative agent. Human messages create a Muse session, LLM responds in-channel. | Gateway WebSocket binding → `agent:muse:discord:channel:1483133844663304272` |
| **#jarvis** | Operator status posts, task creation confirmations, escalation events. | Outbox sender delivers via webhook |
| **#worklog** (`#ralph`) | Mirror of all task lifecycle events. Read-only audit trail. | Outbox sender delivers via webhook |

### Output promotion

When Ralph completes a task (via review-only or review+approval), the result is **auto-promoted**: candidate artifact → promoted artifact → published output. This is idempotent — rerunning the same completion path does not create duplicates.

For tasks that were completed before auto-promotion was wired (or where auto-promotion was skipped), use the manual tool:

```bash
python3 scripts/promote_output.py --list              # see promotable tasks
python3 scripts/promote_output.py --promote task_XXXX  # promote + publish
python3 scripts/promote_output.py --inspect art_XXXX   # show provenance chain
```

### Common problems

**Stale approvals accumulating**

Approvals can become stale when tasks complete, fail, or regress to an earlier state after the approval was requested.

```bash
python3 scripts/reconcile_approvals.py          # see what's stale
python3 scripts/reconcile_approvals.py --apply   # cancel stale ones
```

**Transient failures (NVIDIA timeout, browser tab_open_failed)**

These are retryable. Ralph will not auto-retry — operator must:

```bash
python3 scripts/run_ralph_v1.py --retry task_XXXX
```

**Queue backlog growing**

Ralph processes one task per 10-minute cycle. If the queue grows faster:

```bash
# Run Ralph manually to burn through the queue
python3 scripts/run_ralph_v1.py      # processes one task
python3 scripts/run_ralph_v1.py      # repeat as needed
```

**Systemd drift (repo units changed, live not updated)**

```bash
python3 scripts/sync_systemd_units.py --status     # check for drift
python3 scripts/sync_systemd_units.py              # install + enable
```

**Gateway keeps reconnecting**

The health-monitor restarts the Discord connection every ~10 minutes if it detects a disconnect. This is normal for the Node.js gateway under WSL2. Messages are not lost — the WebSocket reconnects and resumes.

### One-command recovery checks

After a reboot or suspected breakage:

```bash
# 1. Sync systemd units from repo and start core services
python3 scripts/sync_systemd_units.py

# 2. Verify everything is healthy
python3 scripts/runtime_doctor.py

# 3. Check what needs operator action
python3 scripts/operator_status.py
```

---

## Current v5.1 state

The repo has reached required bounded v5.1 runtime closure for the audited master-spec scope.

Bounded v5.1 closure includes:

* task / event / artifact durable state flow
* review and approval-connected candidate handling
* voice-session and voice-route safety surfaces
* browser policy enforcement and bounded browser request flow
* operator-visible browser cancel / interrupt path for pending or accepted browser requests
* Hermes adapter request/result hardening with fail-closed validation
* autoresearch adapter request/result hardening with fail-closed validation
* Strategy Lab standard run outputs materialized per run
* status / export / operator snapshot surfaces for live operational visibility

This means the repo is no longer primarily in “missing required runtime slice” mode. It is in operator hardening, documentation, usability, and future-feature mode.

---

## Core operating model

Jarvis v5.1 is built around a bounded-execution philosophy.

The system is designed to:

* preserve durable records for important actions
* fail closed when request contracts are underspecified
* keep review and approval steps explicit
* expose operator-visible summaries for what the runtime is doing
* prevent hidden widening of capability at trust boundaries

In practice, that means:

* browser actions are requested, reviewed, accepted, stubbed, or cancelled through records
* voice actions route through explicit session and safety logic
* Hermes and autoresearch use request/result contract records instead of loose ad hoc calls
* important decisions become visible through status, state export, and operator snapshot surfaces

---

## Repo layout

This is the practical mental map of the repo.

### `runtime/core/`

Core models, task state, control logic, approvals, review flow, status assembly, and shared runtime helpers.

### `runtime/gateway/`

Operator-facing entry paths for bounded runtime actions such as browser or voice-triggered flows.

### `runtime/browser/`

Browser request/result protocol, policy surfaces, allowlist logic, reporting, and backend integration seam.

### `runtime/voice/`

Voice pipeline, routing, session handling, and safety-aware dispatch behavior.

### `runtime/integrations/`

Bounded adapters for execution backends: NVIDIA/Kimi (`nvidia_executor.py`), OpenAI/GPT (`openai_executor.py`), Hermes (`hermes_adapter.py`, `hermes_transport.py`), Bowser browser (`bowser_adapter.py`), Kitt quant (`kitt_quant_workflow.py`), and autoresearch.

### `runtime/researchlab/`

Strategy Lab / research campaign durable state and runner helpers.

### `runtime/dashboard/`

Operator-facing read-model construction such as state export and operator snapshot.

### `tests/`

Focused validation for bounded runtime slices. In this repo, several important tests are runnable directly with `python3`.

### `docs/spec/`

Master spec, implementation checklist, and spec-facing documentation.

### `state/`

Durable runtime state. Some of this may be ignored in git, but it is central to how the runtime operates locally.

---

## Key durable concepts

## Task records

Tasks are the main unit of work. They move through bounded lifecycle states and connect to events, artifacts, review, and approval surfaces.

## Task events

Events are the chronological log of important actions. They help reconstruct what happened without relying on memory.

## Artifacts

Artifacts represent produced outputs. Candidate artifacts usually matter when something is awaiting review or approval.

## Review and approval

Review and approval are not decorative. They are part of the trust boundary. A candidate may exist without being promoted. A review/approval checkpoint is the explicit seam between generation and promotion.

## Browser action request/result records

Browser work is not just “done.” It is requested, recorded, and then either blocked, pending review, accepted, stubbed, or cancelled.

## Voice session records

Voice interactions flow through session and route safety surfaces rather than being treated as raw freeform commands.

## Hermes task request/result records

Hermes is represented through durable request/result records with hardened request validation and failure categorization.

## Lab run request/result records

Autoresearch / Strategy Lab execution uses durable experiment-style request/result records and standard run outputs.

---

## Status surfaces you should know

There are three read-model surfaces you should think of as your operational dashboard spine.

### Status summary

Built from runtime state and subsystem summaries. This is your top-level operational view.

### State export

Structured export of current runtime state for dashboard or tooling consumption.

### Operator snapshot

A compact operator-facing view of current runtime posture, recent subsystem state, and important summaries.

These surfaces matter because v5.1 intentionally routes visibility through them instead of inventing a different reporting path for every feature.

---

## Startup and validation

Before doing real work, use a consistent validation routine.

### Recommended validation sequence

```bash
cd /home/rollan/.openclaw/workspace/jarvis-v5
python3 scripts/validate.py
python3 runtime/core/run_runtime_regression_pack.py
python3 scripts/smoke_test.py
```

### What each command does

#### `python3 scripts/validate.py`

Runs repo validation checks and catches structural/runtime consistency issues. This is the first thing to trust when verifying the repo is in a sane state.

#### `python3 runtime/core/run_runtime_regression_pack.py`

Runs the bounded regression pack for key runtime slices.

#### `python3 scripts/smoke_test.py`

Useful for local deployment-level smoke behavior.

### Focused direct-script test examples

```bash
cd /home/rollan/.openclaw/workspace/jarvis-v5
python3 tests/test_hermes_adapter.py
python3 tests/test_autoresearch_adapter.py
python3 tests/test_browser_gateway.py
```

This repo has been hardened so several key tests are runnable directly with `python3`, not only through pytest.

---

## Common operator workflows

## 1. Check whether the runtime is healthy

Use:

```bash
cd /home/rollan/.openclaw/workspace/jarvis-v5
python3 scripts/validate.py
python3 runtime/core/run_runtime_regression_pack.py
```

If both are green, the bounded runtime spine is usually healthy enough for local operator work.

## 2. Inspect current task and subsystem posture

Start from the status/state export/operator snapshot path rather than poking random files first.

Look for:

* blocked tasks
* pending review
* pending approvals
* browser request/result summaries
* Hermes failure category counts
* autoresearch failure category counts

## 3. Run Hermes-backed bounded generation

Hermes requests should only run through the existing contract path. The point is not just generation; the point is bounded, validated generation with durable result recording.

You should expect:

* request validation before dispatch
* blocked/invalid behavior for underspecified contracts
* durable result records
* explicit failure categories for malformed, unreachable, timeout, or execution failures

## 4. Run an autoresearch campaign / Strategy Lab pass

Autoresearch should be treated like an experiment pipeline, not a freeform codegen path.

You should expect:

* explicit request contract
* baseline reference and benchmark slice reference
* bounded sandbox root
* target module and eval command
* durable run result
* standard run outputs written for successful runs

## 5. Operate browser actions safely

Browser actions live behind request/result records and policy surfaces.

Typical flow:

1. request browser action
2. allowlist / confirmation policy evaluated
3. request becomes blocked, pending review, or accepted
4. accepted action may be stubbed in bounded mode
5. pending or accepted action may now be cancelled by operator

## 6. Operate voice safely

Voice is not just a shortcut input. It has its own route safety and session surfaces.

Use voice features with the expectation that:

* session state matters
* route safety matters
* not every voice command should become execution
* operator visibility matters more than convenience shortcuts

---

## Browser operation

## What browser v5.1 currently does

The browser layer provides a bounded request/result model rather than unrestricted computer control.

Key behaviors include:

* request recording
* policy / allowlist handling
* confirmation state tracking
* evidence refs and reporting surfaces
* shared status visibility
* operator cancel / interrupt for pending or accepted requests

## Browser request states

Practical states include:

* `blocked`
* `pending_review`
* `accepted`
* `cancelled`
* execution terminal states such as `stubbed` through the bounded path

## Cancel behavior

v5.1 includes a bounded cancel path for browser actions.

Supported transitions:

* `accepted -> cancelled`
* `pending_review -> cancelled`

Not supported:

* cancelling a blocked request
* cancelling a request that already has a terminal execution result
* executing a request after it has been cancelled

Durable cancel metadata includes:

* `cancelled_at`
* `cancelled_by`
* `cancel_reason`

Operator-facing reporting includes:

* `cancelled_request_count`
* `cancelled_result_count`

This is important because cancel is now part of the trust boundary, not just UI sugar.

---

## Cadence voice operation

Cadence is designed as a two-layer voice interface. Both layers are described here with their current status.

### Layer 1: Wake-word command — PARTIAL

Always-listening wake-word detection that captures a spoken command and routes it into the task system.

**Pipeline**: openWakeWord wake detection → audible beep (earcon) → Silero VAD speech gating → faster-whisper STT → `route_cadence_utterance()` → task creation or direct action → Piper/Coqui TTS response.

**What exists**:
* `cadence_daemon.py` — two-phase loop (passive standby → wake → command capture → route)
* `live_listener.py` — subprocess: openWakeWord + Silero VAD + faster-whisper (runs in `.venv-voice`, Python 3.12)
* `cadence_ingress.py` — intent classification, task creation, voice command routing
* `tts_piper.py` / `tts_coqui_render.py` — TTS output
* `cues.py` / `feedback.py` — earcon playback (wake_accept, command_open, route_ok, error)
* systemd unit `cadence-voice-daemon.service` — daemon is running (596 MB resident)
* Transcript routing and TTS output are independently proven

**What's blocked**: Mic capture via RDPSource is unavailable in WSL2. Without live mic input, there is no end-to-end wake-to-command proof. The daemon runs but receives no audio.

### Layer 2: Cadence conversation — LIVE (replay mode)

Persistent conversational AI copilot that answers questions about live runtime state, proposes actions with confirmation, and maintains multi-turn context.

**What exists**:
* `runtime/personaplex/engine.py` — conversation loop with LLM (Qwen via LM Studio)
* `runtime/personaplex/session.py` — persistent multi-turn session state with rolling summary
* `runtime/personaplex/context.py` — live runtime context assembly (tasks, approvals, agents, health)
* `runtime/personaplex/intent.py` — rule-based intent classifier (conversational / command / escalation / meta)
* `runtime/personaplex/cli.py` — terminal REPL
* Cadence voice → conversation bridge in `cadence_ingress.py`
* Command safety: "approve task X" produces a proposal with confirmation prompt, never silently executes

**Proven via replay**:
```bash
python3 scripts/cadence_status.py --replay "Jarvis what needs my attention right now"
python3 scripts/cadence_status.py --replay "Jarvis please approve task_a7d82c0f29f8"
```

**What's blocked**: Same as Layer 1 — live mic capture on WSL2.

---

## Hermes operation

## What Hermes is in v5.1

Hermes is a bounded execution adapter for candidate-oriented generation tasks. It is not a freeform unconstrained agent inside the runtime.

**Status**: LIVE (as of b70a8b4). Hermes transport calls LM Studio Qwen directly — no external daemon needed. Ralph includes `hermes_adapter` in ELIGIBLE_BACKENDS and will dispatch Hermes-routed tasks automatically. Requires LM Studio to be running.

## Hermes request contract expectations

A Hermes task request is expected to include a valid contract such as:

* objective
* timeout
* supported sandbox class
* allowed tools
* model override policy constrained to allowed families/provider rules
* supported return format
* capability declaration
* callback contract aligned to task and lane

If those contract fields are not present or are policy-invalid, Hermes now fails closed before dispatch.

## Hermes failure categories

Hermes now records durable failure categorization such as:

* invalid request contract
* timeout
* unreachable backend
* malformed response
* execution failure

These categories roll into the existing summary path, which means you can inspect Hermes failures from the same operational spine instead of reading raw logs first.

## Practical operator guidance

When Hermes fails:

1. inspect the request contract first
2. inspect failure category next
3. only then inspect backend transport or payload details

This avoids wasting time debugging a backend when the request itself was underspecified.

---

## Autoresearch / Strategy Lab operation

## What autoresearch is in v5.1

Autoresearch is a bounded experiment-runner path for strategy or research passes, with durable contracts, durable results, and standard output materialization.

## Required contract shape

You should expect a valid run to include at minimum:

* objective
* objective metrics
* primary metric consistent with the metric list
* baseline reference
* benchmark slice reference
* bounded sandbox class
* sandbox root
* target module
* program markdown path
* eval command
* pass index
* remaining budget units
* task-type metadata

Underspecified requests fail closed.

## Result expectations

A valid result should include well-formed fields such as:

* summary
* hypothesis
* metrics object
* recommendation object
* numeric metric maps
* bounded status semantics

Malformed result payloads are categorized explicitly instead of being loosely accepted.

## Standard run outputs

For successful bounded lab runs, v5.1 now writes standard run outputs under the research sandbox.

Per run, the output directory pattern is:

```text
<repo_root>/<sandbox_root>/<run_id>/standard_run_outputs/
```

Expected files:

* `run_config.json`
* `baseline_metrics.json`
* `candidate_metrics.json`
* `delta_metrics.json`
* `candidate.patch`
* `experiment_log.md`
* `recommendation.json`

These outputs are linked back to durable records, including:

* `candidate_patch_path`
* `experiment_log_path`
* `raw_result["standard_run_outputs"]`

This means a run is both inspectable as structured state and inspectable as concrete filesystem outputs.

---

## Review, approval, and promotion

## Why this matters

A lot of confusion in agent systems comes from blending generation with approval. Jarvis v5.1 explicitly does not treat them as the same thing.

## Practical mental model

* generation can produce a candidate
* review determines whether the candidate looks acceptable
* approval determines whether it is allowed to move forward
* promotion is a separate action from generation itself

This is part of the runtime’s trust-boundary design.

## What operators should watch

Pay attention to:

* tasks waiting in pending review
* approval checkpoint records
* candidate artifact linkage
* whether a subsystem is allowed to fallback or not
* whether degraded mode would weaken posture

---

## Safety controls and trust boundaries

## The core rule

The system should not silently widen capability just because a subsystem is unavailable or a contract is underspecified.

## Practical examples

* Hermes should not run with a bad request contract
* autoresearch should not run without baseline/benchmark and bounded sandbox metadata
* browser should not quietly execute a cancelled request
* review-required outputs should not auto-promote because a reviewer is absent
* degraded behavior should remain operator-visible

## What “fail closed” means here

Fail closed does not mean “everything breaks.” It means the runtime prefers explicit blocking, invalid-request results, or operator-visible degraded behavior instead of pretending a risky request is fine.

---

## Where to look when something breaks

## Start in this order

### 1. Validation output

Run:

```bash
cd /home/rollan/.openclaw/workspace/jarvis-v5
python3 scripts/validate.py
```

### 2. Regression pack

Run:

```bash
cd /home/rollan/.openclaw/workspace/jarvis-v5
python3 runtime/core/run_runtime_regression_pack.py
```

### 3. Focused subsystem test

Examples:

```bash
cd /home/rollan/.openclaw/workspace/jarvis-v5
python3 tests/test_browser_gateway.py
python3 tests/test_hermes_adapter.py
python3 tests/test_autoresearch_adapter.py
```

### 4. Durable state and summaries

Inspect:

* status summary
* state export
* operator snapshot
* relevant task/event/result records

### 5. Only after that, inspect implementation details

At that point you can dive into the affected protocol, adapter, or gateway code.

---

## Troubleshooting guide

## Browser action will not execute

Check:

* request status
* confirmation state
* allowlist/policy decision
* whether it has been cancelled
* whether a terminal result already exists

## Hermes request failed immediately

Check:

* request validation findings
* timeout value
* allowed tools
* model override policy
* provider policy
* callback contract alignment

## Autoresearch failed before meaningful work started

Check:

* baseline reference
* benchmark slice reference
* sandbox root
* target module
* eval command
* primary metric validity
* task metadata contract

## Results exist but operator view looks wrong

Check the status/state export/operator snapshot path before assuming execution failed. Sometimes the issue is in read-model expectations rather than the execution record itself.

## A change feels “implemented” but not trustworthy

Ask whether it has all three:

* durable record
* bounded transition rule
* test coverage

If one of those is missing, it probably is not truly production-ready even if it works once.

---

## Recommended day-to-day workflow

A good operator loop for this repo is:

1. validate the repo
2. run the regression pack
3. run the focused subsystem you are touching
4. inspect summaries rather than guessing
5. keep changes bounded
6. commit by slice, not by giant mixed batch
7. keep docs honest about what is actually proven

Example:

```bash
cd /home/rollan/.openclaw/workspace/jarvis-v5
python3 scripts/validate.py
python3 runtime/core/run_runtime_regression_pack.py
python3 tests/test_browser_gateway.py
git status
```

---

## What is intentionally not claimed here

This guide does not claim:

* unrestricted computer control
* autonomous approval-free promotion everywhere
* full backend-complete multi-provider rollout
* every future v5.x idea already being present
* that every possible test path has been exercised through a full pytest baseline

It reflects the live bounded v5.1 runtime state, not aspirational marketing.

---

## Suggested companion docs

This guide works best alongside:

* `README.md` for quick orientation
* `docs/RUNBOOK.md` for day-to-day operational procedures
* `docs/ARCHITECTURE.md` for subsystem map and data flow
* `docs/spec/V5_1_FREEZE_NOTES.md` for freeze summary and post-v5.1 boundaries
* `docs/spec/Jarvis_OS_v5_1_Master_Spec.md` as authority

---

## Quick command block

```bash
cd /home/rollan/.openclaw/workspace/jarvis-v5
python3 scripts/validate.py
python3 runtime/core/run_runtime_regression_pack.py
python3 scripts/smoke_test.py
python3 tests/test_browser_gateway.py
python3 tests/test_hermes_adapter.py
python3 tests/test_autoresearch_adapter.py
git status
```

---

## Final operator note

The best way to use Jarvis v5.1 is to treat it like a bounded system with explicit records, explicit trust boundaries, and explicit operator control.

Do not optimize first for maximum autonomy.
Optimize first for:

* visibility
* recoverability
* boundedness
* reviewability
* clean state transitions

That is what makes the system usable when it gets bigger.
