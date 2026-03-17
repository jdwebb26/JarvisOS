# Jarvis Discord Operator State

Date: 2026-03-13
Branch: `feature/5.2-control-plane-live-lanes`

This is the compact operator state for the current Jarvis Discord lane.

## Commits Of Interest

- `3e104b3` Document OpenClaw reasoning/status leak handoff
- `8f7caf5` Document OpenClaw live publish patch seam
- `aaa631d` Add NIMO stabilization and Discord retest handoff docs
- `e64eff7` Document external Discord live reply contamination seam
- `39ce70f` Sanitize Discord reply imports and tighten live reply contract
- `c642fe7` Harden Discord session truth and repair detection
- `d4330f7` Activate 5.2 sidecars and operator runtime diagnostics

## Current Active Discord Path

- agent: `jarvis`
- provider: `lmstudio`
- model: `qwen/qwen3.5-9b`
- backend/API: `openai-completions`
- endpoint: `http://100.70.114.34:1234/v1`
- host classification: `NIMO`
- fallback posture: fail-closed
- configured fallbacks: `[]`
- auth profile count: one Jarvis auth profile

`qwen/qwen3.5-9b` should remain Jarvis primary.

## What Is Already Fixed Repo-Side

- Jarvis Discord binding is pinned fail-closed to the intended `lmstudio/qwen/qwen3.5-9b` path.
- malformed Discord session poison was detected and repaired
- repo-side routing and retry/failover drift were ruled out as primary blockers
- imported assistant replies are sanitized for repo/operator reporting in `runtime/integrations/openclaw_sessions.py`
- truthful runtime and ShadowBroker clean-reply hints exist in `scripts/operator_discord_runtime_check.py`
- operator docs now exist for NIMO stabilization, postfix retest, OpenClaw publish contamination, and reasoning/status leak handoff

## What Remains Broken

### External OpenClaw / Runtime Side

1. heavier live Discord/OpenClaw turns previously hit:
   - first hard failure: `Model unloaded.`
   - second failure: timeout during a secondary internal step on the same provider path
2. startup/bootstrap/status/reasoning spill is still happening upstream of repo summaries
3. the newest affected raw session shows giant internal-looking prompt/status dumps in the raw `lmstudio` assistant row
4. `delivery-mirror` also mirrors contaminated assistant text when it is present

### Not The Blocker

- repo routing
- malformed session poison
- Jarvis configured fallback drift
- missing repo-side reply-import cleanup

## Exact Current Boundary

### Repo-Side Fixed

- binding truth
- operator truth summaries
- malformed-session visibility and repair
- repo-side imported-reply cleanup
- truthful sidecar/runtime phrasing

### External-Runtime-Side Still Broken

- NIMO-hosted live runtime stability on heavier Discord/OpenClaw turns
- OpenClaw startup/reset prompt visibility
- OpenClaw outbound filtering for internal bootstrap/status spill
- `delivery-mirror` reproducing contaminated assistant text

## Newest Affected Local Evidence

Newest affected session:

- `~/.openclaw/agents/jarvis/sessions/a80eb363-5384-4508-8a80-24494b43d96b.jsonl`

What it shows:

- session-start banner appears in `openclaw` / `delivery-mirror`
- reset/startup prompt is injected as a `user` message
- giant `Reasoning:` / `session_status` / missing-file / sandbox-path / image-tool chatter is present in the raw `lmstudio` assistant row
- a later giant queued-task bootstrap dump is present in a raw `lmstudio` assistant row and then mirrored by `delivery-mirror`

So the current leak is not only a mirror artifact. The raw model-visible prompt/bootstrap spill is still the primary issue.

## What The Operator Should Do Next

1. Do not do more repo-side routing work right now.
2. If working NIMO-side, open:
   - [docs/nimo_runtime_stabilization_runbook.md](/home/rollan/.openclaw/workspace/jarvis-v5/docs/nimo_runtime_stabilization_runbook.md)
   - [docs/nimo_runtime_quick_commands.md](/home/rollan/.openclaw/workspace/jarvis-v5/docs/nimo_runtime_quick_commands.md)
3. If working installed OpenClaw-side, open:
   - [docs/openclaw_live_publish_patch_plan.md](/home/rollan/.openclaw/workspace/jarvis-v5/docs/openclaw_live_publish_patch_plan.md)
   - [docs/openclaw_reasoning_status_leak_handoff.md](/home/rollan/.openclaw/workspace/jarvis-v5/docs/openclaw_reasoning_status_leak_handoff.md)
   - [docs/discord_live_publish_contamination.md](/home/rollan/.openclaw/workspace/jarvis-v5/docs/discord_live_publish_contamination.md)
4. After any external fix, run the Snowglobe retest in:
   - [docs/discord_nimo_postfix_retest.md](/home/rollan/.openclaw/workspace/jarvis-v5/docs/discord_nimo_postfix_retest.md)

## Recommended Next Codex / Manual Slice

The next bounded slice should be external-runtime-focused:

- either NIMO model residency stabilization first, if `Model unloaded.` still reproduces on fresh heavy turns
- or installed OpenClaw startup/reset prompt visibility cleanup first, if the primary visible failure is prompt/status spill

Do not reopen repo architecture unless fresh evidence shows the repo is again the source of truth for the failure.
