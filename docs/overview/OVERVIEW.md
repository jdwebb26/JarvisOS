# Jarvis OS v5.1 — System Overview

> Autonomous multi-agent AI runtime for NQ futures strategy discovery, execution, and operator supervision.
> Running on OpenClaw `v2026.3.13` — Qwen-primary, locally hosted.

---

## What This Is

Jarvis OS coordinates a fleet of specialized AI agents that receive work through Discord, execute it via local LLMs (primarily Qwen 3.5 on LM Studio), and surface results back to the operator for review and approval. The quant system discovers, validates, and paper-trades NQ futures strategies. **Nothing reaches production without human sign-off.**

- **Single operator** — designed for one operator on one machine. Dashboard and gateway bind to localhost only.
- **Human-in-the-loop** — all promotions, paper-trade requests, and live trade decisions require explicit operator approval.

---

## What Is Running Right Now

### Persistent services

| Service | What it does | Port | Status |
|---------|-------------|------|--------|
| `openclaw-gateway` | Node.js Discord bot, WebSocket, agent session routing | 18789 (loopback) | **LIVE** |
| `openclaw-inbound-server` | HTTP API for operator replies and approval routing | 18790 (loopback) | **LIVE** |
| `openclaw-dashboard` | Operator dashboard | 18793 (loopback) | **LIVE** |
| `pulse-webhook` | TradingView webhook receiver for Pulse alerts | 18795 (0.0.0.0) | **LIVE** |
| `cadence-voice-daemon` | Wake-word + VAD + STT + TTS | — (audio) | **PARTIAL** — mic blocked on WSL2 |

### Timer-driven services

| Timer | Interval | What it does |
|-------|----------|-------------|
| `openclaw-review-poller` | 30 sec | Polls `#review` for approve/reject text + emoji reactions |
| `openclaw-discord-outbox` | 60 sec | Delivers pending Discord messages via webhooks |
| `openclaw-operator-status` | 5 min | Posts action summary to `#jarvis` when operator attention needed |
| `openclaw-ralph` | 10 min | Picks one queued task, dispatches to backend, requests review |
| `openclaw-kitt-paper` | 10 min | Kitt paper trading cycle — position tracking, proof sweeps |
| `quant-lane-b-cycle` | 4 hours | Quant intelligence cycle: Atlas → Fish → Hermes → Kitt |
| `openclaw-factory-weekly` | Sun 2 AM | Strategy Factory full batch run |
| `openclaw-ops-check` | Sun 3 AM | Doctor + security audit + backup |

### Cron

| Schedule | What it does |
|----------|-------------|
| Every 2 min | `local_executor.py` — polls task queue (SQLite), dispatches strategy factory runs |

### LLM providers

| Provider | Models | Status |
|----------|--------|--------|
| LM Studio (local) | Qwen 3.5 — 9B / 35B / 122B + Coder 30B | **PRIMARY** |
| NVIDIA API | Kimi K2.5 (used by Kitt) | **LIVE** |
| Anthropic API | Claude Sonnet 4.6 | **LIVE** |
| OpenAI API | GPT-4.1 Mini | Scaffolded |

---

## Agent Roster

| Agent | Role | Model | Type |
|-------|------|-------|------|
| **Jarvis** | Orchestrator — routes tasks, decomposes work | Qwen 3.5 35B | Embedded |
| **HAL** | Builder — implements code, runs backtests | Qwen3 Coder 30B | ACP (acpx) |
| **Ralph** | Task runner — picks queued work, dispatches, requests review | Qwen 3.5 35B | Timer (10 min) |
| **Archimedes** | Technical reviewer — code review, quality gates | Qwen3 Coder Next | Embedded |
| **Anton** | Supreme reviewer — high-stakes final decisions | Qwen 3.5 122B | Embedded |
| **Hermes** | Research daemon — deep research, evidence bundles | Qwen 3.5 122B | On-demand |
| **Scout** | Recon — web search, market analysis | Qwen 3.5 35B | Embedded |
| **Muse** | Creative — design, copy, brainstorming | Qwen 3.5 35B | Embedded |
| **Bowser** | Browser agent — headless web workflows | Qwen 3.5 35B | Embedded (bounded) |
| **Kitt** | Quant lead — NQ briefs, strategy oversight | Kimi K2.5 (NVIDIA) | Interactive |
| **Cadence** | Voice ingress — wake-word, STT, TTS | Qwen 3.5 9B | Daemon (partial) |
| **Qwen** | Qwen-Agent — ACP-backed qwen-agent plugin | Qwen 3.5 35B | ACP |
| **Claude** | External model agent (Anthropic) | Claude Sonnet 4.6 | Embedded |
| **Fish** | Scenario modeling & forecasting (powered by Salmon Adapter) | Qwen 3.5 35B | Embedded |
| **Atlas** | Experiment design — candidate mutation, hypothesis generation | Qwen 3.5 35B | Embedded |
| **Sigma** | Strategy validation — gate enforcement, candidate reject/accept | Qwen 3.5 35B | Embedded |

