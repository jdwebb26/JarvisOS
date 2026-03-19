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
| Dashboard | http://127.0.0.1:18793/ (systemd) | **LIVE** |
| LM Studio (Qwen) | 100.70.114.34:1234 | **LIVE** |
| NVIDIA / Kimi K2.5 | api.nvidia.com | **LIVE** |
| SearXNG | localhost:8888 | **LIVE** |
| PinchTab (browser) | 127.0.0.1:9867 (systemd) | **LIVE** |
| Discord outbox sender | systemd timer, 60s interval | **LIVE** |
| Operator inbound server | http://127.0.0.1:18790 (systemd) | **LIVE** |
| Ralph timer | systemd timer, 10 min interval (600s) | **LIVE** |
| Review poller | systemd timer, 30s interval | **LIVE** |
| Todo poller | systemd timer, 2m interval | **LIVE** |
| Strategy factory cron | daily 4AM data, Sunday batch | **LIVE** |

## 2. Discord Delivery

14 webhooks verified HTTP 200 on 2026-03-19:
JARVIS, REVIEW, COUNCIL, BOWSER, HAL, KITT, WORKLOG, SCOUT, CADENCE, HERMES, MUSE, QWEN, ATLAS, FISH.

Quant lane Discord delivery verified 2026-03-19:
- **Kitt (#kitt)**: delivered — briefs, execution results
- **Atlas (#atlas)**: delivered — candidate_packet events route to own channel (was previously mis-routed to #kitt)
- **Fish (#fish)**: delivered — scenario_packet events route to own channel (was previously skipped with "no event mapping")
- **#review**: delivered — approval requests with `approve qpt_xxx` / `reject qpt_xxx` instructions
- **Worklog**: delivered — mirrors for promotions, execution, approvals
- **Jarvis forward**: delivered — approval requests forwarded
- **Sigma (#sigma)**: delivered — promotion, rejection, validation events

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
| **Ralph** | Qwen 3.5-35B | Full operator-usable loop: task claim → HAL dispatch → Archimedes auto-review → operator approval → completion → **auto-promotion** (artifact + output published automatically). CLI: `--status`, `--approve`, `--reject`, `--retry`. Rejected reviews fail cleanly. Stale-running recovery. Idle clears error state. |
| **Hermes** | Qwen 3.5-35B (LM Studio) | Fully wired: `hermes_adapter` in backend_dispatch + Ralph ELIGIBLE_BACKENDS. Transport calls LM Studio directly (no external daemon needed). Proven 2026-03-18. Requires LM Studio running. |
| **Muse** | Qwen 3.5-35B (LM Studio) | Creative lane active. Gateway binding → Discord channel. Full round-trip proven: Discord message → gateway session → LLM response → Discord delivery. |

## 4. Agents — Partial or Blocked

| Agent | Status | What's missing |
|-------|--------|----------------|
| **Cadence — wake-word command layer** | PARTIAL | Daemon running (`cadence-voice-daemon.service`, 596 MB). Full pipeline built: openWakeWord → Silero VAD → faster-whisper STT → command routing → Piper/Coqui TTS. Transcript routing and TTS independently proven. Mic blocked: RDPSource unavailable in WSL2. No end-to-end wake-to-command proof. |
| **Cadence — conversation layer** | LIVE (replay) | Persistent conversational copilot with live runtime context, multi-turn sessions, command safety (propose-not-execute). Bridged to Cadence wake pipeline. Mic blocked: same as L1. Proven via replay mode 2026-03-18. |
| **Claude** | BLOCKED | `ANTHROPIC_API_KEY=REPLACE_ME` in `secrets.env`. No Python-track adapter exists (gateway config only). User must set a real key AND a `claude_executor` adapter would need to be built for Python-track dispatch. |

## 5. Core Runtime Systems

### Working
- **Task lifecycle**: create → queue → start → checkpoint → complete/fail. Events emitted at every transition
- **Review/approval chain**: HAL → Archimedes review → Anton/operator approval. Resumable checkpoints
- **Backend dispatch**: `nvidia_executor`, `openai_executor`, `browser_backend`, `kitt_quant`, `hermes_adapter` wired. `execute_once()` picks queued tasks
- **Context engine**: bounded 6-turn working memory, budget guard (72%/82%), tool filtering, skill allowlists
- **Memory system**: episodic + semantic writes from task outcomes, review verdicts, approval decisions, routing decisions
- **Learnings ledger**: JSONL-backed (`state/learnings/`), writes from failures/rejections/operator corrections, filtered retrieval per agent
- **Delegation compact mode**: HAL/Archimedes get abbreviated context for delegated tasks
- **Session hygiene**: automatic rotation before context builds for stale sessions
- **Token budget enforcement**: global budget in `state/token_budgets/`, applied after every Ralph HAL/Archimedes call. 841 tokens tracked from live proof runs. Hard stop blocks task at threshold
- **Regression scoring**: `scripts/run_regression.py` scores execution traces for output completeness, model drift, token efficiency, routing correctness. Traces recorded from every Ralph HAL/Archimedes call in `state/run_traces/`
- **#todo intake (live Discord ingress)**: `discord_todo_poller.py` (systemd timer, 2m) polls Discord `#✅todo` channel (1471188572932673549) → `submit_todo()` → task created with `ralph_adapter` backend → Ralph picks up → HAL → Archimedes auto-review → completed (if `approval_required=false`) or → operator approval → completed. No Jarvis turn. Programmatic submissions also work via gateway inbound server → bridge cycle. Proven end-to-end with real Discord message 2026-03-18 (`task_ddd67cb59a46` from Discord, `task_248303915d69` no-approval, `task_129e548cb242` with approval)
- **#review approval lane**: `approval_requested` events post to #review with approve/reject instructions. Only emitted when `approval_required=true`. Operator approvals via gateway `/operator/approval` endpoint (or `discord_review_poller.py` for emoji/text commands). Proven end-to-end 2026-03-18 (`apr_a4ea9dfa2183`, `apr_903c0215a3b3`)
- **Auto-promotion**: When Ralph completes a task (either via review-only or review+approval path), auto-promotes the backend result into a candidate artifact → promoted artifact → published output. Idempotent (skips if already promoted or no result). Manual `promote_output.py` still works. Proven 2026-03-18: `task_3c9715eb0b8a` → `art_16a2cedf68f7` → `out_a18aa391c271`
- **Flowstate distillation lane**: `runtime/flowstate/` — source_store, distill_store, promotion_store, index_builder. Operator CLI: `scripts/flowstate.py` (ingest, distill, status, inspect). Source records → extraction artifacts → distillation artifacts stored in `state/flowstate_sources/`. Promotion is explicit and approval-gated — no auto-promotion into memory or tasks. Proven with real input 2026-03-18 (`fsrc_468a022ffbd5` → `fdist_2847639a4cb2`)

### Working (operator tooling)
- **Runtime profiles**: 5 named profiles (local_only, hybrid, cloud_fast, cloud_smart, degraded). `set` → sync → gateway restart
- **Model visibility**: `runtime_profiles status` (terminal) / `post` (Discord). Profile changes auto-post to #jarvis
- **Operator cockpit**: `scripts/operator_cockpit.py` — service health, agent states, blockers. `--discord` posts live status to #jarvis
- **Operator status**: `scripts/operator_status.py` — phone-friendly action summary: pending approvals, failed/blocked tasks, service health, outbox. `--discord` posts to #jarvis, `--if-needed` posts only when action required (safe for timer use)
- **Validate**: `scripts/validate.py` — 395 checks, comprehensive

### Not working / scaffold only
- **OpenAI / GPT**: Fully wired as `openai_executor` adapter + model registry entry (`gpt-4.1-mini`) + capability profile + `openclaw.json` provider. **Disabled by default** — `gpt` family not in any agent's `allowed_families`. Gated behind `OPENAI_API_KEY` presence. Current key returns 401 (unfunded or invalid). **A ChatGPT subscription does NOT fund API usage** — requires separate billing at https://platform.openai.com/account/billing. Status check: `python3 scripts/check_openai_provider.py --ping`. 26 tests pass. Commit 490e83f.
- **Multi-node burst routing** (NIMO/Koolkidclub): scaffolded, `burst_allowed=false` everywhere. Not live
- **Routing policy enforcement**: `runtime_routing_policy.json` is enforced via runtime profiles (4240dcf). `load_runtime_routing_policy()` applies active profile overrides. `sync_routing_policy_to_openclaw.py` propagates to `openclaw.json`. Gateway uses `openclaw.json` as its config surface, which the sync script keeps aligned with the policy
- **A2A protocol**: doc-only, no implementation
- **Adaptation lab / DSPy optimizer**: scaffold, never run live
- **Token budget cost tracking**: token counts tracked, USD cost tracking wired but local LLMs report $0. Will matter when cloud providers (OpenAI, Claude) are active
- **ShadowBroker**: scaffold, external runtime not present
- **TradingView adapter**: doc-only
- **Mission control adapter**: doc-only

## 6. Strategy Factory

- **Pipeline**: data pull → feature gen → candidate gen → simulation → gates → robustness → scoring → promotion
- **Cron**: daily 4AM OHLCV+VIX, Sunday 2AM batch run, Sunday 6AM memory compaction
- **Status**: pipeline code present, cron scheduled. No strategy has reached PF ≥ 1.5 promotion gate yet
- **Live data**: OHLCV and VIX data pulls running. Feature generation runs after data pull

## 6b. Quant Lanes (Lane A — Money Path)

**Spec**: `docs/spec/QUANT_LANES_OPERATING_SPEC_v3.5.1.md`
**Status**: Lane A live-integrated into runtime. Lane B (Atlas/Fish/Hermes/TradeFloor) runtime-safe with restart recovery.

### What works
- **Packet contracts**: 33 canonical types, 7 lanes, validation. `workspace/quant/shared/schemas/packets.py`
- **Strategy registry**: file-locked, transition-authority-validated, append-only history. `workspace/quant/shared/registries/strategy_registry.py`
- **Approval registry**: structured approval objects (`qpt_` IDs), pre-flight validation. `workspace/quant/shared/registries/approval_registry.py`
- **Sigma validation lane**: validates candidates (PF/Sharpe/DD/trades gates), promotes or rejects, emits Discord events directly. `workspace/quant/sigma/validation_lane.py`
- **Executor lane**: paper adapter with full pre-flight (kill switch, approval, risk limits, broker health), emits Discord events directly. Live adapter stubbed. `workspace/quant/executor/executor_lane.py`
- **Kitt brief producer**: reads shared/latest, shows pipeline/execution/approvals/operator actions. Spec §7 format. `workspace/quant/kitt/brief_producer.py`
- **Discord routing**: 15 quant event kinds routed through `emit_event()`. Atlas → #atlas, Fish → #fish, Sigma → #sigma, execution → #kitt, approvals → #review, briefs → #kitt. Worklog mirror + Jarvis forward for key events
- **Review poller integration**: `qpt_` approval IDs matched by review poller, routed to quant approval bridge. Operator types `approve qpt_xxx` in #review
- **Operator CLI**: `scripts/quant_lanes.py` — status, brief, request-paper, approve-paper, execute, strategies, approvals

### Live Discord delivery (verified 2026-03-19)
- Kitt briefs → #kitt: **delivered**
- Atlas candidates → #atlas: **delivered** (was previously mis-routed to #kitt)
- Fish scenarios → #fish: **delivered** (was previously skipped — no event mapping)
- Approval requests → #review: **delivered** (with approve/reject commands)
- Worklog mirrors: **delivered**
- Sigma promotions/rejections → #sigma: **delivered**

### Proven live (36 tests + 32-check live proof)
- Candidate → Sigma validation → promotion (Discord event to #sigma + worklog + jarvis)
- Kitt papertrade request → approval_requested to #review (with approve/reject instructions)
- Operator approval via review poller path → PAPER_QUEUED
- Executor paper trade → fill (Discord event to #kitt)
- Strategy lifecycle: IDEA → CANDIDATE → VALIDATING → PROMOTED → PAPER_QUEUED → PAPER_ACTIVE
- Kitt brief shows pipeline, execution result, operator action items

### Lane B — Intelligence Lanes (schedulable)
- **Cycle runner**: `quant_lanes.py lane-b-cycle` runs Hermes → Atlas → Fish → TradeFloor → Kitt brief. Restart-safe, idempotent, file-locked against overlap, respects governor/scheduler/dedup.
- **Systemd timer**: `ops/systemd/quant-lane-b-cycle.{service,timer}` — oneshot service + 4h timer. Install via `python3 scripts/quant_lane_b_timer.py install && python3 scripts/quant_lane_b_timer.py enable`. Override cadence with `systemctl --user edit quant-lane-b-cycle.timer`.
- **Atlas exploration lane**: rejection-aware candidate generation. Scheduler/host-aware. Governor-integrated.
- **Fish scenario/calibration lane**: forecast, calibrate, confidence adjustment. Scheduler-aware.
- **Hermes research intake**: research/dataset/repo/theme packets. 24h dedup. Directed requests.
- **TradeFloor synthesis**: agreement tier 0-4, 6h cadence enforcement, degraded on scheduler block. Kitt consumes via TRADEFLOOR brief section.
- **Individual lane commands**: `atlas-batch`, `fish-batch`, `hermes-batch`, `tradefloor` in CLI.
- **Overlap protection**: file lock prevents concurrent cycle runs from timer/manual invocation.
- **Proven**: 132 pytest, 26+50 proof checks. Repeated cycles verified: dedup holds, cadence blocks, overlap blocked, state coherent.

## 7. Known State Quirks

- **Bowser realized model shows stale**: `qwen3.5-122b-a10b` instead of `qwen3.5-35b`. Cosmetic — Bowser's execution goes through PinchTab, not LLM
- **Hermes realized model shows stale**: last session used 35B, policy says 122B. No real impact — Hermes transport calls LM Studio directly, not via gateway session
- **Cockpit snapshot in watchboard is stale**: auto-generated block from earlier run. Agent states may have changed since

## 8. What To Do Next (by user impact)

### Operator actions (unblock immediately)
1. **Set ANTHROPIC_API_KEY** in `~/.openclaw/secrets.env` — unblocks Claude agent
2. ~~Start Hermes daemon~~ **DONE** — Hermes wired directly via LM Studio transport (b70a8b4). No external daemon needed. Requires LM Studio running.

### High-leverage improvements
3. **First real strategy factory run with operator review** — prove the end-to-end IDEA → BACKTESTED → PROMOTED pipeline with a real NQ strategy candidate
4. ~~Wire Ralph to cron~~ **DONE** — Ralph timer (`openclaw-ralph.timer`, 10 min / 600s) and review poller (`openclaw-review-poller.timer`, 30s) are live
5. ~~Activate Muse~~ **DONE** — Muse live as creative Discord lane (channel 1483133844663304272, model qwen3.5-35b-a3b via LM Studio). `openclaw agent --agent muse --message "..."` for direct turns

### Medium-leverage
6. **Session monitoring dashboard** — surface session sizes, turn counts, stale sessions for operator visibility
7. **Cadence wake-word layer unblocking** — mic blocked on WSL2 RDPSource. Investigate PulseAudio/pipewire WSL passthrough to complete end-to-end wake-to-command proof
8. ~~Cadence conversation layer~~ **DONE** — Cadence L2 conversation engine live via voice bridge (a485ad6). Multi-turn sessions, live runtime context, command safety. Blocked only on WSL2 mic (same as L1).

---

## Reference

- **Spec verification**: [SPEC_VERIFICATION_MATRIX.md](SPEC_VERIFICATION_MATRIX.md) — does feature X actually work?
- **Feature intake**: [FEATURE_PROMPTS.md](FEATURE_PROMPTS.md) — large ideas before they become tasks
- **Proof journal**: [live_runtime_watchboard.md](live_runtime_watchboard.md) — per-item evidence (A through S)
- **Historical inventory**: `spec_feature_inventory_live_gap_2026-03-17.md` (1300+ line audit, superseded by this doc + matrix)
- **System architecture**: `SYSTEM.md`, `Jarvis_OS_v5_1_Master_Spec.md`
- **Strategy lifecycle**: `PROMOTION.md`, `RISK_POLICY.md`
- **Agent roster**: `runtime/core/agent_roster.py`, `config/agent_channel_map.json`
