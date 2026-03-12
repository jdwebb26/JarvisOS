# Jarvis 5.2 Runtime Migration

## What 5.2 is

Jarvis 5.2 is the next runtime posture after the bounded v5.1 closure.  
Its target is a multi-model, policy-routed runtime with richer backend health, replay, scoring, and operator visibility.

This repo does not claim that 5.2 runtime behavior is already live.

## What stays the same

- Jarvis remains the public face and control plane.
- Conversation is not execution.
- Explicit `task:` semantics remain the execution boundary.
- Qwen-first remains the live default posture until routing-core migration tickets land.
- Review, approval, provenance, replayability, and bounded trust boundaries stay intact.

## What this scaffold pass adds

- docs that separate live v5.1 posture from the 5.2 target
- backend health and accelerator state scaffolding
- replay/scoring scaffolding on top of the existing eval trace spine
- additive dashboard/operator visibility fields for future nodes, backend health, degraded state, reroute posture, and eval scaffolding
- bootstrap/validate/smoke/doctor/handoff awareness of the new scaffolding

## What is deferred

- routing-core changes
- backend selection redesign
- execution authority changes
- async orchestration redesign
- real reroute execution behavior
- multi-model rollout
- accelerator-aware scheduling logic

## Why safe-first tickets come before routing-core tickets

Safe-first tickets are ordered ahead of routing-core work because they create the observability and validation spine needed to review a future migration without widening execution authority.

That means:
- operators can see backend health and degraded posture before reroute logic changes
- replay/scoring seams exist before routing decisions depend on them
- bootstrap, validate, smoke, and handoff flows understand the new state dirs before core routing behavior is touched

The intent is to make future 5.2 routing work additive, reviewable, and reversible rather than a control-plane rewrite.
