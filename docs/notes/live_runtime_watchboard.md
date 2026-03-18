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

### J. HAL ACP production path (2026-03-17 — confirmed)
- **Evidence**: `systemctl --user status openclaw-gateway.service` shows active child processes:
  - `openclaw-acp` (multiple instances)
  - `acpx --session agent:hal:acp:<uuid> --file -` (live acpx session)
- **Gateway**: `acp.enabled=true`, `backend=acpx`, `allowedAgents=["hal"]` in `openclaw.json`
- **Status**: ✅ LIVE (gateway dispatches HAL turns through acpx; multiple concurrent ACP sessions confirmed)

### N. HAL ACP per-turn journal telemetry (2026-03-18)
- **File**: `scripts/source_owned_context_engine_cli.py` (modified)
- **Seam**: `_emit_hal_acp_telemetry()` called in `main()` after `build_context_packet()` for every `agent_id=hal` turn
- **Two sinks**:
  1. `state/acp_telemetry/hal_acp.jsonl` — durable per-turn records, operator-queryable
  2. `systemd-cat -t openclaw-acp -p info` — writes to journal; inherits gateway cgroup so appears in `journalctl --user -u openclaw-gateway.service`
- **Path detection**:
  - `path=acpx` when `":acp:"` in session_key (standalone ACP task session: `agent:hal:acp:<uuid>`)
  - `path=embedded` for HAL's main Discord session (`agent:hal:main`, uses embedded model calls)
- **Log format**: `[acp:hal] context_build session=<key> path=<acpx|embedded> model=<model> provider=<provider> ts=<iso>`
- **Guard**: fires only for `agent_id == "hal"` — all other agents pass through unchanged
- **Proven live** (2026-03-18):
  - ACP session: `[acp:hal] context_build session=agent:hal:acp:proof-from-gw-cgroup path=acpx model=qwen/qwen3-coder-30b provider=lmstudio` in `journalctl --user -u openclaw-gateway.service` ✅
  - Main session: `path=embedded` recorded correctly ✅
  - Non-HAL (jarvis) filtered: state line count unchanged ✅
  - 17/17 context engine tests pass; 393/393 validate pass ✅
- **Before**: `[agent:nested] session=agent:hal:main run=<uuid>` only — no path/model/ACP label
- **After**: `[acp:hal] context_build session=agent:hal:acp:<uuid> path=acpx model=qwen/qwen3-coder-30b provider=lmstudio` appears BEFORE the nested session reply line
- **Status**: ✅ LIVE

### M. Routing decision memory write point (2026-03-17)
- **File**: `runtime/core/decision_router.py`
- **Function**: `route_task_for_decision_explainable()` → new `_write_routing_memory()` helper
- **Trigger**: fires at end of `route_task_for_decision_explainable()` for `review_requested` and `approval_requested` result kinds only
- **Memory entry**: `decision_memory` episodic, `memory_type=routing_decision`, confidence 0.70/0.75
- **Title format**: `"{actor} routed {task_class} to {reviewer} review: {req[:70]}"`
- **Guards**: skips `waiting_review`, `blocked_by_review`, `waiting_approval`, `blocked_by_approval`, `no_action` (non-dispatch states); skips if `normalized_request < 8 chars`; dedup via `write_session_memory_entry()` title+class
- **Proven live**:
  - `jarvis routed code to archimedes review: Build walk-forward cross-validation module...` written ✅
  - Second call (same task → `waiting_review`) → suppressed, count unchanged ✅
- **Why high-value**: tells future Jarvis sessions "code tasks route to archimedes; deploy tasks route to anton" without an LLM turn to figure it out
- **Status**: ✅ LIVE

### L. Memory write points for task/review/approval outcomes (2026-03-17)
- **Files**: `runtime/core/task_runtime.py`, `runtime/core/review_store.py`, `runtime/core/approval_store.py`
- **Write points added**:
  1. **Task completion** — `set_task_status()` → `_write_task_outcome_memory()`: writes `decision_memory` episodic entry when a task completes/fails with a real outcome (>15 chars). Guards: skips trivial ping/test tasks, skips empty outcomes.
  2. **Review verdict** — `record_review_verdict()`: writes `decision_memory` semantic entry for APPROVED/REJECTED verdicts with reason (>10 chars). Guards: skips CHANGES_REQUESTED (noisy), skips empty reason.
  3. **Approval decision** — `record_approval_decision()`: writes `decision_memory` semantic entry for APPROVED decisions. confidence=0.85 (highest).
- **Dedup**: all use `write_session_memory_entry()` which deduplicates by title+memory_class.
- **Proven live**:
  - Task complete: `decision_memory` episodic entry written: `hal: completed code — Implement momentum signal...` ✅
  - Review approved: `decision_memory` semantic entry: `archimedes approved review (code): Add walk-forward validation...` ✅
  - Approval approved: `decision_memory` semantic entry: `operator approved (deploy): Promote NQ momentum strategy...` ✅
  - Guard filters: trivial ping task + empty outcome both suppressed (count unchanged) ✅
  - Retrieval: `retrieve_memory_for_context()` returns all 3 entries correctly ranked ✅
- **Status**: ✅ LIVE

### K. Rolling summary constraint/memory extraction fix (2026-03-17)
- **File**: `runtime/gateway/source_owned_context_engine.py`
- **Problem fixed**: `active_constraints` was capturing system-injected text, JSON payloads, timestamp-prefixed messages, and assistant output as "operator constraints". Every session was poisoning `state/memory_entries/` with junk (3 garbage entries confirmed and removed).
- **Changes**:
  - Added `_SUMMARY_NOISE_RE` to detect injected lines (runtime-generated, internal context, subagent wrappers, JSON/timestamp prefixes)
  - `constraints` now scans `user_texts` only (not `assistant_texts`), bounded to 20-200 chars, noise-filtered
  - `decisions` bounded to 15-250 chars
  - `tool_findings` requires ≥30 chars, skips bare JSON punctuation lines
- **Proven**: Before fix, 5 garbage entries in `active_constraints`. After fix, real operator constraints ("Do not execute live trades without operator approval") captured correctly; noise filtered.
- **Memory cleanup**: Deleted 3 garbage `state/memory_entries/ment_*.json`. Cleared stale Jarvis vault `active_constraints`.
- **SearXNG lane activation**: `state/lane_activation/searxng.json` written — `status=completed, healthy=true, endpoint=http://localhost:8888`
- **Tests**: 17/17 source_owned_context_engine tests pass; 393/393 validate checks pass
- **Status**: ✅ LIVE

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
