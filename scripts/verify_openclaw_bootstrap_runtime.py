#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.agent_roster import (
    AGENT_SKILL_ALLOWLIST,
    CANONICAL_AGENT_ROSTER,
    build_agent_roster_summary,
    build_agent_runtime_loadout,
    get_agent_runtime_type,
    infer_agent_id,
    _allowed_skill_names_for_agent,
    _allowed_tool_names_for_agent,
)
from runtime.integrations.openclaw_sessions import scan_all_specialist_channel_sessions


DEFAULT_OPENCLAW_ROOT = Path.home() / ".openclaw"
DEFAULT_CONFIG_PATH = DEFAULT_OPENCLAW_ROOT / "openclaw.json"
DEFAULT_HANDLER_PATH = Path.home() / ".npm-global/lib/node_modules/openclaw/dist/bundled/bootstrap-extra-files/handler.js"
DEFAULT_BUNDLE_PATH = Path.home() / ".npm-global/lib/node_modules/openclaw/dist/auth-profiles-iXW75sRj.js"

AGENT_BOOTSTRAP_FILE_NAMES = [
    "AGENTS.md",
    "SOUL.md",
    "TOOLS.md",
    "IDENTITY.md",
    "USER.md",
    "HEARTBEAT.md",
    "BOOTSTRAP.md",
    "MEMORY.md",
    "memory.md",
]

TARGET_TOP_LEVEL_FILES = [
    "IDENTITY.md",
    "TOOLS.md",
    "BOOTSTRAP.md",
    "SOUL.md",
]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _bool_map(path: Path, text: str) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "checks": text,
    }


def _inspect_handler(path: Path) -> dict[str, Any]:
    text = _read_text(path)
    return _bool_map(
        path,
        {
            "agent_bootstrap_overlay_present": "resolveAgentBootstrapOverlayFiles" in text,
            "agent_bootstrap_overlay_uses_agent_dir": 'const rawAgentDir = typeof agentEntry?.agentDir === "string" ? agentEntry.agentDir.trim() : "";' in text,
            "agent_bootstrap_overlay_replaces_by_name": "mergeAgentBootstrapFiles" in text,
            "agent_bootstrap_overlay_without_patterns": 'if (hookConfig?.enabled === false) return;' in text
            and "const overlayFiles = await resolveAgentBootstrapOverlayFiles(context);" in text,
        },
    )


def _inspect_bundle(path: Path) -> dict[str, Any]:
    text = _read_text(path)
    return _bool_map(
        path,
        {
            "runtime_network_interface_guard": "function listTailnetAddresses() {\n\tconst ipv4 = [];\n\tconst ipv6 = [];\n\tlet ifaces;\n\ttry {\n\t\tifaces = os.networkInterfaces();\n\t}\n\tcatch {\n\t\treturn {\n\t\t\tipv4: [],\n\t\t\tipv6: []\n\t\t};\n\t}\n" in text
            and "function pickPrimaryLanIPv4() {\n\tlet nets;\n\ttry {\n\t\tnets = os.networkInterfaces();\n\t}\n\tcatch {\n\t\treturn;\n\t}\n" in text,
            "bridge_payload_fields": 'skills_prompt: typeof params.skillsPrompt === "string" ? params.skillsPrompt : ""' in text
            and 'agent_id: typeof params.agentId === "string" ? params.agentId : ""' in text
            and 'provider_id: typeof params.providerId === "string" ? params.providerId : ""' in text
            and 'model_id: typeof params.modelId === "string" ? params.modelId : ""' in text,
            "filtered_skills_applied": 'if (typeof sourceOwnedContextSeed?.filteredSkillsPrompt === "string") skillsPrompt = sourceOwnedContextSeed.filteredSkillsPrompt;' in text,
            "source_owned_report_merge": "sourceOwnedContextSeed?.systemPromptReport" in text,
            "source_owned_visible_tools": "sourceOwnedContextSeed?.visibleTools" in text,
        },
    )


def _load_latest_agent_session(agent_root: Path) -> tuple[Path | None, dict[str, Any] | None]:
    sessions_file = agent_root / "sessions" / "sessions.json"
    if not sessions_file.exists():
        return sessions_file, None
    try:
        payload = json.loads(sessions_file.read_text(encoding="utf-8"))
    except Exception:
        return sessions_file, None
    latest_entry: dict[str, Any] | None = None
    latest_updated = -1
    for entry in payload.values():
        updated = entry.get("updatedAt") or 0
        try:
            updated = int(updated)
        except Exception:
            updated = 0
        if updated > latest_updated:
            latest_updated = updated
            latest_entry = entry
    return sessions_file, latest_entry


