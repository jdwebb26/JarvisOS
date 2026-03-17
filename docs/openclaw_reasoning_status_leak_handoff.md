## Purpose

This handoff captures the newer live Discord leak where Jarvis emitted internal-looking reasoning, status, bootstrap, and file-creation chatter directly into the channel.

Conclusion: this is not a separate OpenClaw status-event stream being forwarded to Discord. In the newest reproduced case, the leaked content is already present in the raw `lmstudio` assistant text. That makes this an upstream bootstrap/prompt spill plus weak delivery filtering problem, not a clean one-file event-router bug.

## Exact Newest Session Evidence

Newest affected session:

- `~/.openclaw/agents/jarvis/sessions/a80eb363-5384-4508-8a80-24494b43d96b.jsonl`

Key rows:

1. Session-start mirror banner:

```json
{"provider":"openclaw","model":"delivery-mirror","text":"✅ New session started · model: lmstudio/qwen/qwen3.5-9b"}
```

2. Reset/startup prompt injected as a `user` message:

```text
A new session was started via /new or /reset. Execute your Session Startup sequence now...
```

3. Raw `lmstudio` assistant row is already contaminated:

- provider: `lmstudio`
- model: `qwen/qwen3.5-9b`
- stopReason: `length`

Representative leaked content from that raw model row:

```text
Do not ask if they need help. Just respond to them as your persona would.
✅ New session started · model: lmstudio/q ...
IDENTITY.md: MISSING
The file /home/IDENTITY.md is missing.
session_status: 📊 session_status
## Reasoning: on (visible)
## Reasoning: off (visible)
## Reasoning: thin
## configuration
## Reason in sandboxed session, use sandboxed paths ...
## Identity file missing
## Reason image: Analyze an image with the configured image model.
...
cat > /home/rollan/.openclaw/workspace/jarvis-v5/IDENTITY.md << 'EOF'
...
cat > /home/rollan/.openclaw/workspace/jarvis-v5/USER.md << 'EOF'
...
```

That row proves the leak is not merely `delivery-mirror` or a status event frame. The model itself is emitting internal/bootstrap content as assistant text.

## Installed Files Inspected

- `~/.npm-global/lib/node_modules/openclaw/dist/reply-DhtejUNZ.js`
- `~/.npm-global/lib/node_modules/openclaw/dist/pi-embedded-helpers-WkKFkFQ7.js`
- `~/.npm-global/lib/node_modules/openclaw/dist/deliver-xtu58uBi.js`
- `~/.npm-global/lib/node_modules/openclaw/dist/sessions-DNn6Jbbx.js`
- `~/.npm-global/lib/node_modules/openclaw/dist/gateway-cli-vk3t7zJU.js`

Read-only runtime context also checked:

- latest `sessions.json`
- newest affected session transcript above
- recent `journalctl --user -u openclaw-gateway.service`

## What This Leak Is And Is Not

### What it is

- raw model-visible bootstrap contamination
- weak outbound sanitization before live delivery
- weak mirrored-transcript sanitization

### What it is not

- not a pure `delivery-mirror` bug
- not a standalone Discord publish bridge inventing `Reasoning:` lines
- not a separate internal status/debug frame serializer directly emitting those lines to the channel

## Exact Contamination Chain

1. OpenClaw creates a fresh session and injects startup/reset instructions.
2. The model sees startup/bootstrap text that includes internal contract and file/status material.
3. The raw `lmstudio` assistant response spills that material back verbatim or near-verbatim.
4. `normalizeReplyPayload(...)` and `sanitizeUserFacingText(...)` are far too weak to stop it.
5. OpenClaw delivers that contaminated assistant body to Discord.
6. OpenClaw may also mirror derived text into the session transcript, but the user-visible leak has already happened by step 4.

## Why No Safe Local Hotfix Was Applied

No small safe hotfix was applied in this pass because the leak is now too broad and unconstrained for an honest one-file filter patch.