### Quant lane services (temporary fallback)

These have Discord channels for outbound event delivery but are **not** fully separate interactive agents. Inbound messages route to Jarvis as a temporary fallback.

| Service | Channel | Purpose |
|---------|---------|---------|
| Pulse | `#pulse` | Discretionary NQ alerts & proposals |

---

## Discord Channel Model

### Operator-facing channels

| Channel | Purpose |
|---------|---------|
| **#review** | **Operator action inbox.** Review requests, approval requests, paper-trade approvals, pulse proposals. Respond with `approve apr_xxx` or emoji reactions. |
| **#worklog** | **Audit trail.** Completion receipts, review verdicts, approval decisions. Read-only — nothing here needs action. |
| **#jarvis** | **Escalations only.** Failures, blocked tasks, quant alerts, factory summaries, warnings, errors. Low-noise — only operator-action-needed events. |

### Agent channels

| Channel | What goes there | Interactive? |
|---------|----------------|-------------|
| `#hal` | Builder execution output | Yes — HAL responds |
| `#kitt` | Quant briefs, strategy oversight | Yes — Kitt responds |
| `#hermes` | Research daemon output | Yes — Hermes responds |
| `#scout` | Recon, web search results | Yes — Scout responds |
| `#muse` | Creative agent output | Yes — Muse responds |
| `#bowser` | Browser automation output | Yes — Bowser responds |
| `#cadence` | Voice/TTS events only | Voice-only channel |
| `#qwen` | Qwen-Agent output | Yes (ACP) |
| `#ralph` | Overflow / task runner output | Yes — Ralph responds |

### Quant lane channels

| Channel | What goes there | Interactive? |
|---------|----------------|-------------|
| `#sigma` | Validation events | Yes — Sigma responds |
| `#atlas` | Discovery events | Yes — Atlas responds |
| `#fish` | Scenario events | Yes — Fish responds (powered by Salmon Adapter) |
| `#pulse` | Alert events | Outbound only (jarvis fallback) |

---

## Task Lifecycle

```
QUEUED → RUNNING → WAITING_REVIEW → WAITING_APPROVAL → COMPLETED → PROMOTED
                 ↘ FAILED (retryable)
                 ↘ BLOCKED (needs operator)
```

Every task flows through this lifecycle. Nothing is auto-promoted. All promotions require explicit operator action.

---

## Review and Approval Flow

```
Ralph dispatches → HAL executes → Archimedes reviews → Operator approves → Promoted
```

- Review and approval requests appear in `#review`
- Approve via Discord: `approve apr_xxx` or emoji ✅ reaction
- Reject via Discord: `reject apr_xxx [reason]` or ❌ reaction
- Rerun: `rerun apr_xxx`
- ID patterns: `apr_*` (approvals), `qpt_*` (quant paper-trade), `pulse_*` (alerts), `promo_*` (promotions)
- Completion receipts go to `#worklog`, not `#review`
- High-stakes items (quant, deploy) escalate to Anton
- Review poller checks every 30 seconds; decisions route through inbound server → runtime → outbox → Discord

---

## The Quant System

Strategy Factory is **one part** of the broader quant system. The full picture:

