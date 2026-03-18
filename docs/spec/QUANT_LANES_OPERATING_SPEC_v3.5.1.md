# QUANT LANES OPERATING SPEC v3.5.1

Purpose: define the quant lane architecture for Jarvis/OpenClaw so autonomous quant work runs continuously without lane confusion, only escalating meaningful results to the operator, and reliably moving worthy candidates toward real money.

This spec is operational. It defines roles, inputs, outputs, autonomy boundaries, storage, routing, feedback loops, strategy lifecycle, risk controls, observability, local resource management, adaptive governance, and implementation scope.

Changes from v3.5: Phase 0 scope pinned to brutally small vertical slice, Executor broker adapter seam (paper adapter first, live stubbed behind same interface), TradeFloor sparse-from-day-one enforcement.

---

## 1. Core principles

1. Keep lanes narrow. One job per lane, done well.
2. Prefer autonomous packet production over chatty agent behavior.
3. Do not require human review for every experiment.
4. Only escalate high-value results.
5. Separate research, experimentation, simulation, validation, briefing, and execution.
6. Local-first by default, cloud when materially useful.
7. TradeFloor is a workflow, not a permanent agent.
8. Strategy Factory remains its own lane under Sigma. Not subordinated to Atlas or Fish.
9. Prove the loop before scaling infrastructure. Build vertical slices first.
10. Every lane emits health signals. Silent lanes are broken lanes.
11. Feedback flows backward. Rejections teach exploration. Execution results teach validation.
12. Every strategy has a lifecycle state. No candidate floats in limbo.
13. Paper trading is the mandatory path before live. No shortcuts.
14. Live execution only through Executor, only after explicit operator approval.
15. Portfolio-level risk is tracked, not just individual trade risk.
16. Executor must never depend on cloud for anything execution-critical.
17. Local machine resources are finite. Lanes must not stampede. Concurrency is capped and prioritized.
18. The runtime governor pushes productive lanes harder and backs off unproductive ones. Autonomy is earned, not permanent.
19. The governor can throttle lanes but cannot silently lower safety standards, bypass approval gates, or disable risk controls.

---

## 2. Local resource management and host-aware scheduling

### The problem

If Atlas runs a heavy batch, Sigma validates a hard candidate, Fish does a scenario pass, Kitt synthesizes a brief, and TradeFloor fires — all at the same time — the hosts get hammered regardless of how clean the lane design is. The spec must prevent this.

### Named hosts

| Host | Role | Specs | Notes |
|------|------|-------|-------|
| NIMO | Primary quant compute | 128 GB RAM, primary GPU | Main heavy-lane box. Most quant work runs here. |
| SonLM | Secondary overflow | Lighter box | Support and overflow. Lighter batches, Fish scenarios, Hermes research. |

Additional burst hosts may exist later but are not assumed. Host definitions are stored in `shared/config/hosts.json`.

### Concurrency rules

**Global heavy-job cap: 3.**
**NIMO heavy-job cap: 2.**
**SonLM heavy-job cap: 1.**

A "heavy job" is any lane invocation that runs a local LLM inference, a large backtest, a scenario simulation, or any task expected to take >30 seconds of sustained compute.

Light jobs (reading packets, writing packets, updating registry, health_summary emission, file I/O) do not count toward caps.

**Never run more than 1 truly large local LLM inference per host at a time.** VRAM is not shareable. If a higher-priority lane needs inference and a lower-priority lane is using the GPU on that host, the lower-priority job finishes its current generation step then yields.

If a lane needs to start a heavy job and the host cap is hit, it either queues (priority-ordered), overflows to the other host if capacity exists, or bursts to cloud.

### Preferred host placement

| Lane | Primary host | Overflow | Notes |
|------|-------------|----------|-------|
| Kitt | NIMO | Cloud | Operator-facing, needs strongest local model |
| Atlas | NIMO | SonLM for lighter batches, cloud for heavy | Most compute-hungry lane |
| Sigma | NIMO | Cloud for high-value validation | Needs strong reasoning for validation |
| Fish | SonLM preferred | Cloud | Scenarios are important but not NIMO-critical |
| Hermes | Mixed / lightweight | Either host | Low compute, mostly I/O |
| Executor | Isolated, NIMO preferred | N/A (local-only for execution-critical) | Must never be blocked by other lanes |
| TradeFloor | Strongest available | Cloud preferred | Synthesis-heavy, reads packets not giant contexts |

Placement is configured in `shared/config/hosts.json` and can be adjusted without redeployment.

### Priority order

When contention exists on a host, lanes are scheduled in this order:

| Priority | Lane | Rationale |
|----------|------|-----------|
| 1 (highest) | Executor | Execution-critical, must never wait |
| 2 | Kitt | Operator-facing synthesis |
| 3 | Sigma | Validation near paper review is time-sensitive |
| 4 | TradeFloor | On-demand, should complete promptly |
| 5 | Fish | Important but not time-critical |
| 6 | Atlas | Exploration is the most deferrable |
| 7 (lowest) | Hermes | Background research |

### Lane cadence defaults

Not every lane should run at the same frequency. Defaults (configurable in shared/config/cadence.json):

| Lane | Default cadence | Notes |
|------|----------------|-------|
| Kitt | Every 1-4 hours during market hours, on-demand otherwise | Operator-facing, should be fresh |
| Atlas | Every 4-8 hours | Exploration is batch work, not real-time |
| Fish | Every 6-12 hours, plus event-triggered | Scenarios change on macro events, not every hour |
| Sigma | On-demand (triggered by incoming candidates or review timers) | Validation is reactive, not scheduled |
| Hermes | Every 2-4 hours, plus on-demand from research_requests | Background research feeder |
| Executor | Continuous monitoring when positions are active, otherwise dormant | Must be responsive when active |
| TradeFloor | On-demand only, max once per 6 hours unless operator explicitly overrides | Never continuous. Override must be logged. |

Cadence is a default, not a hard limit. The adaptive governor (Section 3) can adjust cadence up or down based on lane performance.

### Cloud burst as pressure relief

When a lane hits the host concurrency cap or the VRAM queue is long:
- the lane may burst to cloud if its routing profile permits
- bursting logs estimated cost in health_summary
- bursting immediately frees local resources for higher-priority lanes
- this makes cloud routing a resource management tool, not just a quality tool

### Scheduler implementation

The concurrency scheduler is a shared utility in `workspace/quant/shared/`:
- maintains a lightweight lock/semaphore file: `shared/scheduler/active_jobs.json`
- tracks which host each job is running on
- each lane registers before starting a heavy job (including host), deregisters on completion
- if host cap is hit, lane checks priority and either queues, overflows to alternate host, or bursts to cloud
- stale registrations (older than configured timeout, default 30 minutes) are auto-cleared

### Enforcement through shared utilities

The scheduler is advisory at the OS level, but enforcement happens at the chokepoints that matter. The following shared utilities **must** check scheduler state before proceeding with heavy work:

1. **Packet writer utility** — before any write that triggers a heavy downstream job, check scheduler.
2. **LLM inference wrapper** — before any local model call, check scheduler and host VRAM. If occupied, queue. If higher-priority lane waiting, yield after current generation step.
3. **Backtest runner** — before starting any backtest or simulation, check scheduler. These are the heaviest local jobs.
4. **TradeFloor invocation utility** — before running TradeFloor, check scheduler state, host availability, and invocation frequency cap.

If a lane bypasses these shared utilities and runs heavy work directly, that is an implementation bug. All lanes must route heavy work through shared utilities.

**Health visibility:** every health_summary includes `scheduler_waits`, `scheduler_bypasses` (should always be 0), and `host_used`.

---

## 3. Adaptive runtime governor

### Purpose

The governor dynamically increases or decreases lane intensity based on usefulness, efficiency, health, and host pressure. It prevents waste without requiring manual tuning of every lane's parameters.

The governor is mandatory for autonomous quant work. Without it, lanes either run at fixed intensity (wasteful when unproductive, insufficient when productive) or require constant manual adjustment.

### What the governor controls per lane

