# Fish Lane Activation — Landed 2026-03-19

## Merge Details

- **Merge SHA**: `cd45a8e`
- **Pushed main SHA**: `fb37b29`
- **Feature branch**: `feat/fish-lane-activation` (commit `d37ee95`)
- **Gateway restart**: 2026-03-19T12:55:26-05:00

## Verification Results

| Check | Result |
|-------|--------|
| `openclaw config validate` | `valid: true` |
| Fish agent in `agents.list` | Yes — `Fish (Scenario & Forecasting)` |
| `#fish` channel `1483916169672130754` bound to | `fish` (was `jarvis`) |
| Fish model | `lmstudio/qwen3.5-35b-a3b` primary, `lmstudio/qwen/qwen3.5-9b` fallback |
| Fish exec | `deny` |
| Gateway RPC | OK |
| Preflight | CLEAR (0 failures, 2 advisory warnings — pre-existing, unrelated) |
| Postdeploy | CLEAN (0 failures) |
| Health monitor | HEALTHY (13/13) |
| Journal errors related to Fish | None |

## Naming Confirmation

- **Fish** = the lane / agent / operator-facing identity
- **Salmon Adapter** = the backend implementation (`workspace/quant_infra/salmon/adapter.py`)
- Salmon Adapter is NOT a lane, agent, or separate operator identity
- Packet lane identity remains `"fish"` — unchanged
- Source metadata uses `"salmon_adapter"` — unchanged

## Files Changed (repo-tracked)

- `runtime/core/agent_roster.py` — Fish added to all 4 registries
- `docs/agent_roster.md` — Fish moved from fallback to canonical roster
- `docs/channels.md` — Updated quant lane note
- `docs/overview/OVERVIEW.md` — Fish in Agent Roster table, removed from fallback
- `docs/notes/fish_lane_activation_2026-03-19.md` — activation note

## Files Changed (outside repo, applied directly)

- `~/.openclaw/openclaw.json` — Fish agent entry + binding
- `~/.openclaw/agents/fish/IDENTITY.md` — agent identity
- `~/.openclaw/agents/fish/BOOTSTRAP.md` — agent bootstrap