| Component | What it does | Schedule |
|-----------|-------------|----------|
| **Quant Lane B** | Intelligence cycle: Atlas discovers → Fish models scenarios → Hermes researches → Kitt generates briefs | Every 4 hours |
| **Strategy Factory** | Weekly batch: backtest candidates, run validation gates, promote survivors | Sunday 2 AM |
| **Sigma** | Validation gates — PF, Sharpe, drawdown, trade count thresholds | Per-candidate |
| **Pulse** | Discretionary session alerts, TradingView webhook ingestion, proposals to downstream lanes | Real-time (webhook on :18795) |
| **Kitt** | Paper trading cycle — position tracking, proof sweeps, briefs | Every 10 min |
| **Executor** | Paper position accounting, execution intents, rejection tracking | On event |

### Strategy lifecycle

```
IDEA → CANDIDATE → VALIDATED → PROMOTED → PAPER_TRADING → LIVE
```

Paper-trade and live-trade transitions require explicit operator approval via `#review`.

### Current state (as of 2026-03-19)

- **59 strategies** in the registry, all at CANDIDATE stage with gate failures
- **0 strategies** promoted to paper trading yet
- Logic families tested: EMA crossover, breakout, mean reversion
- Gate failures primarily: insufficient trade counts, Sharpe below 0.5 threshold
- Weekly runs producing artifacts with full candidate → perturbation → regime → stress pipeline

---

## Cadence Voice

**Status: PARTIAL**

Cadence is the operator-facing voice identity. Two-layer architecture:

- **Layer 1 (command):** openWakeWord → Silero VAD → faster-whisper STT → task routing → Piper TTS. Pipeline built and daemon running. Mic capture blocked on WSL2 — RDPSource is silent; Windows ffmpeg pipe capture (`win_capture.py`) is the known workaround but not wired into the daemon.
- **Layer 2 (conversation):** Persistent conversational copilot with live runtime context. Proven via replay mode.

Test: `python3 scripts/cadence_status.py --replay "What needs attention?"`

Note: "Cadence" is the operator-facing identity; "PersonaPlex" is the internal engine name.

---

## OpenClaw Substrate

Jarvis OS runs on the **OpenClaw** upstream runtime (`v2026.3.13`). OpenClaw provides:

- Discord bot gateway (Node.js, WebSocket)
- Agent session management (per-channel, daily reset at 4 AM)
- ACP (Agent Control Protocol) for sandboxed execution (HAL uses this)
- Plugin system (acpx, qwen-agent, discord)
- Health, backup, and security audit commands

Commands: `openclaw status`, `openclaw doctor`, `openclaw security audit`

---

## What Is Still Partial

| Area | Status | What is missing |
|------|--------|----------------|
| Cadence voice | PARTIAL | Live mic blocked on WSL2. Proven in replay only. `win_capture.py` workaround exists but not wired into daemon. |
| Bowser browser | BOUNDED | Request/result protocol live, full external browser lane not proven e2e. |
| Pulse agent | FALLBACK | Outbound-only channel presence. No dedicated interactive agent — inbound routes to Jarvis. Fish, Atlas, and Sigma are now full agents. |
| `#todo` intake | DEAD | `lobster-todo-intake` service has no timer and is not running. Task intake via cron executor only. |
| OpenAI / GPT | SCAFFOLD | Adapter wired but requires funded API billing to activate. |
| v5.2 multi-model routing | SCAFFOLD | Scaffolding exists but not active in production. |
| Daily data pull (4 AM) | NOT SCHEDULED | Documented in FACTORY_RUNBOOK but no systemd timer exists. Only weekly batch is live. |
| TASKS.jsonl / EXPERIMENTS.jsonl | DEPRECATED | Both empty. Tasks migrated to SQLite (`tasks/tasks.db`). |

---

## Daily Operator Checklist

1. Open the dashboard: `http://127.0.0.1:18793`
2. Check `#review` in Discord — approve or reject pending items
3. Glance at `#jarvis` — any failures, alerts, or blocked tasks?
4. Run `python3 scripts/operator_status.py` for terminal summary
5. Review Kitt briefs in `#kitt` for quant awareness
6. If queue is backing up: `python3 scripts/run_ralph_v1.py` to burn one task manually

---

*Jarvis OS v5.1 · OpenClaw v2026.3.13 · Generated 2026-03-19 · [GitHub](https://github.com/jdwebb26/JarvisOS)*
