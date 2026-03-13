## Purpose

This document captures the exact installed OpenClaw seam responsible for the remaining live Discord reply contamination after the repo-side import/report cleanup in commit `39ce70f`.

The remaining issue is external-runtime-side. It is already present in raw OpenClaw session assistant rows before this repo reads or summarizes them.

## Proven Boundary

Newest post-patch live session:

- session file: `~/.openclaw/agents/jarvis/sessions/4e6f6c00-8049-42ab-84f2-2c8ac2986073.jsonl`
- binding:
  - provider override: `lmstudio`
  - model override: `qwen/qwen3.5-9b`

Relevant rows:

1. OpenClaw injects a reset/startup user message:

```text
A new session was started via /new or /reset. Execute your Session Startup sequence now - read the required files before responding to the user...
```

2. The raw model assistant row already contains contamination:

```text
Be natural. Do not include a greeting unless there are no other messages in the current channel.

✅ New session started · model: lmstudio/q
</think>

NO_REPLY
```

3. OpenClaw then mirrors a cleaned-but-still-contaminated assistant row:

```text
Be natural. Do not include a greeting unless there are no other messages in the current channel.

✅ New session started · model: lmstudio/q
```

This proves the contamination is upstream of the repo importer/report seam.

## Exact Installed Files

Primary installed OpenClaw seams:

- `~/.npm-global/lib/node_modules/openclaw/dist/reply-DhtejUNZ.js`
- `~/.npm-global/lib/node_modules/openclaw/dist/pi-embedded-helpers-WkKFkFQ7.js`
- `~/.npm-global/lib/node_modules/openclaw/dist/sessions-DNn6Jbbx.js`
- `~/.npm-global/lib/node_modules/openclaw/dist/deliver-xtu58uBi.js`
- `~/.npm-global/lib/node_modules/openclaw/dist/gateway-cli-vk3t7zJU.js`

Equivalent sibling bundles with the same logic also exist in the same dist directory.

## Exact Functions / Seams

### 1. Reset prompt injection

In `reply-DhtejUNZ.js`:

- `BARE_SESSION_RESET_PROMPT`
- `runPreparedReply(...)`
- `baseBodyFinal = isBareSessionReset ? BARE_SESSION_RESET_PROMPT : baseBody`

In `gateway-cli-vk3t7zJU.js`:

- the same bare reset prompt is assigned to `message` for `/new` or `/reset` flows

This is the model-visible startup/reset prompt seam.

### 2. Reset notice banner delivery

In `reply-DhtejUNZ.js`:

- `buildResetSessionNoticeText(...)`
- `sendResetSessionNotice(...)`

This generates and sends the `✅ New session started · model: ...` banner.

### 3. User-facing payload normalization before delivery

In `reply-DhtejUNZ.js`:

- `normalizeReplyPayload(...)`

Current behavior:

- strips exact or embedded `NO_REPLY`
- strips heartbeat tokens
- calls `sanitizeUserFacingText(...)`

### 4. Weak sanitizer

In `pi-embedded-helpers-WkKFkFQ7.js`:

- `sanitizeUserFacingText(...)`

Current behavior is too weak for this failure mode. It strips final tags, but it does not reliably strip:

- orphan `</think>`
- startup chatter like `Be natural. Do not include a greeting...`
- session banners like `✅ New session started · model: ...`
- other startup/control residues when they arrive mixed into assistant output

### 5. Mirror transcript append

In `deliver-xtu58uBi.js`:

- `deliverOutboundPayloads(...)`
- passes `normalized.text` into `mirror`

In `sessions-DNn6Jbbx.js`:

- `resolveMirroredTranscriptText(...)`
- `appendAssistantMessageToSessionTranscript(...)`

This mirrors the already-normalized delivery text into the session transcript as:

- provider: `openclaw`
- model: `delivery-mirror`

There is no extra sanitization in the mirror append path.

## Exact Contamination Chain