Reasons:

1. The raw model output is not limited to a few control tokens. It includes arbitrary startup text, file-missing chatter, session labels, reasoning/status labels, and generated shell commands.
2. A pattern-only patch in minified dist would be brittle and easy to under-filter or over-filter.
3. The clean fix boundary is upstream of delivery:
   - reduce model-visible startup/bootstrap spill
   - stop file scaffolding from entering the model-visible prompt
   - then keep a narrow sanitizer as a backstop
4. This pass could not force a fresh end-to-end Discord verification turn after a risky external hot edit.

## Exact File / Function Seams To Patch Next

Primary seams:

### 1. Startup/reset prompt injection

In `reply-DhtejUNZ.js`:

- `BARE_SESSION_RESET_PROMPT`
- `runPreparedReply(...)`
- `baseBodyFinal = isBareSessionReset ? BARE_SESSION_RESET_PROMPT : baseBody`

In `gateway-cli-vk3t7zJU.js`:

- `/new` or `/reset` handling that assigns `message = BARE_SESSION_RESET_PROMPT`

This is the first seam to fix if the goal is to stop the model from seeing and echoing bootstrap instructions.

### 2. Outbound sanitizer backstop

In `pi-embedded-helpers-WkKFkFQ7.js`:

- `sanitizeUserFacingText(...)`

This should remain a backstop, but it is not enough as the only fix because the spill set is now much broader than `NO_REPLY` and `</think>`.

### 3. Reply normalization before delivery

In `reply-DhtejUNZ.js`:

- `normalizeReplyPayload(...)`

This is where a stricter pre-delivery reject/drop rule could be added if upstream bootstrap cleanup still leaves recognizable internal-only frames.

## Safe Patch Decision

There is not a clearly safe small local installed-package patch for this leak class from this pass.

The earlier idea of extending `sanitizeUserFacingText(...)` is no longer sufficient on its own, because the raw assistant text is now an arbitrary prompt dump rather than a small set of known control markers.

## Operator Hotfix Plan If Someone Chooses To Edit Installed OpenClaw Anyway

If a human operator still chooses to hotfix the installed package locally, do it as one grouped step and treat it as an external runtime experiment:

1. Back up:
   - `reply-DhtejUNZ.js`
   - `pi-embedded-helpers-WkKFkFQ7.js`
2. First reduce startup/reset prompt visibility:
   - change the bare reset path so the full startup instruction block is not sent as normal user-visible/model-visible body text
3. Then add a narrow backstop in `sanitizeUserFacingText(...)` for:
   - `## Reasoning:`
   - `session_status:`
   - `Identity file missing`
   - `The file ... is missing.`
   - obvious startup banner lines
   - fenced shell-file creation chatter for `IDENTITY.md` / `USER.md`
4. Restart:
   - `systemctl --user restart openclaw-gateway.service`
5. Send one fresh Discord Jarvis turn
6. Inspect:
   - newest `~/.openclaw/agents/jarvis/sessions/*.jsonl`
   - recent `journalctl --user -u openclaw-gateway.service`
   - `python3 scripts/operator_discord_runtime_check.py --json`

## Retest Criteria

After any external hotfix, verify:

- no `Reasoning:` / `session_status` / `Identity file missing` lines reach Discord
- no startup task list or shell `cat > ... EOF` blocks reach Discord
- raw `lmstudio` assistant text is materially cleaner, not just `delivery-mirror`
- no new false-positive stripping of real user-facing content

## Rollback

If installed-file backups were created, rollback is:

1. restore the original backed-up dist files
2. restart `openclaw-gateway.service`
3. re-run one Discord test turn and confirm behavior returned to the pre-hotfix state

## Scope Note

This handoff does not reopen repo routing, Scout, or model-selection work. `qwen/qwen3.5-9b` should remain Jarvis primary. The blocker remains external-runtime-side.
