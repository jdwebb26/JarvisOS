# Agent Specialization Hardening — Status 2026-03-15

## What was fixed

### Explicit name-based allowlists (were implicit / category-based)

`runtime/core/agent_roster.py` now contains two authoritative dicts — `AGENT_TOOL_ALLOWLIST` and
`AGENT_SKILL_ALLOWLIST` — that define exact tool/skill names for all 9 agents. Enforcement in
`filter_tools_for_agent()` and `filter_skills_prompt_for_agent()` checks exact names only; the old
category-fallback paths are gone.

### Fail-closed unknown-agent handling (was silent Jarvis fallback)

`_allowed_tool_names_for_agent()` and `_allowed_skill_names_for_agent()` previously fell back to
Jarvis's allowlist when an agent was unknown. Both now return `[]` for any agent not in
`CANONICAL_AGENT_ROSTER`. `infer_agent_id()` already guarantees a known ID for configured agents,
so the fallback was dead code, but it was a latent security risk — removed.

### `build_agent_runtime_loadout` reports filtered tools (not raw tools)

The function internally calls `filter_tools_for_agent` so its `loadedTools.visibleToolNames` output
is always the post-filter set. The `systemPromptReport` produced by `build_context_packet` carries
the same filtered view.

### ACP runtime type tracking

`AGENT_RUNTIME_TYPES` dict and `get_agent_runtime_type()` added to `agent_roster.py`. HAL is
`"acp_ready"` (first ACP candidate); all other agents are `"embedded"`. The type is reported in
`build_agent_runtime_loadout`, `build_agent_roster_summary`, and the verifier.

### Verifier — static policy vs live session evidence clearly separated

`scripts/verify_openclaw_bootstrap_runtime.py` now always prints `Policy (from code):` derived
directly from code allowlists, independent of any session state.  The live-session section is
clearly labelled:

> `Live session (raw session tools re-filtered with current policy):`

This label makes explicit that sessions record the HOST-provided raw pre-filter tool list, and the
verifier re-applies current policy to reconstruct the filtered view. If policy changed since the
session ran, the reconstructed view reflects current policy, not what actually ran.

### Test suite hardened

`tests/test_source_owned_context_engine.py` — the test for agent-specific skill loading was using
fake skill names not in `config/skill_inventory.json`, causing `_normalize_skill_names()` to silently
drop them. Fixed to use real inventory names (`discord`, `voice-call`, `coding-agent`, `session-logs`,
`blogwatcher`, `sag`), real tool names (`read`, `exec`, `browser_navigate`), and was added to the
`__main__` block so it runs on direct execution.

---

## What is now enforced in code

| Enforcement point | Location | Behaviour |
|---|---|---|
| Tool allowlist (exact name) | `filter_tools_for_agent()` in `agent_roster.py` | Drops any tool not in per-agent `AGENT_TOOL_ALLOWLIST`; fail-closed for unknown agents |
| Skill allowlist (exact name) | `filter_skills_prompt_for_agent()` in `agent_roster.py` | Drops any skill not in per-agent `AGENT_SKILL_ALLOWLIST`; `COMMON_DENIED_SKILL_NAMES` applied first |
| Inventory normalization | `_normalize_skill_names()` | Drops skill names not present in `config/skill_inventory.json` |
| Global skill deny | `COMMON_DENIED_SKILL_NAMES = ["clawhub", "weather", "gog"]` | Applied before allowlist check for all agents |
| Context engine enforcement | `_select_tool_exposure()` in `source_owned_context_engine.py` | Calls `filter_tools_for_agent` for non-discord or task-requiring prompts; returns empty tool set for simple Discord chat |
| Filtered output used by host | `build_context_packet()` → `filteredSkillsPrompt`, `visibleTools` | Proven by live bundle checks `filtered_skills_applied=True`, `source_owned_visible_tools=True` |

---

## What is only scaffolded / documented

| Item | Status | Notes |
|---|---|---|
| ACP harness for HAL | `acp_ready` — NOT active | `acp.enabled=false` in `openclaw.json`; activate by flipping `acp.enabled=true` and changing HAL's `runtime.type` to `"acp"` |
| ACP for Hermes | future candidate | Will follow same steps as HAL once HAL is validated |
| Bowser browser bridge | scaffold only | `browser`/`browser_navigate` tools are in allowlist but host does not pass them in live sessions yet |
| Hermes live daemon | blocked by external runtime | Adapter seam exists; availability depends on external runtime |
| Ralph full autonomy loop | blocked by external runtime | Memory/consolidation intent scaffolded; full loop blocked |

