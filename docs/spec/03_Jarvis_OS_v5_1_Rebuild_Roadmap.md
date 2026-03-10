# Jarvis OS v5.1 Rebuild Roadmap

## 1. Release philosophy
Ship the control seams first.
Do not start with voice, desktop automation, or “cool agent” behavior.
Start with the parts that make the system structurally safe and extendable.

## 2. Milestone order
### Milestone 0 — Freeze scope and contracts
Deliverables:
- lock rebuild spec
- lock north star and guardrails
- lock schema versioning rule
- lock candidate-first promotion and demotion rule
- lock Qwen routing table
- lock release scope vs deferred scope

Exit condition:
- no open ambiguity on core seams

### Milestone 1 — Task spine refresh
Deliverables:
- `execution_backend` on TaskRecord
- `schema_version` on all core records
- candidate lifecycle states including demotion
- provenance metadata skeleton
- multi-operator-ready IDs
- task envelope model
- dependency blocking fields

Exit condition:
- core state can express backend work safely and reversibly

### Milestone 2 — Control spine
Deliverables:
- global kill switch
- subsystem circuit breakers
- budget hard-stop auto-pause
- DegradationPolicy lifecycle
- visible control-state reporting
- phone-friendly stop path design

Exit condition:
- autonomy can be stopped without agent cooperation

### Milestone 3 — Approval/resume refresh
Deliverables:
- resumable checkpoints
- approval timeout behavior
- dependency blocking behavior
- demotion / revocation flows
- reviewer outage behavior

Exit condition:
- review/approval is resumable, explicit, and reversible

### Milestone 4 — Hermes adapter
Deliverables:
- HermesTaskRequest / HermesTaskResult
- Hermes backend mapping to sandbox classes
- timeout / retry / unreachable behavior
- Qwen parser/tool-call compatibility tests
- policy-visible fallback behavior
- Hermes working-memory boundary rules

Exit condition:
- Hermes runs as a subordinate backend with durable trace and event visibility

### Milestone 5 — Eval and trace foundation
Deliverables:
- EvalProfile lifecycle
- EvalOutcome lifecycle
- RunTrace storage
- OTel-aware field naming
- replay-to-eval starter loop
- trajectory collection decision points

Exit condition:
- important work is traceable and evaluable

### Milestone 6 — Strategy Lab
Deliverables:
- LabRunRequest / LabRunResult
- S3 sandbox runner
- program file template
- frozen benchmark slice support
- diversity map scaffolding
- candidate patch artifact flow

Exit condition:
- autoresearch can contribute bounded strategy experiments without touching production directly

### Milestone 7 — Ralph consolidation
Deliverables:
- candidate digest generation
- memory class/type support
- memory decay/contradiction fields
- memory matrix
- compression gate
- consolidation pass rules
- baseline update summaries

Exit condition:
- autonomy windows improve memory quality rather than only burning tokens

### Milestone 8 — Voice v1/v2
Deliverables:
- dictation path
- conversational voice session manager
- transcript + summary artifacts
- explicit task confirmation in voice
- voice evals
- notification adapter compatibility

Exit condition:
- voice is a real front door without bypassing task policy

### Milestone 9 — Browser automation
Deliverables:
- bounded browser runner
- task-envelope enforcement
- screenshot capture
- replayable browser traces
- browser evals
- manual confirmation on sensitive actions

Exit condition:
- browser control is useful, scoped, and reversible

### Milestone 10 — Hardening
Deliverables:
- validate.py expansion
- doctor.py expansion
- security/trustworthiness checks
- skill/plugin approval flow
- MCP authorization/conformance checks
- provenance completeness checks

Exit condition:
- deployment catches the obvious ways the OS can fail

## 3. Acceptance gates
### Structural gates
- every execution-bearing task carries backend metadata
- candidate-first promotion is enforced everywhere
- demotion/revocation is enforced everywhere
- all core records are versioned
- kill switch and circuit breakers are externally enforceable

### Hermes gates
- Hermes cannot become system-of-record
- Hermes outputs land as candidates
- Hermes timeouts and failures create structured events
- Hermes uses approved Qwen endpoints and passes compatibility tests

### Strategy Lab gates
- no direct production writes
- baseline refs are explicit
- benchmark slice refs are explicit
- evals include veto checks and quality metrics
- diversity map is populated for promoted strategies

### Memory gates
- promoted memories pass the compression/type gate
- Ralph consolidation produces candidates, not direct truth
- contradiction and decay fields exist
- retrieval remains artifact-linked and reversible

### Voice/browser gates
- voice cannot silently create risky work
- browser actions are scoped by task envelope
- sensitive actions require confirmation
- traces and screenshots exist for major runs

### Hardening gates
- validate.py catches config, model, permission, and gateway issues
- doctor.py reports degradation, budgets, and controls
- emergency controls are testable
- replay-to-eval can create at least one permanent regression case

## 4. Codex / implementation-agent instructions
When implementing from this package:
1. Treat the Spec as authoritative.
2. Do not reopen locked doctrine unless the implementation is blocked.
3. Prefer the smallest change that preserves the spec’s seams.
4. Preserve candidate-first promotion above convenience.
5. Do not add new frameworks unless explicitly requested.
6. Do not silently keep v4 architecture just because it still runs.
7. When uncertain, choose explicit schemas over hidden agent magic.
8. When uncertain, choose reversible behavior over clever autonomy.
9. Always update structured state instead of inferring from chat.
10. Always keep Qwen-family routing and policy visible.
11. If a subsystem seems to need a direct shortcut into truth, stop and redesign the seam.

## 5. Practical first build order
1. task spine + schema versioning
2. candidate/demotion lifecycle
3. emergency controls + budgets
4. resumable approvals + dependency blocking
5. Hermes adapter
6. eval/trace/replay foundation
7. Strategy Lab
8. Ralph consolidation
9. voice
10. browser automation
11. hardening