def _tool_objects_from_session(session_entry: dict[str, Any]) -> list[dict[str, Any]]:
    report = session_entry.get("systemPromptReport") or {}
    entries = (report.get("tools") or {}).get("entries") or []
    tools: list[dict[str, Any]] = []
    for item in entries:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        tools.append(
            {
                "name": name,
                "toolName": name,
                "description": str(item.get("summary") or item.get("description") or ""),
            }
        )
    return tools


def _build_agent_runtime_exposure(agent_id: str, session_entry: dict[str, Any], *, root: Path) -> dict[str, Any]:
    skills_snapshot = session_entry.get("skillsSnapshot") or {}
    skills_prompt = str(skills_snapshot.get("prompt") or "")
    tools = _tool_objects_from_session(session_entry)
    loadout = build_agent_runtime_loadout(agent_id=agent_id, skills_prompt=skills_prompt, tools=tools, root=root)
    tool_allowlist = _allowed_tool_names_for_agent(agent_id)
    visible_tools = [name for name in (loadout["loadedTools"].get("visibleToolNames") or [])]
    unexpected = sorted(set(visible_tools) - set(tool_allowlist))
    missing = sorted(set(tool_allowlist) - set(visible_tools))
    return {
        "runtimeType": get_agent_runtime_type(agent_id),
        "skills": loadout["loadedSkills"],
        "tools": loadout["loadedTools"],
        "toolAllowlist": tool_allowlist,
        "unexpectedTools": unexpected,
        "missingAllowedTools": missing,
    }


def _resolve_agent_entry(config: dict[str, Any], agent_id: str) -> dict[str, Any] | None:
    for entry in config.get("agents", {}).get("list", []):
        if str(entry.get("id") or "").strip().lower() == agent_id.lower():
            return entry
    return None


