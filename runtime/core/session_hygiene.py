#!/usr/bin/env python3
"""Automatic orchestration session hygiene.

Detects oversized or saturated orchestration sessions for Jarvis, HAL, and
Archimedes, archives their transcripts, and resets session metadata so the
gateway sees a clean session on the next turn.

Only touches main orchestration sessions (``agent:{agent}:main``).
Discord-bound sessions and unrelated agents are never modified.

Designed to be called from the context engine CLI before every model send.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Optional


# ── Thresholds ──────────────────────────────────────────────────────────────
# Transcript file > this many bytes triggers rotation.
TRANSCRIPT_SIZE_THRESHOLD_BYTES = 50_000  # ~50 KB
# Transcript file > this many lines triggers rotation.
TRANSCRIPT_LINE_THRESHOLD = 80
# Only these agents' main sessions are candidates for hygiene.
ORCHESTRATION_AGENTS = ("jarvis", "hal", "archimedes")
# Session key pattern for orchestration sessions.
_MAIN_SESSION_KEY_TEMPLATE = "agent:{agent}:main"


_ROTATION_COUNTER = 0


def _now_stamp() -> str:
    global _ROTATION_COUNTER
    _ROTATION_COUNTER += 1
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + f"-{_ROTATION_COUNTER:03d}"


def _count_lines(path: Path) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except Exception:
        return 0


def _load_sessions_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_sessions_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def check_and_rotate_orchestration_session(
    *,
    agent_id: str,
    openclaw_root: Path,
    size_threshold: int = TRANSCRIPT_SIZE_THRESHOLD_BYTES,
    line_threshold: int = TRANSCRIPT_LINE_THRESHOLD,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Check a single orchestration agent's main session and rotate if needed.

    Returns a report dict with keys:
        agent, action, reason, transcript_bytes, transcript_lines,
        archive_path (if rotated), error (if any)
    """
    agent = str(agent_id).strip().lower()
    report: dict[str, Any] = {
        "agent": agent,
        "action": "none",
        "reason": "",
        "transcript_bytes": 0,
        "transcript_lines": 0,
        "archive_path": None,
        "error": None,
    }

    sessions_dir = openclaw_root / "agents" / agent / "sessions"
    sessions_json_path = sessions_dir / "sessions.json"

    if not sessions_json_path.exists():
        report["action"] = "skip"
        report["reason"] = "no_sessions_json"
        return report

    sessions_data = _load_sessions_json(sessions_json_path)
    main_key = _MAIN_SESSION_KEY_TEMPLATE.format(agent=agent)
    entry = sessions_data.get(main_key)

    if not entry or not isinstance(entry, dict):
        report["action"] = "skip"
        report["reason"] = "no_main_session_entry"
        return report

    # Resolve transcript file path.
    session_file = entry.get("sessionFile") or ""
    if not session_file:
        session_id = entry.get("sessionId") or ""
        if session_id:
            session_file = str(sessions_dir / f"{session_id}.jsonl")

    if not session_file:
        report["action"] = "skip"
        report["reason"] = "no_transcript_path"
        return report

    transcript_path = Path(session_file)
    if not transcript_path.exists():
        report["action"] = "skip"
        report["reason"] = "transcript_missing"
        return report

    # Measure transcript.
    try:
        file_size = transcript_path.stat().st_size
    except Exception:
        file_size = 0
    line_count = _count_lines(transcript_path)
    report["transcript_bytes"] = file_size
    report["transcript_lines"] = line_count

    needs_rotation = file_size > size_threshold or line_count > line_threshold

    if not needs_rotation:
        report["action"] = "ok"
        report["reason"] = "within_thresholds"
        return report

    if dry_run:
        report["action"] = "would_rotate"
        report["reason"] = (
            f"over_threshold: {file_size}B>{size_threshold}B"
            if file_size > size_threshold
            else f"over_threshold: {line_count}lines>{line_threshold}lines"
        )
        return report

    # ── Rotate: archive transcript, truncate, reset metadata ──
    stamp = _now_stamp()
    try:
        archive_name = f"hygiene-{stamp}-{transcript_path.name}"
        archive_path = transcript_path.parent / archive_name
        shutil.copy2(transcript_path, archive_path)
        # Truncate original transcript.
        transcript_path.write_text("", encoding="utf-8")
        report["archive_path"] = str(archive_path)
    except Exception as exc:
        report["action"] = "error"
        report["error"] = f"archive_failed: {exc}"
        return report

    # Reset session metadata in sessions.json.
    try:
        if main_key in sessions_data:
            sessions_data[main_key]["contextTokens"] = None
            sessions_data[main_key]["tokens"] = None
            sessions_data[main_key]["model"] = None
        _save_sessions_json(sessions_json_path, sessions_data)
    except Exception as exc:
        report["action"] = "partial"
        report["error"] = f"metadata_reset_failed: {exc}"
        return report

    report["action"] = "rotated"
    report["reason"] = (
        f"transcript_oversized: {file_size}B/{line_count}lines"
    )
    return report


def run_orchestration_hygiene(
    *,
    openclaw_root: Path,
    agents: tuple[str, ...] = ORCHESTRATION_AGENTS,
    size_threshold: int = TRANSCRIPT_SIZE_THRESHOLD_BYTES,
    line_threshold: int = TRANSCRIPT_LINE_THRESHOLD,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Run hygiene checks for all orchestration agents.

    Returns a list of per-agent reports.
    """
    reports: list[dict[str, Any]] = []
    for agent in agents:
        report = check_and_rotate_orchestration_session(
            agent_id=agent,
            openclaw_root=openclaw_root,
            size_threshold=size_threshold,
            line_threshold=line_threshold,
            dry_run=dry_run,
        )
        reports.append(report)
    return reports


def pre_context_build_hygiene(
    *,
    session_key: str,
    openclaw_root: Optional[Path] = None,
    size_threshold: int = TRANSCRIPT_SIZE_THRESHOLD_BYTES,
    line_threshold: int = TRANSCRIPT_LINE_THRESHOLD,
) -> Optional[dict[str, Any]]:
    """Lightweight hygiene check for a single session before context build.

    Only acts on orchestration main sessions.  Returns the report if
    rotation was performed, None otherwise.
    """
    if not session_key:
        return None

    # Only act on orchestration main sessions.
    agent_id = ""
    for agent in ORCHESTRATION_AGENTS:
        if session_key.startswith(f"agent:{agent}:main"):
            agent_id = agent
            break
    if not agent_id:
        return None

    if openclaw_root is None:
        candidate = Path.home() / ".openclaw"
        if not candidate.exists():
            return None
        openclaw_root = candidate

    report = check_and_rotate_orchestration_session(
        agent_id=agent_id,
        openclaw_root=openclaw_root,
        size_threshold=size_threshold,
        line_threshold=line_threshold,
    )
    if report.get("action") == "rotated":
        return report
    return None
