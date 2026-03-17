# Live Runtime Watchboard — 2026-03-17

**Purpose**: Track what is live, what is newly wired, what is proven, what is blocked.
**Keep short. Update on meaningful changes only.**

---

## What Is Live Now

| System | Status | Notes |
|--------|--------|-------|
| Gateway (openclaw-gateway.service) | ✅ LIVE | PID 1935168, ws://127.0.0.1:18789 |
| Discord channel bindings | ✅ LIVE | 12 channels resolved (+6 after hermes) |
| LM Studio (Qwen models) | ✅ LIVE | 100.70.114.34:1234 |
| NVIDIA/Kimi-K2.5 (Kitt) | ✅ LIVE | Proven 2026-03-17 |
| SearXNG web search | ✅ LIVE | localhost:8888, proven live |
| PinchTab browser backend | ✅ LIVE | 127.0.0.1:9867, user service |
| Bowser browser actions (execute path) | ✅ LIVE | navigate/snapshot/screenshot proven |
| Voice/Cadence ingress classification | ✅ LIVE | cadence_ingress.py, routing live |
| Claude provider (Anthropic) | ✅ LIVE | channel 1483515985628627116, needs real API key |
| Strategy factory (cron) | ✅ LIVE | daily 4AM data, Sunday factory run |

---

## Newly Wired (2026-03-17 — this task)

### A. Agent channel map
- **File**: `config/agent_channel_map.json`
- **Content**: All 13 agents mapped (channel IDs + voice_only flags + routing rule sets)
- **Status**: ✅ LIVE

### B. Agent status store
- **File**: `runtime/core/agent_status_store.py`
- **State dir**: `state/agent_status/<agent_id>.json`
- **Purpose**: Cheap per-agent "what is happening now" — no LLM needed to inspect
- **Proven**: `get_agent_status("bowser")` returns live state after browser action
- **Status**: ✅ LIVE

### C. Backend result store
- **File**: `runtime/core/backend_result_store.py`
- **State dir**: `state/backend_results/bkres_*.json`
- **Purpose**: Compact summaries of completed backend actions. Jarvis reads before touching full artifacts.
- **Proven**: `get_latest_result("bowser")` returns summary from live Bowser navigate
- **Status**: ✅ LIVE

### D. Discord event router
- **File**: `runtime/core/discord_event_router.py`
- **State dirs**: `state/dispatch_events/` + `state/discord_outbox/`
- **Purpose**: Normalizes events → owner channel + worklog mirror + jarvis forward. No LLM.
- **Proven**:
  - `browser_result` from bowser → owner ch `1483539080271761408` + worklog mirror ✅
  - `task_completed` from `cadence` → blocked (cadence is voice-only) ✅
  - `voice_session_started` from `cadence` → owner ch `1483537502152425625` ✅
- **Status**: ✅ LIVE

### E. Worklog mirror helper
- **File**: `runtime/core/worklog_mirror.py`
- **Purpose**: Thin wrapper to force worklog outbox entry from any event kind
- **Proven**: `mirror_browser_result(...)` writes to worklog outbox ✅
- **Status**: ✅ LIVE

### F. Bowser adapter wired to stores
- **File**: `runtime/integrations/bowser_adapter.py` (modified)
- **What changed**: After every `handle_browser_action()` result:
  1. `update_agent_status("bowser", ...)` → `state/agent_status/bowser.json`
  2. `save_backend_result(...)` → `state/backend_results/bkres_*.json`
  3. `emit_event("browser_result", "bowser", ...)` → dispatch_event + outbox entries
- **Proven**: Live navigate → confirmed in agent_status + backend_results + outbox ✅
- **Status**: ✅ LIVE

### G. Discord channel additions (openclaw.json)
- **New bindings**: bowser (`1483539080271761408`), cadence (`1483537502152425625`)
- **New allowlist entries**: bowser, cadence, worklog (`1483539374854639761`)
- **Gateway proof**: `+6` channels resolved at startup (was `+3`)
- **Status**: ✅ LIVE

---

## What Is Proven

| Claim | Evidence |
|-------|----------|
| Bowser live navigate creates agent_status | `get_agent_status("bowser")` confirmed after live run |
| Bowser live navigate creates backend_result | `get_latest_result("bowser")` confirmed |
| browser_result routes to bowser channel | `emit_event` → `owner_channel_id: 1483539080271761408` |
| browser_result mirrors to worklog | `worklog_mirrored: True`, outbox entries for `1483539374854639761` |
| non-voice event blocked from cadence | `task_completed` from `cadence` → `cadence_blocked: True` |
| voice event passes to cadence | `voice_session_started` → `1483537502152425625` |
| gateway resolves all 12 channels | `+6` after hermes in gateway log |

---

### H. Discord outbox sender (2026-03-17)
- **File**: `runtime/core/discord_outbox_sender.py`
- **State dir**: `state/discord_delivery/dlv_*.json`
- **Mechanism**: reads `discord_outbox/*.json` status=pending, resolves channel_id → JARVIS_DISCORD_WEBHOOK_* env var, POSTs via `dispatch_utils.post_webhook()`, marks delivered/failed/skipped
- **Timer**: `openclaw-discord-outbox.service` + `.timer` (60s interval, systemd user unit, enabled)
- **Status**: ✅ LIVE (mechanism proven; all existing webhook URLs in secrets.env are HTTP 403 expired)

### I. Task/review/approval lifecycle emitters (2026-03-17)
- `task_runtime.set_task_status()` → `emit_event()` + `update_agent_status()` on every transition
- `review_store.request_review()` + `record_review_verdict()` → `emit_event(review_requested/review_completed)`
- `approval_store.request_approval()` + `record_approval_decision()` → `emit_event(approval_requested/approval_completed)`
- All wrapped in try/except; never break existing task lifecycle
- **Status**: ✅ LIVE (wired; proven via `_emit_task_status_event` direct test)

---

## What Is Still Blocked / Partial

| Item | Why Blocked | Fix |
|------|-------------|-----|
| **Discord webhooks expired** | All 4 existing webhook URLs (JARVIS, CREW, REVIEW, COUNCIL) return HTTP 403. New webhooks for bowser/cadence/worklog/hal/scout etc. never created. | User: Discord Server Settings → Integrations → Webhooks → create one per channel → set `JARVIS_DISCORD_WEBHOOK_*` in `~/.openclaw/secrets.env` |
| Claude agent live calls | `ANTHROPIC_API_KEY=REPLACE_ME` | User sets real key |
| Hermes external daemon | External service not running | Activate external Hermes service |
| Ralph autonomy loop | Needs ACP or external runtime | — |
| Muse Discord channel | No channel ID configured | — |

---

## Exact Next Highest-Leverage Tasks

1. **Recreate Discord webhooks** — single user action; unblocks all live Discord delivery. Create one webhook per channel in Discord Server Settings, set env vars in `~/.openclaw/secrets.env`.
2. **Set ANTHROPIC_API_KEY** — user action; unblocks Claude agent.
3. **Verify first real live delivery** — after webhooks set, trigger a test browser action and confirm #bowser and #worklog receive the message.
4. **Hermes daemon activation** — external service prerequisite.
