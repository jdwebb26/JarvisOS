# Jarvis OS v5.1 Rebuild Package

This package is the rebuilt implementation handoff for Codex, Hermes-facing adapters, and future Jarvis agents.

Files:
- `01_Jarvis_OS_v5_1_Rebuild_Spec.md` — rules-only authoritative spec
- `02_Jarvis_OS_v5_1_Rebuild_Design_Notes.md` — rationale, comparisons, and tradeoffs
- `03_Jarvis_OS_v5_1_Rebuild_Roadmap.md` — sequencing and milestones
- `04_Jarvis_OS_v5_1_Rebuild_Implementation_Checklist.md` — practical build checklist
- `05_Jarvis_OS_v5_1_Repo_Build_Map.md` — repo/file mapping for implementation
- `06_Jarvis_OS_v5_1_Research_Appendix.md` — concise external research synthesis

Recommended usage:
1. Treat `01_Jarvis_OS_v5_1_Rebuild_Spec.md` as the source of truth.
2. Use `02_..._Design_Notes.md` when the spec leaves room for interpretation.
3. Use `03_..._Roadmap.md` to sequence work.
4. Use `04_..._Implementation_Checklist.md` to track progress.
5. Use `05_..._Repo_Build_Map.md` to map changes to repo files.
6. Use `06_..._Research_Appendix.md` to understand why the rebuild made these calls.

Package thesis:
Jarvis remains the only primary public face and control plane.
Hermes is the research daemon.
autoresearch is the lab daemon.
All backend outputs enter as candidates, not truth.
Promotion requires policy, review, evaluation where applicable, and provenance metadata.
Every important subsystem is stoppable, attributable, replayable, and reversible.
