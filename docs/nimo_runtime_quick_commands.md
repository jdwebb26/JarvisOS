# NIMO Runtime Quick Commands

Use this only as a compact command sheet alongside [docs/nimo_runtime_stabilization_runbook.md](/home/rollan/.openclaw/workspace/jarvis-v5/docs/nimo_runtime_stabilization_runbook.md).

It does not replace the full runbook.

## Process / Listener

```bash
ps -ef | rg -i 'lm studio|lmstudio'
ss -ltnp | rg ':1234'
```

## Config / State Search

```bash
for p in "$HOME/.config" "$HOME/.local/share" "$HOME"; do
  find "$p" -maxdepth 4 \( -iname '*lm*studio*' -o -iname '*lmstudio*' \) 2>/dev/null
done
```

## Residency / Unload Search

```bash
rg -n -i 'keep.?loaded|auto.?unload|idle|unload|evict|preload|warm' \
  "$HOME/.config" "$HOME/.local/share" 2>/dev/null
```

## Direct Local Retest

```bash
curl -sS --max-time 40 http://127.0.0.1:1234/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen/qwen3.5-9b","messages":[{"role":"user","content":"Reply with exactly pong."}],"temperature":0,"max_tokens":16}'

curl -sS --max-time 40 http://127.0.0.1:1234/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen/qwen3.5-9b","messages":[{"role":"user","content":"Reply with exactly pong."}],"temperature":0,"max_tokens":16}'
```

## Fix Order Reminder

1. keep `qwen/qwen3.5-9b` loaded or pinned
2. disable idle unload if possible
3. prewarm once after restart
4. only then consider timeout increase
