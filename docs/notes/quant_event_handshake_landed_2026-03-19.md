# Quant Event Handshake — Landing Note (2026-03-19)

## What landed

File-queue-based event handshake chain: **Kitt → Salmon/Fish → Sigma → Jarvis**.

### Chain behavior

1. **Kitt** emits events to `workspace/quant_infra/events/kitt/pending/` on position opens, closes, updates
2. **systemd path unit** watches that directory and auto-triggers the handshake service
3. **Salmon** consumes pending Kitt events, refreshes Fish scenario packet and markdown
4. **Sigma** validates the current paper-trade state (gate checks, flag generation)
5. **Jarvis** refreshes the operator summary report

Each step is bounded, idempotent, and independently faulted.

### Files added/modified

| File | Purpose |
|------|---------|
| `workspace/quant_infra/events/__init__.py` | Events package |
| `workspace/quant_infra/events/emitter.py` | File-queue event emitter (emit, read, mark_processed) |
| `workspace/quant_infra/handshake.py` | Chain orchestrator — runs salmon→sigma→jarvis steps |
| `workspace/quant_infra/salmon/event_consumer.py` | Salmon event consumer — reads Kitt events, triggers scenario refresh |
| `workspace/quant_infra/sigma/paper_trade_validator.py` | Sigma paper-trade validator — gate checks, flag generation |
| `workspace/quant_infra/kitt/run_kitt_cycle.py` | Modified — emits events on position state changes |
| `workspace/quant_infra/kitt/paper_trader.py` | Modified — emits events on position opens/closes |
| `workspace/quant_infra/jarvis/observability.py` | Modified — supports handshake-triggered refresh |
| `systemd/user/openclaw-quant-handshake.service` | Oneshot service — runs handshake.py |
| `systemd/user/openclaw-quant-handshake.path` | Path unit — watches kitt/pending for new events |

### Event queue path

```
workspace/quant_infra/events/kitt/pending/    <- new events land here
workspace/quant_infra/events/kitt/processed/  <- consumed events move here
```

### Systemd units

- `openclaw-quant-handshake.path`: active (waiting), enabled, watches `events/kitt/pending`
- `openclaw-quant-handshake.service`: oneshot, triggered by path unit, timeout 120s

## Verification

### End-to-end proof
- Emitted `position_update` event for position `kpp-b11467922433`
- Path unit auto-triggered handshake service (status=0/SUCCESS)
- Event moved from `pending/` to `processed/`
- Sigma validated: verdict=flag, 2 flags
- Operator report refreshed
- All 3 steps completed OK

### Existing timer health
- `openclaw-kitt-paper.timer`: active (waiting), next trigger in ~8min
- `openclaw-salmon.timer`: active (waiting), next trigger in ~2min
- Both timers unaffected by handshake landing

### Checks
- Preflight: CLEAR (0 fail)
- Postdeploy: CLEAN (0 fail)
- Smoke test: PASS (5/5 green)

## Merge details

- **Source commit**: `5367468` (from `feat/quant-event-handshake`)
- **Cherry-picked as**: `5a8babc`
