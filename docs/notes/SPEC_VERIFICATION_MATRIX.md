# Spec Verification Matrix

Tracks whether each spec-promised feature actually works in production.

> See also: [CURRENT_TRUTH.md](CURRENT_TRUTH.md) (status/backlog), [live_runtime_watchboard.md](live_runtime_watchboard.md) (proof journal)

## How to use

Each row is a spec claim. Status is one of: **LIVE** | **PARTIAL** | **BLOCKED** | **SCAFFOLD** | **DOC-ONLY**.
Only update status when you have live proof (not just code review).

---

## Control Plane

| Feature | Spec | Status | Evidence |
|---------|------|--------|----------|
| Multi-agent Discord channel bindings | v5.1 | **LIVE** | 12 channels resolved, all agents bound |
| Source-owned context engine | v5.1 | **LIVE** | 6-turn window, budget guard, tool filtering |
| Context budget guard (72%/82%) | v5.1 | **LIVE** | Integer estimation bug fixed 2026-03-16 |
| Tool/skill allowlists per agent | v5.1 | **LIVE** | Fail-closed, unknown agents get 0 tools |
| Runtime routing policy | v5.2 | **LIVE** | Profile-driven via `runtime_profiles.py` → `sync_routing_policy_to_openclaw.py` → `openclaw.json` |
| Multi-node burst routing | v5.2 | **SCAFFOLD** | Code exists, `burst_allowed=false` everywhere |
| HAL ACP harness | v5.1 | **LIVE** | Gateway dispatches HAL through acpx |

## Agent Lanes

| Feature | Spec | Status | Evidence |
|---------|------|--------|----------|
| Kitt quant specialist | v5.1 | **LIVE** | First-class dispatch (`kitt_quant`), SearXNG + Kimi K2.5, brief artifacts |
| Hermes research daemon | v5.1 | **BLOCKED** | Adapter hardened, external daemon not running |
| Ralph autonomy loop | v5.1 | **LIVE** | Bounded v1: claim → HAL proxy → review → complete. End-to-end proven |
| Bowser browser bridge | v5.1 | **LIVE** | PinchTab backend, navigate/snapshot/text proven |
| Cadence voice | v5.2 | **PARTIAL** | Stack built, mic blocked (WSL2 RDPSource) |
| Muse creative | v5.1 | **SCAFFOLD** | Bootstrap files present, no live session |

## Task / Governance

| Feature | Spec | Status | Evidence |
|---------|------|--------|----------|
| Task lifecycle (create→complete) | v5.1 | **LIVE** | Events at every transition |
| Review chain (HAL→Archimedes→Anton) | v5.1 | **LIVE** | Proven with real tasks |
| Resumable approval checkpoints | v5.1 | **LIVE** | Checkpoint → approve → resume path working |
| Promotion governance gates | v5.1 | **LIVE** | Code exists, no strategy has reached PF ≥ 1.5 yet |
| Emergency controls / kill switches | v5.1 | **LIVE** | Global kill, subsystem breakers, rate governors |

## Memory / Learning

| Feature | Spec | Status | Evidence |
|---------|------|--------|----------|
| Episodic + semantic memory | v5.1 | **LIVE** | Writes from tasks, reviews, approvals, routing |
| Learnings ledger | custom | **LIVE** | JSONL-backed, writes from failures/rejections, filtered retrieval |
| Memory retrieval for context | v5.1 | **LIVE** | Called every turn, returns ranked entries |

## Integrations

| Feature | Spec | Status | Evidence |
|---------|------|--------|----------|
| SearXNG web search | v5.2 | **LIVE** | localhost:8888, proven |
| NVIDIA / Kimi K2.5 | custom | **LIVE** | api.nvidia.com, proven |
| Discord webhooks (all 12) | custom | **LIVE** | All HTTP 200, emoji-first format |
| ShadowBroker OSINT | v5.2 | **SCAFFOLD** | External runtime not present |
| TradingView adapter | v5.2 | **DOC-ONLY** | No implementation |
| A2A protocol | v5.2 | **DOC-ONLY** | No implementation |

## Strategy Factory

| Feature | Spec | Mission | Status | Evidence |
|---------|------|---------|--------|----------|
| Data pull (OHLCV + VIX) | v5.1 | 90-day | **LIVE** | Daily 4AM cron |
| Feature generation | v5.1 | 90-day | **LIVE** | Runs after data pull |
| Candidate → Backtest pipeline | v5.1 | 90-day | **LIVE** | Pipeline code present, Sunday batch |
| PF ≥ 1.5 promotion gate | Mission | 90-day | **NOT YET** | No candidate has passed yet |
| Paper trading | Mission | 90-day | **NOT YET** | Requires promotion gate pass + operator approval |
