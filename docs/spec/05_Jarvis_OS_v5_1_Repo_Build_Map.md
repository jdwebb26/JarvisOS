# Jarvis OS v5.1 Repo Build Map

## Purpose
This document maps the rebuild spec to likely repo locations and legacy files that need isolation or replacement.

## 1. Core target modules
### runtime/core/models.py
Add or refresh:
- TaskRecord
- TaskEvent
- ArtifactRecord
- TokenBudget
- DegradationPolicy
- RunTrace
- PromotionProvenance
- MemoryEntry

### runtime/core/routing.py
Add or refresh:
- backend selection
- model lane selection
- dependency blocking decisions
- model override exception handling

### runtime/core/execution.py
Add or refresh:
- task envelope enforcement
- autonomy mode handling
- control-state checks before every step
- candidate lifecycle writes

### runtime/auditor/models.py
Add or refresh:
- ReviewVerdict
- ApprovalRecord
- resumable checkpoint refs
- demotion / revocation actions

### runtime/reporter/
Add or refresh:
- HealthSummary
- TaskStatusSummary
- ApprovalQueueSummary
- AutonomyDigest
- DegradationSummary

### runtime/flowstate/
Add or refresh:
- FlowstateSource
- FlowstateDistillation
- PromotionProposal
- demotion path for promoted distillations

### runtime/integrations/hermes_adapter.py
Create:
- HermesTaskRequest / HermesTaskResult handling
- backend mapping
- timeout/retry/fallback rules
- Qwen tool-call compatibility tests

### runtime/integrations/autoresearch_adapter.py
Create:
- LabRunRequest / LabRunResult handling
- Strategy Lab run orchestration
- artifact registration

### runtime/researchlab/
Create or refresh:
- runner.py
- policies.py
- programs/
- baseline management
- diversity map support

### runtime/controls/
Create or refresh:
- kill switch
- circuit breakers
- budget hard-stop auto-pause
- control-state storage

### runtime/voice/
Create or refresh:
- session manager
- transcript normalizer
- task confirmation path
- summary artifact creation

### runtime/browser/
Create or refresh:
- bounded browser runner
- screenshot capture
- sensitive-action confirmation
- replayable trace hooks

### scripts/validate.py
Expand checks for:
- current model names
- gateway bind posture
- budgets and control availability
- Discord permission splits where relevant
- plugin/skill approval posture
- MCP auth posture
- unsafe fallback/degradation conditions

### scripts/doctor.py
Expand summaries for:
- control-state
- degradation-state
- approval blockers
- budgets
- replay/eval status

## 2. Legacy files likely needing isolation or replacement
### hyperloop.py
Current issues:
- old swarm framing
- CrewAI council-style review loop
- file-lock based control pattern
- reinjection semantics outside structured state

Expected v5.1 action:
- isolate as legacy compatibility or replace with structured Ralph service

### permissions.py
Current issues:
- command-role gating is useful but still framed around older swarm command surface

Expected v5.1 action:
- preserve useful permission logic but align with explicit task/control/approval actions

### memory.py
Current issues:
- storage plumbing may not reflect final memory doctrine
- likely lacks full class/type matrix, contradiction handling, and demotion rules

Expected v5.1 action:
- wrap or replace with memory-spine logic matching the new record model

### tools.py
Current issues:
- likely still too permissive relative to sandbox classes and task envelopes

Expected v5.1 action:
- align tool execution with sandbox and control policies

### setup.sh and runtime branding
Current issues:
- any lingering “swarm” framing is architectural drift

Expected v5.1 action:
- rename and reframe around Jarvis OS control plane

## 3. Minimum first-pass file sequence
1. models.py
2. auditor models and checkpoints
3. controls module
4. routing/execution changes
5. Hermes adapter
6. eval/trace layer
7. autoresearch adapter
8. Ralph/memory refresh
9. voice
10. browser
11. validate/doctor
