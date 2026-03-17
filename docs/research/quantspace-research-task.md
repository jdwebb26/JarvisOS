# QuantSpace Research Task
## Reverse-Engineering AutoQuant for Jarvis v5.1 Integration

**Status:** In Progress  
**Created:** 2026-03-13  
**Researcher:** Jarvis (with sub-agent support)  
**Target:** QuantSpace implementation under Jarvis v5.1 Strategy Lab rules

---

## Research Objectives

### Primary Goal
Reverse-engineer AutoQuant's architecture from public information and design a compatible implementation that adheres to Jarvis v5.1 Strategy Lab principles (candidate-first promotion, bounded experiments, explicit review gates).

### Secondary Goals
- Identify which AutoQuant features are worth implementing
- Map AutoQuant's swarm mechanics to Jarvis v5.1 task/event/artifact contracts
- Design safety boundaries that prevent black-box autonomy from bypassing review
- Create implementation roadmap with clear milestones

---

## Known AutoQuant Details (from blog post)

### Architecture Overview
- **135 autonomous agents** operating in distributed network
- **4-layer pipeline:**
  1. Macro (regime detection)
  2. Sector (momentum rotation)
  3. Alpha (8-factor scoring)
  4. Adversarial Risk Officer (veto low-conviction trades)
- **Evolution mechanism:** Darwinian selection with layer weights
- **Competition:** 30 mutations per round
- **Propagation:** Best strategies spread across swarm

### Factor Model
- **Starting point:** 8-factor equal-weight portfolios (Sharpe ~1.04)
- **Agent discoveries:**
  - Dropped: dividend, growth, trend factors
  - Adopted: risk-parity sizing
  - Result: Sharpe 1.32, 3x return, 5.5% max drawdown
- **Mutation targets:** factor weights, position sizing, risk controls

### Evaluation Framework (v2.6.9+)
- **Out-of-sample validation:** 70/30 train/test split with overfit penalty
- **Crisis stress testing scenarios:**
  - GFC '08
  - COVID '20
  - 2022 rate hikes
  - Flash crash
  - Stagflation
- **Composite scoring:** Optimizes for crisis resilience, not just historical Sharpe
- **Data integration:** Real market data (not synthetic)
- **Sentiment injection:** RSS feeds wired into factor models
- **Cross-domain learning:** Research DAG with ML insights biasing finance mutations

### Key Results
- Factor pruning + risk parity emerged without explicit instruction
- Parsimony won: simpler portfolios outperformed complex ones
- Crisis resilience became primary optimization target

---

## Jarvis v5.1 Strategy Lab Constraints

### Must-Have Requirements
1. **Program file definition:** Every lab run must reference a program with:
   - Objective and constraints
   - Forbidden edits
   - Success metrics and failure vetoes
   - Dataset/benchmark assumptions
   - Expected output format

2. **Required outputs per run:**
   - `run_config.json`
   - `baseline_metrics.json`
   - `candidate_metrics.json`
   - `delta_metrics.json`
   - `candidate.patch`
   - `experiment_log.md`
   - `recommendation.json`

3. **No direct production writes:** All changes go through candidate promotion
4. **Explicit review gates:** Risk Officer must be a policy-visible review step, not hidden autonomy
5. **Diversity map:** Track behavioral dimensions (strategy type, regime sensitivity, turnover, drawdown profile)
6. **Veto checks in eval profiles:** Separate hard vetoes from quality metrics

### Forbidden Behaviors
- Modifying production repo directly
- Touching live trading code paths
- Altering review/approval logic without elevated review
- Silent model-family switching
- Hidden reinject loops not reflected in structured state

---

## Research Questions to Answer

### Architecture Mapping
1. How does AutoQuant's 4-layer pipeline map to Jarvis v5.1 subsystems?
2. Can the "adversarial Risk Officer" be implemented as a review gate rather than autonomous agent?
3. What replaces the 135-agent swarm with bounded, explicit task envelopes?

### Factor Model Details (Gaps)
4. Which specific 8 factors did AutoQuant start with?
5. What are the mutation rules for factor weights? (random walk? gradient-based?)
6. How does risk-parity sizing calculation work in their implementation?
7. What's the exact overfit penalty formula in OOS validation?

### Evaluation Framework
8. How are crisis scenarios parameterized and injected into backtests?
9. What's the composite scoring function? (weights for Sharpe, DD, turnover, etc.)
10. How does RSS sentiment feed integrate with factor models?
11. What's the Research DAG structure and how do ML insights bias mutations?

### Implementation Feasibility
12. Which components can be implemented in v5.1 without breaking existing contracts?
13. What requires new subsystems vs. extending existing ones (Hermes, Strategy Lab)?
14. Are there security risks in AutoQuant's black-box approach we must avoid?

---

## Proposed QuantSpace Architecture (Preliminary)

### Layer 1: Macro Regime Detector
- **Jarvis mapping:** Hermes research daemon + eval profile
- **Function:** Detect market regimes (bull/bear/sideways, high/low vol)
- **Output:** Regime classification with confidence scores
- **Review gate:** Must pass regime detection accuracy validation before use