---

## Current ACP status

```
acp.enabled = false  (openclaw.json)
acp_scaffold.enabled = false  (config/runtime_routing_policy.json)
HAL runtime_type = "acp_ready"  (agent_roster.py, openclaw.json runtime block)
```

ACP is fully scaffolded but not active. No code paths change until `acp.enabled=true` is explicitly
set by the operator.

---

## Per-agent matrix

All enforcement via `AGENT_TOOL_ALLOWLIST` and `AGENT_SKILL_ALLOWLIST` in `runtime/core/agent_roster.py`.

| Agent | Runtime type | Tool allowlist (count) | Skill allowlist (count) | Live session evidence |
|---|---|---|---|---|
| jarvis | embedded | 13 | 5 | live-session-refiltered — 0 unexpected tools ✓ |
| hal | acp_ready | 17 | 5 | session exists, no tool entries captured yet |
| archimedes | embedded | 6 | 2 | no session yet |
| anton | embedded | 7 | 2 | no session yet |
| hermes | embedded | 12 | 5 | no session yet |
| scout | embedded | 11 | 5 | live-session-refiltered — 0 unexpected tools ✓ |
| bowser | embedded | 9 | 1 | live-session-refiltered — 0 unexpected tools ✓ |
| muse | embedded | 4 | 4 | no session yet |
| ralph | embedded | 10 | 2 | no session yet |

"no session yet" means enforcement is code-correct but no observed session data is available for
comparison. It is not a broken state.

---

## Validation commands run

```sh
python3 tests/test_agent_roster.py                    # PASS
python3 tests/test_source_owned_context_engine.py     # PASS
python3 tests/test_openclaw_specialization_bridge.py  # exit 0
python3 scripts/validate.py                           # PASS  pass=387 warn=0 fail=0
python3 scripts/smoke_test.py                         # PASS  (5/5 regression + dashboard rebuild)
python3 scripts/verify_openclaw_bootstrap_runtime.py \
  --agent jarvis --agent hal --agent archimedes --agent anton \
  --agent hermes --agent scout --agent bowser --agent muse --agent ralph \
  --json > /tmp/verify_exposure.json
```

Live bundle checks (all True):

| Check | Result |
|---|---|
| `agent_bootstrap_overlay_present` | True |
| `agent_bootstrap_overlay_uses_agent_dir` | True |
| `agent_bootstrap_overlay_replaces_by_name` | True |
| `agent_bootstrap_overlay_without_patterns` | True |
| `runtime_network_interface_guard` | True |
| `bridge_payload_fields` | True |
| `filtered_skills_applied` | True |
| `source_owned_report_merge` | True |
| `source_owned_visible_tools` | True |

---

## Remaining gaps — missing session evidence only

The following agents have no live session snapshot yet:
`archimedes`, `anton`, `hermes`, `muse`, `ralph`

HAL has a session file but no tool entries were captured (agent has not run a full session yet).

These are **evidence gaps only** — not enforcement gaps. The allowlist code is correct and will
enforce on first live run. No further code changes are needed for these agents.

---

## Files changed in this hardening pass

### In-repo (will be committed)

| File | Change |
|---|---|
| `runtime/core/agent_roster.py` | Added `AGENT_RUNTIME_TYPES`, `get_agent_runtime_type()`, explicit per-agent allowlists, fail-closed unknown-agent handling, `runtimeType` in loadout/roster summary |
| `config/runtime_routing_policy.json` | Added `acp_scaffold` section |
| `scripts/verify_openclaw_bootstrap_runtime.py` | Imports `get_agent_runtime_type`, `infer_agent_id`, `_allowed_{tool,skill}_names_for_agent`; always shows static policy; clearly labels session data as raw-refiltered |
| `tests/test_agent_roster.py` | Added `test_generic_skill_blocks_are_not_implicitly_loaded_for_jarvis` to `__main__` |
| `tests/test_source_owned_context_engine.py` | Fixed skill/tool names to real inventory values; updated assertions; added new test to `__main__` |
| `docs/agent_roster.md` | Replaced category-based matrix with exact-name allowlist matrix; added embedded-vs-ACP section |
| `docs/STATUS_2026-03-15_agent_specialization_hardening.md` | This file |

### Outside repo (NOT committed — manual preservation needed)

| File | Change |
|---|---|
| `~/.openclaw/openclaw.json` | Added top-level `"acp"` config block; added `"runtime"` block to HAL's agent entry |
