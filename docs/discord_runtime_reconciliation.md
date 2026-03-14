# Discord Runtime Reconciliation

Date: 2026-03-12

This note is a blunt reconciliation of what is already implemented inside `jarvis-v5` versus what is still blocking real Discord operation outside the repo.

It is not a new design doc.
It is a repo-truth and machine-truth checkpoint.

## Bottom Line

Repo-side routing/control-plane work is no longer the main blocker for Discord text operation.

What is already true:

- Jarvis repo routing is real and policy-backed.
- Jarvis repo summaries already expose:
  - `routing_control_plane_summary`
  - `extension_lane_status_summary`
  - `lane_activation_summary`
  - `local_model_lane_proof_summary`
  - `workspace_registry_summary`
  - `shadowbroker_summary`
  - `operator_go_live_gate`
- Workspace access control is implemented as default-deny registered access, not arbitrary roaming.
- ShadowBroker is integrated as a non-authoritative external sidecar.

What is still blocking real Discord operation:

- the active external OpenClaw/LM Studio runtime path
- prompt-template / session-runtime compatibility on the live NiMo 9B path
- repeated live-chat timeout behavior on the active `lmstudio` chat path
- saving/staging/pushing the large current repo worktree cleanly

Operational boundary from Snowglobe:

- Snowglobe can prove the active Discord binding and inspect OpenClaw session/log evidence.
- Snowglobe can probe the NIMO HTTP endpoint directly.
- Snowglobe does **not** currently have a proven direct admin path into the NIMO LM Studio runtime:
  - no `~/.ssh/config` entry
  - no visible remote mount
  - no machine-visible NIMO LM Studio config/state path

So the next runtime stabilization step is a NIMO-host operator action, not another Snowglobe repo patch.

## Already Implemented In Repo

### 1. Routing control plane summary

Implemented in:

- [runtime/core/status.py](/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/status.py)
- [runtime/dashboard/operator_snapshot.py](/home/rollan/.openclaw/workspace/jarvis-v5/runtime/dashboard/operator_snapshot.py)
- [runtime/dashboard/state_export.py](/home/rollan/.openclaw/workspace/jarvis-v5/runtime/dashboard/state_export.py)

This is already real:

- latest route state
- latest failed route
- degradation link
- fallback blocked for safety
- primary runtime posture
- burst capacity posture

### 2. Extension lane status summary

Implemented in:

- [runtime/core/status.py](/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/status.py)
- [tests/test_extension_lane_status_summary.py](/home/rollan/.openclaw/workspace/jarvis-v5/tests/test_extension_lane_status_summary.py)

This is already real and blunt:

- `live_and_usable`
- `implemented_but_blocked_by_external_runtime`
- `scaffold_only`
- `deprecated_alias`

### 3. Lane activation summary

Implemented in:

- [runtime/integrations/lane_activation.py](/home/rollan/.openclaw/workspace/jarvis-v5/runtime/integrations/lane_activation.py)
- [tests/test_lane_activation.py](/home/rollan/.openclaw/workspace/jarvis-v5/tests/test_lane_activation.py)

This is already real:

- durable activation attempt/result records
- machine-local live/not-live truth
- no fake healthy state

### 4. Local model proof summary

Implemented in:

- local proof activation scripts and summaries
- [tests/test_local_model_lane_activation.py](/home/rollan/.openclaw/workspace/jarvis-v5/tests/test_local_model_lane_activation.py)

This is already real:

- bounded Unsloth proof lane
- bounded DSPy proof lane
- lanes become `live_and_usable` only after real proof evidence

### 5. Operator go-live gate

Implemented in:

- [scripts/operator_go_live_gate.py](/home/rollan/.openclaw/workspace/jarvis-v5/scripts/operator_go_live_gate.py)
- [docs/operator_go_live_checklist.md](/home/rollan/.openclaw/workspace/jarvis-v5/docs/operator_go_live_checklist.md)
- [tests/test_operator_go_live_gate.py](/home/rollan/.openclaw/workspace/jarvis-v5/tests/test_operator_go_live_gate.py)

This is already real:

- one machine-truth command
- honest ready/blocked/scaffold/deprecated breakdown
- no fake readiness

### 6. Workspace registry access control

Implemented in:

- [runtime/core/workspace_registry.py](/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/workspace_registry.py)
- [tests/test_workspace_registry.py](/home/rollan/.openclaw/workspace/jarvis-v5/tests/test_workspace_registry.py)

This is already real:

- durable workspace registry
- default deny
- operator approval bit
- explicit lane/agent grants
- no arbitrary filesystem roaming

