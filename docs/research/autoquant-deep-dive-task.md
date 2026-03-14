# AutoQuant Deep-Dive Research Task
## Pure Autonomy Mode — No Review Gates, Just Exploration

**Status:** Ready to Execute  
**Mode:** Autonomous research (no review gates)  
**Reference:** Jarvis v5.1 Strategy Lab as fallback only  
**Goal:** Understand AutoQuant's black-box autonomy and assess feasibility

---

## Research Objective

Conduct deep-dive investigation into AutoQuant's architecture, mechanics, and results to determine:
- What's real implementation vs. marketing fluff
- Which components are feasible to replicate
- Whether the "black-box swarm" approach is actually viable or just lucky
- How much of this we can steal for our own quant research system

**Key constraint:** No review gates blocking exploration. Let the research run autonomous and see what emerges.

---

## Investigation Areas

### 1. Architecture Deep-Dive

#### The 4-Layer Pipeline (AutoQuant's Core)
- **Layer 1: Macro Regime Detection**
  - What signals define regimes?
  - How are regime transitions detected?
  - Confidence scoring mechanism
  
- **Layer 2: Sector Momentum Rotation**
  - Sector ranking methodology
  - Rotation triggers and timing
  - Concentration limits (if any)
  
- **Layer 3: Alpha Factor Scoring**
  - The exact 8 starting factors (names, formulas, data sources)
  - How factors are scored and combined
  - Weight evolution mechanism
  
- **Layer 4: Adversarial Risk Officer**
  - Veto criteria and thresholds
  - Low-conviction trade definition
  - How it differs from traditional risk management

#### Swarm Mechanics
- **135 agents:** How are they instantiated? What's each agent's state?
- **Mutation operators:** Exact formulas for:
  - Factor weight mutations (random walk? Gaussian? gradient-based?)
  - Position sizing mutations
  - Risk control mutations
- **Darwinian selection:** Fitness function, selection pressure, elitism rate
- **Cross-pollination:** How do discoveries propagate between agents?
- **Communication protocol:** Shared memory? Message passing? File-based?

#### Evolution Dynamics
- **Layer weight evolution:** How do Macro/Sector/Alpha/Risk weights change?
- **30 mutations per round:** Selection process, competition mechanism
- **Convergence timeline:** When did they hit Sharpe 1.32? How many rounds?
- **Parsimony emergence:** Why did simpler portfolios win? Statistical evidence?

### 2. Implementation Mechanics (Reverse-Engineering)

#### Factor Model Details
- **8-factor composition:**
  - Value factors (which ones?)
  - Momentum factors (which ones?)
  - Quality factors (which ones?)
  - Size factors (if any)
  - Low-volatility factors (if any)
  - Dividend/growth/trend (the ones they dropped — why exactly?)
- **Factor calculation:** Source data, lookback periods, normalization
- **Weight initialization:** Equal-weight starting point
- **Mutation rules:** Exact mathematical formulation

#### Position Sizing Evolution
- **Risk-parity sizing:** How is it calculated?
  - Covariance matrix estimation method
  - Target volatility scaling
  - Constraints (leverage limits, concentration caps)
- **Sizing mutation:** How do agents evolve from equal-weight to risk-parity?

#### Crisis Stress Testing
- **Scenario parameterization:**
  - GFC '08: Which assets crashed? What signals triggered it?
  - COVID '20: Flash crash mechanics, recovery patterns
  - 2022 rate hikes: Duration of stress, regime shift detection
  - Flash crash: Event definition, detection threshold
  - Stagflation: Inflation + growth signals, portfolio response
- **Stress injection:** How are scenarios injected into backtests?
- **Resilience scoring:** Composite metric for crisis performance

#### OOS Validation & Overfit Penalty
- **70/30 split:** Exact methodology (time-based? random?)
- **Overfit penalty formula:** Mathematical specification
  - Is it a penalty term in the objective function?
  - How is overfitting detected?
  - Threshold for triggering penalty
- **Validation frequency:** When does OOS check occur during evolution?

#### RSS Sentiment Integration
- **Feed sources:** Which RSS feeds? Financial news? Social media?
- **Sentiment extraction:** NLP method (rule-based? ML model?)
- **Factor integration:** How does sentiment bias factor scores?
  - Weight adjustment mechanism
  - Threshold for sentiment-driven trades
- **Temporal dynamics:** How quickly does sentiment affect positions?

#### Cross-Domain Learning & Research DAG
- **Research DAG structure:** Nodes, edges, data flow
- **ML insights:** What ML models are used? What insights do they generate?
- **Bias mechanism:** How do non-finance insights bias finance mutations?
  - Example: Computer vision pattern recognition applied to price charts?
- **Cross-pollination protocol:** When and how does cross-domain learning trigger?

### 3. Results Analysis (Statistical Evidence)

#### Factor Pruning Discovery
- **Dividend factor:** Why was it dropped? Performance metrics before/after
- **Growth factor:** Same analysis
- **Trend factor:** Same analysis
- **Statistical significance:** Is the improvement real or noise?
- **Regime dependence:** Did these factors work in some regimes but not others?

#### Risk Parity Adoption
- **Performance comparison:** Equal-weight vs. risk-parity over full history
- **Drawdown analysis:** How did risk-parity reduce max DD from X% to 5.5%?
- **Turnover impact:** Did risk-parity increase or decrease trading frequency?
- **Stability metrics:** Factor weight volatility before/after adoption

