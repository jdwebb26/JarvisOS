# Next Operator Actions

## Use This Order

1. If you are working repo-side only: do nothing else repo-side right now.
2. If you are working NIMO-side:
   - open [docs/nimo_runtime_stabilization_runbook.md](/home/rollan/.openclaw/workspace/jarvis-v5/docs/nimo_runtime_stabilization_runbook.md)
   - use [docs/nimo_runtime_quick_commands.md](/home/rollan/.openclaw/workspace/jarvis-v5/docs/nimo_runtime_quick_commands.md) as the compact command sheet
3. If you are working installed OpenClaw-side:
   - open [docs/openclaw_live_publish_patch_plan.md](/home/rollan/.openclaw/workspace/jarvis-v5/docs/openclaw_live_publish_patch_plan.md)
   - open [docs/openclaw_reasoning_status_leak_handoff.md](/home/rollan/.openclaw/workspace/jarvis-v5/docs/openclaw_reasoning_status_leak_handoff.md)
   - inspect the exact dist seams called out there
4. After either external fix:
   - run [docs/discord_nimo_postfix_retest.md](/home/rollan/.openclaw/workspace/jarvis-v5/docs/discord_nimo_postfix_retest.md)

## Healthy Enough To Trust Again

Treat Jarvis Discord as healthy enough to trust again only if all of these are true on the same fresh attempt:

- no `Model unloaded.`
- no same-attempt timeout on the provider path
- no raw startup/bootstrap/status/reasoning spill in the newest raw `lmstudio` assistant row
- no giant contaminated `delivery-mirror` replay
- `python3 scripts/operator_discord_runtime_check.py --json` shows fresh live execution evidence, not just bound-path truth