| Parameter | Description | Range |
|-----------|-------------|-------|
| batch_size | How many candidates/experiments per cycle | 1 – configured max |
| max_iterations | Max iterations within a single cycle | 1 – configured max |
| cooldown_interval | Minimum time between cycles | 0 – configured max (seconds) |
| cloud_burst_allowed | Whether this lane may burst to cloud | true / false |
| escalation_threshold | How strong a signal must be to escalate | float 0-1 |
| cadence_multiplier | Multiplier on default cadence (0.5 = twice as fast, 2.0 = half as fast) | 0.5 – 4.0 |

These parameters are stored per lane in `shared/config/governor_state.json` and updated by the governor after each cycle.

### Scoring dimensions

Every lane computes four scores each cycle. These scores drive governor decisions.

#### usefulness_score (0-1)
Is the lane producing outputs that matter downstream?

| Lane | Measured by |
|------|------------|
| Atlas | Fraction of candidates that reach Sigma (not rejected at intake) |
| Sigma | Fraction of validated candidates that reach PROMOTED or paper path |
| Fish | Fraction of scenario/forecast packets referenced in Kitt briefs |
| Kitt | Fraction of briefs/alerts that trigger operator action or downstream lane response |
| Hermes | Fraction of research packets referenced by other lanes |
| Executor | Fraction of executions completing without error |
| TradeFloor | Whether Kitt referenced the tradefloor_packet in its last brief |

#### efficiency_score (0-1)
Useful outputs per unit of runtime and cost.

| Measurement | How |
|------------|-----|
| Cost per useful packet | estimated_cloud_cost / useful_packets_produced |
| Runtime per useful output | total_runtime / useful_packets_produced |
| Cloud efficiency | useful_packets_from_cloud / total_cloud_bursts |

#### health_score (0-1)
Operational reliability.

| Signal | Impact |
|--------|--------|
| Timeout rate | High timeout → low health |
| Error/crash rate | Any crash → significant penalty |
| Silent period | Exceeding expected cadence → low health |
| Stale output age | Producing old-looking packets → low health |

#### confidence_score (0-1)
How much trust to place in current outputs. (This overlaps with the per-lane confidence in Section 8 but is specifically for governor decisions.)

| Lane | Source |
|------|--------|
| Fish | Calibration trend (improving = higher) |
| Atlas | Rejection clustering trend (diversifying = higher, repeating = lower) |
| Sigma | Paper review survival rate |
| Kitt | Alert precision (did alerts lead to real value?) |
| Executor | Execution correctness rate |

### Governor decision logic

After each lane cycle, the governor reads the four scores and applies threshold-based rules.

**Implementation rule: start with simple threshold-based logic. Do not build reinforcement learning or complex optimization. The governor adjusts one parameter at a time, by one step, in one direction.** More sophisticated adaptation can be added later if threshold-based governance proves insufficient.

#### Push harder (increase intensity) when ALL of:
- usefulness_score > 0.5
- efficiency_score > 0.4
- health_score > 0.7
- host pressure is low (host has capacity for another heavy job)
- cloud budget has headroom (if cloud burst is needed)

Actions (pick the most impactful, apply one per cycle):
- increase batch_size by 1
- decrease cooldown_interval by one step
- decrease cadence_multiplier by 0.25 (run more often)
- enable cloud_burst_allowed if currently disabled

#### Hold steady when:
- scores are in acceptable ranges but not all "push" conditions are met
- no backoff triggers are active

Action: no parameter changes.

#### Back off (decrease intensity) when ANY of:
- usefulness_score < 0.2 for 2+ consecutive cycles
- health_score < 0.4
- host memory/VRAM pressure above threshold
- repeated timeout cluster (3+ timeouts in last 2 cycles)
- cloud spend exceeds lane soft cap
- efficiency_score < 0.2 for 2+ consecutive cycles

Actions (pick the most impactful, apply one per cycle):
- decrease batch_size by 1 (minimum 1)
- increase cooldown_interval by one step
- increase cadence_multiplier by 0.25 (run less often)
- disable cloud_burst_allowed
- if 3+ consecutive backoff cycles with no improvement: pause lane, emit health_summary with governor_action: "paused", require health_summary acknowledgment before resuming

#### Pause lane when:
- health_score < 0.2
- 3+ consecutive backoff cycles with no score improvement
- host is critically overloaded

Paused lanes emit only health_summary. They do not produce work packets until the governor resumes them (automatically when conditions improve, or manually by operator).

### Lane-specific governor rules

These supplement the general logic above with lane-specific push/backoff triggers.

#### Atlas
Push harder when: Sigma shortlist rate improving, rejection diversity healthy, useful candidate density rising.
Back off when: repeated rejection_reason clusters, zero shortlisted over multiple cycles, host pressure high, cloud burn without downstream value.
Special actions: mutate away from failure families, require Hermes research packet before next batch if stuck.

#### Fish
Push harder when: calibration improving, Kitt is referencing scenario packets.
Back off when: forecast divergence vs reality worsening, scenario packets repeatedly ignored.
Special actions: switch to calibration-only mode when confidence is low.

#### Sigma
Push harder when: validation queue has strong pre-filtered candidates, host manageable.
Back off when: queue dominated by junk, heavy inference contention.
Special actions: raise intake threshold, require stronger Atlas candidate rank before accepting.

#### Kitt
Push harder when: briefs producing operator-useful setups, alerts rare but accurate.
Back off when: too many packets arriving (synthesis latency growing), operator-facing output becoming noisy.
Special actions: compress more aggressively, raise alert threshold, reduce intake from low-value lanes.

#### Hermes
Push harder when: active research requests exist, downstream lanes consuming packets.
Back off when: no active requests, packet reuse low, outputs bloated.
Special actions: fall back to watchlist-only mode, emit shorter packets.

#### Executor
Push harder when: paper-trade queue exists and approvals present.
Back off when: broker instability, execution errors, position mismatch, risk alarm, connectivity issues.
Special actions: pause execution lane immediately on risk/broker failure, emit urgent health_summary.

#### TradeFloor
Push harder: N/A (TradeFloor is on-demand only, capped at 1x per 6 hours).
Back off when: cloud unavailable and local fallback produces low-quality synthesis.
Special actions: skip cycle and log rather than produce degraded output if quality would be unacceptable.

### Governor constraints (hard limits)

The governor can:
- adjust batch sizes, cadence, cooldowns, cloud permissions, escalation thresholds
- pause and resume lanes
- reroute work between hosts

The governor **cannot** (requires operator approval):
- enable live trading
- disable risk controls
- remove review from paper/live path
- expand permissions to new execution surfaces
- override kill switch
- raise cloud budget caps beyond configured limits
- destructive config changes

### Governor state storage

```
workspace/quant/shared/config/governor_state.json
```

Contains per-lane current parameters plus last-cycle scores. Updated after every lane cycle. The governor reads this before making decisions and writes it after.

---

## 4. Strategy lifecycle

Every candidate strategy exists in exactly one lifecycle state at all times.

### State diagram

```
IDEA → CANDIDATE → VALIDATING → REJECTED
                              → PROMOTED → PAPER_QUEUED → PAPER_ACTIVE → PAPER_REVIEW → LIVE_QUEUED → LIVE_ACTIVE → LIVE_REVIEW
                                                                                      → PAPER_KILLED                            → LIVE_KILLED
                                                                                      → ITERATE (back to CANDIDATE)              → RETIRED
```

### Transition authority

This table is the single source of truth for who may move a strategy between states. No lane may write a transition it does not own.

