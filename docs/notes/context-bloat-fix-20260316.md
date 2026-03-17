# Context Bloat Fix — 2026-03-16

## Root Cause

`_build_prompt_budget()` in `runtime/gateway/source_owned_context_engine.py` passed integer char counts to `estimate_tokens()`. That function calls `str(value)` then measures string length, so:

```python
estimate_tokens(215728)  # str(215728) = "215728" → 6 chars → 2 tokens
# Should be: 215728 // 4 = 53932 tokens
```

With token counts underestimated by ~27,000×, `overSafeThreshold` never fired for tool-heavy sessions. Budget checks were meaningless, emergency compaction never triggered, and large tool results were passed directly to the model — causing "Context size has been exceeded" on agents like Jarvis and Scout.

The `compaction: safeguard` mode in `openclaw.json` doesn't help here: it silently cancels for Qwen/LM Studio sessions (no API key to call the compaction endpoint).

## Fix (`source_owned_context_engine.py`)

**Edit 1** — Replaced three `estimate_tokens(integer)` calls with direct integer division:

```python
# Before (bug):
"recentConversationTurns": {"tokens": estimate_tokens(recent_chars), ...},
"rawToolOutputs":           {"tokens": estimate_tokens(tool_output_chars), ...},
"metadataWrappers":         {"tokens": estimate_tokens(metadata_chars), ...},

# After (correct):
"recentConversationTurns": {"tokens": max(0, (recent_chars + 3) // 4), ...},
"rawToolOutputs":           {"tokens": max(0, (tool_output_chars + 3) // 4), ...},
"metadataWrappers":         {"tokens": max(0, (metadata_chars + 3) // 4), ...},
```

**Edit 2** — Added emergency tool-distill pass after the compaction step:

When the compacted 3-turn window is still over safe threshold (which can now happen with correct estimation), all remaining tool results in that window are force-distilled to short stubs before the packet is returned. Fires only when needed; `compaction.reason` is set to `"emergency_tool_distill"` for observability.

## Validation

Tested with a synthetic session: 10 turns, each with 4 tool results × 120K chars = 480K chars total in the working window. With the fix:
- `overSafeThreshold` correctly detected as `True`
- `compaction.reason = "emergency_tool_distill"` fired
- Tool result content replaced with distilled stubs
- `blocked: False` — packet returned successfully

## No Restart Needed

The gateway invokes `source_owned_context_engine_cli.py` as a fresh subprocess per model turn. Changes take effect immediately on the next Discord turn.

## What Remains

- The `estimate_tokens()` function itself is still broken for integer inputs; the three call sites in `_build_prompt_budget` are fixed, but any other callers should be audited.
- Scout's channel session (`e6437dcd`) had 472KB of tool results (~65K tokens). It's within budget now but should be reset if it keeps growing.
- Long-running sessions that never idle-reset (Jarvis ran 24+ hours before failing) bypass the `idleMinutes: 120` reset. Consider a hard turn-count ceiling in `source_owned_context_engine.py`.
