#!/usr/bin/env python3
"""discord_event_router — normalize runtime events → owner channel + outbox entries.

Design rules:
  - Local structured state is truth. Discord is presentation.
  - No LLM calls. Status text is deterministic English templates.
  - Cadence channel is VOICE-ONLY. Non-voice events are rejected/rerouted.
  - Every event writes a dispatch_event record.
  - Outbox entries written to state/discord_outbox/ for delivery.

Event kinds supported:
    task_created, task_started, task_progress, task_completed, task_failed,
    task_blocked, review_requested, review_completed, approval_requested,
    approval_completed, artifact_promoted, browser_action, browser_result,
    voice_session_started, voice_session_ended, tts_started, tts_completed,
    call_started, call_ended, agent_online, agent_offline, agent_status,
    delegation_sent, delegation_received, warning, error
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import new_id, now_iso


# ---------------------------------------------------------------------------
# Load channel map
# ---------------------------------------------------------------------------

def _load_channel_map(root: Optional[Path] = None) -> dict[str, Any]:
    base = Path(root or ROOT).resolve()
    path = base / "config" / "agent_channel_map.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# State directories
# ---------------------------------------------------------------------------

def _dispatch_dir(root: Optional[Path] = None) -> Path:
    d = Path(root or ROOT).resolve() / "state" / "dispatch_events"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _outbox_dir(root: Optional[Path] = None) -> Path:
    d = Path(root or ROOT).resolve() / "state" / "discord_outbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Deterministic status text templates
# ---------------------------------------------------------------------------

_AGENT_DISPLAY: dict[str, str] = {
    "jarvis": "Jarvis", "hal": "HAL", "scout": "Scout",
    "anton": "Anton", "archimedes": "Archimedes", "hermes": "Hermes",
    "kitt": "Kitt", "claude": "Claude", "qwen": "Qwen",
    "bowser": "Bowser", "cadence": "Cadence", "muse": "Muse", "ralph": "Ralph",
}


def _display(agent_id: str) -> str:
    return _AGENT_DISPLAY.get(agent_id, agent_id.capitalize())


def _render_status_text(kind: str, payload: dict[str, Any]) -> str:
    """Produce a deterministic plain-English status line for a runtime event."""
    agent = _display(payload.get("agent_id", "unknown"))
    task_id = payload.get("task_id", "")
    task_label = f" {task_id}:" if task_id else ""
    detail = payload.get("detail", "")
    target = payload.get("target", "")
    reviewer = _display(payload.get("reviewer_id", ""))
    artifact = payload.get("artifact_id", "")

    templates: dict[str, str] = {
        "task_created":        f"{agent} created task{task_label} {detail}",
        "task_started":        f"{agent} started task{task_label} {detail}",
        "task_progress":       f"{agent} task{task_label} in progress. {detail}",
        "task_completed":      f"{agent} completed task{task_label} {detail}",
        "task_failed":         f"{agent} FAILED task{task_label} {detail}",
        "task_blocked":        f"{agent} task{task_label} BLOCKED. {detail}",
        "review_requested":    f"{agent} requested review for task{task_label} {detail}",
        "review_completed":    f"{reviewer or agent} completed review for task{task_label} {detail}",
        "approval_requested":  f"{agent} requires approval for task{task_label} {detail}",
        "approval_completed":  f"Approval completed for task{task_label} {detail}",
        "artifact_promoted":   f"{agent} promoted artifact {artifact}. {detail}",
        "browser_action":      f"{agent} executing browser action on {target}.",
        "browser_result":      f"{agent} completed browser action on {target}. {detail}",
        "voice_session_started": "Cadence voice session started.",
        "voice_session_ended":   "Cadence voice session ended.",
        "tts_started":           "Cadence TTS started.",
        "tts_completed":         "Cadence TTS completed.",
        "call_started":          "Cadence call started.",
        "call_ended":            "Cadence call ended.",
        "agent_online":        f"{agent} is online.",
        "agent_offline":       f"{agent} went offline.",
        "agent_status":        f"{agent}: {detail}",
        "delegation_sent":     f"{agent} delegated task{task_label} to {target}.",
        "delegation_received": f"{agent} received delegation{task_label} from {target}.",
        "warning":             f"WARNING [{agent}]: {detail}",
        "error":               f"ERROR [{agent}]: {detail}",
    }
    text = templates.get(kind, f"{agent}: [{kind}] {detail}")
    return text.strip()


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------

def _resolve_owner_channel_id(
    kind: str,
    agent_id: str,
    channel_map: dict[str, Any],
) -> Optional[str]:
    """Return the Discord channel ID that should receive this event."""
    agents = channel_map.get("agents", {})
    voice_only_kinds = set(channel_map.get("voice_only_event_kinds", []))

    # Voice events always go to cadence
    if kind in voice_only_kinds:
        return agents.get("cadence", {}).get("channel_id")

    # For known agents, use their channel
    entry = agents.get(agent_id, {})
    ch_id = entry.get("channel_id")

    # If the resolved channel is cadence but event is NOT voice → reject
    cadence_ch = agents.get("cadence", {}).get("channel_id")
    if ch_id and ch_id == cadence_ch and kind not in voice_only_kinds:
        return None  # blocked

    return ch_id


def _should_mirror_worklog(kind: str, channel_map: dict[str, Any]) -> bool:
    return kind in set(channel_map.get("worklog_mirror_event_kinds", []))


def _should_forward_jarvis(kind: str, channel_map: dict[str, Any]) -> bool:
    return kind in set(channel_map.get("jarvis_forward_event_kinds", []))


# ---------------------------------------------------------------------------
# Outbox entry
# ---------------------------------------------------------------------------

def _write_outbox_entry(
    channel_id: str,
    text: str,
    event_id: str,
    kind: str,
    label: str,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    entry_id = new_id("outbox")
    entry: dict[str, Any] = {
        "entry_id": entry_id,
        "created_at": now_iso(),
        "channel_id": channel_id,
        "text": text,
        "source_event_id": event_id,
        "event_kind": kind,
        "label": label,
        "status": "pending",
    }
    path = _outbox_dir(root) / f"{entry_id}.json"
    path.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    return entry


# ---------------------------------------------------------------------------
# Main public interface
# ---------------------------------------------------------------------------

def emit_event(
    kind: str,
    agent_id: str,
    *,
    task_id: str = "",
    detail: str = "",
    target: str = "",
    reviewer_id: str = "",
    artifact_id: str = "",
    extra: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Create a dispatch_event record and write outbox entries for Discord routing.

    Returns a summary dict with:
        event_id, owner_channel_id, worklog_mirrored, jarvis_forwarded,
        cadence_blocked, text, outbox_entries
    """
    resolved_root = Path(root or ROOT).resolve()
    channel_map = _load_channel_map(resolved_root)

    event_id = new_id("devt")
    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "task_id": task_id,
        "detail": detail,
        "target": target,
        "reviewer_id": reviewer_id,
        "artifact_id": artifact_id,
        **(extra or {}),
    }

    # Resolve owner channel
    owner_ch = _resolve_owner_channel_id(kind, agent_id, channel_map)
    cadence_blocked = False
    agents = channel_map.get("agents", {})
    voice_only_kinds = set(channel_map.get("voice_only_event_kinds", []))

    # Detect cadence block: agent is cadence but event is non-voice
    cadence_entry = agents.get("cadence", {})
    cadence_ch = cadence_entry.get("channel_id")
    if kind not in voice_only_kinds and agent_id == "cadence":
        cadence_blocked = True
        owner_ch = None  # blocked

    # Render text
    text = _render_status_text(kind, payload)

    # Worklog + Jarvis decisions
    mirror_worklog = _should_mirror_worklog(kind, channel_map)
    forward_jarvis = _should_forward_jarvis(kind, channel_map)
    worklog_ch = channel_map.get("logical_channels", {}).get("worklog", {}).get("channel_id")
    jarvis_ch = channel_map.get("logical_channels", {}).get("jarvis", {}).get("channel_id")

    # Build dispatch event record
    dispatch_record: dict[str, Any] = {
        "event_id": event_id,
        "created_at": now_iso(),
        "kind": kind,
        "agent_id": agent_id,
        "task_id": task_id,
        "owner_channel_id": owner_ch,
        "worklog_mirrored": mirror_worklog and bool(worklog_ch),
        "jarvis_forwarded": forward_jarvis and bool(jarvis_ch) and (owner_ch != jarvis_ch),
        "cadence_blocked": cadence_blocked,
        "text": text,
        "payload": payload,
    }
    dp = _dispatch_dir(resolved_root) / f"{event_id}.json"
    dp.write_text(json.dumps(dispatch_record, indent=2) + "\n", encoding="utf-8")

    # Write outbox entries
    outbox_entries: list[dict[str, Any]] = []

    if owner_ch and not cadence_blocked:
        outbox_entries.append(_write_outbox_entry(
            owner_ch, text, event_id, kind, "owner", resolved_root,
        ))

    if mirror_worklog and worklog_ch and worklog_ch != owner_ch:
        outbox_entries.append(_write_outbox_entry(
            worklog_ch, text, event_id, kind, "worklog", resolved_root,
        ))

    # Jarvis forward (skip if owner IS jarvis already to avoid duplicate)
    if forward_jarvis and jarvis_ch and jarvis_ch != owner_ch:
        outbox_entries.append(_write_outbox_entry(
            jarvis_ch, text, event_id, kind, "jarvis_fwd", resolved_root,
        ))

    return {
        "event_id": event_id,
        "kind": kind,
        "owner_channel_id": owner_ch,
        "worklog_mirrored": dispatch_record["worklog_mirrored"],
        "jarvis_forwarded": dispatch_record["jarvis_forwarded"],
        "cadence_blocked": cadence_blocked,
        "text": text,
        "outbox_entries": outbox_entries,
    }


