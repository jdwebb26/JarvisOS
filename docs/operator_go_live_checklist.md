# Operator Go-Live Checklist

Use:

```bash
python3 scripts/operator_go_live_gate.py
```

This writes:

- `state/logs/operator_go_live_gate.json`

## Gate meaning

The gate is `READY NOW` only when all of these are true:

- repo `validate` posture is green
- repo `smoke_test` posture is green
- primary runtime posture is healthy
- a default home runtime workspace exists
- at least one non-scaffold, non-deprecated lane is actually live on this machine

## Lane labels

- `READY NOW`
  - lane is `live_and_usable`
- `BLOCKED BY CONFIG`
  - lane integration exists, but config or proof contract is missing
- `BLOCKED BY EXTERNAL RUNTIME`
  - lane integration exists, config may exist, but the runtime/service/proof is not healthy
- `SCAFFOLD ONLY`
  - repo surface exists but no live activation path is present
- `DEPRECATED ALIAS`
  - compatibility/read-model alias only

## Notes

- This gate uses existing summaries and activation/proof records only.
- It does not promote anything into routing or model policy.
- A previously implemented lane is not enough. It must have current machine-local evidence.
