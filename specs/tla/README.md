# TLA+ Specs For JarvisOS Control-Plane Semantics

This folder holds small formal models for the parts of JarvisOS where control-plane correctness matters more than implementation style:

- task lifecycle progression
- review / approval gating
- scheduler lease ownership and retry semantics

These specs live beside the runtime, not inside the runtime hot path, for two reasons:

1. The runtime must stay simple and operational. TLC model checking is an offline design and regression tool, not something we run during live task execution.
2. The point here is to protect control-plane semantics, not to formalize model prompting, Discord reply text, or operator UX flows.

This is intentionally not "TLA+ for the whole OS." The scope stays narrow and auditable.

## What Each Spec Protects

`TaskLifecycle.tla`
- models a finite task state machine close to the repo's `queued/running/waiting_review/waiting_approval/ready_to_ship/completed/failed/archived` flow
- uses a slightly normalized vocabulary (`created`, `routed`, `review_pending`, `approved`, `rejected`) to keep the state machine compact
- protects event emission, parent linkage, terminal completion semantics, and archive safety

`ApprovalGate.tla`
- models the rule that produced work must be reviewed before promotion when review is required
- protects against reviewer-unavailable auto-promotion and degraded-mode bypass
- makes the review target explicit: decisions must apply to the produced artifact/result, not only the original request text

`SchedulerLease.tla`
- models claim / lease / retry / expiry semantics for scheduler-owned work
- protects against concurrent execution by multiple owners
- protects once-only jobs and retry ceilings
- makes lease resolution progress explicit

## Repo Terminology Drift

The runtime already uses these status names:

- `queued`
- `running`
- `waiting_review`
- `waiting_approval`
- `ready_to_ship`
- `shipped`
- `completed`
- `failed`
- `cancelled`
- `archived`

The TLA+ specs deliberately collapse some of that vocabulary:

- `created` / `routed` are explicit spec states even though the runtime usually persists tasks starting at `queued`
- `review_pending` stands in for runtime `waiting_review`
- `approved` / `rejected` are explicit approval decision states, while the runtime usually records those as review/approval objects plus task transitions
- `completed` in the spec means "terminal result exists"; runtime `ready_to_ship` and `shipped` add extra deployment/publish semantics beyond that

When the runtime semantics change, update the spec comments and README first. Only then decide whether the runtime and spec should converge or whether the difference is intentional.

## Install TLA+ Toolbox

Option 1: TLA+ Toolbox
- Download from: <https://lamport.azurewebsites.net/tla/toolbox.html>
- Open this repo and import the modules under `specs/tla/`

Option 2: TLC from command line
- Download `tla2tools.jar` from: <https://lamport.azurewebsites.net/tla/tools.html>
- Or install it from your package manager if your workstation already packages TLC

## Example TLC Commands

Run from repo root:

```bash
java -cp tla2tools.jar tlc2.TLC -deadlock -workers auto specs/tla/TaskLifecycle.tla
java -cp tla2tools.jar tlc2.TLC -deadlock -workers auto -config specs/tla/TaskLifecycle.cfg specs/tla/TaskLifecycle.tla
java -cp tla2tools.jar tlc2.TLC -deadlock -workers auto -config specs/tla/ApprovalGate.cfg specs/tla/ApprovalGate.tla
java -cp tla2tools.jar tlc2.TLC -deadlock -workers auto -config specs/tla/SchedulerLease.cfg specs/tla/SchedulerLease.tla
```

If your TLC wrapper is installed directly:

```bash
tlc -deadlock -workers auto -config specs/tla/TaskLifecycle.cfg specs/tla/TaskLifecycle.tla
tlc -deadlock -workers auto -config specs/tla/ApprovalGate.cfg specs/tla/ApprovalGate.tla
tlc -deadlock -workers auto -config specs/tla/SchedulerLease.cfg specs/tla/SchedulerLease.tla
```

## How Contributors Should Use This

When task, review, approval, or lease semantics change:

1. Update the relevant spec comments and invariants.
2. Re-run TLC locally.
3. If runtime terminology drift changed, update this README.
4. Only then update the runtime implementation.

These specs should stay:

- finite
- small
- safety-focused
- grounded in real Jarvis/OpenClaw control-plane terms

Do not expand this folder into a speculative formalization of every subsystem. If a new spec is added, it should protect a concrete control-plane guarantee that would be expensive to rediscover from production failures.
