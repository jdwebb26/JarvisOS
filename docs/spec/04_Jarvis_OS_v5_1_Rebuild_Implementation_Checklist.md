# Jarvis OS v5.1 Rebuild Implementation Checklist

## Read first
- [ ] Read `01_Jarvis_OS_v5_1_Rebuild_Spec.md`
- [ ] Read `02_Jarvis_OS_v5_1_Rebuild_Design_Notes.md`
- [ ] Read `03_Jarvis_OS_v5_1_Rebuild_Roadmap.md`
- [ ] Read `05_Jarvis_OS_v5_1_Repo_Build_Map.md`
- [ ] Confirm the release scope is v5.1, not v5.2+

## Core contracts
- [ ] Add `schema_version` to TaskRecord, TaskEvent, ArtifactRecord, ReviewVerdict, ApprovalRecord, MemoryEntry
- [ ] Add `execution_backend` to TaskRecord
- [ ] Add candidate lifecycle states including demotion
- [ ] Add `provenance_ref` to ArtifactRecord
- [ ] Add `operator_id` support
- [ ] Add schema defaults for forward compatibility

## Controls and budgets
- [ ] Implement global kill switch
- [ ] Implement per-subsystem circuit breakers
- [ ] Implement budget hard-stop auto-pause
- [x] Add TokenBudget record
- [x] Add DegradationPolicy record
- [ ] Check controls before every task step and autonomy cycle

## Dependency blocking and reversibility
- [x] Add blocked-dependency status and blocker references
- [x] Define speculative candidate-only downstream behavior
- [x] Implement demotion path for artifacts
- [x] Implement revocation path for memory entries
- [x] Mark impacted downstream artifacts when upstream sources are revoked

## Hermes
- [x] Implement HermesTaskRequest
- [x] Implement HermesTaskResult
- [ ] Map Hermes backends to sandbox classes
- [ ] Enforce approved Qwen endpoints only
- [ ] Validate Qwen tool-call/parser compatibility
- [ ] Emit structured events for start, checkpoint, timeout, completion, failure

## Strategy Lab / autoresearch
- [x] Implement LabRunRequest
- [x] Implement LabRunResult
- [ ] Preserve fixed-budget run pattern
- [ ] Enforce S3 sandbox
- [ ] Require program file template
- [x] Require `baseline_ref` and `benchmark_slice_ref`
- [ ] Store required lab outputs
- [x] Add diversity map scaffolding

## Review and approvals
- [x] Add resumable checkpoint references
- [x] Define dependent-task behavior under pending approval
- [x] Ensure reviewer outages do not auto-promote review-required work
- [ ] Implement model-override exception logging

## Memory and Ralph
- [x] Add memory classes and structural types
- [x] Add confidence/decay/contradiction fields
- [ ] Implement memory compression gate
- [x] Implement Ralph consolidation pass
- [x] Ensure consolidation creates candidates, not direct truth
- [ ] Add memory matrix policy

## Eval and trace
- [x] Implement EvalProfile
- [x] Implement EvalOutcome
- [ ] Separate veto checks from quality metrics
- [x] Implement RunTrace
- [ ] Align field naming with OTel GenAI where practical
- [x] Add replay-to-eval path for important failures
- [ ] Decide trajectory collection path and redaction rules

## Voice and browser
- [ ] Implement V1 dictation
- [ ] Implement V2 conversational voice
- [ ] Persist transcript + summary artifacts
- [ ] Require explicit task confirmation for voice tasking
- [ ] Implement bounded browser automation
- [ ] Enforce task envelopes
- [ ] Capture screenshots where practical
- [ ] Require confirmation for sensitive browser actions

## Security and validation
- [ ] Enforce localhost-only gateway default
- [ ] Require approval for external skills/plugins
- [ ] Scope and expire tokens where supported
- [ ] Add validation checks for injection, exfiltration, unsafe fallback, and MCP auth posture
- [ ] Expand validate.py
- [ ] Expand doctor.py

## Multi-surface and operators
- [ ] Add notification adapter interface
- [ ] Add operator_id to task, approval, and control actions
- [ ] Keep Discord-first UX while avoiding Discord-only internals

## Cleanup
- [ ] Remove or isolate v4 swarm assumptions
- [ ] Remove direct memory writes from arbitrary chains
- [ ] Stop treating chat scrollback as state
- [ ] Update setup/runtime language away from “swarm”

## Done criteria
- [x] Candidate-first promotion is enforced across all subsystems
- [x] Demotion/revocation works across memory and artifacts
- [ ] Emergency controls work without agent cooperation
- [x] Hermes and autoresearch run behind explicit contracts
- [ ] Ralph improves memory quality during autonomy windows
- [ ] Voice/browser are scoped and reviewable
- [ ] No major v4 architectural drift remains in the main path
