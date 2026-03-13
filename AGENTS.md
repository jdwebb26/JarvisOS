# Jarvis v5 -> v5.1 upgrade instructions

This repository is the current Jarvis v5 codebase.

Your job is to upgrade this existing repo in place toward the Jarvis OS v5.1 target.

Do not:
- start a new project
- create a separate v5.1 repo
- do a giant rewrite
- re-architect working v5 slices unless necessary
- reintroduce vague v4 swarm behavior

Read these files before making significant changes:
1. docs/spec/01_Jarvis_OS_v5_1_Rebuild_Spec.md
2. docs/spec/03_Jarvis_OS_v5_1_Rebuild_Roadmap.md
3. docs/spec/05_Jarvis_OS_v5_1_Repo_Build_Map.md
4. docs/spec/04_Jarvis_OS_v5_1_Rebuild_Implementation_Checklist.md

For live Discord or other user-facing Jarvis chat replies, also read:
5. docs/discord_live_reply_contract.md

Interpretation rules:
- 01_Jarvis_OS_v5_1_Rebuild_Spec.md is the source of truth
- 03_Roadmap defines implementation order
- 05_Repo_Build_Map suggests likely file locations
- 04_Checklist is for tracking completeness, not overriding the spec
- For post-freeze or cleanup passes, prefer proving parity against the master spec and live code before changing runtime behavior

Non-negotiable v5.1 principles:
- provider-agnostic routing
- Qwen-first by policy, not architecture lock-in
- candidate-first artifact lifecycle
- promotion, demotion, revocation
- resumable approvals
- emergency controls
- durable provenance and replayability
- memory discipline
- subsystem contracts
- bounded multimodal control

Architectural rules:
- backend outputs remain candidates until promoted
- no chat-inferred state
- no arbitrary direct memory writes
- no hidden reinject loops
- no subsystem may silently become the system of record
- Jarvis is the public face; Hermes/autoresearch/Ralph are subsystems

Implementation style:
- prefer small, surgical edits
- preserve working tests
- preserve existing v5 backbone where possible
- prefer explicit schemas over hidden agent magic
- prefer reversible behavior over clever autonomy
- be honest about what is stubbed, partial, or broken

Suggested practical build order:
1. foundation cleanup / bootstrap alignment
2. durable task + artifact + event spine
3. candidate/demotion lifecycle
4. status / heartbeat / reporter
5. Hermes thin adapter
6. resumable approvals
7. Strategy Lab / autoresearch thin adapter
8. Ralph consolidation pass
9. voice/browser only after core trust boundaries are real

When completing a task:
- explain which files changed
- run relevant validation/tests
- report exactly what passed and failed
- identify the next highest-leverage slice

Post-freeze hygiene rules:
- prefer doc, checklist, and repo-hygiene parity over runtime edits
- remove tracked generated junk when it is clearly not source
- do not reopen support-plane or architecture work unless the live code proves a real bug or spec gap

## Discord Reply Seam

When answering in the live Jarvis Discord lane:

- never expose raw prompt scaffolding, XML-ish tags, internal section labels, or file-loader diagnostics
- never echo text like `</context>`, `<system_status>`, `<system_instructions>`, `</system_prompt>`, or `[MISSING] Expected at: ...`
- treat prompt/bootstrap file loading as internal implementation detail
- treat `USER.md` as optional personalization memory, not a required user-facing dependency
- if `USER.md` is unavailable or unreadable, continue silently without mentioning it to the user
- answer model/runtime questions from current repo/operator truth, not stale bootstrap assumptions
- for ShadowBroker and other sidecars, distinguish:
  - repo integration truth
  - machine-local live activation truth
  - degraded/blocked/unknown external runtime truth