### Layer 2: Sector Rotation Engine
- **Jarvis mapping:** Strategy Lab experiment with sector momentum factors
- **Function:** Rank sectors by relative strength, rotation signals
- **Output:** Sector allocation weights per regime
- **Review gate:** Sector concentration limits enforced as veto check

### Layer 3: Alpha Factor Scoring
- **Jarvis mapping:** Core Strategy Lab run with factor mutation loop
- **Function:** Score assets using evolved factor model
- **Mutation mechanism:** Explicit task envelopes with bounded parameter sweeps
- **Review gate:** Factor importance must be interpretable, no black-box weights

### Layer 4: Adversarial Risk Officer (as Review Gate)
- **Jarvis mapping:** Anton risk review lane + emergency controls
- **Function:** Veto trades violating risk constraints
- **Implementation:** Policy-visible veto checks in eval profiles
- **Review gate:** Risk Officer decisions logged and auditable, not hidden autonomy

### Swarm Mechanism Replacement
- **Instead of 135 autonomous agents:** Explicit task queue with dependency tracking
- **Instead of Darwinian selection:** Candidate promotion based on eval profile scores
- **Instead of cross-pollination:** Shared experiment registry with provenance tracking
- **Safety:** All mutations bounded by task envelopes, no hidden state reinjection

---

## Implementation Roadmap (Proposed)

### Phase 1: Foundation (Week 1-2)
- [ ] Define QuantSpace program file template
- [ ] Implement crisis stress testing eval profile
- [ ] Build OOS validation framework with overfit penalty
- [ ] Create baseline backtest harness (8-factor equal-weight)

### Phase 2: Factor Evolution Loop (Week 3-4)
- [ ] Design factor mutation operators (weights, inclusion/exclusion)
- [ ] Implement bounded parameter sweep task envelopes
- [ ] Build candidate diversity map tracking
- [ ] Create recommendation.json generator

### Phase 3: Risk Officer Integration (Week 5)
- [ ] Define risk veto checks in eval profiles
- [ ] Implement position sizing constraints (risk-parity baseline)
- [ ] Build trade-level review gate with audit trail
- [ ] Add emergency control integration for risk breaches

### Phase 4: Advanced Features (Week 6+)
- [ ] RSS sentiment feed integration (Hermes research daemon)
- [ ] Cross-domain learning via Research DAG (if ML insights available)
- [ ] Multi-regime regime detection with Hermes
- [ ] Composite scoring optimization for crisis resilience

### Phase 5: Safety & Review Integration (Ongoing)
- [ ] All outputs as candidates until promoted
- [ ] Explicit review policies for each layer
- [ ] Emergency controls testable and externally enforceable
- [ ] Replay-to-eval loop for failures

---

## Security & Safety Considerations

### AutoQuant Risks to Avoid
1. **Black-box autonomy:** No hidden state reinjection loops
2. **Unreviewed production writes:** All changes through promotion spine
3. **Silent model switching:** Explicit override exception path with logging
4. **Overfitting:** OOS validation + overfit penalty as hard veto
5. **Crisis blindness:** Stress testing as required eval profile, not optional
6. **Uninterpretable factors:** Factor importance must be explainable
7. **Risk Officer bypass:** Veto checks policy-visible, not agent-hidden

### Jarvis v5.1 Safeguards to Enforce
- Every mutation bounded by task envelope with explicit constraints
- All candidate strategies require eval profile pass before promotion
- Risk Officer decisions logged in RunTrace for auditability
- Emergency controls externally enforceable (not agent-dependent)
- Diversity map prevents strategy collapse into single pattern
- Memory consolidation produces candidates, not direct truth

---

## Next Steps

1. **Complete research:** Fill gaps in factor model details and mutation rules
2. **Design program file:** Create QuantSpace template with objectives/constraints/vetoes
3. **Map to v5.1 contracts:** Ensure all outputs fit TaskRecord/ArtifactRecord schemas
4. **Build MVP:** Implement Phase 1 foundation before adding complexity
5. **Review gate design:** Define explicit policies for each layer's promotion
6. **Safety audit:** Verify no black-box autonomy slips through

---

## Open Questions for Operator

- Do you want to implement the full 4-layer pipeline, or start with a subset?
- Should the Risk Officer be fully autonomous within bounds, or require explicit review per trade?
- How much of AutoQuant's swarm mechanics do we want vs. replacing with explicit task queues?
- What's our tolerance for black-box factor combinations vs. requiring full interpretability?
- Do you have access to RSS feed APIs and historical market data for backtesting?

---

**Researcher Notes:**  
*AutoQuant is impressive but risky as a reference — their swarm approach found good results but could also find spurious ones. Our job is to keep the exploration power while adding Jarvis v5.1's safety rails. The key insight: parsimony won, so our implementation should favor simple, interpretable factor models over complex black-box ensembles.*

**Status:** Awaiting operator direction on scope and priorities.
