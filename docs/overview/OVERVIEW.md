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

| Service | What it does | Status |
|---------|-------------|--------|
| `openclaw-gateway` | Node.js Discord bot, WebSocket, agent session routing | **LIVE** |
| `openclaw-inbound-server` | HTTP API on `:18790` for operator replies | **LIVE** |
| `openclaw-dashboard` | Operator dashboard at `http://127.0.0.1:18793` | **LIVE** |
| `cadence-voice-daemon` | Wake-word + VAD + STT + TTS | **PARTIAL** — mic blocked on WSL2 |

### Timer-driven services

| Timer | Interval | What it does |
|-------|----------|-------------|
| `openclaw-ralph` | 10 min | Picks one queued task, dispatches to backend, requests review |
| `openclaw-review-poller` | 30 sec | Polls `#review` for approve/reject reactions |
| `lobster-todo-intake` | 2 min | Polls `#todo` for new task messages |
| `openclaw-discord-outbox` | 60 sec | Delivers pending Discord messages via webhooks |
| `openclaw-operator-status` | 5 min | Posts action summary to `#jarvis` when needed |
| `quant-lane-b-cycle` | 4 hours | Quant intelligence cycle: Atlas, Fish, Hermes, Kitt |
| `openclaw-factory-weekly` | Sun 2 AM | Strategy Factory batch run |
| `openclaw-ops-check` | Sun 3 AM | Doctor + security audit + backup |

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

### Quant lane services (temporary fallback)

These have Discord channels for outbound event delivery but are **not** fully separate interactive agents. Inbound messages route to Jarvis as a temporary fallback.

| Service | Channel | Purpose |
|---------|---------|---------|
| Sigma | `#sigma` | Strategy validation gates |
| Atlas | `#atlas` | Strategy candidate generation |
| Fish | `#fish` | Market scenario analysis |
| Pulse | `#pulse` | Discretionary NQ alerts and proposals |

---

## Discord Channel Model

### Operator-facing channels

| Channel | Purpose |
|---------|---------|
| **#review** | **Operator action inbox.** Review requests, approval requests, paper-trade approvals, pulse proposals. |
| **#worklog** | **Audit trail.** Completion receipts, review verdicts, approval decisions. Nothing here needs action. |
| **#jarvis** | **Escalations only.** Failures, blocked tasks, alerts, factory summaries, warnings. Low-noise. |
| **#todo** | **Task intake.** Post a message to create a task. Picked up every 2 minutes. |

### Agent channels

| Channel | What goes there | Interactive? |
|---------|----------------|-------------|
| `#hal` | Builder execution output | Yes |
| `#kitt` | Quant briefs, strategy oversight | Yes |
| `#hermes` | Research daemon output | Yes |
| `#scout` | Recon, web search results | Yes |
| `#muse` | Creative agent output | Yes |
| `#bowser` | Browser automation output | Yes |
| `#cadence` | Voice/TTS events only | Voice-only |
| `#qwen` | Qwen-Agent output | Yes (ACP) |
| `#sigma` / `#atlas` / `#fish` / `#pulse` | Quant lane events | Outbound only (jarvis fallback) |

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
- Approve via Discord: `approve apr_xxx` or emoji reaction
- Approve via CLI: `python3 scripts/run_ralph_v1.py --approve task_xxx`
- Completion receipts go to `#worklog`, not `#review`
- High-stakes items (quant, deploy) escalate to Anton

---

## The Quant System

Strategy Factory is **one part** of the broader quant system:

| Component | What it does | Schedule |
|-----------|-------------|----------|
| **Quant Lane B** | Intelligence cycle: Atlas → Fish → Hermes → Kitt briefs | Every 4 hours |
| **Strategy Factory** | Weekly batch: backtest, validate, promote survivors | Sunday 2 AM |
| **Sigma** | Validation gates — PF, Sharpe, drawdown thresholds | Per-candidate |
| **Pulse** | Discretionary session alerts, proposals to downstream lanes | Real-time |
| **Paper trading** | Approved strategies execute paper trades via executor | On approval |

### Strategy lifecycle

```
IDEA → CANDIDATE → VALIDATED → PROMOTED → PAPER_TRADING → LIVE
```

Paper-trade and live-trade transitions require explicit operator approval.

---

## Cadence Voice

**Status: PARTIAL**

Two-layer voice interface. Daemon running but mic capture blocked on WSL2.

- **Layer 1 (command):** openWakeWord → Silero VAD → faster-whisper STT → task routing → Piper TTS. Built, not proven e2e without live mic.
- **Layer 2 (conversation):** Persistent conversational copilot with live runtime context. Proven via replay mode.

Test: `python3 scripts/cadence_status.py --replay "What needs attention?"`

---

## OpenClaw Substrate

Jarvis OS runs on the OpenClaw runtime (`v2026.3.13`), which provides:

- Discord bot gateway (Node.js, WebSocket)
- Agent session management (per-channel, daily reset at 4 AM)
- ACP (Agent Control Protocol) for sandboxed execution
- Plugin system (acpx, qwen-agent, discord)
- Health, backup, and security audit commands

Commands: `openclaw status`, `openclaw doctor`, `openclaw security audit`

---

## What Is Still Partial

| Area | Status | What is missing |
|------|--------|----------------|
| Cadence voice | PARTIAL | Live mic blocked on WSL2. Proven in replay only. |
| Bowser browser | BOUNDED | Protocol live, full external lane not proven e2e. |
| Sigma/Atlas/Fish/Pulse | FALLBACK | Outbound-only. No dedicated interactive agents. |
| OpenAI / GPT | SCAFFOLD | Adapter wired, needs funded API billing. |
| v5.2 multi-model routing | SCAFFOLD | Not active in production. |
| Daily data pull | NOT SCHEDULED | Documented but no timer exists. Only weekly batch is live. |

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