### 7. ShadowBroker integration

Implemented in:

- [runtime/integrations/shadowbroker_adapter.py](/home/rollan/.openclaw/workspace/jarvis-v5/runtime/integrations/shadowbroker_adapter.py)
- [docs/shadowbroker_deployment.md](/home/rollan/.openclaw/workspace/jarvis-v5/docs/shadowbroker_deployment.md)

This is already real as a sidecar lane:

- healthcheck
- snapshot fetch
- degraded/blocked states
- durable health/snapshot/event records
- operator-visible summary

It is still non-authoritative by design.

## What The Repo Already Says About Discord/Jarvis Routing

### Repo policy/config truth

Repo-side runtime policy currently aligns with the intended operating model:

- [config/models.yaml](/home/rollan/.openclaw/workspace/jarvis-v5/config/models.yaml)
  - router: `Qwen3.5-9B` on `http://100.70.114.34:1234/v1`
  - worker/reviewer: `Qwen3.5-35B`
  - auditor: `Qwen3.5-122B`
- [config/runtime_routing_policy.json](/home/rollan/.openclaw/workspace/jarvis-v5/config/runtime_routing_policy.json)
  - `jarvis` prefers `Qwen3.5-9B`
  - `scout` prefers `Qwen3.5-35B`
  - embeddings are local-only
  - burst is forbidden for Jarvis/Scout defaults
- [config/model_policy.json](/home/rollan/.openclaw/workspace/jarvis-v5/config/model_policy.json)
  - still explicitly describes a scaffold-era Qwen-first policy layer, not live Discord binding

### External OpenClaw binding truth

Current external OpenClaw config is also basically aligned:

- `~/.openclaw/openclaw.json`
  - default primary: `lmstudio/qwen/qwen3.5-9b`
  - default fallback: `lmstudio/qwen3.5-35b-a3b`
  - `jarvis` primary: `lmstudio/qwen/qwen3.5-9b`
  - `scout` primary: `lmstudio/qwen3.5-35b-a3b`
  - `channels.modelByChannel.discord = {}`

Active Discord session truth:

- `~/.openclaw/agents/jarvis/sessions/sessions.json`
  - `providerOverride = lmstudio`
  - `modelOverride = qwen/qwen3.5-9b`
- latest session file:
  - `provider = lmstudio`
  - `modelId = qwen/qwen3.5-9b`

Conclusion:

- active provider path is not the main current blocker
- the live Discord route is already pointed at the NiMo-hosted 9B path
- the repo does not currently prove that Discord is hitting a healthy chat-serving path end to end; it only proves the intended binding

### Retry/failover truth

Current Jarvis config is fail-closed:

- primary: `lmstudio/qwen/qwen3.5-9b`
- fallbacks: `[]`
- Jarvis auth profiles: one (`lmstudio:default`)

OpenClaw still logs generic lines like:

- `Profile lmstudio:default timed out. Trying next account...`

Local OpenClaw source shows that line is emitted before `advanceAuthProfile()` checks whether another account actually exists.

So today that log line is potentially misleading:

- it does **not** prove a second real Jarvis account/path is configured
- with the current Jarvis config, it more likely means a generic internal retry/failover wrapper was entered on the same fail-closed path

Operator truth should therefore distinguish:

- configured path truth
- real alternate configured path presence
- generic internal retry semantics

### Current provider/model binding files actually in play

Repo-side:

- [config/models.yaml](/home/rollan/.openclaw/workspace/jarvis-v5/config/models.yaml)
- [config/runtime_routing_policy.json](/home/rollan/.openclaw/workspace/jarvis-v5/config/runtime_routing_policy.json)
- [config/model_policy.json](/home/rollan/.openclaw/workspace/jarvis-v5/config/model_policy.json)

External OpenClaw-side:

- `~/.openclaw/openclaw.json`
- `~/.openclaw/agents/jarvis/agent/models.json`
- `~/.openclaw/agents/jarvis/agent/auth-profiles.json`
- `~/.openclaw/agents/jarvis/sessions/sessions.json`

What those currently say:

- Jarvis Discord is bound to `providerOverride=lmstudio`
- Jarvis Discord is bound to `modelOverride=qwen/qwen3.5-9b`
- `lmstudio` in OpenClaw currently points at `http://100.70.114.34:1234/v1`
- repo routing policy still says:
  - Jarvis default = `Qwen3.5-9B`
  - Scout default = `Qwen3.5-35B`
  - embeddings = local-only
  - burst forbidden for normal Jarvis/Scout defaults

