# Jarvis 5.2 Migration Status

This file is an operator-facing status label for the current 5.2 sidecars and extensions.

Use only these labels:

- `live_and_usable`
- `implemented_but_blocked_by_external_runtime`
- `scaffold_only`
- `deprecated_alias`

These labels describe current repo truth and external-runtime availability. They are not roadmap language.

## Lane Status

- `shadowbroker`
  - `implemented_but_blocked_by_external_runtime` unless the external ShadowBroker service is configured and healthy now
  - becomes `live_and_usable` only when config + health path are green
- `world_ops`
  - `deprecated_alias`
  - remains the compatibility aggregation layer; prefer ShadowBroker for the external OSINT sidecar path
- `autoresearch_upstream_bridge`
  - `implemented_but_blocked_by_external_runtime` unless an upstream autoresearch runtime is actually configured and completing runs
- `adaptation_lab_unsloth`
  - `implemented_but_blocked_by_external_runtime` unless Unsloth is installed and a real bounded proof run has actually completed on this machine
- `optimizer_dspy`
  - `implemented_but_blocked_by_external_runtime` unless DSPy is installed and a real bounded proof run has actually completed on this machine
- `hermes_bridge`
  - `implemented_but_blocked_by_external_runtime` unless the external Hermes bridge is actually completing runs
- `searxng`
  - `implemented_but_blocked_by_external_runtime` unless the configured SearXNG backend healthcheck is green
- `browser_bridge`
  - `scaffold_only`
- `mission_control_adapter`
  - `scaffold_only`
- `a2a`
  - `scaffold_only`

## Notes

- Do not call a lane `live_and_usable` unless a real runtime path has been validated.
- `implemented_but_blocked_by_external_runtime` means the Jarvis-side integration exists, but the required external service/runtime is not currently configured or healthy.
- `deprecated_alias` means the lane exists only as a compatibility/read-model path and should not be treated as the preferred integration surface.
- These labels should match `extension_lane_status_summary` in status, operator snapshot, state export, and doctor output.
