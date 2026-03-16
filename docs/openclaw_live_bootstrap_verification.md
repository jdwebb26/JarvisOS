# OpenClaw Live Bootstrap Verification

Use the repo-owned verifier to answer two questions without hand-inspecting the installed dist bundle:

1. Are the per-agent `~/.openclaw/agents/<id>/*.md` files connected to the active runtime path right now?
2. Which live bootstrap basenames resolve from top-level agent files, `agent/` fallbacks, or workspace-base files?

Quick check:

```bash
python3 scripts/verify_openclaw_bootstrap_runtime.py --agent jarvis --agent hal --agent bowser
```

JSON form:

```bash
python3 scripts/verify_openclaw_bootstrap_runtime.py --agent jarvis --agent hal --agent bowser --json
```

What it verifies:

- the installed `bootstrap-extra-files/handler.js` still contains the agent overlay patch
- the installed auth-profile bundle still consumes the source-owned bridge fields
- the installed auth-profile bundle still contains the embedded/local fallback that calls the bundled bootstrap handler when internal hooks were not preloaded
- the active precedence order is `top_level_agent_root -> agent_dir -> workspace_base`
- whether `IDENTITY.md`, `TOOLS.md`, `BOOTSTRAP.md`, and `SOUL.md` are used directly at runtime for each selected agent
- the exact active source path chosen for each bootstrap basename

Interpretation:

- `top_level_agent_root` means `~/.openclaw/agents/<id>/<name>` is authoritative live runtime input for that basename
- `agent_dir` means the runtime is falling back to `~/.openclaw/agents/<id>/agent/<name>`
- `workspace_base` means the run kept the workspace-loaded file for that basename

Because the current config now points agentDir at the parent folders, the verifier should show `top_level_agent_root` as the active source for every `AGENTS/SOUL/TOOLS/IDENTITY/BOOTSTRAP` basename that was moved up, leaving `agent_dir` for the legacy backups.

Note:

- workspace-base files are loaded from the effective runtime workspace; in sandboxed runs OpenClaw may read a sandbox copy of the configured workspace file
- this verifier is read-only because the live runtime hook already reads top-level agent files directly when present

Repair command for the installed dist patch:

```bash
python3 scripts/openclaw_specialization_bridge.py --apply
```

That helper now restores four live seams together:

- the installed runtime network-interface soft-fail guard in `auth-profiles-iXW75sRj.js`

- the Discord session bindings now mirror the latest `systemPromptReport` (loadedSkills, loadedTools, agentRuntimeLoadout)

- source-owned bridge payload/report fields in the auth bundle
- top-level per-agent bootstrap overlay support in `bootstrap-extra-files/handler.js`
- the embedded/local fallback that invokes the same bundled handler when `openclaw agent --local` did not preload internal hooks
