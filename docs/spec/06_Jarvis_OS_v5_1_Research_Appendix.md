# Jarvis OS v5.1 Research Appendix

## Included high-value external signals
### Agent Skills
Portable skills with `SKILL.md` are now an open standard, and VS Code has moved beyond skills into plugin bundles that package skills, tools, and hooks.
Implication: Jarvis should separate portable skills from installable plugins.

### MCP and authorization
MCP now has explicit authorization guidance centered on OAuth 2.1 and is mature enough to be the preferred external tool interface direction.
Implication: prefer MCP, but gate adoption on authorization and conformance.

### A2A
A2A has become a real interoperability direction for agent-to-agent interaction.
Implication: make Hermes/Jarvis contracts A2A-shaped without fully protocol-locking v5.1.

### Sleep-time compute / memory consolidation
Recent memory work emphasizes asynchronous consolidation during downtime.
Implication: Ralph should consolidate memory, not only run queued tasks.

### OTel GenAI and MCP semantic conventions
OpenTelemetry now has meaningful GenAI semantic conventions and MCP-specific semantic work.
Implication: align RunTrace naming now even if storage remains local in v5.1.

### OWASP agentic guidance
OWASP now treats agentic security as a mature threat model with practical guidance.
Implication: validate.py / doctor.py should evolve toward trustworthiness and security validation, not just config validation.

### Provenance / attestations
Software supply chain norms are moving toward provenance and attestations.
Implication: promoted artifacts should be attestation-ready even before v5.1 adopts full cryptographic attestations.

### Replay-to-eval
Production agent debugging increasingly treats traces as the raw material for regression evals.
Implication: important failures should be replayable and convertible into eval fixtures.

### Qwen3.5 refresh
The current Qwen lineup is stronger for a Qwen-first OS than earlier assumptions suggested.
Implication: refresh the routing table and keep multimodal work in the Qwen3.5 family by default.

### Discord operational changes
Discord permission splits and voice encryption requirements changed recently.
Implication: validate.py should check current permission needs where relevant, and Discord voice work should remain deferred and explicitly planned rather than assumed.

## Explicit non-adoptions
The rebuild intentionally does **not** adopt:
- Letta/MemGPT as infrastructure
- graph databases
- Qwen-Agent as control-plane infrastructure
- OpenHands / LangGraph / Temporal as core runtime dependencies
- full A2A protocol commitment
- full OTel backend rollout