1. OpenClaw injects `BARE_SESSION_RESET_PROMPT` during bare `/new` or `/reset`.
2. That startup/reset text is model-visible.
3. The model emits startup/control junk such as:
   - `Be natural. Do not include a greeting...`
   - `</think>`
   - `NO_REPLY`
   - older sessions also showed `Session Startup Sequence`
4. `normalizeReplyPayload(...)` removes only part of the junk.
5. `sanitizeUserFacingText(...)` is not strong enough to remove the remaining startup/control chatter.
6. `deliverOutboundPayloads(...)` sends that partially cleaned text to the live channel.
7. The same partially cleaned text is mirrored into the session transcript by `delivery-mirror`.

## Smallest Patch Concept

The narrowest practical external patch is:

1. Patch `sanitizeUserFacingText(...)` in `pi-embedded-helpers-WkKFkFQ7.js`
2. Strip the observed startup/control residues before delivery:
   - `</think>`
   - standalone `NO_REPLY`
   - the exact startup line beginning `Be natural. Do not include a greeting`
   - reset banner lines beginning `✅ New session started · model:`
3. Leave error rewriting and existing final-tag stripping intact

Why this is the narrowest seam:

- `normalizeReplyPayload(...)` already routes every outbound reply through `sanitizeUserFacingText(...)`
- `routeReply(...)` then passes the sanitized `text` into both live delivery and `delivery-mirror`
- so one sanitizer patch can affect both user-facing delivery and the mirrored transcript row

## Why This Pass Did Not Patch Installed OpenClaw

This pass stopped at diagnosis and a patch plan instead of editing the installed package because:

1. the target is a minified external dist under `~/.npm-global`, not a repo-owned source file
2. the patch would be a production edit outside the workspace and would need backup, restart, and live retest together
3. this pass did not have a clean way to force one fresh Discord/OpenClaw end-to-end verification turn after patching
4. the more correct source fix may be upstream of the sanitizer:
   - stop leaking reset/startup prompt content into model-visible text in the first place
   - decide whether the reset banner should be generated separately from model output

## Recommended External Patch Order

1. Back up:
   - `reply-DhtejUNZ.js`
   - `pi-embedded-helpers-WkKFkFQ7.js`
   - `sessions-DNn6Jbbx.js` only if mirror-specific fallback is needed
2. First patch only `sanitizeUserFacingText(...)`
3. Restart `openclaw-gateway.service`
4. Send one fresh Discord Jarvis message that creates or uses a fresh session
5. Inspect:
   - newest `~/.openclaw/agents/jarvis/sessions/*.jsonl`
   - recent `journalctl --user -u openclaw-gateway.service`
6. Only if startup contamination still appears in raw delivered text:
   - patch the reset/startup prompt seam in `reply-DhtejUNZ.js` / `gateway-cli-vk3t7zJU.js`

## Success Criteria After External Patch

- the live Discord-visible assistant reply no longer includes:
  - `Be natural. Do not include a greeting...`
  - `</think>`
  - `NO_REPLY`
  - `Session Startup Sequence`
  - `✅ New session started · model: ...` inside normal assistant body
- the `delivery-mirror` row no longer mirrors those residues
- repo-side summaries stay clean without needing additional filtering

## Retest Steps After External Patch

1. Restart gateway:
   - `systemctl --user restart openclaw-gateway.service`
2. Send one fresh Discord Jarvis prompt
3. Inspect the newest session transcript:
   - verify the raw assistant row no longer contains startup/control junk in the delivered reply body
   - verify the `delivery-mirror` row also stays clean
4. Inspect recent gateway logs for:
   - `Model unloaded.`
   - same-attempt timeout
5. Run repo-side operator check again:
   - `python3 scripts/operator_discord_runtime_check.py --json`

## Scope Note

This patch plan does not reopen repo routing, NIMO model-selection work, or Scout. The current blocker remains external-runtime-side.
