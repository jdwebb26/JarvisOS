# External Lane Activation

This repo can probe and record real machine-local activation state for these external lanes:

- `shadowbroker`
- `searxng`
- `hermes_bridge`
- `autoresearch_upstream_bridge`

It can also record bounded local proof runs for:

- `adaptation_lab_unsloth`
- `optimizer_dspy`

Use:

```bash
python3 scripts/operator_activate_external_lanes.py
```

For local proof lanes:

```bash
python3 scripts/operator_activate_local_model_lanes.py
```

This writes durable activation records under:

- `state/lane_activation/`
- `state/lane_activation_runs/`

## What activation means

A lane is considered live on this machine only when a probe actually succeeds and records:

- `status = completed`
- `healthy = true`

Config by itself is not enough.

For local proof lanes, a previously stored run is not enough either. A lane becomes live on this machine only after a real bounded proof run completes and records `status = completed` with `healthy = true`.

## Lane-specific env contract

ShadowBroker:

- `JARVIS_SHADOWBROKER_BASE_URL`
- `JARVIS_SHADOWBROKER_API_KEY`
- `JARVIS_SHADOWBROKER_TIMEOUT_SECONDS`
- `JARVIS_SHADOWBROKER_VERIFY_SSL`

SearXNG:

- `JARVIS_SEARXNG_URL`

Hermes bridge:

- `JARVIS_HERMES_BRIDGE_COMMAND`
- `JARVIS_HERMES_BRIDGE_CWD`
- `JARVIS_HERMES_BRIDGE_TIMEOUT_SECONDS`

Hermes activation expects the external bridge command to support Jarvis healthcheck mode via:

- `JARVIS_HERMES_BRIDGE_MODE=healthcheck`
- `JARVIS_HERMES_REQUEST_FILE`
- `JARVIS_HERMES_RESULT_FILE`

Autoresearch upstream:

- `JARVIS_AUTORESEARCH_UPSTREAM_COMMAND`
- `JARVIS_AUTORESEARCH_UPSTREAM_CWD`
- `JARVIS_AUTORESEARCH_UPSTREAM_TIMEOUT_SECONDS`

Autoresearch activation uses the existing Jarvis request/result file contract plus:

- `JARVIS_AUTORESEARCH_PROBE_MODE=healthcheck`
- `JARVIS_AUTORESEARCH_REQUEST_FILE`
- `JARVIS_AUTORESEARCH_RESULT_FILE`

Local model proof lanes:

- `JARVIS_UNSLOTH_TINY_MODEL`
- `JARVIS_DSPY_TINY_MODEL`
- `JARVIS_DSPY_API_BASE_URL`
- `JARVIS_DSPY_API_KEY`

## Recorded result fields

Each activation result records:

- `lane`
- `started_at`
- `completed_at`
- `status`
- `runtime_status`
- `configured`
- `healthy`
- `command_or_endpoint`
- `evidence_refs`
- `error`
- `details`
- `operator_action_required`

## Interpretation

- `blocked`
  - missing config or missing runtime binary
- `degraded`
  - configured but probe failed, timed out, or returned a bad payload
- `completed`
  - probe succeeded and the lane is live on this machine

These activation records are operator evidence only. They do not make any lane authoritative for routing, approvals, promotion, or runtime truth.