So the config story is basically coherent.
The failure is after binding, not before binding.

## What Is Still Open For Real Discord Operation

### 1. Active provider path

Current state:

- basically correct
- NiMo 9B is the active Jarvis Discord route
- Scout is mapped to NiMo 35B

Not the main blocker now.

### 2. Model timeout cause

Current state:

- now looks like a real live-path problem, not just a hypothetical one
- current operator context says Discord replies are still timing out on:
  - `lmstudio/qwen/qwen3.5-9b`
  - `lmstudio/qwen3.5-35b-a3b`
- direct curl to NiMo 9B succeeds, but slowly, and returns partial reasoning-style output
- repo-side summaries can classify backend/model timeout, but that does not prove the current Discord failure is timeout-driven

Conclusion:

- timeout is now one of the active blockers on the live chat path
- this still does not look like a repo routing-policy defect by itself

### 3. Failure lifecycle truth

Fresh Discord/OpenClaw evidence now shows a more precise order:

1. request is bound correctly to:
   - `lmstudio/qwen/qwen3.5-9b`
   - `http://100.70.114.34:1234/v1`
   - NIMO
2. the first hard failure is:
   - `Model unloaded.`
3. the second failure is:
   - timeout during a secondary internal step on the same provider path
4. generic OpenClaw wording like:
   - `Trying next account...`
   is not proof of real configured path drift for Jarvis

Current diagnosis priority order is therefore:

1. model residency / unload / eviction on NIMO
2. keep-loaded / pinning / prewarm
3. timeout only after unload is solved
4. prompt/runtime incompatibility only after unload is solved

### 3. Prompt template / session corruption cause

Current state:

- still the strongest remaining external hypothesis
- earlier live evidence showed:
  - `Error rendering prompt with jinja template: "No user query found in messages."`
- current active session file proves the live Discord lane is still going through LM Studio on the NiMo 9B model
- the repo does not control LM Studio prompt templates or OpenClaw’s upstream message formatting

Conclusion:

- this still looks external to the repo seam
- specifically: OpenClaw-to-LM-Studio request/template/runtime compatibility
- timeout and template/runtime issues may both be present on the same external chat path

### 4. Save / push state

Current state:

- the repo worktree is not in a clean committed state
- `git status --short` shows a large set of uncommitted source changes plus generated state/log churn
- several of the new sidecar/control-plane files are still untracked

Conclusion:

- repo-side work is not yet saved/pushed cleanly
- that is an operational blocker for confident deployment/handoff, even if it is not the root cause of Discord failure

## What Not To Touch Next

Do not touch next unless the evidence changes:

- repo routing architecture again
- repo degradation framework again
- repo governance framework again
- dashboard-only wording churn
- ShadowBroker/world-ops sidecar behavior

Do not conflate these with the live Discord problem:

- repo-side lane activation summaries
- workspace registry
- go-live gate
- extension-lane labels

Those are already implemented and not the main blocker.

## Exact Files That Still Need Edits

Repo-side:

- none are strictly required for the next live Discord diagnosis pass based on current evidence

External/machine-side likely next edit targets instead:

- `~/.openclaw/openclaw.json` only if the active provider binding drifts again
- OpenClaw agent/session/provider binding files if Discord is still falling through an unintended model or provider
- LM Studio model/template/runtime config on the NiMo host
- the live OpenClaw Discord request-formatting / timeout path outside this repo

## Smallest Next Patch Plan

Do not patch repo routing again first.

Smallest next move:

1. keep repo code unchanged
2. capture one fresh failing Discord request/response pair from the active OpenClaw session
3. capture one timed-out fallback attempt if the 35B fallback is still being tried
4. compare those payloads against:
   - the direct successful curl contract
   - the active LM Studio model template behavior
5. if the chat path is still using a broken local/Snowglobe LM Studio route, fix the external OpenClaw binding first
6. otherwise fix the external prompt-template/runtime compatibility issue first
7. only return to repo code if that comparison shows a real repo-side request-shaping defect

## Blunt Reconciliation

Repo status:

- control-plane summaries: done
- lane summaries/activation/proof: done
- workspace registry access control: done
- ShadowBroker sidecar integration: done
- operator go-live gate: done

Actual Discord operation:

- still blocked outside the repo seam
- current strongest blockers are:
  - live external timeout behavior on the active LM Studio chat path
  - external prompt-template/runtime compatibility
  - unclean save/push state for the repo worktree

This repo is no longer the obvious first place to patch for the current Discord text failure.
