# OpenClaw Current Truth — 2026-03-18

Single authoritative status of what works, what doesn't, and what to do next.
Updated by proven facts only. Supersedes narrative in older trackers.

**Validate**: `python3 scripts/validate.py` — 395 pass, 0 fail (as of 2026-03-18)

### Which file do I use?
| File | Purpose |
|------|---------|
| **[CURRENT_TRUTH.md](CURRENT_TRUTH.md)** | Current status and backlog (this file) |
| **[SPEC_VERIFICATION_MATRIX.md](SPEC_VERIFICATION_MATRIX.md)** | Spec-to-reality verification — does feature X actually work? |
| **[FEATURE_PROMPTS.md](FEATURE_PROMPTS.md)** | Large feature request intake — ideas before they become tasks |
| **[live_runtime_watchboard.md](live_runtime_watchboard.md)** | Proof journal — detailed evidence for each wired feature |

---

## 1. Live Services

| Service | Endpoint | Status |
|---------|----------|--------|
| Gateway | ws://127.0.0.1:18789 (systemd) | **LIVE** |
| LM Studio (Qwen) | 100.70.114.34:1234 | **LIVE** |
| NVIDIA / Kimi K2.5 | api.nvidia.com | **LIVE** |
| SearXNG | localhost:8888 | **LIVE** |
| PinchTab (browser) | 127.0.0.1:9867 (systemd) | **LIVE** |
| Discord outbox sender | systemd timer, 60s interval | **LIVE** |
| Strategy factory cron | daily 4AM data, Sunday batch | **LIVE** |

## 2. Discord Delivery

All 12 webhooks verified HTTP 200 on 2026-03-18:
JARVIS, REVIEW, COUNCIL, BOWSER, HAL, KITT, WORKLOG, SCOUT, CADENCE, HERMES, MUSE, QWEN.

Messages use emoji-first format (✅/❌/⚠️/📌). Events route to owner channel + worklog mirror + Jarvis forward as configured in `config/agent_channel_map.json`.

## 3. Agents — Working

| Agent | Model | What works |
|-------|-------|------------|
| **Jarvis** | Qwen 3.5-35B (local) or Kimi K2.5 (via profile) | Orchestration, task routing, review/approval delegation, memory writes |
| **HAL** | Qwen 3-Coder-30B | Code execution via ACP (acpx), task completion, artifact production |
| **Archimedes** | Qwen 3-Coder-Next | Code review, approval chain |
| **Anton** | Qwen 3.5-122B | Supreme review, high-stakes approval |
| **Scout** | Qwen 3.5-35B | Web search via SearXNG |
| **Kitt** | Kimi K2.5 (NVIDIA) | Quant briefs via `kitt_quant` dispatch: SearXNG → Bowser → Kimi synthesis → artifact |
| **Bowser** | PinchTab browser | Navigate, snapshot, screenshot, text extraction |
| **Ralph** | Qwen 3.5-35B | Bounded autonomy loop v1: claim task → proxy to HAL → collect review → complete. End-to-end proven |

## 4. Agents — Partial or Blocked

| Agent | Status | What's missing |
|-------|--------|----------------|
| **Hermes** | BLOCKED | Adapter hardened, but external Hermes daemon not running. Needs manual service activation |
| **Cadence** | PARTIAL | Voice stack built (ingress, TTS, call routing). Mic blocked: RDPSource unavailable in WSL2. Parked until mic passthrough |
| **Muse** | NOT ACTIVE | Channel ID configured, bootstrap files present. No live session or task yet |
| **Claude** | BLOCKED | `ANTHROPIC_API_KEY=REPLACE_ME`. User must set real key |

## 5. Core Runtime Systems

### Working
- **Task lifecycle**: create → queue → start → checkpoint → complete/fail. Events emitted at every transition
- **Review/approval chain**: HAL → Archimedes review → Anton/operator approval. Resumable checkpoints
- **Backend dispatch**: `nvidia_executor`, `browser_backend`, `kitt_quant` wired. `execute_once()` picks queued tasks
- **Context engine**: bounded 6-turn working memory, budget guard (72%/82%), tool filtering, skill allowlists
- **Memory system**: episodic + semantic writes from task outcomes, review verdicts, approval decisions, routing decisions
- **Learnings ledger**: JSONL-backed (`state/learnings/`), writes from failures/rejections/operator corrections, filtered retrieval per agent
- **Delegation compact mode**: HAL/Archimedes get abbreviated context for delegated tasks
- **Session hygiene**: automatic rotation before context builds for stale sessions

