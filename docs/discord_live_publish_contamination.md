# Discord Live Publish Contamination

Date: 2026-03-13

This note records the remaining live Jarvis Discord contamination after the repo-side reply-cleanup seam was patched in commit `39ce70f`.

It is evidence and a runbook, not a new design doc.

## Bottom Line

The remaining junk in fresh live Jarvis Discord replies is external to this repo.

It is already present in the raw OpenClaw session assistant messages before any repo-side summary or sanitizer reads them.

The repo-side patch in `runtime/integrations/openclaw_sessions.py` only cleans imported assistant text for operator/reporting use inside this repo. It does not control the actual OpenClaw Discord/new-session publish path.

## Exact Newest Evidence

Newest live Jarvis Discord session:

- `~/.openclaw/agents/jarvis/sessions/sessions.json`
  - `sessionId = 4e6f6c00-8049-42ab-84f2-2c8ac2986073`
  - `providerOverride = lmstudio`
  - `modelOverride = qwen/qwen3.5-9b`

Newest session file:

- `~/.openclaw/agents/jarvis/sessions/4e6f6c00-8049-42ab-84f2-2c8ac2986073.jsonl`

Relevant rows:

1. OpenClaw inserts a reset/new-session prompt as a `user` message:

   - timestamp: `2026-03-13T04:14:47.309Z`
   - text begins:
     - `A new session was started via /new or /reset. Execute your Session Startup sequence now...`

2. The raw model reply is already contaminated:

   - timestamp: `2026-03-13T04:14:59.500Z`
   - `provider = lmstudio`
   - `model = qwen/qwen3.5-9b`
   - `api = openai-completions`
   - text:

```text
Be natural. Do not include a greeting unless there are no other messages in the current channel.

✅ New session started · model: lmstudio/q
</think>

NO_REPLY
```

3. OpenClaw then mirrors part of that reply as a second assistant row:

   - timestamp: `2026-03-13T04:15:00.004Z`
   - `provider = openclaw`
   - `model = delivery-mirror`
   - `api = openai-responses`
   - text:

```text
Be natural. Do not include a greeting unless there are no other messages in the current channel.

✅ New session started · model: lmstudio/q
```

Older fresh contamination in the immediately prior reset session showed the same pattern with different junk:

- `Session Startup Sequence`
- injected file-content chatter
- later mirrored by the same `delivery-mirror` path

## What This Proves

The remaining contamination is not being invented by:

- `runtime/integrations/openclaw_sessions.py`
- `scripts/operator_discord_runtime_check.py`
- repo-side bridge/import summaries

Why:

- the junk is present in the raw `openai-completions` assistant row from `provider=lmstudio`
- only after that does a second `provider=openclaw model=delivery-mirror` row mirror the text

So the contamination path is:

1. OpenClaw injects a built-in reset prompt and startup/bootstrap context
2. the external live model replies with scaffold/control text
3. OpenClaw delivery-mirror mirrors that reply into the session
4. the repo only observes it afterward

## Exact External Source Boundary

The installed OpenClaw package contains the reset prompt:

- `~/.npm-global/lib/node_modules/openclaw/dist/pi-embedded-CtM2Mrrj.js`
- `~/.npm-global/lib/node_modules/openclaw/dist/pi-embedded-DgYXShcG.js`
- `~/.npm-global/lib/node_modules/openclaw/dist/reply-DhtejUNZ.js`
- `~/.npm-global/lib/node_modules/openclaw/dist/plugin-sdk/reply-DFFRlayb.js`

Confirmed string:

- `const BARE_SESSION_RESET_PROMPT = "A new session was started via /new or /reset..."`

The installed OpenClaw package also generates the session-start banner:

- `✅ New session started · model: ...`

The `NO_REPLY` token is also an OpenClaw control token in the installed package/docs, not a repo-defined token in `jarvis-v5`.

## Why The Repo Cannot Fully Fix It

This repo can:

- detect the contamination in imported session text
- sanitize it for repo-side operator summaries
- phrase runtime/ShadowBroker truth correctly

This repo cannot:

- stop OpenClaw from injecting the reset prompt
- stop the external runtime from answering with bootstrap/control text
- stop the external `delivery-mirror` layer from mirroring that contaminated content into live sessions

Any repo-only patch here would be a reporting cleanup, not the real live publish fix.

## Exact Next External Seam To Fix

The next fix must happen in the installed OpenClaw live reply path, specifically around:

1. the reset/new-session prompt path using `BARE_SESSION_RESET_PROMPT`
2. the startup/bootstrap context injection that causes the model to emit:
   - `Session Startup Sequence`
   - `Be natural. Do not include a greeting...`
   - raw control text like `NO_REPLY`
3. the `delivery-mirror` publish/mirror path, which currently mirrors contaminated assistant text into the session

## External Runbook

1. Inspect the OpenClaw source around `BARE_SESSION_RESET_PROMPT` and the new-session auto-reply flow in the installed package or upstream source.
2. Confirm where startup/bootstrap context is appended before the first live reply.
3. Ensure internal startup instructions are not model-visible as user-facing content.
4. Ensure `NO_REPLY`, `</think>`, and similar control tokens are stripped before Discord delivery and before `delivery-mirror` writes the final assistant message.
5. Re-run one fresh Discord `/new` or first-message turn and inspect:
   - raw `openai-completions` assistant row
   - mirrored `delivery-mirror` row
   - actual Discord-visible output
6. Only after that should this repo be revisited for any further cleanup.

## Repo Status After This Finding

The repo-side reply-cleanup seam is still valid and useful.

But a fresh Jarvis Discord reply should not yet be expected to be fully clean, because the remaining contamination is upstream in external OpenClaw/runtime behavior.