def route_event(
    kind: str,
    agent_id: str,
    payload: dict[str, Any],
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Lower-level: just compute routing decision without writing state.

    Returns dict with owner_channel_id, worklog_mirror, jarvis_forward,
    cadence_blocked, rendered_text.
    """
    resolved_root = Path(root or ROOT).resolve()
    channel_map = _load_channel_map(resolved_root)
    voice_only_kinds = set(channel_map.get("voice_only_event_kinds", []))
    agents = channel_map.get("agents", {})
    cadence_ch = agents.get("cadence", {}).get("channel_id")

    cadence_blocked = agent_id == "cadence" and kind not in voice_only_kinds
    owner_ch = None if cadence_blocked else _resolve_owner_channel_id(kind, agent_id, channel_map)
    text = _render_status_text(kind, payload)

    worklog_ch = channel_map.get("logical_channels", {}).get("worklog", {}).get("channel_id")
    jarvis_ch = channel_map.get("logical_channels", {}).get("jarvis", {}).get("channel_id")

    return {
        "owner_channel_id": owner_ch,
        "worklog_mirror": _should_mirror_worklog(kind, channel_map) and bool(worklog_ch),
        "jarvis_forward": _should_forward_jarvis(kind, channel_map) and bool(jarvis_ch),
        "cadence_blocked": cadence_blocked,
        "text": text,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Discord event router CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_emit = sub.add_parser("emit", help="Emit an event and write outbox")
    p_emit.add_argument("kind")
    p_emit.add_argument("agent_id")
    p_emit.add_argument("--task-id", default="")
    p_emit.add_argument("--detail", default="")
    p_emit.add_argument("--target", default="")

    p_route = sub.add_parser("route", help="Show routing decision (no writes)")
    p_route.add_argument("kind")
    p_route.add_argument("agent_id")
    p_route.add_argument("--detail", default="")

    args = parser.parse_args()
    if args.cmd == "emit":
        result = emit_event(
            args.kind, args.agent_id,
            task_id=args.task_id, detail=args.detail, target=args.target,
        )
        print(json.dumps(result, indent=2, default=str))
    elif args.cmd == "route":
        result = route_event(args.kind, args.agent_id, {"detail": args.detail})
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
