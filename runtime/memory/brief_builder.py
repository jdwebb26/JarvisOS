#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.core.models import now_iso


ROOT = Path(__file__).resolve().parents[2]


def _resolved_root(root: Optional[Path] = None) -> Path:
    return Path(root or ROOT).resolve()


def _brief_payload(*, brief_kind: str, title: str, summary: str, sections: list[tuple[str, list[str]]], source_refs: dict[str, Any]) -> dict[str, Any]:
    lines = [
        f"# {title}",
        "",
        "_Derived governed brief. Runtime truth remains in Jarvis state, approvals, reviews, and provenance records._",
        "",
        f"- Brief Kind: `{brief_kind}`",
        f"- Summary: {summary}",
        "",
    ]
    for heading, body in sections:
        lines.append(f"## {heading}")
        lines.append("")
        lines.extend(body or ["_No data._"])
        lines.append("")
    return {
        "brief_kind": brief_kind,
        "title": title,
        "summary": summary,
        "markdown": "\n".join(lines).rstrip() + "\n",
        "source_refs": source_refs,
        "non_authoritative": True,
    }


def build_daily_brief_payload(*, root: Optional[Path] = None) -> dict[str, Any]:
    resolved_root = _resolved_root(root)
    snapshot = build_operator_snapshot(resolved_root)
    state = build_state_export(resolved_root)
    counts = dict(snapshot.get("counts") or {})
    degradation = dict(snapshot.get("degradation_summary") or {})
    sections = [
        (
            "Operator Focus",
            [
                str(snapshot.get("operator_focus") or "No operator focus available."),
                f"Pending reviews: {counts.get('pending_reviews', 0)}",
                f"Pending approvals: {counts.get('pending_approvals', 0)}",
                f"Ready to ship: {counts.get('ready_to_ship', 0)}",
            ],
        ),
        (
            "Degraded Posture",
            [
                f"Active degradation modes: {degradation.get('active_degradation_mode_count', 0)}",
                f"Operator-notify events: {degradation.get('operator_notification_required_event_count', 0)}",
                f"Blocked tasks: {counts.get('blocked', 0)}",
            ],
        ),
        (
            "Memory And Provenance",
            [
                f"Memory entries: {(state.get('memory_discipline_summary') or {}).get('memory_entry_count', 0)}",
                f"Artifact provenance records: {(state.get('provenance_summary') or {}).get('artifact_provenance_count', 0)}",
                f"Routing provenance records: {(state.get('provenance_summary') or {}).get('routing_provenance_count', 0)}",
            ],
        ),
    ]
    return _brief_payload(
        brief_kind="daily",
        title="Jarvis Daily Brief",
        summary="Daily derived operator brief.",
        sections=sections,
        source_refs={
            "operator_snapshot_log": str(resolved_root / "state" / "logs" / "operator_snapshot.json"),
            "state_export_log": str(resolved_root / "state" / "logs" / "state_export.json"),
            "latest_task_provenance_id": ((state.get("provenance_summary") or {}).get("latest_task_provenance") or {}).get("task_provenance_id"),
            "latest_artifact_provenance_id": ((state.get("provenance_summary") or {}).get("latest_artifact_provenance") or {}).get("artifact_provenance_id"),
        },
    )


def build_weekly_brief_payload(*, root: Optional[Path] = None) -> dict[str, Any]:
    resolved_root = _resolved_root(root)
    state = build_state_export(resolved_root)
    candidate = dict(state.get("candidate_promotion_summary") or {})
    replay = dict(state.get("replay_summary") or {})
    skill_registry = dict((state.get("skill_scheduler_summary") or {}).get("registry_summary") or {})
    skill_candidate_summary = dict(skill_registry.get("skill_candidate_summary") or {})
    sections = [
        (
            "Promotion Posture",
            [
                f"Candidates: {candidate.get('candidate_count', 0)}",
                f"Promotable candidates: {candidate.get('promotable_candidate_count', 0)}",
                f"Promoted candidates: {candidate.get('promoted_candidate_count', 0)}",
            ],
        ),
        (
            "Replay And Eval",
            [
                f"Replay plans: {replay.get('replay_plan_count', 0)}",
                f"Replay executions: {replay.get('replay_execution_count', 0)}",
                f"Replay results: {replay.get('replay_result_count', 0)}",
            ],
        ),
        (
            "Skill And Lease Readiness",
            [
                f"Approved skills: {skill_registry.get('approved_skill_count', 0)}",
                f"Skill candidates: {skill_candidate_summary.get('skill_candidate_count', 0)}",
                f"Active task leases: {(state.get('task_lease_summary') or {}).get('active_task_lease_count', 0)}",
            ],
        ),
    ]
    return _brief_payload(
        brief_kind="weekly",
        title="Jarvis Weekly Brief",
        summary="Weekly derived runtime and operator brief.",
        sections=sections,
        source_refs={
            "state_export_log": str(resolved_root / "state" / "logs" / "state_export.json"),
            "latest_replay_result_id": (replay.get("latest_replay_result") or {}).get("replay_result_id"),
            "latest_candidate_id": (candidate.get("latest_candidate") or {}).get("candidate_id"),
        },
    )


def build_session_context_brief_payload(
    *,
    session_key: str,
    objective: str,
    unresolved_questions: list[str],
    active_constraints: list[str],
    recent_decisions: list[str],
    tool_findings: list[str],
    operator_preferences: list[str],
    source_refs: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    sections = [
        ("Current Objective", [objective or "No active objective captured."]),
        ("Unresolved Questions", unresolved_questions or ["None."]),
        ("Active Constraints", active_constraints or ["None."]),
        ("Recent Decisions", recent_decisions or ["None."]),
        ("Tool Findings", tool_findings or ["None."]),
        ("Operator Preferences", operator_preferences or ["None."]),
    ]
    payload = _brief_payload(
        brief_kind="session_context",
        title=f"Session Context Summary: {session_key}",
        summary=objective or "Rolling session context summary.",
        sections=sections,
        source_refs=source_refs or {},
    )
    payload.update(
        {
            "session_key": session_key,
            "objective": objective,
            "unresolved_questions": list(unresolved_questions or []),
            "active_constraints": list(active_constraints or []),
            "recent_decisions": list(recent_decisions or []),
            "tool_findings": list(tool_findings or []),
            "operator_preferences": list(operator_preferences or []),
            "generated_at": now_iso(),
            "updated_at": now_iso(),
        }
    )
    return payload