| From | To | Authority | Trigger |
|------|----|-----------|---------|
| (new) | IDEA | Atlas or Kitt | Generated or proposed |
| IDEA | CANDIDATE | Atlas | Packaged with thesis + evidence |
| CANDIDATE | VALIDATING | Sigma | Sigma accepts for review |
| VALIDATING | REJECTED | Sigma | Fails validation gates |
| VALIDATING | PROMOTED | Sigma | Passes validation thresholds |
| PROMOTED | PAPER_QUEUED | Kitt + Operator | Kitt sends papertrade_request_packet, operator approves (approval_object created) |
| PAPER_QUEUED | PAPER_ACTIVE | Executor | Paper orders placed |
| PAPER_ACTIVE | PAPER_REVIEW | Sigma + Kitt | Review trigger met (duration, trade count, or anomaly) |
| PAPER_REVIEW | LIVE_QUEUED | Kitt + Operator | Paper review passes, operator approves live (approval_object created) |
| PAPER_REVIEW | ITERATE | Sigma | Paper results need adjustment, returns to CANDIDATE with lineage |
| PAPER_REVIEW | PAPER_KILLED | Kitt or Operator | Paper results unacceptable |
| LIVE_QUEUED | LIVE_ACTIVE | Executor | Live orders placed |
| LIVE_ACTIVE | LIVE_REVIEW | Sigma + Kitt | Scheduled review or anomaly trigger |
| LIVE_REVIEW | LIVE_ACTIVE | Sigma + Kitt | Review passes, continue |
| LIVE_REVIEW | LIVE_KILLED | Kitt or Operator | Results unacceptable or risk trip |
| LIVE_ACTIVE | LIVE_KILLED | Operator or Kill Switch | Emergency or operator decision |
| Any terminal | RETIRED | Kitt, Sigma, or Operator | Strategy naturally concluded or archived. Requires retirement_reason. |

Rules:
- REJECTED is terminal for that strategy_id. Atlas may create a new IDEA with parent_id referencing the rejected strategy.
- ITERATE sends the strategy back to CANDIDATE with the same strategy_id and a new state_history entry. Sigma must include iteration guidance.
- Only Operator (or kill switch) can move directly from LIVE_ACTIVE to LIVE_KILLED without LIVE_REVIEW.
- Executor never decides strategy outcomes. Executor transitions are mechanical only.
- RETIRED requires a retirement_reason in the state_history entry (e.g. "strategy expired", "market regime no longer applicable", "superseded by atlas-mean-rev-023", "operator requested"). Atlas, Fish, Hermes, and Executor cannot retire strategies. This prevents RETIRED from becoming a lazy garbage-can transition.

### Strategy registry

Single source of truth: `workspace/quant/shared/registries/strategies.jsonl`

```json
{
  "strategy_id": "atlas-mean-rev-017",
  "lifecycle_state": "PAPER_ACTIVE",
  "state_history": [
    {"state": "IDEA", "at": "2025-06-01T10:00:00Z", "by": "atlas"},
    {"state": "CANDIDATE", "at": "2025-06-01T14:00:00Z", "by": "atlas"},
    {"state": "VALIDATING", "at": "2025-06-02T08:00:00Z", "by": "sigma"},
    {"state": "PROMOTED", "at": "2025-06-03T12:00:00Z", "by": "sigma"},
    {"state": "PAPER_QUEUED", "at": "2025-06-03T18:00:00Z", "by": "kitt", "approval_ref": "approval-2025-06-03-001"},
    {"state": "PAPER_ACTIVE", "at": "2025-06-04T09:30:00Z", "by": "executor"}
  ],
  "parent_id": null,
  "lineage_note": "Mutation of atlas-mean-rev-012 after regime_fragile rejection"
}
```

### Registry write contract

Hard contract. Violations break the system.

1. **Single writer function.** All transitions go through one shared utility. No lane writes raw JSONL directly.
2. **Append-only.** State history entries are appended. Never overwrite or delete history.
3. **File locking mandatory.** Write utility acquires file lock before reading current state. Lock released after write. If lock not acquired within 5 seconds, write fails loudly.
4. **Transition validation.** Write utility checks the transition authority table. Unauthorized transitions fail loudly.
5. **Stale-state guard.** Write utility reads current lifecycle_state before writing. If current state does not match expected "from" state, write fails loudly.
6. **Idempotent.** Exact duplicate transitions (same strategy_id, target state, actor, timestamp) are no-ops.
7. **Failure logging.** Every failed write logs reason, lane, requested transition, and current state.

---

## 5. Approval object

Every operator approval creates a structured approval object. This is what Executor validates against during pre-flight.

### Format

```json
{
  "approval_ref": "approval-2025-06-03-001",
  "created_at": "2025-06-03T17:45:00Z",
  "approved_by": "operator",
  "approval_type": "paper_trade",
  "strategy_id": "atlas-mean-rev-017",
  "approved_actions": {
    "execution_mode": "paper",
    "symbols": ["ES", "NQ"],
    "max_position_size": 2,
    "max_loss_per_trade": 500,
    "max_total_drawdown": 2000,
    "slippage_tolerance": 0.05,
    "valid_from": "2025-06-04T09:30:00Z",
    "valid_until": "2025-06-18T16:00:00Z",
    "broker_target": "paper_adapter"
  },
  "conditions": "Review after 14 days or 20 trades, whichever comes first.",
  "revoked": false,
  "revoked_at": null
}
```

### Required fields

| Field | Type | Description |
|-------|------|-------------|
| approval_ref | string | Unique ID, format: `approval-{date}-{sequence}` |
| created_at | ISO 8601 | When operator approved |
| approved_by | string | Always "operator" for paper/live approvals |
| approval_type | enum | paper_trade or live_trade |
| strategy_id | string | Which strategy this approval covers |
| approved_actions | object | What Executor is allowed to do (see below) |
| conditions | string | Free text conditions or review triggers |
| revoked | boolean | Whether this approval has been revoked |
| revoked_at | ISO 8601 or null | When revoked |

### Approved actions fields

| Field | Type | Description |
|-------|------|-------------|
| execution_mode | paper or live | Must match approval_type |
| symbols | list of strings | Which symbols Executor may trade |
| max_position_size | number | Per-symbol max position |
| max_loss_per_trade | number | Max loss on any single trade |
| max_total_drawdown | number | Max total drawdown before Executor must stop and alert |
| slippage_tolerance | float | Max acceptable slippage |
| valid_from | ISO 8601 | Approval start time |
| valid_until | ISO 8601 | Approval expiry (Executor refuses orders after this) |
| broker_target | string | Which broker/adapter to use |

### Rules

- stored in `workspace/quant/shared/registries/approvals.jsonl`
- Executor must read and validate the approval object during pre-flight, not just check for existence of an approval_ref string
- expired approvals are treated as invalid — Executor refuses
- revoked approvals are treated as invalid — Executor refuses
- operator can revoke by setting revoked=true and revoked_at
- approval objects are append-only (revocation adds a new entry, does not delete the original)
- approval_ref is referenced in strategy registry state_history when transitioning to PAPER_QUEUED or LIVE_QUEUED

---

## 6. Lane roster

### Kitt
Role: live quant lead, market reader, setup coordinator, team synthesizer, operator interface, portfolio monitor.

Mission:
- watch market structure
- read packets from all quant lanes
- produce operator-facing briefs
- alert only on high-confidence opportunities
- orchestrate quant intelligence for the operator
- surface system health every brief cycle
- decide when TradeFloor should be invoked
- decide when a candidate should move toward paper trade review
- track portfolio-level exposure across all active strategies
- monitor portfolio concentration and escalate when thresholds breached

Channel: Discord 1483320979185733722

Primary inputs:
- Hermes research packets
- Atlas candidate packets
- Fish scenario packets
- Sigma validation/promotion/rejection packets
- Executor execution_status, fill, position packets
- live market data summaries
- prior Kitt briefs
- lane health summaries
- TradeFloor packets
- strategy registry
- approval registry

Primary outputs:
- brief_packet (see Section 6 for format)
- setup_packet
- alert_packet
- tradefloor_request_packet
- papertrade_request_packet

