# Jarvis OS v5.1 Rebuild Design Notes

## 1. What changed from the prior package
This rebuild tightens the package around the parts that were still soft:
- north star is now explicit
- dependency blocking is explicit
- demotion/revocation is explicit
- emergency controls are first-class
- promotion provenance is explicit
- replay-to-eval is explicit
- notification adapters and operator profiles are explicit
- trajectory collection is explicit
- skills vs plugins are separated
- trustworthiness validation is a named section

## 2. Why the rebuild still keeps the locked v5 backbone
The locked v5 spec already got the hardest product decisions right:
- explicit task creation
- durable task/event/artifact state
- review and approval lanes
- Flowstate as a compression lane
- deployment validation as part of the product
- Qwen-first doctrine

The rebuild does not replace those choices.
It closes operational gaps around stoppability, reversibility, visibility, and upgrade pressure.

## 3. Research-backed changes worth keeping
### 3.1 Agent Skills
The ecosystem is converging on portable skill folders with `SKILL.md` manifests.
That makes skills a low-cost portability win.
The rebuild treats skills as portable capability folders and plugins as broader installable bundles.

### 3.2 MCP and A2A
The tooling stack is converging on a layered pattern:
- MCP for agent-to-tool interaction
- A2A-style contracts for agent-to-agent interaction

The rebuild adopts MCP as the preferred tool interface direction and makes Hermes/Jarvis interfaces A2A-aware without fully protocol-locking v5.1.

### 3.3 Sleep-time compute / memory consolidation
The Ralph consolidation pass borrows the right concept from the recent sleep-time compute / reflection work without adopting another framework.
The important idea is asynchronous memory reorganization during downtime.
Ralph already has the right place in the architecture to do this.

### 3.4 Provenance and attestations
Software supply chain practice is converging on provenance and attestations.
Jarvis does not need full cryptographic attestations in v5.1, but it should be attestation-ready.
That is why PromotionProvenance exists.

### 3.5 OTel naming alignment
OpenTelemetry now has GenAI semantic conventions and even MCP-specific semantic work.
That makes it worth aligning naming now, even if v5.1 still stores traces locally.

### 3.6 Replay-to-eval
Production agent teams are increasingly using trace replay to generate regression evals.
Jarvis needs the same loop because Hermes, browser automation, and voice all introduce multi-step failures that are hard to debug from final outputs alone.

### 3.7 OWASP agentic guidance
OWASP’s agentic and GenAI guidance is now mature enough that prompt injection, unsafe tool output handling, excessive agency, and exfiltration risk should be explicit validation targets rather than vague security aspirations.

## 4. Why Hermes is still a subsystem, not the face
Hermes is valuable because it already has:
- persistent working memory
- browser and terminal tools
- scheduling and long-running task support
- multi-surface gateway patterns
- a skill system
- multiple runtime backends

Those strengths are also why it should not become Jarvis’s primary identity.
If Hermes becomes the face:
- task IDs split
- approvals split
- memory truth splits
- operator mental model gets noisy
- lane discipline degrades

So Hermes stays the research daemon under Jarvis control.

## 5. Why autoresearch is still the lab daemon
autoresearch is strongest when:
- the editable surface is small
- the budget is fixed
- the eval is clear
- the objective is narrow
- the output is comparative

That fits Strategy Factory extremely well.
It does not fit general orchestration well.

The key design choice is to preserve the fixed-budget experiment pattern and use program files as the leverage point.

## 6. Why candidate-first promotion remains rule #1
Without candidate-first promotion:
- Hermes research can bypass review
- Flowstate ideas can leak into memory
- voice extraction can become accidental execution
- autoresearch patches can become trusted too early
- browser actions can quietly change state without attribution
- Ralph consolidation can pollute memory

Candidate-first promotion is the seam that keeps every subsystem subordinate.

## 7. Why demotion/revocation had to be added
Promotion-only systems accumulate bad truth.
For quant and research-heavy workflows, this is fatal.
A wrong promoted Flowstate artifact, research claim, or strategy conclusion must be revocable.
That is why the rebuild adds demotion, revocation, and impacted-downstream tracking.

## 8. Why emergency controls are a hard requirement
Approvals and budgets are not enough.
Ralph, Hermes, browser automation, and voice all create paths for runaway behavior or runaway cost.
Emergency controls must live outside agent reasoning and must not require model cooperation.

That is why the rebuild adds:
- a global kill switch
- per-subsystem circuit breakers
- budget hard-stop auto-pause

## 9. Why north star had to become explicit
Without an explicit north star, the system can collect features that feel impressive but do not improve the product.
The right north star is not “maximum autonomy.”
It is useful, reviewable, low-drift execution.

## 10. Why dependency blocking matters
The previous package had resumable approvals but did not say what happened to downstream tasks during pending approvals.
That omission would create hidden queue drift overnight.
The rebuild adds explicit dependency blocking and candidate-only speculative precompute rules.

## 11. Why the memory doctrine needed more structure
The earlier draft had the right memory philosophy but not enough operating detail.
The rebuild adds:
- content classes
- structural memory types
- a memory matrix
- a compression gate
- decay and contradiction policy

This is still intentionally lighter than adopting a whole memory framework.
The goal is memory doctrine, not infrastructure sprawl.

## 12. Why skills and plugins are separate concepts
The broader ecosystem is now distinguishing:
- portable skills
- installable bundles that package skills, tools, and hooks

Treating them as the same thing would make policy too coarse.
Jarvis should keep skill portability while gating plugin installation more strictly.

## 13. Why browser automation is still browser-first
This rebuild keeps desktop control out of initial v5.1 scope.
Browser automation is:
- easier to sandbox
- easier to replay
- easier to evaluate
- easier to explain
- closer to structured tool use

Desktop-wide control is still a larger research and safety surface.

## 14. Why Qwen routing had to be refreshed
The Qwen lineup changed enough that the old routing assumptions were stale.
The released Qwen3.5 family is much better for a Qwen-first architecture than the earlier dense-model assumptions suggested.
That is why the rebuild refreshes the routing table and explicitly treats Qwen3.5 as the multimodal default family while keeping Qwen3-Coder-Next for the code lane.

## 15. Why notification adapters and operator profiles matter now
Jarvis still behaves like a single-operator OS, but structuring approvals, controls, and notifications around operator IDs and adapters now will be much cheaper than retrofitting it later.
This is one of the easiest future-proofing wins in the package.

## 16. Why trajectory collection is included but constrained
Trajectory data could become very valuable for future Qwen tuning or evaluation.
But trajectory collection can also become a privacy and memory mess.
So the rebuild permits deliberate trajectory collection while explicitly requiring linkage, redaction capability, and policy awareness.

## 17. What the rebuild still refuses to do
The rebuild still refuses to:
- replace Jarvis with Hermes
- make autoresearch a public bot
- add graph databases prematurely
- add new orchestration frameworks for prestige
- over-promise phone/desktop autonomy in v5.1
- weaken review and approval rules for convenience

## 18. Practical rule of thumb for implementation agents
If an implementation choice makes the system:
- less stoppable
- less attributable
- less reversible
- less reviewable
- more hidden

then it is probably wrong for v5.1 even if it looks clever.
