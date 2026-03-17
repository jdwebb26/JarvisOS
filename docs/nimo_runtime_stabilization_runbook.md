# NIMO Runtime Stabilization Runbook

Date: 2026-03-12

This is the exact operator runbook for stabilizing the NIMO-hosted LM Studio path used by Jarvis Discord.

It is intentionally blunt.
It assumes the work is being done on the NIMO host, not from Snowglobe.

## Access Boundary

Snowglobe does **not** currently have proven direct admin access to NIMO.

What Snowglobe can prove:

- the active Jarvis Discord binding
- the exact endpoint used by OpenClaw
- direct HTTP probes to that endpoint
- the OpenClaw session and gateway evidence around the failed live Discord path

What Snowglobe cannot currently prove:

- shell access on NIMO
- the real LM Studio process state on NIMO
- the real LM Studio config/state files on NIMO
- the real keep-loaded / unload / eviction settings on NIMO

So the runtime stabilization work below must be done by a NIMO-host operator.

## Already-Proven Facts From Snowglobe

- Jarvis Discord is pinned fail-closed to:
  - `lmstudio/qwen/qwen3.5-9b`
- The provider resolves to:
  - `http://100.70.114.34:1234/v1`
- Host classification is:
  - `NIMO`
- Direct probes to that exact endpoint/model succeed back-to-back.
- The real Discord/OpenClaw path still fails.
- The first hard failure is:
  - `Model unloaded.`
- The second failure is:
  - timeout during a secondary internal step on the same provider path
- Jarvis should remain pinned to `lmstudio/qwen/qwen3.5-9b` during this pass.
- Repo routing is not the blocker.
- Session poison is cleared.

## Hypothesis Order

Use this order. Do not jump around.

1. model unload / eviction
2. keep-loaded / pinning / prewarm
3. timeout only after unload is solved
4. prompt/runtime incompatibility only after unload is solved

## NIMO-Host Inspection

Run these on NIMO.

### 1. Find the LM Studio process and listener

```bash
ps -ef | rg -i 'lm studio|lmstudio'
ss -ltnp | rg ':1234'
```

Expected:
- LM Studio or its runtime is actually serving on `127.0.0.1:1234` or the expected bound interface.

### 2. Find real LM Studio config/state locations

Do not assume a path. Search.

```bash
for p in "$HOME/.config" "$HOME/.local/share" "$HOME"; do
  find "$p" -maxdepth 4 \( -iname '*lm*studio*' -o -iname '*lmstudio*' \) 2>/dev/null
done
```

### 3. Search for residency / unload / preload settings

```bash
rg -n -i 'keep.?loaded|auto.?unload|idle|unload|evict|preload|warm' \
  "$HOME/.config" "$HOME/.local/share" 2>/dev/null
```

### 4. Inspect model/runtime logs if visible

Use the actual service/log path you found. If LM Studio is started under systemd or a launcher, inspect that service/log source directly.

Look for:
- model unloaded
- eviction
- idle unload
- OOM / VRAM pressure
- model load / unload around the Discord failure timestamp

## Smallest Safe Change Order

Apply changes in this order only.

### Step 1. Keep `qwen/qwen3.5-9b` loaded / pinned

If LM Studio exposes a per-model keep-loaded, pin, or persistent residency option:
- enable it for `qwen/qwen3.5-9b`

### Step 2. Disable idle unload / auto-unload for that model

If LM Studio exposes idle unload or eviction behavior:
- disable it for `qwen/qwen3.5-9b`

### Step 3. Prewarm once after restart

After restarting LM Studio/runtime, run one direct probe locally on NIMO:

```bash
curl -sS --max-time 40 http://127.0.0.1:1234/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen/qwen3.5-9b","messages":[{"role":"user","content":"Reply with exactly pong."}],"temperature":0,"max_tokens":16}'
```

### Step 4. Only then consider timeout increase

Do this only if:
- `Model unloaded.` is gone
- but the Discord/OpenClaw path still times out

Do not start with a timeout increase.

## Direct Retest Commands On NIMO

Run both after the keep-loaded / unload fix.

```bash
curl -sS --max-time 40 http://127.0.0.1:1234/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen/qwen3.5-9b","messages":[{"role":"user","content":"Reply with exactly pong."}],"temperature":0,"max_tokens":16}'

curl -sS --max-time 40 http://127.0.0.1:1234/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen/qwen3.5-9b","messages":[{"role":"user","content":"Reply with exactly pong."}],"temperature":0,"max_tokens":16}'
```

## Success Criteria

The NIMO-side fix is good enough to hand back to Snowglobe only if:

- `qwen/qwen3.5-9b` stays loaded across repeated requests
- there is no visible unload/eviction around the retest
- both direct requests return without timeout

## Failure Tree

### If `Model unloaded.` still appears

Interpretation:
- keep-loaded / pinning / unload controls are still not working
- or runtime capacity pressure is forcing eviction

Next step:
- inspect memory / VRAM pressure on NIMO
- reduce competing runtime pressure before touching timeouts

### If unload disappears but timeout remains

Interpretation:
- timeout is now the primary blocker

Next step:
- inspect runtime latency under the heavier Jarvis/OpenClaw path
- consider a modest timeout increase only now

### If unload disappears and timeout disappears but output is malformed

Interpretation:
- prompt/runtime incompatibility or request-shape issue is now next

Next step:
- compare the real Jarvis/OpenClaw request shape with the simple direct probe payload

## What Not To Change First

Do not start by:
- repointing Jarvis to another model
- changing Scout
- reopening repo routing
- adding model fallbacks
- increasing timeout before unload is addressed
