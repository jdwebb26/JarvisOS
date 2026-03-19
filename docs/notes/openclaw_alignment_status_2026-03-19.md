# OpenClaw Alignment Status — 2026-03-19

Operational snapshot after the March 19 hardening and cleanup passes.

## Completed

### Gateway hardening — exec deny (runtime-only, openclaw.json)
8 of 14 agents now have `tools.exec.security = "deny"` at the gateway level:
- **Safe six (batch 1):** anton, scout, bowser, cadence, muse, kitt
- **Batch 2:** archimedes, claude

These agents already had no `exec` tool in their Python-level roster allowlists (`agent_roster.py`). The gateway deny is defense-in-depth.

### Agents intentionally NOT denied
| Agent | Reason |
|-------|--------|
| jarvis | Orchestrator, needs full tool access |
| hal | Builder agent, ACP-backed, requires exec |
| qwen | ACP-backed agent, requires exec |
| ralph | Has `process`/`cron` tools; deny deferred pending `process` tool audit |
| hermes | Has `process` tool + future ACP candidate; set to allowlist later |
| main | Default agent, operator-facing |

### Systemd cleanup
- 16 dead/orphan unit files removed from `~/.config/systemd/user/`
- Ghost `lobster-discord.service` and `lobster-enrich.service` resolved (stale symlinks in `default.target.wants/` + orphan `.service.d/` drop-in dirs removed)
- `daemon-reload` applied; ghosts confirmed gone

### Repo cleanup (this pass)
13 stale `.bak`/`.stabilized` files removed from the repo:
- `runtime/core/qwen_approval_state.json.bak_stale64`
- `runtime/core/qwen_candidate_applier.py.bak_20260310`
- `runtime/core/qwen_candidate_applier.py.bak_after_manual_repair`
- `runtime/core/qwen_candidate_writer.py.bak_before_patch_plan_arg`
- `runtime/core/qwen_candidate_writer.py.bak_before_task_ready_fix`
- `runtime/core/qwen_candidate_writer.py.bak_before_timeout_bump`
- `runtime/core/qwen_patch_executor.py.bak_before_orchestrator`
- `runtime/core/qwen_patch_executor.py.bak_before_patch_plan_arg`
- `runtime/core/qwen_patch_planner.py.bak_before_taskid_bridge`
- `runtime/core/qwen_patch_planner.py.stabilized_after_manual_clean_plan_2026-03-09`
- `runtime/core/qwen_write_gate.json.bak_stale64`
- `config/models.yaml.bak_20260312_124437`
- `systemd/user/openclaw-gateway.service.bak`

### Crontab cleanup
- Obsolete `flowstate_bot.py` crontab entry removed (prior pass)
- `openclaw.json.bak-*` files in `~/.openclaw/` left intact (runtime backups, not repo)

### Memory renewal
- Provider: `ollama` (local)
- Model: `qwen3-embedding:0.6b`
- Status: 253 files indexed across all agents
- Note: `qwen3-embedding:4b` was attempted but failed on current hardware (too slow for batch timeouts). The 0.6b model works and is the live config.

### Gateway version
- OpenClaw v2026.3.13 (latest on npm as of this date)
- No pending upgrade target

## Runtime-only changes (NOT in repo)

These live exclusively in `~/.openclaw/openclaw.json` and systemd user state:
1. `agents.defaults.memorySearch` set to `ollama` / `qwen3-embedding:0.6b`
2. 8 agent entries have `tools.exec.security = "deny"` added
3. Systemd user units cleaned (files removed, daemon-reloaded)
4. Crontab: flowstate_bot entry removed

## Intentionally untouched

| Item | Reason |
|------|--------|
| Crontab `task_updates.py` | Runs every minute. Fails constantly (404 on deleted Discord channel 1479281547998662757). Generates ~44K log lines of tracebacks. **Broken but harmless.** Do not remove yet — may still be needed if the channel ID is updated. |
| Crontab `local_executor.py` | Runs every 2 minutes. **Healthy and active.** Completed tasks 126 and 127 today. Keep. |
| Ralph/Hermes exec policy | Deferred pending `process` gateway tool audit and Hermes ACP roadmap clarity |
| Model routing | Working, no changes needed |
| Discord channel mappings | Working, no changes needed |
| `docs/live_snapshots/*.bak*` | Explicitly excluded from cleanup |

## Known pre-existing conditions

- **6 failed tasks** in `state/tasks/` — causes `degraded` health verdict. These are retryable backlog, not a system fault.
- **17 systemd unit drift** — `sync_systemd_units.py` reports drift between repo unit definitions and installed units. Expected after the cleanup pass removed dead units that the repo still references.
- **`operator.read` scope errors** — dashboard WS client sends requests with limited scopes. Pre-existing, cosmetic.
- **`task_updates.py` 404 spam** — see above. ~44K lines of tracebacks in log. Harmless but noisy.

## Next optional passes

1. **Fix or remove `task_updates.py` crontab** — either update the Discord channel ID or remove the entry entirely. The log file is growing unbounded.
2. **Hermes exec allowlist** — set `exec.security = "allowlist"` with empty allow list (effectively deny, but structurally ready for future ACP commands).
3. **Ralph exec deny** — safe after confirming the `process` gateway tool does not internally require exec permissions.
4. **Systemd unit sync** — run `sync_systemd_units.py` to reconcile repo definitions with installed state, clearing the 17-unit drift warning.
5. **Failed task triage** — review and either retry or archive the 6 failed tasks to clear the degraded health verdict.
6. **Log rotation** — `task_updates.log` (44K lines) and `local_executor.log` (8K lines) have no rotation. Will grow indefinitely.

## Operator recommendation

The system is operationally clean. The hardening layer is in place for all agents that provably don't need exec. The remaining items are quality-of-life improvements, not safety issues. The next high-value action is fixing or removing the broken `task_updates.py` crontab entry to stop the 404 log spam.
