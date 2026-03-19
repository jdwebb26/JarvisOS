# Jarvis OS v5.1

Autonomous multi-agent runtime for task execution, research, approvals, and operator supervision. Part of the [OpenClaw](https://github.com/jdwebb26/JarvisOS) project.

Jarvis OS coordinates a fleet of specialized AI agents that receive work through Discord, execute it via local LLMs (Qwen 3.5 on LM Studio), and surface results back to the operator for review and approval. Nothing reaches production without human sign-off.

---

## What's live right now

These components are running on the live machine and have been proven end-to-end.

| Component | How it runs | What it does |
|-----------|------------|--------------|
| **Gateway** | `openclaw-gateway.service` (persistent) | Node.js Discord bot, WebSocket, agent session routing |
| **Inbound Server** | `openclaw-inbound-server.service` (persistent) | HTTP API on `:18790` for operator replies and approvals |
| **Ralph** | `openclaw-ralph.timer` (every 10 min) | Picks queued tasks, dispatches to backend, requests review |
| **Review Poller** | `openclaw-review-poller.timer` (every 30s) | Polls Discord `#review` for `approve`/`reject` reactions |
| **Todo Intake** | `lobster-todo-intake.timer` (every 2 min) | Polls Discord `#todo` for new human tasks |
| **Outbox Sender** | `openclaw-discord-outbox.timer` (every 60s) | Delivers pending Discord messages via webhooks |
| **Operator Status** | `openclaw-operator-status.timer` (every 5 min) | Posts action summary to `#jarvis` when approvals/failures exist |
| **Dashboard** | `openclaw-dashboard.service` (persistent) | Browser UI at `http://127.0.0.1:18793/` |
| **Hermes** | On-demand via Ralph or gateway | Deep research via LM Studio Qwen — produces artifacts and evidence bundles |
| **Auto-promotion** | Wired into task completion flow | Promotes completed task outputs through lifecycle gates |

### Live backends

| Backend | Status | Notes |
|---------|--------|-------|
| **Qwen (LM Studio)** | Live | Primary. Qwen 3.5 35B/122B at `http://100.70.114.34:1234/v1` |
| **Hermes (research)** | Live | Calls Qwen via `hermes_transport.py`, returns structured reports |
| **NVIDIA (Kimi 2.5)** | Live | Requires `NVIDIA_API_KEY` in `.env` |
| **Browser (Bowser)** | Live | Headless browser actions, operator-cancellable |
| **Kitt (quant)** | Live | Quant brief generation |
| **SearXNG** | Live | Local search at `http://localhost:8888` |
| **OpenAI / GPT** | Scaffolded | Adapter exists but requires valid API billing to activate |
| **Claude** | Blocked | No API access configured |

### Not finished / out of scope here

| Area | Status |
|------|--------|
| **Cadence — wake-word command layer** | PARTIAL — daemon running, wake detection + VAD + STT + TTS built. Mic blocked on WSL2 (RDPSource unavailable). No live end-to-end wake-to-command proof yet. |
| **Cadence — PersonaPlex conversation layer** | MISSING — no persistent conversational AI / copilot surface exists. Current code is one-shot command routing only. |
| **Strategy Factory** | Separate pipeline at `~/.openclaw/workspace/strategy_factory/` |
| **v5.2 multi-model routing** | Scaffolding only — not active in production |

---

## Quick start

### 1. Check health

Open the dashboard:
```
http://127.0.0.1:18793/
```

Or from terminal:
```bash
cd ~/.openclaw/workspace/jarvis-v5
python3 scripts/validate.py            # full runtime validation (395 checks)
python3 scripts/operator_status.py     # what needs attention right now
python3 scripts/operator_next.py       # single next recommended action
```

### 2. Process approvals

Tasks that complete execution wait for human approval before their outputs are promoted.

**Via Discord**: React with the appropriate emoji in `#review`, or type `approve apr_xxxxx`.

**Via CLI**:
```bash
python3 scripts/run_ralph_v1.py --approve task_xxxxx
```

**Via dashboard**: Click the "Approve" button next to any pending approval — it copies the command to your clipboard.

### 3. Retry failures

```bash
python3 scripts/run_ralph_v1.py --retry task_xxxxx
```

### 4. Submit new work

**Via Discord**: Post a message in `#todo`. The intake timer picks it up within 2 minutes.

**Via CLI**:
```bash
python3 scripts/todo_intake.py --message "Research the latest VIX regime characteristics"
```

### 5. Promote outputs

```bash
python3 scripts/promote_output.py --promote task_xxxxx
```

---

## Agent model

Jarvis OS uses specialized agents that communicate through Discord channels. Each agent has a defined role, bounded authority, and a dedicated workspace.

| Agent | Role | Execution |
|-------|------|-----------|
| **Jarvis** | Orchestrator — routes tasks, decomposes work | Coordination only, no direct code execution |
| **Hal** | Builder — implements code, runs backtests | Sandboxed (Docker) |
| **Ralph** | Task runner — picks queued work, dispatches, requests review | Bounded autonomy loop (10-min timer) |
| **Hermes** | Research daemon — deep research, evidence generation | Calls Qwen LLM, produces structured reports |
| **Scout** | Recon — market analysis, web search | SearXNG-backed |
| **Archimedes** | Technical reviewer — code review, quality gates | Review-only authority |
| **Anton** | Supreme reviewer — council decisions | Approval authority |
| **Bowser** | Browser agent — automated web workflows | Headless browser, operator-cancellable |
| **Muse** | Creative — design, copy, brainstorming | Suggestion-only |

### Discord channels

| Channel | Purpose |
|---------|---------|
| `#todo` | Human task intake — messages become queued tasks |
| `#work` | Agent output — completed work posted here |
| `#review` | Approval flow — operators approve/reject here |
| `#flowstate` | Status updates — agent heartbeats, cycle summaries |
| `#jarvis` | Operator alerts — action summaries when approvals/failures exist |

### Task lifecycle

```
QUEUED → RUNNING → WAITING_REVIEW → WAITING_APPROVAL → COMPLETED → PROMOTED
                 ↘ FAILED (retryable)
                 ↘ BLOCKED (needs operator intervention)
```

Every task flows through this lifecycle. Nothing is auto-promoted to production — all promotions require explicit operator action.

---

## Dashboard

The operator dashboard runs at `http://127.0.0.1:18793/` (localhost only) and auto-refreshes every 30 seconds.

**What it shows:**
- **Status strip** — health verdict, approval/failure/blocked/queued counts at a glance
- **Next Action** — the single most important thing to do right now
- **Pending Approvals** — tasks awaiting human sign-off, with one-click approve buttons
- **Failed** — retryable failures with error context and retry buttons
- **Blocked** — tasks that need manual intervention
- **Queued** — work waiting to be picked up
- **Promotable Outputs** — completed work ready for promotion

**API endpoint**: `GET http://127.0.0.1:18793/api/data` returns the full dashboard state as JSON.

---

## Key scripts

All scripts live in `scripts/` and are run from the repo root.

### Operator workflow
| Script | What it does |
|--------|-------------|
| `operator_status.py` | Current state: approvals, failures, queue depth |
| `operator_next.py` | Single recommended next action |
| `run_ralph_v1.py --approve <id>` | Approve a pending task |
| `run_ralph_v1.py --retry <id>` | Retry a failed task |
| `todo_intake.py --message "..."` | Submit new work |
| `promote_output.py --promote <id>` | Promote a completed output |

### Diagnostics
| Script | What it does |
|--------|-------------|
| `validate.py` | Full runtime validation suite (395 checks) |
| `runtime_doctor.py` | Health checks with fix suggestions |
| `smoke_test.py` | Quick deployment smoke test |
| `hermes_live_proof.py` | Verify Hermes research path end-to-end |

### Dashboard / status
| Script | What it does |
|--------|-------------|
| `dashboard.py` | Serve the operator dashboard (default `:18792`) |
| `dashboard.py --json` | Dump dashboard data to stdout |
| `dashboard.py --snapshot` | Write snapshot to `state/logs/dashboard.json` |

---

## Project structure

```
jarvis-v5/
├── runtime/
│   ├── core/           # Task store, models, routing, status, approvals, reviews
│   ├── controls/       # Control plane — pause, resume, degradation
│   ├── executor/       # Backend dispatch (Qwen, NVIDIA, Hermes, browser, quant)
│   ├── gateway/        # Gateway CLI wrappers for each backend
│   ├── integrations/   # Backend adapters (hermes, nvidia, bowser, searxng, etc.)
│   ├── ralph/          # Ralph v1 bounded autonomy loop
│   ├── browser/        # Headless browser subsystem
│   ├── evals/          # Trace store, replay, eval scaffolding
│   └── researchlab/    # Autoresearch and evidence bundle system
├── scripts/            # Operator-facing CLI tools (90+ scripts)
├── tests/              # pytest test suite
├── agents/             # Per-agent bootstrap workspaces (hermes/, etc.)
├── state/              # Runtime state (tasks, requests, results, logs)
├── docs/               # Architecture docs, runbooks, specs
│   └── spec/           # Master specs (v5.1, v5.2)
└── configs/            # Runtime configuration
```

### State directories

| Path | Contents |
|------|----------|
| `state/tasks/` | One JSON file per task |
| `state/hermes_requests/` | Hermes research request records |
| `state/hermes_results/` | Hermes research result records |
| `state/approvals/` | Approval records |
| `state/reviews/` | Review records |
| `state/artifacts/` | Generated artifacts (reports, patches, configs) |
| `state/logs/` | Dashboard snapshots, event boards, operator exports |

---

## Configuration

### Environment (`.env`)

Secrets and config live in `~/.openclaw/.env`:

| Variable | Purpose |
|----------|---------|
| `OPENCLAW_GATEWAY_TOKEN` | Gateway API authentication |
| `JARVIS_WEBHOOK_URL` | Discord webhook for `#jarvis` |
| `CREW_WEBHOOK_URL` | Discord webhook for `#work` |
| `REVIEW_WEBHOOK_URL` | Discord webhook for `#review` |
| `JARVIS_SEARXNG_URL` | SearXNG instance URL |
| `NVIDIA_API_KEY` | NVIDIA API access (for Kimi 2.5) |

### LLM models

Model configuration lives in `~/.openclaw/agents/hermes/models.json`. The primary backend is LM Studio running locally with Qwen 3.5 models. The system enforces a Qwen-first policy — no silent cross-family model switching.

### Agent config

Agent definitions, workspaces, and Discord channel bindings are in `~/.openclaw/openclaw.json`.

---

## Validation

```bash
# Full validation (395 checks)
python3 scripts/validate.py

# Runtime regression pack
python3 runtime/core/run_runtime_regression_pack.py

# Focused test suites
python3 -m pytest tests/test_hermes_adapter.py -v
python3 -m pytest tests/test_hermes_transport.py -v
python3 -m pytest tests/test_autoresearch_adapter.py -v
python3 -m pytest tests/test_browser_gateway.py -v
```

Current baseline: **395 pass, 1 warn, 0 fail**.

---

## Known limits

- **Single operator** — designed for one operator (Rollan) on one machine. No multi-user auth.
- **Localhost only** — dashboard and gateway bind to `127.0.0.1`. Not exposed to the network.
- **LM Studio required** — Hermes and Qwen backends need LM Studio running at the configured address.
- **No Claude API** — Claude integration is blocked until real API access is configured.
- **No GPT in production** — OpenAI adapter is scaffolded but not active without valid billing.
- **Cadence command layer partial** — wake-word daemon is running but mic capture is blocked on WSL2 (RDPSource unavailable). No live end-to-end wake-to-command proof.
- **Cadence PersonaPlex missing** — the persistent conversational AI / copilot layer does not exist yet. Current Cadence is one-shot command routing only.
- **Strategy Factory separate** — the quant backtesting pipeline lives at `~/.openclaw/workspace/strategy_factory/` and is operated independently.
- **v5.2 features are scaffolding** — multi-model routing, deeper replay/scoring, and accelerator visibility are not yet active.

---

## Further reading

| Document | What it covers |
|----------|---------------|
| [Operating Guide](docs/OPERATING_GUIDE.md) | Full operator manual — daily workflows, subsystem details, troubleshooting |
| [Master Spec](docs/spec/Jarvis_OS_v5_1_Master_Spec.md) | Complete v5.1 technical specification |
| [Agent Roster](docs/agent_roster.md) | Detailed agent role definitions and capabilities |
| [External Lane Activation](docs/external_lane_activation.md) | Backend lane status labels and activation state |
| [Deployment](docs/deployment.md) | Service installation and systemd setup |