def _candidate_rows(agent_root: Path, agent_dir: Path, workspace_dir: Path, name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind, path in (
        ("top_level_agent_root", agent_root / name),
        ("agent_dir", agent_dir / name),
        ("workspace_base", workspace_dir / name),
    ):
        rows.append(
            {
                "kind": kind,
                "path": str(path),
                "exists": path.exists(),
            }
        )
    return rows


def _select_active_source(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in candidates:
        if row["exists"]:
            return row
    return None


def _resolve_agent_sources(entry: dict[str, Any]) -> dict[str, Any]:
    agent_id = str(entry.get("id") or "").strip()
    agent_dir = Path(str(entry.get("agentDir") or "")).expanduser().resolve()
    agent_root = agent_dir.parent
    workspace_dir = Path(str(entry.get("workspace") or "")).expanduser().resolve()
    runtime_config = dict(entry.get("runtime") or {})
    files: dict[str, Any] = {}
    top_level_direct_runtime: dict[str, Any] = {}

    for name in AGENT_BOOTSTRAP_FILE_NAMES:
        candidates = _candidate_rows(agent_root, agent_dir, workspace_dir, name)
        active = _select_active_source(candidates)
        files[name] = {
            "active": active,
            "candidates": candidates,
            "direct_runtime": bool(active),
        }
        if name in TARGET_TOP_LEVEL_FILES:
            top_level_path = agent_root / name
            top_level_direct_runtime[name] = {
                "path": str(top_level_path),
                "exists": top_level_path.exists(),
                "used_directly_at_runtime": bool(active and active["kind"] == "top_level_agent_root"),
                "active_source_kind": active["kind"] if active else "missing",
                "active_source_path": active["path"] if active else None,
            }

    session_path, session_entry = _load_latest_agent_session(agent_dir)
    session_snapshot: dict[str, Any] = {
        "sessionFile": str(session_path) if session_path else None,
        "sessionKey": str(session_entry.get("sessionKey") or "") if session_entry else None,
        "skillsPromptChars": 0,
        "toolEntryCount": 0,
    }
    if session_entry:
        skills_prompt = str((session_entry.get("skillsSnapshot") or {}).get("prompt") or "")
        tool_entries = (session_entry.get("systemPromptReport") or {}).get("tools", {}).get("entries") or []
        session_snapshot.update(
            {
                "skillsPromptChars": len(skills_prompt),
                "toolEntryCount": len(tool_entries),
            }
        )
    return {
        "agentId": agent_id,
        "workspaceDir": str(workspace_dir),
        "agentDir": str(agent_dir),
        "agentRoot": str(agent_root),
        "precedence": [
            "top_level_agent_root",
            "agent_dir",
            "workspace_base",
        ],
        "notes": [
            "The installed bootstrap hook reads top-level ~/.openclaw/agents/<id>/<name> first.",
            "If a basename is absent there, it falls back to ~/.openclaw/agents/<id>/agent/<name>.",
            "If both are absent, the run keeps the workspace base file loaded by loadWorkspaceBootstrapFiles(...).",
            "Workspace-base files are loaded from the effective runtime workspace; in sandboxed runs that may be a sandbox copy of the configured workspace.",
        ],
        "topLevelTargetFiles": top_level_direct_runtime,
        "bootstrapFiles": files,
        "sessionSnapshot": session_snapshot,
        "_sessionEntry": session_entry,
        "configuredRuntime": runtime_config,
    }


def _inspect_specialist_channel_sessions(config: dict[str, Any], openclaw_root: Path) -> dict[str, Any]:
    """Cross-reference openclaw.json Discord bindings with actual live session directories.

    For each Discord channel binding, reports which agent actually has the session for that
    channel (which may differ from the configured agentId if legacy agent names are still
    present in the agents directory).

    Status values:
      ok                  — configured agentId matches the session_agent_id in the session key
      stale_legacy_session— a legacy / pre-rename agent (e.g. builder, reviewer) has the session;
                            the configured agentId has no Discord session for this channel yet
      wrong_canonical_agent— a different canonical agent (not the configured one) has the session
      no_session_yet      — no Discord session exists for this channel at all; will be created on
                            first inbound message
    """
    canonical_ids = set(CANONICAL_AGENT_ROSTER.keys())

    # Read bindings from openclaw.json
    expected_bindings: list[dict[str, Any]] = []
    for binding in config.get("bindings", []):
        match = binding.get("match") or {}
        if match.get("channel") != "discord":
            continue
        peer = match.get("peer") or {}
        channel_id = str(peer.get("id") or "").strip()
        agent_id = str(binding.get("agentId") or "").strip().lower()
        if channel_id and agent_id:
            expected_bindings.append({"expected_agent_id": agent_id, "channel_id": channel_id})

    # Scan all agent session directories
    all_sessions = scan_all_specialist_channel_sessions(openclaw_root=openclaw_root)
    sessions_by_channel: dict[str, list[dict[str, Any]]] = {}
    for s in all_sessions:
        sessions_by_channel.setdefault(s["channel_id"], []).append(s)

    # Build per-channel audit rows
    channel_rows: list[dict[str, Any]] = []
    for binding in expected_bindings:
        expected = binding["expected_agent_id"]
        cid = binding["channel_id"]
        channel_sessions = sessions_by_channel.get(cid, [])

        correct = [s for s in channel_sessions if s["session_agent_id"] == expected]
        stale_legacy = [s for s in channel_sessions if s["session_agent_id"] != expected and s["session_agent_id"] not in canonical_ids]
        wrong_canonical = [s for s in channel_sessions if s["session_agent_id"] != expected and s["session_agent_id"] in canonical_ids]

        if correct:
            status = "ok"
        elif not channel_sessions:
            status = "no_session_yet"
        elif wrong_canonical:
            status = "wrong_canonical_agent"
        else:
            status = "stale_legacy_session"

        channel_rows.append({
            "channel_id": cid,
            "expected_agent_id": expected,
            "status": status,
            "correct_sessions": [{"session_key": s["session_key"], "session_id": s["session_id"], "updated_at": s["updated_at"], "group_channel": s["group_channel"]} for s in correct],
            "stale_legacy_sessions": [{"session_key": s["session_key"], "dir_agent_id": s["dir_agent_id"], "sessions_file": s["sessions_file"], "updated_at": s["updated_at"]} for s in stale_legacy],
            "wrong_canonical_sessions": [{"session_key": s["session_key"], "dir_agent_id": s["dir_agent_id"], "updated_at": s["updated_at"]} for s in wrong_canonical],
        })

    # Find legacy ghost sessions not accounted for in any binding
    bound_channels = {b["channel_id"] for b in expected_bindings}
    ghost_sessions = [
        {"session_key": s["session_key"], "channel_id": s["channel_id"], "dir_agent_id": s["dir_agent_id"], "updated_at": s["updated_at"]}
        for s in all_sessions
        if s["channel_id"] not in bound_channels
    ]

    ok_count = sum(1 for r in channel_rows if r["status"] == "ok")
    stale_count = sum(1 for r in channel_rows if r["status"] == "stale_legacy_session")
    missing_count = sum(1 for r in channel_rows if r["status"] == "no_session_yet")
    wrong_count = sum(1 for r in channel_rows if r["status"] == "wrong_canonical_agent")

    return {
        "channelBindingAudit": channel_rows,
        "ghostSessions": ghost_sessions,
        "summary": {
            "ok": ok_count,
            "stale_legacy_session": stale_count,
            "no_session_yet": missing_count,
            "wrong_canonical_agent": wrong_count,
        },
        "operatorNote": (
            "Stale legacy sessions (builder, reviewer) hold the active Discord state for their channel. "
            "The host will create a new specialist session on next inbound message. "
            "To force the new session now: delete the stale entry from the agent's sessions/sessions.json "
            "and archive the corresponding .jsonl file."
            if stale_count > 0 else ""
        ),
    }


def _build_report(config_path: Path, handler_path: Path, bundle_path: Path, agent_ids: list[str] | None) -> dict[str, Any]:
    config = _load_json(config_path)
    repo_root = Path(__file__).resolve().parents[1]
    configured_agent_ids = [str(entry.get("id") or "").strip() for entry in config.get("agents", {}).get("list", [])]
    selected_agent_ids = agent_ids or configured_agent_ids
    agents: list[dict[str, Any]] = []
    for agent_id in selected_agent_ids:
        entry = _resolve_agent_entry(config, agent_id)
        if entry is None:
            agents.append({"agentId": agent_id, "missingFromConfig": True})
            continue
        agents.append(_resolve_agent_sources(entry))
    for agent in agents:
        if not agent.get("missingFromConfig"):
            aid = agent["agentId"]
            # Static policy is always authoritative — derived from code, not session state.
            # "configuredSkillAllowlist" = raw names from AGENT_SKILL_ALLOWLIST (before inventory normalization).
            # "effectiveSkillAllowlist"  = after _normalize_skill_names() (filtered to installed inventory).
            raw_skill_allowlist = [
                str(s).strip().lower()
                for s in (AGENT_SKILL_ALLOWLIST.get(infer_agent_id(agent_id=aid)) or [])
            ]
            agent["staticPolicy"] = {
                "toolAllowlist": sorted(_allowed_tool_names_for_agent(aid)),
                "configuredSkillAllowlist": sorted(raw_skill_allowlist),
                "effectiveSkillAllowlist": sorted(_allowed_skill_names_for_agent(aid)),
                "runtimeType": get_agent_runtime_type(aid),
            }
        session_entry = agent.pop("_sessionEntry", None)
        if session_entry:
            agent["runtimeExposure"] = _build_agent_runtime_exposure(agent["agentId"], session_entry, root=repo_root)
            agent["runtimeExposure"]["sessionDataAvailable"] = True
        else:
            agent["runtimeExposure"] = {"sessionDataAvailable": False}
    specialist_channels = _inspect_specialist_channel_sessions(config, DEFAULT_OPENCLAW_ROOT)
    return {
        "configPath": str(config_path),
        "installedRuntime": {
            "bootstrapHandler": _inspect_handler(handler_path),
            "authProfilesBundle": _inspect_bundle(bundle_path),
        },
        "authoritativeRuntimeBootstrapPath": {
            "installedBundleFunction": "runEmbeddedAttempt(...) -> resolveBootstrapContextForRun(...) -> resolveBootstrapFilesForRun(...) -> applyBootstrapHookOverrides(...)",
            "installedBootstrapHook": "bootstrap-extra-files/handler.js -> resolveAgentBootstrapOverlayFiles(...) -> mergeAgentBootstrapFiles(...)",
            "installedSystemPromptBridge": "runEmbeddedAttempt(...) -> runSourceOwnedContextEngineBridge(...) -> buildSystemPromptReport(...)",
            "repoBridgeCli": str((Path(__file__).resolve().parents[1] / "scripts" / "source_owned_context_engine_cli.py").resolve()),
            "repoSourceOwnedEngine": str((Path(__file__).resolve().parents[1] / "runtime" / "gateway" / "source_owned_context_engine.py").resolve()),
        },
        "agents": agents,
        "specialistChannelAudit": specialist_channels,
        "agentRosterSummary": build_agent_roster_summary(root=repo_root),
    }


def _print_human(report: dict[str, Any]) -> None:
    runtime = report["installedRuntime"]
    print(f"Config: {report['configPath']}")
    print(f"Bootstrap handler: {runtime['bootstrapHandler']['path']}")
    for key, value in runtime["bootstrapHandler"]["checks"].items():
        print(f"  {key}: {value}")
    print(f"Auth bundle: {runtime['authProfilesBundle']['path']}")
    for key, value in runtime["authProfilesBundle"]["checks"].items():
        print(f"  {key}: {value}")
    print("Precedence: top_level_agent_root -> agent_dir -> workspace_base")
    print("Runtime path: runEmbeddedAttempt -> resolveBootstrapContextForRun -> resolveBootstrapFilesForRun -> applyBootstrapHookOverrides")
    print("System prompt bridge: runEmbeddedAttempt -> runSourceOwnedContextEngineBridge -> buildSystemPromptReport")
    for agent in report["agents"]:
        print()
        print(f"[{agent['agentId']}]")
        if agent.get("missingFromConfig"):
            print("  missing from ~/.openclaw/openclaw.json agents.list")
            continue
        runtime_type = get_agent_runtime_type(agent["agentId"])
        print(f"  runtime_type (repo): {runtime_type}")
        configured_runtime = agent.get("configuredRuntime") or {}
        configured_type = str(configured_runtime.get("type") or "embedded")
        print(f"  runtime_type (config): {configured_type}")
        acp_config = configured_runtime.get("acp") or {}
        backend_label = acp_config.get("backend") or configured_runtime.get("backend")
        if backend_label or acp_config.get("cwd"):
            cwd_value = acp_config.get("cwd") or ""
            print(f"    configured backend: {backend_label or '(default)'} cwd: {cwd_value or '(default)'}")
        for name in TARGET_TOP_LEVEL_FILES:
            row = agent["topLevelTargetFiles"][name]
            print(
                f"  {name}: top-level exists={row['exists']} used_directly_at_runtime={row['used_directly_at_runtime']} "
                f"active={row['active_source_kind']} {row['active_source_path'] or ''}".rstrip()
            )
        print("  Active bootstrap basenames:")
        for name in AGENT_BOOTSTRAP_FILE_NAMES:
            active = agent["bootstrapFiles"][name]["active"]
            if not active:
                print(f"    {name}: missing")
                continue
            print(f"    {name}: {active['kind']} -> {active['path']}")
        # Static policy — always present, derived from code allowlists.
        static = agent.get("staticPolicy") or {}
        tool_allowlist = static.get("toolAllowlist") or []
        skill_allowlist = static.get("configuredSkillAllowlist") or []
        tool_line = ", ".join(tool_allowlist) if tool_allowlist else "none"
        skill_line = ", ".join(skill_allowlist) if skill_allowlist else "none"
        print(f"  Policy (from code):")
        print(f"    Allowed tools ({len(tool_allowlist)}): {tool_line}")
        print(f"    Allowed skills ({len(skill_allowlist)}): {skill_line}")

        # Live session — only available when a session has been recorded with tool/skill data.
        # NOTE: The session records the HOST-provided raw pre-filter tools (systemPromptReport.tools.entries),
        # not the filtered output. The verifier re-applies current policy code to those raw tools, so
        # the result below reflects current policy enforcement against the last session's raw inputs.
        # If policy has changed since that session ran, the visible tools shown here may differ from
        # what the model actually received during that session.
        exposure = agent.get("runtimeExposure") or {}
        has_session_data = bool(exposure.get("sessionDataAvailable"))
        snapshot = agent.get("sessionSnapshot") or {}
        has_tool_entries = int(snapshot.get("toolEntryCount") or 0) > 0
        if has_session_data and has_tool_entries:
            skills = exposure.get("skills") or {}
            tools = exposure.get("tools") or {}
            obs_skill_names = list(skills.get("loadedSkillNames") or [])
            obs_tool_names = list(tools.get("visibleToolNames") or [])
            obs_skill_line = ", ".join(obs_skill_names) if obs_skill_names else "none"
            obs_tool_line = ", ".join(obs_tool_names) if obs_tool_names else "none"
            print(f"  Live session (raw session tools re-filtered with current policy):")
            print(f"    Loaded skills ({len(obs_skill_names)}): {obs_skill_line}")
            print(f"    Visible tools ({len(obs_tool_names)}): {obs_tool_line}")
            unexpected = exposure.get("unexpectedTools") or []
            missing = exposure.get("missingAllowedTools") or []
            if unexpected:
                print(f"    Unexpected tools (NOT in allowlist): {', '.join(unexpected)}")
            else:
                print(f"    Unexpected tools: none  ✓")
            if missing:
                # "Missing" means the allowlist permits them but they weren't in this session's tool set.
                # This is normal — sessions only include tools the host decided to pass in.
                print(f"    Allowlisted but not observed ({len(missing)}): {', '.join(missing)}")
                print(f"      (These are policy-allowed but were not passed in by the host for this session)")
        elif has_session_data and not has_tool_entries:
            print(f"  Live session: EXISTS but no tool data — policy comparison not available")
            print(f"    (Session record exists but no tools were captured — agent may not have run yet.)")
            print(f"    (Allowlist is code-enforced when the session is active — no manual action needed.)")
        else:
            print(f"  Live session: NO DATA — policy comparison not available")
            print(f"    (No live session exists for this agent yet.)")
            print(f"    (Allowlist is code-enforced when the session is active — no manual action needed.)")

        if snapshot:
            parts = [
                f"promptChars={snapshot.get('skillsPromptChars', 0)}",
                f"toolEntries={snapshot.get('toolEntryCount', 0)}",
            ]
            if snapshot.get("sessionFile"):
                parts.append(f"file={snapshot['sessionFile']}")
            print(f"  Session snapshot: {' | '.join(parts)}")


def _print_specialist_channel_audit(report: dict[str, Any]) -> None:
    audit = report.get("specialistChannelAudit") or {}
    summary = audit.get("summary") or {}
    rows = audit.get("channelBindingAudit") or []
    ghosts = audit.get("ghostSessions") or []
    print()
    print("=== Specialist channel audit ===")
    print(f"  ok={summary.get('ok', 0)}  stale_legacy={summary.get('stale_legacy_session', 0)}  no_session_yet={summary.get('no_session_yet', 0)}  wrong_canonical={summary.get('wrong_canonical_agent', 0)}")
    for row in rows:
        cid = row["channel_id"]
        expected = row["expected_agent_id"]
        status = row["status"]
        icon = "✓" if status == "ok" else ("?" if status == "no_session_yet" else "✗")
        print(f"  {icon} channel:{cid} → expected:{expected}  status:{status}")
        for s in row.get("correct_sessions", []):
            print(f"      real session: {s['session_key']}  (channel: {s.get('group_channel', '')})")
        for s in row.get("stale_legacy_sessions", []):
            print(f"      STALE legacy session: {s['session_key']} in {s['sessions_file']}")
            print(f"        → Host will create agent:{expected}:discord:channel:{cid} on next inbound message.")
            print(f"        → To force now: remove stale entry from {s['sessions_file']}")
        for s in row.get("wrong_canonical_sessions", []):
            print(f"      WRONG canonical agent: {s['session_key']}")
    if ghosts:
        print(f"  Ghost sessions (channel not in bindings config):")
        for g in ghosts:
            print(f"    {g['session_key']}  channel:{g['channel_id']}")
    note = audit.get("operatorNote") or ""
    if note:
        print(f"  Note: {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the live OpenClaw bootstrap wiring for agent-specific runtime files.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to ~/.openclaw/openclaw.json")
    parser.add_argument("--handler", type=Path, default=DEFAULT_HANDLER_PATH, help="Path to installed bootstrap-extra-files handler.js")
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE_PATH, help="Path to installed auth-profiles bundle")
    parser.add_argument("--agent", action="append", dest="agents", help="Restrict output to one or more agent ids")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    report = _build_report(
        config_path=args.config.expanduser().resolve(),
        handler_path=args.handler.expanduser().resolve(),
        bundle_path=args.bundle.expanduser().resolve(),
        agent_ids=args.agents,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)
        _print_specialist_channel_audit(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