### Working (operator tooling)
- **Runtime profiles**: 5 named profiles (local_only, hybrid, cloud_fast, cloud_smart, degraded). `set` → sync → gateway restart
- **Model visibility**: `runtime_profiles status` (terminal) / `post` (Discord). Profile changes auto-post to #jarvis
- **Operator cockpit**: `scripts/operator_cockpit.py` — service health, agent states, blockers
- **Validate**: `scripts/validate.py` — 395 checks, comprehensive

### Not working / scaffold only
- **Multi-node burst routing** (NIMO/Koolkidclub): scaffolded, `burst_allowed=false` everywhere. Not live
- **Routing policy enforcement**: `runtime_routing_policy.json` is enforced via runtime profiles (4240dcf). `load_runtime_routing_policy()` applies active profile overrides. `sync_routing_policy_to_openclaw.py` propagates to `openclaw.json`. Gateway uses `openclaw.json` as its config surface, which the sync script keeps aligned with the policy
- **A2A protocol**: doc-only, no implementation
- **Adaptation lab / DSPy optimizer**: scaffold, never run live
- **ShadowBroker**: scaffold, external runtime not present
- **TradingView adapter**: doc-only
- **Mission control adapter**: doc-only

## 6. Strategy Factory

- **Pipeline**: data pull → feature gen → candidate gen → simulation → gates → robustness → scoring → promotion
- **Cron**: daily 4AM OHLCV+VIX, Sunday 2AM batch run, Sunday 6AM memory compaction
- **Status**: pipeline code present, cron scheduled. No strategy has reached PF ≥ 1.5 promotion gate yet
- **Live data**: OHLCV and VIX data pulls running. Feature generation runs after data pull

## 7. Known State Quirks

- **Bowser realized model shows stale**: `qwen3.5-122b-a10b` instead of `qwen3.5-35b`. Cosmetic — Bowser's execution goes through PinchTab, not LLM
- **Hermes realized model shows stale**: last session used 35B, policy says 122B. No real impact since Hermes daemon isn't running
- **Cockpit snapshot in watchboard is stale**: auto-generated block from earlier run. Agent states may have changed since

## 8. What To Do Next (by user impact)

### Operator actions (unblock immediately)
1. **Set ANTHROPIC_API_KEY** in `~/.openclaw/secrets.env` — unblocks Claude agent
2. **Start Hermes daemon** — unblocks deep research pipeline

### High-leverage improvements
3. **First real strategy factory run with operator review** — prove the end-to-end IDEA → BACKTESTED → PROMOTED pipeline with a real NQ strategy candidate
4. **Wire Ralph to cron** — memory compaction, queue draining, failure analytics as scheduled jobs (Ralph v1 loop is proven, just needs cron entry)
5. **Activate Muse** — send first message to Muse Discord channel to create session

### Medium-leverage
6. **Session monitoring dashboard** — surface session sizes, turn counts, stale sessions for operator visibility
7. **Cadence mic passthrough** — blocked on WSL2 RDPSource. Investigate PulseAudio/pipewire WSL passthrough

---

## Reference

- **Spec verification**: [SPEC_VERIFICATION_MATRIX.md](SPEC_VERIFICATION_MATRIX.md) — does feature X actually work?
- **Feature intake**: [FEATURE_PROMPTS.md](FEATURE_PROMPTS.md) — large ideas before they become tasks
- **Proof journal**: [live_runtime_watchboard.md](live_runtime_watchboard.md) — per-item evidence (A through S)
- **Historical inventory**: `spec_feature_inventory_live_gap_2026-03-17.md` (1300+ line audit, superseded by this doc + matrix)
- **System architecture**: `SYSTEM.md`, `Jarvis_OS_v5_1_Master_Spec.md`
- **Strategy lifecycle**: `PROMOTION.md`, `RISK_POLICY.md`
- **Agent roster**: `runtime/core/agent_roster.py`, `config/agent_channel_map.json`