Risk authority:
- Kitt monitors portfolio-level concentration, correlation, total exposure
- Kitt does not enforce per-trade limits (Executor's job)
- if portfolio thresholds breached: Kitt escalates + Executor refuses new orders (dual enforcement)
- shared/config/risk_limits.json is source of truth for both

Kitt should: synthesize, prioritize, escalate, coordinate, maintain portfolio view, report health, be single operator interface.

Kitt should not: brute-force experiments, deeply validate, execute trades, spam operator.

Escalation rule: notify operator for high-confidence setups, important consensus, urgent market shifts, candidates worthy of paper/live, execution anomalies, health anomalies, portfolio risk breaches, TradeFloor high-conviction or actionable agreement.

---

### Atlas
Role: autonomous autoquant / R&D lab.

Channel: Discord 1483916149573025793

Primary inputs: datasets, Hermes research, Kitt ideas, prior experiments, Sigma strategy_rejection_packets, strategy registry, AutoQuant tooling.

Primary outputs: idea_packet, candidate_packet, experiment_batch_packet, failure_learning_packet, health_summary.

Atlas should: generate, mutate, explore, rank, package, adapt from rejections, check registry for duplicates, log feedback intake.

Atlas should not: validate, notify operator for routine experiments, trade, submit duplicates of active strategies.

Escalation rule: top candidates, novel discoveries, or material changes to Kitt's view only.

Feedback contract:
- reads Sigma strategy_rejection_packets, adapts when rejections cluster on a pattern
- reads Sigma paper_review_packets to learn what survived live conditions
- logs which patterns it has adapted to

---

### Fish
Role: scenario, simulation, forecasting, MiroFish lane.

Channel: Discord 1483916169672130754

Primary inputs: macro/event data, Hermes research, market regime data, Kitt scenario requests, MiroFish repo, realized outcome data.

Primary outputs: scenario_packet, forecast_packet, regime_packet, risk_map_packet, calibration_packet, health_summary.

Fish should: simulate, forecast, map futures, self-calibrate.

Fish should not: validate strategies, own promotion, trade.

Escalation rule: major regime changes, strong divergence, or forecasts that materially alter Kitt's stance.

Feedback contract:
- periodically compares forecasts to outcomes
- calibration adjusts own confidence weights
- Fish confidence = f(calibration history); poor recent accuracy → lower confidence scores
- calibration_packet shared with Kitt

---

### Sigma
Role: Strategy Factory lane, validation, lifecycle gatekeeper, paper-trade reviewer.

Channel: Discord 1483916191046041811

Primary inputs: Strategy Factory specs, candidate_packets from Atlas/Kitt, backtest configs, strategy registry, validation history, Executor paper/live results.

Primary outputs: validation_packet, promotion_packet, strategy_rejection_packet, papertrade_candidate_packet, paper_review_packet, health_summary.

Sigma should: validate, gate, promote/reject, maintain rigor, explain rejections for Atlas, review paper and live performance.

Sigma should not: judge every lane, receive every raw idea, replace Atlas, trade.

Escalation rule: candidate passes validation, deserves paper consideration, or paper/live review reveals significant deviation.

Strategy rejection packet (required fields):
- rejection_reason: curve_fit | poor_oos | insufficient_trades | regime_fragile | excessive_drawdown | invalid_execution_assumptions | correlation_to_existing | other
- rejection_detail: free text
- suggestion: optional

---

### Hermes
Role: external research feeder.

Direction: set by research_request_packets from other lanes or operator. Without requests, follows shared/config/watch_list.json. Dedup: skip same source within configurable window (default 24h) unless re-requested.

Primary inputs: SearXNG, repos, articles, tweets, docs, transcripts, datasets, research_request_packets.

Primary outputs: research_packet, dataset_packet, repo_packet, theme_packet, health_summary.

Hermes should not: make quant decisions, validate, spam operator, self-direct indefinitely.

---

### Executor
Role: execution lane for approved paper and live trades. Local-only for all execution-critical operations.

Channel: no standalone Discord stream. Key outputs through Kitt and review channel.

Primary inputs: papertrade_request_packet with valid approval_ref (from Kitt, after operator approval), live_trade_packet with valid approval_ref (from Kitt, after operator approval), risk_limits.json, kill_switch.json, approval registry, broker adapter, strategy registry.

Primary outputs: execution_intent_packet, execution_status_packet, fill_packet, execution_rejection_packet, position_update_packet, kill_switch_event, health_summary.

Pre-flight checks (all must pass):
1. approval_ref exists in approvals.jsonl, is not expired, is not revoked
2. execution_mode matches approval_type
3. symbols are within approved_actions.symbols
4. position would not breach per-strategy limits (from approval + risk_limits.json)
5. position would not breach portfolio limits (from risk_limits.json)
6. kill switch not engaged
7. broker connection healthy

Failure on any check: refuse, emit execution_rejection_packet, do not retry.

Execution-critical (local-only, never cloud): order placement, risk checks, kill switch checks, position reconciliation, pre-flight, fill processing.

Cloud-allowed (non-critical only): execution summaries, health_summary, post-hoc analytics.

Broker adapter architecture:
- Executor talks to brokers through a pluggable adapter interface.
- **Build the paper adapter first.** It must implement the full adapter interface (place order, check status, get fills, get positions, cancel order) against a simulated/paper environment.
- **Stub the live broker adapter behind the same interface.** Live methods throw "not implemented" until live trading is explicitly built and tested.
- All pre-flight checks, approval validation, kill switch logic, and risk enforcement run identically regardless of which adapter is active. The adapter is the last mile, not the control layer.
- This means the entire paper-trade path can be proven end-to-end before any live broker code exists.

Executor should: be fast, deterministic, auditable, enforce all checks, log durably.

Executor should not: discover, validate, self-authorize, bypass controls, decide strategy outcomes.

Execution rejection packet (required fields):
- execution_rejection_reason: invalid_approval | expired_approval | revoked_approval | mode_mismatch | symbol_not_approved | strategy_limit_breach | portfolio_limit_breach | kill_switch_engaged | broker_unhealthy | broker_rejected | insufficient_liquidity | other
- execution_rejection_detail: string
- order_details: object

---

### TradeFloor
Role: invoked synthesis workflow. Routes through Kitt.

Invoked: on operator request, schedule, Kitt request, material lane disagreement, near-promotion, portfolio review. **Max once per 6 hours by default.** Operator or Kitt can override the cap for urgent synthesis, but the override must be logged in the tradefloor_packet and health_summary.

**Sparse from day one.** TradeFloor is a premium signal, not a chatbot. Treat invocations like you're paying for an analyst's time. If nothing material has changed since the last TradeFloor run, skip the cycle even if the timer allows it. Kitt can decide "nothing worth synthesizing" and not invoke. The 6-hour cap is a ceiling, not a target.

Input (from shared/latest/ and lane directories): latest from each lane + strategy registry + approval registry snapshot.

Output structure:
1. Agreement matrix
2. Disagreement matrix (with per-lane confidence from Section 8)
3. Confidence-weighted synthesis
4. Agreement tier (see Section 8)
5. Pipeline snapshot (strategies per lifecycle state, bottlenecks)
6. Immediate next actions (concrete, lane-assigned)
7. Deferred questions
8. Operator recommendation (notify / skip / schedule, with reasoning)

Routing: save to workspace/quant/tradefloor/, update shared/latest/, Kitt reads and decides what operator sees.

### TradeFloor vs Council

TradeFloor and Council are two distinct systems. They must not be confused.

| | TradeFloor (this spec) | Council (council.py) |
|---|---|---|
| Scope | Quant lanes only | General-agent coordination across all of Jarvis/OpenClaw |
| Mode | File-first, packet-first | Live Discord thread, sequential agent debate |
| Input | Reads shared/latest/ quant packets and strategy registry | Reads conversation context |
| Output | Structured tradefloor_packet with agreement tier | Discord thread with agent responses |
| Routing | Saved to file → shared/latest/ → Kitt decides what operator sees | Posted directly to Discord |
| Invocation | On-demand, sparse, capped (max 1x per 6 hours) | On-demand |
| Naming in packets | tradefloor_packet, tradefloor_request_packet | N/A (not part of quant packet system) |

**Hard rule:** for all quant lane work, TradeFloor (file-first, packet-first, Kitt-routed) is the canonical and only synthesis workflow. Council is a separate general-purpose system for non-quant multi-agent coordination. Council output does not feed the quant lane packet system. TradeFloor output does not feed the general Council system. They have distinct names, distinct invocation paths, and distinct codebases. No agent should confuse the two.

**Mental model:**
- Council = whole-system brain, general-agent coordination
- TradeFloor = trading desk consensus engine, quant-only

---

## 7. Kitt summary format contracts

Kitt is the single operator-facing interface. Its outputs must be structured and scannable.

### Brief packet format

```
KITT BRIEF — {date} {time}
━━━━━━━━━━━━━━━━━━━━━━━━━

MARKET READ
{1-3 sentence market structure summary}

TOP SIGNAL
{The single most important thing right now. Could be a setup, a regime shift, a TradeFloor consensus, or nothing.}

PIPELINE
  PAPER_ACTIVE: {count} strategies ({strategy_ids})
  LIVE_ACTIVE:  {count} strategies ({strategy_ids})
  Near promotion: {any strategies approaching paper review or live consideration}
  
PORTFOLIO SNAPSHOT
  Total exposure: {summary}
  Concentration flags: {any, or "clean"}
  Correlation flags: {any, or "clean"}

LANE ACTIVITY
  Atlas: {1-line summary of recent batch output}
  Fish:  {1-line summary of current regime/scenario view}
  Sigma: {1-line summary of recent validations}
  Hermes: {1-line summary of recent research}

TRADEFLOOR (if invoked since last brief)
  Agreement tier: {none | weak | strong | high_conviction | actionable}
  Key finding: {1 sentence}
  
EXECUTION (if active)
  {Per-strategy: status, PnL summary, any anomalies}

SYSTEM HEALTH
  Active lanes: {list}
  Silent/errored: {any, or "all healthy"}
  Host status: NIMO {load summary} | SonLM {load summary}
  Cloud spend (24h): {amount}
  Feedback loops: {Atlas consuming rejections: yes/no, Fish calibrating: yes/no}
  Governor: {per-lane summary: pushed/held/backed off/paused}

OPERATOR ACTION NEEDED
  {List of items needing approval or attention, or "none"}
```

### TradeFloor summary format (when Kitt surfaces TradeFloor output)

```
TRADEFLOOR SUMMARY — {date}
Agreement tier: {tier}
Consensus: {1-2 sentences on what lanes agree on}
Key disagreement: {1-2 sentences on where lanes diverge}
Recommended action: {concrete next step}
Operator review needed: {yes/no + reason}
```

### Execution summary format (when Kitt surfaces Executor output)

```
EXECUTION UPDATE — {strategy_id}
Mode: {paper/live}
Status: {active/filled/rejected/killed}
Trades: {count} | PnL: {amount} | Drawdown: {current}
Slippage: {avg vs expected}
Anomalies: {any, or "none"}
Next review: {date or trigger}
```

These formats are templates, not rigid schemas. Kitt may adjust wording but must include all sections relevant to current state. Empty sections can be omitted (e.g. no TRADEFLOOR section if TradeFloor hasn't run, no EXECUTION section if nothing is active).

---

## 8. TradeFloor agreement tiers

"TradeFloor agrees" must mean something concrete. These tiers define what it means.

| Tier | Name | Definition | What it signals |
|------|------|------------|-----------------|
| 0 | No agreement | Lanes diverge or insufficient data | No actionable consensus. Kitt notes it, no escalation. |
| 1 | Weak agreement | 2+ lanes align on direction, no strong objection from others | Interesting but not actionable on its own. Kitt may note in brief. |
| 2 | Strong agreement | Kitt + Sigma align, and at least one of Atlas/Fish supports the same direction | Meaningful consensus across research and validation. Kitt highlights in brief. |
| 3 | High-conviction agreement | Kitt + Sigma + at least one of Atlas/Fish align, no execution/risk objection, and all supporting lanes have confidence > configured threshold (default 0.6) | Serious signal. Kitt escalates to operator as notable consensus. |
| 4 | Actionable agreement | High-conviction agreement PLUS a concrete recommended action (paper-trade this candidate, shift regime stance, adjust portfolio) | Strongest possible TradeFloor signal. Kitt presents to operator with clear action recommendation. |

### How TradeFloor determines the tier

1. TradeFloor reads each lane's latest packet and its confidence score.
2. TradeFloor checks alignment: do the lanes' theses point in the same direction for the topic at hand?
3. TradeFloor checks for objections: does any lane actively contradict?
4. TradeFloor checks confidence: are supporting lanes above threshold?
5. TradeFloor checks actionability: is there a concrete action (not just "things look good")?
6. TradeFloor assigns the highest tier whose conditions are fully met.
7. TradeFloor includes the tier and its reasoning in the tradefloor_packet.

### What operator sees

| Tier | Operator visibility |
|------|-------------------|
| 0-1 | In Kitt brief only, no notification |
| 2 | Highlighted in Kitt brief, no notification |
| 3 | Kitt brief + notification (notify but don't block) |
| 4 | Kitt brief + notification + clear action item requiring response |

---

## 9. Confidence sources for TradeFloor synthesis

| Lane | Source | Adjustment mechanism |
|------|--------|---------------------|
| Fish | Calibration history | Recent calibration error rate scales confidence. High error across last K calibration_packets → penalized. |
| Sigma | Validation quality + paper review survival | Tracks fraction of PROMOTED strategies surviving paper. Low survival → lower Sigma confidence in own promotions. |
| Atlas | Historical promotion rate + post-paper survival | Tracks fraction of candidates reaching PROMOTED. Also tracks post-paper survival. Low rates → lower Atlas confidence. |
| Kitt | Synthesis-level | Weighted synthesis of other lanes' confidences. Reflects agreement level and source calibration. |
| Hermes | Recency + source quality | Primary sources (official docs, peer-reviewed) > secondary. Stale research for fast-moving topics carries lower weight. |

TradeFloor reads confidence from each lane's latest packet and uses them to weight synthesis. TradeFloor does not invent its own confidence.

---

## 10. Standard packet contract

### Core fields (required on every packet)

| Field | Type | Description |
|-------|------|-------------|
| packet_id | string | Format: `{lane}-{type}-{timestamp}-{short_hash}` |
| packet_type | string | One of the canonical types |
| lane | string | Producing lane |
| created_at | ISO 8601 | When produced |
| thesis | string | One-sentence summary |
| priority | enum | low, medium, high, critical |

### Extended fields (include when meaningful, omit when not)

| Field | Type | When |
|-------|------|------|
| strategy_id | string | Any packet referencing a strategy |
| symbol_scope | string or list | Symbol-specific |
| timeframe_scope | string | Timeframe-specific |
| confidence | float 0-1 | When lane has confidence estimate |
| evidence_refs | list of packet_ids | Building on prior work |
| artifacts | list of file paths | Associated files |
| action_requested | string | Downstream action needed |
| escalation_level | enum | none, team_only, kitt_only, operator_review, urgent_operator |
| supersedes | packet_id | Replacing a prior packet |
| approval_ref | string | Referencing an approval |
| notes | string | Anything else |

### Strategy rejection fields (on strategy_rejection_packet)

| Field | Type |
|-------|------|
| rejection_reason | enum: curve_fit, poor_oos, insufficient_trades, regime_fragile, excessive_drawdown, invalid_execution_assumptions, correlation_to_existing, other |
| rejection_detail | string |
| suggestion | string (optional) |

### Execution rejection fields (on execution_rejection_packet)

| Field | Type |
|-------|------|
| execution_rejection_reason | enum: invalid_approval, expired_approval, revoked_approval, mode_mismatch, symbol_not_approved, strategy_limit_breach, portfolio_limit_breach, kill_switch_engaged, broker_unhealthy, broker_rejected, insufficient_liquidity, other |
| execution_rejection_detail | string |
| order_details | object |

### Execution fields (on execution-related packets)

| Field | Type |
|-------|------|
| execution_mode | paper or live |
| strategy_id | string |
| symbol | string |
| side | long or short |
| order_type | market, limit, stop, etc. |
| sizing | object: method + parameters |
| risk_limits | object: max_loss, max_position, etc. |
| approval_ref | string (mandatory) |
| execution_status | pending, filled, partial, rejected, cancelled |
| fill_price | float (when filled) |
| slippage | float (when filled) |
| error_code | string (when rejected) |

### Paper review fields (on paper_review_packet)

| Field | Type |
|-------|------|
| strategy_id | string |
| review_period | object: start, end |
| trade_count | int |
| realized_pf | float |
| realized_sharpe | float |
| max_drawdown | float |
| avg_slippage | float |
| fill_rate | float |
| portfolio_correlation | float |
| consistency_flag | pass or fail |
| outcome | advance_to_live, iterate, or kill |
| outcome_reasoning | string |
| iteration_guidance | string (required if iterate) |

### TradeFloor fields (on tradefloor_packet)

| Field | Type |
|-------|------|
| agreement_tier | int 0-4 |
| agreement_tier_reasoning | string |
| agreement_matrix | object |
| disagreement_matrix | object |
| confidence_weighted_synthesis | string |
| pipeline_snapshot | object |
| next_actions | list of objects (action + assigned_lane) |
| deferred_questions | list of strings |
| operator_recommendation | enum: notify, skip, schedule |
| operator_recommendation_reasoning | string |
| degraded | boolean (true if cloud was unavailable and local fallback was used) |

### Health summary fields (on health_summary)

| Field | Type |
|-------|------|
| lane | string |
| period_start | ISO 8601 |
| period_end | ISO 8601 |
| packets_produced | int |
| packets_by_type | object |
| escalation_count | int |
| error_count | int |
| cloud_bursts | int |
| estimated_cloud_cost | float |
| notable_events | string |
| scheduler_waits | int (times this lane queued due to concurrency cap) |
| scheduler_bypasses | int (times heavy work started without registering — should always be 0) |
| host_used | string (NIMO, SonLM, cloud, or mixed) |
| local_runtime_seconds | float |
| cloud_runtime_seconds | float |
| usefulness_score | float 0-1 |
| efficiency_score | float 0-1 |
| health_score | float 0-1 |
| confidence_score | float 0-1 |
| governor_action_taken | string (push, hold, backoff, pause, or none) |
| governor_reason | string (brief explanation) |
| current_batch_size | int |
| current_cadence_multiplier | float |

### Canonical packet type list

**Research** (Hermes): research_packet, dataset_packet, repo_packet, theme_packet

**Research direction** (any lane → Hermes): research_request_packet

**Discovery** (Atlas): idea_packet, candidate_packet, experiment_batch_packet, failure_learning_packet

**Scenarios** (Fish): scenario_packet, forecast_packet, regime_packet, risk_map_packet, calibration_packet

**Validation** (Sigma): validation_packet, promotion_packet, strategy_rejection_packet, papertrade_candidate_packet, paper_review_packet

**Operator request** (Kitt): papertrade_request_packet, live_trade_packet

**Execution** (Executor): execution_intent_packet, execution_status_packet, fill_packet, execution_rejection_packet, position_update_packet, kill_switch_event

**Briefing** (Kitt): brief_packet, setup_packet, alert_packet

**Synthesis** (TradeFloor or Kitt): tradefloor_packet, tradefloor_request_packet

**System** (all lanes): health_summary

**Packet flow clarity:**
```
Sigma → strategy_rejection_packet    (strategy failed validation)
Executor → execution_rejection_packet (order rejected by broker or pre-flight)

Sigma → papertrade_candidate_packet  (strategy fit for paper — goes to Kitt, NOT to Executor)
Kitt → papertrade_request_packet     (operator, please approve paper)
Kitt → live_trade_packet             (operator, please approve live)

Executor listens for: papertrade_request_packet or live_trade_packet WITH valid approval_ref
Executor does NOT listen for: papertrade_candidate_packet (that is Sigma → Kitt only)
```

No other packet types should be invented without updating this spec.

---

## 11. Paper-trade review contract

### Review triggers (any one triggers PAPER_REVIEW)

- minimum paper duration elapsed (configurable, default 14 days)
- minimum trade count reached (configurable, default 20 round-trips)
- anomaly detected (drawdown spike, execution quality collapse, slippage surge)
- operator requests review

### Review criteria

Sigma evaluates, Kitt synthesizes. Both must agree for advancement.

| Criterion | Metric | Pass threshold | Source |
|-----------|--------|----------------|--------|
| Profitability | Realized PF | >= configured min (default 1.3) | fill_packets |
| Risk-adjusted | Realized Sharpe | >= configured min (default 0.8) | fill_packets |
| Drawdown | Max realized DD | <= configured max (default 15%) | position_update_packets |
| Slippage | Avg slippage vs backtest | <= configured tolerance (default 2x backtest) | fill_packets vs validation_packet |
| Execution quality | Fill rate | >= configured min (default 90%) | fill_packets |
| Portfolio overlap | Correlation to active strategies | <= configured max (default 0.7) | Kitt portfolio tracking |
| Consistency | Win rate stability | No single week > 60% of total PnL | fill_packets |

Thresholds stored in shared/config/review_thresholds.json. Operator-adjustable without redeployment.

### Review outcomes

| Outcome | Transition | Action |
|---------|-----------|--------|
| advance_to_live | PAPER_REVIEW → LIVE_QUEUED (requires operator approval) | Kitt emits alert, operator approves, Executor transitions |
| iterate | PAPER_REVIEW → ITERATE → CANDIDATE | Sigma writes iteration guidance, lineage preserved |
| kill | PAPER_REVIEW → PAPER_KILLED | Archived with learnings, failure feeds Atlas |

---

## 12. Market data contract

| Lane | Data type | Source | Freshness | Retention | Fallback |
|------|-----------|--------|-----------|-----------|----------|
| Kitt | Live quotes, order book, intraday bars | Primary feed (config) | < 30s | 30d rolling | Degrade to delayed; flag staleness |
| Atlas | Historical OHLCV, tick data | Local store + Hermes datasets | EOD ok, intraday preferred | Full history | Last snapshot; log gap |
| Fish | Macro indicators, event calendars, vol surfaces | Hermes + macro API | Daily for macro; event-driven | 1y rolling | Last known; flag stale in confidence |
| Sigma | Backtest prices, execution cost estimates | Local store + spread/slippage data | EOD ok | Full history | Refuse validation if missing; rejection with "insufficient_data" |
| Executor | Real-time quotes, broker state, balances, positions | Broker API | < 5s for order decisions | All fills/positions permanent | Refuse execution; execution_rejection broker_unhealthy; auto kill switch if disconnect > threshold |
| Hermes | Web, APIs, repos, social | SearXNG + APIs | Varies | Cache per dedup window | Log failure; try alt; skip if all fail |
| TradeFloor | None (reads packets) | shared/latest/ | N/A | N/A | N/A |

Sources defined in shared/config/data_sources.json. Must be populated before Phase 1.

---

## 13. Handoff graph

### Forward flow

```
Research:       Hermes ──→ Kitt / Atlas / Fish / Sigma
Discovery:      Atlas ──→ Sigma ──→ [PROMOTED] ──→ Kitt ──→ Operator ──→ Executor
Discretionary:  Hermes + Fish + Atlas ──→ Kitt ──→ Operator
Scenario:       Fish ──→ Kitt ──→ (TradeFloor optional) ──→ Operator if material
Validation:     Kitt idea ──→ Sigma ──→ Kitt
Paper trade:    Sigma PROMOTED ──→ Kitt request ──→ Operator approval ──→ Executor
Paper review:   Executor results ──→ Sigma + Kitt ──→ advance / iterate / kill
Live trade:     advance ──→ Kitt live_trade_packet ──→ Operator approval ──→ Executor
Synthesis:      All lanes ──→ TradeFloor ──→ Kitt ──→ Operator
```

### Feedback flow

```
Sigma strategy_rejection ──→ Atlas
Sigma paper_review ──→ Atlas
Fish calibration ──→ Fish + Kitt
Executor fills/slippage ──→ Sigma
Executor results ──→ strategy registry
Hermes direction ←── all lane priorities
Operator feedback ──→ Kitt ──→ relevant lane
```

### Health flow

```
All lanes ──→ health_summary ──→ Kitt ──→ operator (in brief)
```

---

## 14. Autonomy and review policy

### Autonomous (no review)
- research, packet production, experiments, backtests, scenarios, calibration, ranking, artifacts, synthesis, idea generation, tests, feedback, health emission

### Notify (don't block)
- high-confidence Kitt setup, Sigma promotion, major Fish regime shift, Atlas breakthrough, TradeFloor tier 3+ agreement, health anomaly, execution anomaly, portfolio near limits

### Require operator approval
- paper-trade (PAPER_QUEUED), live-trade (LIVE_QUEUED), kill switch engage/disengage, LIVE_ACTIVE retirement, destructive config changes, permission expansion, routing changes affecting spend/risk, budget cap overrides

---

## 15. Risk and portfolio management

### Risk authority split

| Scope | Authority | Source |
|-------|-----------|--------|
| Per-trade limits | Executor enforces | approval object + risk_limits.json |
| Portfolio limits | Kitt monitors + Executor enforces | risk_limits.json |
| Escalation on breach | Kitt → operator | brief / alert |
| Order refusal on breach | Executor | execution_rejection_packet |

Dual enforcement: portfolio breach → Executor refuses new exposure AND Kitt escalates.

### Kill switch
- checked before every order (kill_switch.json)
- operator can engage anytime
- engaging cancels open orders, prevents new ones
- kill_switch_event surfaced immediately through Kitt
- disengaging requires operator approval
- auto-engages on broker disconnect > configured threshold

---

## 16. Observability

### Lane health
Every lane: health_summary per work cycle (including governor scores and action taken), minimum once per 24 hours.

### Kitt brief health section
Every brief includes: active lanes, silent/errored lanes, packet flow, feedback loop status, execution status, portfolio snapshot, cloud spend, host pressure (NIMO/SonLM), governor status per lane (pushed/held/backed off/paused).

### Circuit breakers

Circuit breakers are the hard-stop layer. The governor handles gradual adjustment; circuit breakers handle emergencies.

| Condition | Action |
|-----------|--------|
| Atlas zero promotions across N batches (default 5) | Governor pauses Atlas, failure_learning_packet, Kitt flags |
| Fish calibration error > threshold across K cycles | Governor backs off Fish, confidence degradation flag |
| Sigma rejection > 95% across M cycles | Kitt flags (Atlas broken or Sigma too strict) |
| Executor repeated rejects/disconnects/slippage | Alert, Kitt escalates, governor pauses Executor |
| Missing approval_ref | Hard refusal, execution_rejection_packet |
| Silent lane (no health in 48h) | Kitt flags |
| Portfolio breach | Kitt alerts, Executor refuses new exposure |
| Broker disconnect > threshold | Kill switch auto-engages |
| Host memory/VRAM critically overloaded | Governor pauses lowest-priority running lane |
| Lane paused by governor for 3+ cycles with no improvement | Kitt flags for operator attention |

### Cost tracking
- cloud bursts in health_summary with estimated cost
- Kitt aggregates in briefs
- soft caps in budget_caps.json, per lane per day
- fallback to local when cap hit
- governor disables cloud_burst_allowed for a lane if it exceeds its soft cap

---

## 17. Local/cloud routing

Default: local-first. Cloud when stronger synthesis matters, local inadequate, brief/tradefloor quality justifies cost, high-value validation.

| Lane | Default | Cloud for |
|------|---------|-----------|
| Kitt | Local-first | Premium briefs |
| Atlas | Local-heavy | Difficult synthesis/coding |
| Fish | Local-first | Heavy scenario synthesis |
| Sigma | Local-first | High-value validation |
| Hermes | Mixed | N/A |
| TradeFloor | Strongest efficient model | Always (reads packets, not giant contexts). If cloud unavailable: fall back to best local model, mark tradefloor_packet as `degraded: true`, and log in health_summary. Kitt must note degraded synthesis in brief. |
| Executor | **Local-only for execution-critical** | Non-critical reporting only |

All lanes support profile-aware routing. Burst cost in health_summary. Cloud burst also serves as local pressure relief (see Section 2).

---

## 18. Storage

### Flowstate
External ingestion only.

### Quant lane storage

```
workspace/quant/
  shared/
    schemas/
    registries/
      strategies.jsonl
      approvals.jsonl
      watch_list.json
    latest/
    config/
      risk_limits.json
      budget_caps.json
      kill_switch.json
      data_sources.json
      review_thresholds.json
      cadence.json
      hosts.json
      governor_state.json
    scheduler/
      active_jobs.json
  kitt/
    briefs/ setups/ alerts/ health/
  atlas/
    idea_packets/ candidate_packets/ experiment_batches/ learnings/ health/
  fish/
    scenario_packets/ forecast_packets/ regime_packets/ calibration/ health/
  sigma/
    validation_packets/ promotion_packets/ rejection_packets/ papertrade_candidates/ paper_reviews/ health/
  hermes/
    research_packets/ dataset_packets/ repo_packets/ health/
  executor/
    execution_intents/ execution_status/ fills/ positions/ rejects/ health/
  tradefloor/
    tradefloor_packets/
```

### Obsidian mirror (optional)
```
Obsidian/Quant/ Kitt/ Atlas/ Fish/ Sigma/ Hermes/ Executor/ TradeFloor/
```

### Rules
- compact packets in workspace/quant
- large research in outputs/Obsidian
- shared/latest/ always current
- strategies.jsonl = lifecycle source of truth
- approvals.jsonl = approval source of truth

### Restart
- stateless between invocations, all state in filesystem
- on restart: read own latest + shared/latest/
- missing state: log gap, start fresh

---

## 19. Discord behavior

**Kitt** (1483320979185733722): briefs, setups, synthesis, alerts, tradefloor summaries, execution outcomes.

**Atlas** (1483916149573025793): top batch summaries, high-value candidates, learnings. Never every trial.

**Fish** (1483916169672130754): regime updates, scenarios, forecasts, periodic calibration.

**Sigma** (1483916191046041811): validation results, promotions/rejections, papertrade candidates, paper reviews.

**Review**: approvals only — paper, live, kill switch, control changes.

**Outputs**: ingestion artifacts, research extractions.

**Executor**: no standalone channel. Kitt summarizes. Review handles approvals.

---

## 20. Lane non-confusion rules

**Kitt:** don't search full space, deeply validate, execute trades, skip health/portfolio.

**Atlas:** don't require review for routine, validate (Sigma's job), take over Strategy Factory, ignore rejections, submit duplicates.

**Fish:** scenarios ≠ validated strategies, don't own promotion, don't skip calibration.

**Sigma:** don't judge every lane, don't absorb exploration, own validation + SF, always explain rejections, review paper results not just backtests.

**Hermes:** packets not essays, don't self-direct indefinitely, deduplicate.

**Executor:** don't discover/validate, don't self-authorize, don't bypass controls, don't hide anomalies, never cloud for execution-critical.

**TradeFloor:** don't read histories, synthesize packets not data, structured template, route through Kitt.

---

## 21. Implementation phases

### Phase 0 — vertical slice (brutally small)

This must be the smallest possible proof that the core loop works. Do not scaffold the world. Do not build utilities. Do not wire Discord. Just prove the loop.

Scope: one candidate, one pass/reject, one paper approval, one Executor dry-run, one Kitt brief. That's it.

Steps:
1. Pick one concrete strategy idea.
2. Write one research_packet (Hermes) as a simple JSON file with core fields only.
3. Write one candidate_packet (Atlas) referencing that research.
4. Write one validation_packet + either strategy_rejection_packet or promotion_packet (Sigma).
5. If promoted: write one papertrade_candidate_packet (Sigma) and one papertrade_request_packet (Kitt).
6. Create one approval_object as a JSON file. Attach it to a mock Executor dry-run.
7. Write one execution_intent_packet and one execution_status_packet (Executor) — paper mode, no real broker.
8. Write one brief_packet (Kitt) summarizing the entire flow.
9. Create one strategy registry entry and walk it through state transitions by hand.
10. Document every friction point: missing fields, awkward handoffs, unclear ownership.

Deliver: the JSON files from steps 1-9, initial strategy registry, friction log, finalized minimal schema. This should take hours, not days. If it takes more than a day, the scope has crept.

### Phase 1 — scaffolding
Schemas, directory tree, registry + write utility with locking, approval registry, config files (risk, budget, kill switch, data sources, review thresholds, cadence, hosts, governor_state, watch list), scheduler utility with host-awareness, Discord wiring, lane identity files, packet read/write utils, health template with governor fields.

### Phase 2 — core loop (Kitt + Sigma + Executor)
Kitt intake + briefs (Section 7 format) + portfolio tracking. Sigma validation + rejection + promotion + paper review (Section 11 criteria). Strategy lifecycle transitions via registry utility. Approval object creation flow. Executor pre-flight + routing + registry updates. Paper → operator → Executor flow.

### Phase 3 — discovery + scenarios + synthesis (Atlas + Fish + TradeFloor + Hermes)
Atlas loop + rejection intake + registry check. Fish scenario + calibration + confidence. TradeFloor structured synthesis + agreement tiers (Section 9). Hermes request intake + dedup. Escalation thresholds. TradeFloor → Kitt routing.

### Phase 4 — governor + observability + hardening
Threshold-based adaptive governor (Section 3). Governor scoring integration per lane. Host-aware scheduling enforcement across NIMO + SonLM. Health emission with governor fields everywhere. Circuit breakers integrated with governor. Cost tracking + caps + governor cloud control. Portfolio risk monitoring. Kill switch + auto-engage. Obsidian mirror. Profile-aware routing. Dashboard including governor status. Integration test: full pipeline with governor active across both hosts.

**Implementation rule for governor: start threshold-based only.** Do not build RL or optimization. One parameter, one step, one direction per cycle. Prove the simple version works before adding sophistication.

---

## 22. Worker split

### Prerequisite
Phase 0 complete. Interface contracts agreed.

### Interface contracts (before parallel work)

1. strategy_rejection_packet schema (Sigma → Atlas)
2. execution_rejection_packet schema (Executor → Kitt)
3. tradefloor_packet → Kitt intake contract (including agreement_tier)
4. papertrade_candidate_packet schema (Sigma → Kitt)
5. execution_status_packet fields Kitt summarizes
6. strategy registry write contract (transitions, locking)
7. approval object format and registry contract
8. paper_review_packet schema (Sigma → Kitt)
9. health_summary governor fields schema (all lanes must emit the same governor fields)

### Worker 1 — scaffolding + governor foundation (Phase 1)
Owns: shared/, schemas, configs, utilities, registries, scheduler, governor_state.

Delivers:
- directory tree with host config and governor_state
- host-aware scheduler utility (tracks NIMO/SonLM per job)
- governor_state.json structure with per-lane parameters
- health_summary template with governor fields
- all config files including hosts.json

### Worker 2 — Kitt + Sigma + Executor (Phase 2)
Owns: kitt/, sigma/, executor/.

Delivers: Kitt intake + briefs + portfolio tracking + governor status in briefs. Sigma validation/rejection/promotion/paper_review. Executor pre-flight + approval validation + host-isolated execution. Strategy lifecycle. Example flow.

### Worker 3 — Atlas + Fish + TradeFloor + Hermes (Phase 3)
Owns: atlas/, fish/, tradefloor/, hermes/.

Delivers: Atlas loop + rejection intake + registry check + governor score emission. Fish calibration + confidence + governor score emission. TradeFloor synthesis + agreement tiers. Hermes request + dedup. Per-lane usefulness/efficiency/health/confidence scoring.

### Worker 4 — governor + observability (Phase 4, after merge)
Owns: cross-cutting governor logic, health monitoring, host scheduling enforcement, polish.

Delivers:
- threshold-based governor decision logic
- governor reads scores from health_summaries, writes updated parameters to governor_state.json
- push/hold/backoff/pause actions per lane
- lane-specific governor rules (Section 3)
- circuit breaker integration with governor
- host pressure monitoring across NIMO + SonLM
- cost tracking with governor cloud control
- kill switch mechanics
- Obsidian mirroring
- integration test: full pipeline with governor active

### Worker 4 — observability (Phase 4, after merge)
Owns: cross-cutting health, monitoring, kill switch, scheduler enforcement, polish.

---

## 23. Supervisor prompt

```
Work on main.

Goal: implement Quant Lanes Operating Spec v3.5.1.

Prerequisites:
- Phase 0 vertical slice complete.
- Nine interface contracts agreed (Section 22).

Constraints:
- Lanes narrow, non-overlapping.
- Kitt = operator-facing lead + portfolio tracker.
- Atlas = autoquant lab, learns from rejections.
- Fish = scenario/simulation, self-calibrates, confidence adjusts.
- Sigma = Strategy Factory + validation + paper review with concrete criteria.
- Hermes = directed research with dedup.
- Executor = local-only execution, approved paper/live, pre-flight mandatory, approval object validated.
- TradeFloor = invoked synthesis with agreement tiers (0-4), routes through Kitt.
- TradeFloor is file-first/packet-first. Council (council.py) is a separate general-agent system, never used for quant work.
- TradeFloor max once per 6 hours unless operator/Kitt explicitly overrides with logged justification.
- Every strategy has lifecycle state in registry.
- Registry writes through shared utility with locking and transition validation.
- Approvals through structured approval objects in approvals.jsonl.
- Rejections split: strategy_rejection_packet vs execution_rejection_packet.
- Paper review has concrete pass/fail criteria in review_thresholds.json.
- Confidence sources defined per lane.
- Named hosts: NIMO (primary, cap 2 heavy), SonLM (overflow, cap 1 heavy), global cap 3.
- All heavy work through shared utilities that check scheduler + host. No raw model calls outside wrappers.
- Adaptive governor: threshold-based, one parameter one step per cycle. Push productive lanes, back off unproductive. Governor cannot bypass safety/approval gates.
- No review for routine experiments.
- Operator approval for paper/live/destructive only.
- Local-first, cloud-capable with cost tracking.
- Executor never cloud for execution-critical.
- TradeFloor agreement tier 3-4 = operator notification.

File ownership:
- Worker 1: shared/, schemas, configs, utilities, registries, scheduler, governor_state
- Worker 2: kitt/, sigma/, executor/
- Worker 3: atlas/, fish/, tradefloor/, hermes/
- Worker 4 (post-merge): governor logic, observability, host enforcement

Required outputs per worker:
- exact files changed
- what proven vs assumed
- tests run
- feedback loop proof
- governor scoring proof (Workers 3, 4)
- commit hash

When done:
- reconcile at interface contracts
- short summary
- gaps only
```

---

## 24. Success criteria

1. Kitt produces concise briefs (Section 7 format) with portfolio, health, host status, and governor summary.
2. Atlas discovers autonomously, adapts from rejections, stops repeating failures.
3. Fish produces distinct scenarios, calibrates, adjusts own confidence.
4. Sigma validates rigorously with structured rejections and concrete paper review criteria.
5. Hermes feeds directed, deduplicated research.
6. TradeFloor synthesizes with tiered agreement (0-4), surfaced through Kitt.
7. Executor handles paper/live with full pre-flight against approval objects, never bypasses.
8. Every strategy has clear lifecycle state. Nothing floats.
9. Operator interrupted only for meaningful events. TradeFloor tier 3-4 = real signal.
10. Local/cloud works with cost visibility. Executor local-only for execution.
11. Feedback loops provably work.
12. Health observable without manual investigation, including governor status per lane.
13. Portfolio risk tracked and dual-enforced (Kitt + Executor).
14. Kill switch works including auto-engage on broker disconnect.
15. Paper review has concrete criteria and three outcomes.
16. Registry writes locked, validated, append-only. Approvals structured and validated.
17. NIMO and SonLM are used intentionally: host-aware scheduling prevents overload, governor adjusts placement.
18. Adaptive governor prevents host thrash while letting productive lanes scale up. Governor actions are visible in every health_summary and Kitt brief.
19. Governor cannot silently lower safety standards, bypass approvals, or disable risk controls.
20. System remains understandable after weeks of autonomous operation.
21. Worthy candidates reach paper. Paper winners reach live. Losers feed back.
