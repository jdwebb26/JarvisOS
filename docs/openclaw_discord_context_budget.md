# OpenClaw Discord Context Budget

Date: 2026-03-13

This pass adds a bounded-context hotfix to the live OpenClaw embedded-run path.

## Policy

- Prompt budget is estimated before each model call.
- The report is persisted through the existing `systemPromptReport.promptBudget` path.
- Categories reported:
  - `systemPrompt`
  - `recentConversationTurns`
  - `toolSchemas`
  - `retrievedMemory`
  - `rawToolOutputs`
  - `metadataWrappers`
- Discord simple-chat turns use `toolExposure.mode = "chat-minimal"` and attach no tool schemas.
- Discord working memory defaults to a raw user-turn window of `6` when no tighter channel history limit is configured.
- Old Discord metadata wrappers and stale tool-result blobs are distilled before prompt send.
- If the raw-turn window is exceeded or the estimated prompt size exceeds the safe threshold, the runtime compacts before the model call.
- Safe threshold: `72%` of model context window.
- Hard stop threshold: `82%` of model context window.
- If the prompt still exceeds the hard threshold after preflight compaction, the model call is blocked instead of sending an obviously unsafe request.

## Operator Visibility

- Live runtime persistence:
  - `~/.openclaw/agents/jarvis/sessions/sessions.json`
  - field: `systemPromptReport.promptBudget`
  - field: `systemPromptReport.toolExposure`
- Repo-side visibility:
  - `runtime/integrations/openclaw_sessions.py`
  - surfaced in the OpenClaw Discord session integrity summary as:
    - `latest_prompt_budget`
    - `tool_exposure_mode`
    - `tool_exposure_reason`

## Verification

1. Restart the gateway:
   - `systemctl --user restart openclaw-gateway.service`
2. Send a fresh Discord turn:
   - `reply with only: pong`
3. Inspect:
   - `python3 scripts/operator_discord_runtime_check.py --json`
   - `~/.openclaw/agents/jarvis/sessions/sessions.json`
   - newest `~/.openclaw/agents/jarvis/sessions/*.jsonl`
4. Confirm:
   - prompt budget fields are present
   - `toolExposure.mode` is `chat-minimal` on simple Discord chat
   - estimated total tokens stop growing linearly across turns
   - preflight compaction triggers once the raw-turn window or safe budget is exceeded

## Known Limitations

- The hotfix is applied to the installed OpenClaw dist bundle, not repo-owned JS source.
- Repo tests cover operator-visible reporting of the new budget fields, not the installed bundle execution path itself.
- The current preflight tool-exposure heuristic is intentionally narrow:
  - simple Discord chat gets no tools
  - task/code/file/shell-looking prompts still receive the full existing tool surface
