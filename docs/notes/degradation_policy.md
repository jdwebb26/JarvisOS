# Durable DegradationPolicy Notes

Jarvis now persists degradation policy and degradation lifecycle state in durable JSON files:

- `state/degradation_policies/*.json`
- `state/degradation_events/*.json`

This is the control-plane record for degraded runtime behavior. It is not a prompt-only or log-only convention.

## What is persisted

- policy per subsystem:
  - `subsystem`
  - `degradation_mode`
  - `fallback_action`
  - `requires_operator_notification`
  - `auto_recover`
  - `retry_policy`
- event per degradation incident:
  - failure category
  - governed fallback action
  - retry policy
  - operator-notification requirement
  - active vs recovered lifecycle
  - source refs explaining why the subsystem degraded

## Current live wiring

- Hermes failures record degradation events through `runtime/integrations/hermes_adapter.py`
- reviewer/auditor gate failures record degradation events through `runtime/core/promotion_governance.py`
- status/export/snapshot/handoff surfaces consume `runtime/core/degradation_policy.py`

## Important rule

Degraded mode must never silently reduce security posture.

In particular:

- review-required work cannot auto-promote when the reviewer lane is unavailable
- approval-required work cannot auto-promote when the auditor lane is unavailable
- Hermes fallback remains policy-governed and fail-closed by default
