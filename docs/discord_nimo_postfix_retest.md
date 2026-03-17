# Discord NIMO Post-Fix Retest

Use this from Snowglobe after the NIMO operator says:

- `qwen/qwen3.5-9b` is pinned / kept loaded
- idle unload is disabled if possible
- the model was prewarmed after restart

## 1. Send one fresh Discord Jarvis message

In the live Discord `#jarvis` channel, send a small request such as:

```text
jarvis ping
```

Do not reuse old conclusions from earlier failed turns. This must be a fresh attempt after the NIMO-side fix.

## 2. Inspect the latest Jarvis session binding

```bash
sed -n '1,220p' ~/.openclaw/agents/jarvis/sessions/sessions.json
```

Confirm the active session is still bound to:
- `providerOverride = lmstudio`
- `modelOverride = qwen/qwen3.5-9b`

## 3. Inspect the newest session JSONL

```bash
latest=$(ls -1t ~/.openclaw/agents/jarvis/sessions/*.jsonl | head -n 1)
echo "$latest"
sed -n '1,260p' "$latest"
```

Look for:
- a fresh user turn
- a normal assistant reply
- no `errorMessage: "Model unloaded."`

## 4. Inspect recent gateway logs

```bash
journalctl --user -u openclaw-gateway.service -n 120 --no-pager
```

Check the same fresh attempt for absence of:
- `Model unloaded.`
- `embedded run timeout`
- `Profile lmstudio:default timed out`

## 5. Run the repo-side truth check

From the repo root:

```bash
python3 scripts/operator_discord_runtime_check.py --json
```

## Success Criteria

The NIMO path is stabilized only if all of these are true on the same fresh attempt:

- no `Model unloaded.`
- no embedded run timeout on that attempt
- no generic retry line attached to a failed live run on that attempt
- a normal assistant reply appears in the fresh session JSONL
- `operator_discord_runtime_check.py --json` shows fresh live execution evidence instead of only bound-path truth

## If Failure Remains

### If unload is gone but timeout remains

Interpretation:
- model residency is improved
- runtime latency or capacity is now the primary blocker

Next step:
- investigate timeout/runtime capacity on NIMO

### If timeout is gone but output is malformed

Interpretation:
- prompt/runtime incompatibility is now the primary blocker

Next step:
- compare the real Jarvis/OpenClaw request shape against the successful direct probe payload

### If neither unload nor timeout remains

Interpretation:
- the NIMO path is stabilized

Next step:
- treat Jarvis Discord as healthy on the intended primary path