#### Convergence Analysis
- **Timeline:** How many rounds until Sharpe 1.32 was reached?
- **Agent diversity:** Did all agents converge to same solution, or multiple paths?
- **Early failures:** What bad strategies were tried and rejected?
- **Critical discoveries:** Which agent made the key breakthroughs?

### 4. Feasibility Assessment

#### Data Requirements
- **Market data sources:** Which providers? Historical depth required?
- **Factor calculation data:** Where do factor values come from?
- **RSS feed access:** Do they have paid API access or free feeds?
- **Crisis scenario data:** How are historical crises parameterized?
- **Cost estimate:** What's the data budget for replication?

#### Compute Requirements
- **135-agent swarm:** CPU hours per round? Parallelization strategy?
- **Backtest engine:** Vectorized? Event-driven? Custom simulator?
- **ML model training:** If using ML for sentiment/DAG, what models?
- **Cloud vs. local:** Can this run on consumer hardware or needs cluster?

#### Implementation Complexity
- **High-complexity components:**
  - Cross-domain learning (Research DAG)
  - RSS sentiment integration (NLP pipeline)
  - Adaptive regime detection (ML-based?)
- **Medium-complexity components:**
  - Factor mutation operators
  - Risk-parity sizing calculation
  - Crisis stress testing framework
- **Low-complexity components:**
  - Basic backtest harness
  - OOS validation split
  - Sharpe/DD metric calculation

#### Security/Safety Implications
- **Black-box risks:** What happens when agents find spurious patterns?
- **Overfitting danger:** How likely is the swarm to overfit to historical noise?
- **Crisis blindness:** Can autonomous exploration miss tail risks?
- **Uninterpretable strategies:** If a strategy works but we can't explain why, do we trust it?
- **Autonomy vs. control:** Where do we draw the line on agent freedom?

### 5. Jarvis Integration Potential

#### Features Worth Stealing (High Priority)
1. **Crisis stress testing framework** — essential for robust quant research
2. **OOS validation with overfit penalty** — prevents curve-fitting
3. **Factor pruning discovery process** — lets agents find parsimonious models
4. **Risk-parity sizing evolution** — proven improvement over equal-weight
5. **Composite scoring for resilience** — optimizes for real-world performance

#### Features Requiring Jarvis Constraints (Medium Priority)
1. **Review gates on high-conviction trades** — prevent catastrophic errors
2. **Factor interpretability requirements** — no black-box factor combinations
3. **Emergency controls integration** — externally enforceable kill switches
4. **Candidate promotion policy** — all strategies reviewed before deployment
5. **Diversity map enforcement** — prevent strategy collapse into single pattern

#### Features to Reject or Modify (Low Priority)
1. **Pure black-box autonomy** — too risky without safety rails
2. **Hidden state reinjection loops** — violates Jarvis v5.1 principles
3. **Silent model-family switching** — requires explicit override path
4. **Unreviewed production writes** — all changes must go through promotion spine
5. **Agent communication without audit trail** — every discovery must be logged

#### Recommended Hybrid Approach
- **Autonomy layer:** Let agents explore factor combinations, sizing strategies, risk controls freely within bounded task envelopes
- **Safety layer:** Implement explicit review gates for:
  - High-leverage trades (>X% portfolio)
  - Strategies with Sharpe > Y (potential overfitting signal)
  - Any strategy that violates hard constraints (max DD, turnover limits)
- **Audit trail:** Every agent action logged to RunTrace with full provenance
- **Emergency controls:** Externally enforceable kill switch for risk breaches
- **Interpretability requirement:** All promoted strategies must have explainable factor logic

---

## Research Output Requirements

### Deliverables
1. **Comprehensive research report** (this document + appendices)
2. **Code snippets/examples** where available (AutoQuant repo if public, or equivalent implementations)
3. **Feasibility matrix:** What's easy/medium/hard to implement
4. **Data source recommendations:** Where to get market data, RSS feeds, factor values
5. **Compute estimates:** Hardware requirements for 135-agent swarm
6. **Risk assessment:** Security/safety implications of autonomous exploration
7. **Implementation roadmap:** Phased approach with milestones
8. **Recommendation:** Full AutoQuant implementation vs. selective adoption vs. reject

### Format
- Markdown document with clear sections
- Code blocks for any implementations found
- Tables for comparison matrices
- Charts/graphs if available (convergence plots, performance comparisons)
- Links to all sources consulted

---

## Execution Notes

**Mode:** Pure autonomy research — no review gates blocking the investigation  
**Reference:** Jarvis v5.1 Strategy Lab as fallback only (not constraints)  
**Goal:** Understand AutoQuant's black-box approach and assess viability  
**Output:** Clear recommendations on whether to pursue full implementation or selective adoption

**Key question to answer:** Is AutoQuant's success real or spurious? Can we replicate it without the risks?

---

## Researcher Notes

*AutoQuant is impressive but potentially dangerous as a reference. Their swarm approach found good results (Sharpe 1.32, 5.5% max DD) but could also find equally spurious patterns that look good in-sample and fail out-of-sample. Our job is to separate signal from noise, understand what's real implementation vs. marketing fluff, and decide what's worth stealing for our own system.*

*The key insight from their results: parsimony won. Simpler portfolios outperformed complex ones. This suggests we should favor interpretable factor models over black-box ensembles, even if the swarm discovers them autonomously.*

**Status:** Ready to execute research task  
**Expected duration:** 2-4 hours for deep-dive investigation  
**Dependencies:** Access to AutoQuant blog post, any public code repos, financial data sources
