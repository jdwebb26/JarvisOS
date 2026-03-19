# Salmon Adapter Runtime — 2026-03-19

## What was added

| File | Purpose |
|------|---------|
| `systemd/user/openclaw-salmon.service` | Oneshot service — runs `workspace/quant_infra/salmon/adapter.py` |
| `systemd/user/openclaw-salmon.timer` | 10-minute timer, staggered +2min after Kitt |

No changes to `workspace/quant_infra/salmon/adapter.py` — the existing CLI entrypoint was already suitable.

## Cadence

- Every **10 minutes** via systemd timer
- **Staggered**: starts at 420s after boot (Kitt starts at 300s), so Salmon fires ~2 minutes after each Kitt cycle
- `Persistent=true` — catches up if a run was missed (e.g. during suspend)
- Timeout: 120s max per run

## Outputs refreshed

| Output | Path | Consumer |
|--------|------|----------|
| Fish packet | `workspace/quant_infra/packets/fish/latest.json` | Fish lane / runtime |
| Scenario markdown | `workspace/quant_infra/research/fish_scenarios/latest.md` | Operator / Scout |
| DuckDB rows | `workspace/quant_infra/warehouse/quant.duckdb` → `fish_scenarios` table | Sigma / analytics |
| Timestamped scenario | `workspace/quant_infra/research/fish_scenarios/scenario_YYYYMMDDTHHMMSS.md` | Audit trail |

## Fish lane relationship

- **Fish** is the operator-facing lane identity (appears in packets, routing, Discord)
- **Salmon Adapter** is the backend implementation that generates scenario data for Fish
- This timer operationalizes the Salmon backend only — Fish identity, routing, and bootstrap are unchanged
- No changes to `openclaw.json`, `agent_roster.py`, or Fish identity files

## Behavior

- If open Kitt paper positions exist: generates 6 position-specific scenarios per position
- If no open positions: generates 3 baseline market scenarios
- Writes to Fish packet path and scenario markdown regardless
- DuckDB insert failures are non-fatal (logged as WARN, cycle continues)
- Exit 0 in all normal cases (including no open positions)

## Verification

- Manual `systemctl --user start openclaw-salmon.service`: status=0/SUCCESS
- Fish packet refreshed at service run time
- Scenario markdown refreshed at service run time
- 6 scenarios generated for active Kitt position (kpp-b11467922433)
- Timer active and waiting, next trigger in ~10 minutes
- Preflight: CLEAR, Postdeploy: CLEAN
