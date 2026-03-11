#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.heartbeat_reports import build_heartbeat_report_summary, save_heartbeat_report
from runtime.core.models import HeartbeatReportRecord, HeartbeatStatus, new_id, now_iso
from runtime.core.status import summarize_status


def _folder_counts(path: Path) -> dict:
    if not path.exists():
        return {"exists": False, "json_files": 0}
    return {"exists": True, "json_files": len(list(path.glob("*.json")))}


def _budget_remaining(status: dict) -> dict:
    latest_budget = ((status.get("token_budget_summary") or {}).get("latest_token_budget") or {})
    if not latest_budget:
        return {}
    usage = dict(latest_budget.get("current_usage") or {})
    return {
        "tokens_per_task": latest_budget.get("max_tokens_per_task"),
        "tokens_per_cycle": latest_budget.get("max_tokens_per_cycle"),
        "cost_usd_per_cycle": latest_budget.get("max_cost_usd_per_cycle"),
        "current_usage": usage,
    }


def _make_subsystem_record(
    *,
    subsystem_name: str,
    status: str,
    current_task_count: int,
    error_summary: str,
    budget_remaining: dict,
    source_refs: dict,
) -> HeartbeatReportRecord:
    timestamp = now_iso()
    return HeartbeatReportRecord(
        heartbeat_report_id=new_id("heartbeat"),
        subsystem_name=subsystem_name,
        created_at=timestamp,
        updated_at=timestamp,
        status=status,
        last_active_at=timestamp,
        current_task_count=current_task_count,
        error_summary=error_summary,
        budget_remaining=budget_remaining,
        source_refs=source_refs,
    )


def _subsystem_heartbeat_rows(root: Path, status: dict, degraded_signals: list[str]) -> list[HeartbeatReportRecord]:
    control = (status.get("control_state", {}) or {}).get("effective", {})
    token_budget = _budget_remaining(status)
    blocked_count = status.get("counts", {}).get("blocked", 0)
    running_count = status.get("counts", {}).get("running", 0)
    waiting_review = status.get("counts", {}).get("waiting_review", 0)
    waiting_approval = status.get("counts", {}).get("waiting_approval", 0)

    hermes_status = HeartbeatStatus.HEALTHY.value
    hermes_error = ""
    degradation_summary = status.get("degradation_summary", {}) or {}
    latest_degradation = degradation_summary.get("latest_degradation_event") or {}
    if latest_degradation.get("subsystem") == "hermes_adapter":
        failure_category = latest_degradation.get("failure_category") or "degraded"
        if failure_category == "unreachable_backend":
            hermes_status = HeartbeatStatus.UNREACHABLE.value
        else:
            hermes_status = HeartbeatStatus.DEGRADED.value
        hermes_error = latest_degradation.get("reason") or failure_category

    subsystem_rows = [
        _make_subsystem_record(
            subsystem_name="local_core",
            status=HeartbeatStatus.DEGRADED.value if degraded_signals else HeartbeatStatus.HEALTHY.value,
            current_task_count=running_count + blocked_count,
            error_summary=", ".join(degraded_signals),
            budget_remaining=token_budget,
            source_refs={"status_generated_at": status.get("generated_at")},
        ),
        _make_subsystem_record(
            subsystem_name="Hermes",
            status=hermes_status,
            current_task_count=running_count,
            error_summary=hermes_error,
            budget_remaining=token_budget,
            source_refs={"latest_degradation_event_id": latest_degradation.get("degradation_event_id")},
        ),
        _make_subsystem_record(
            subsystem_name="autoresearch",
            status=HeartbeatStatus.HEALTHY.value,
            current_task_count=running_count,
            error_summary="",
            budget_remaining=token_budget,
            source_refs={},
        ),
        _make_subsystem_record(
            subsystem_name="Ralph",
            status=HeartbeatStatus.HEALTHY.value,
            current_task_count=0,
            error_summary="",
            budget_remaining=token_budget,
            source_refs={},
        ),
        _make_subsystem_record(
            subsystem_name="browser_automation",
            status=HeartbeatStatus.STOPPED.value,
            current_task_count=0,
            error_summary="not_enabled_by_policy",
            budget_remaining={},
            source_refs={"policy": "multimodal_scaffolding_only"},
        ),
        _make_subsystem_record(
            subsystem_name="voice",
            status=HeartbeatStatus.STOPPED.value,
            current_task_count=0,
            error_summary="not_enabled_by_policy",
            budget_remaining={},
            source_refs={"policy": "multimodal_scaffolding_only"},
        ),
        _make_subsystem_record(
            subsystem_name="reviewer_lane",
            status=HeartbeatStatus.HEALTHY.value,
            current_task_count=waiting_review,
            error_summary="",
            budget_remaining={},
            source_refs={},
        ),
        _make_subsystem_record(
            subsystem_name="auditor_lane",
            status=HeartbeatStatus.HEALTHY.value,
            current_task_count=waiting_approval,
            error_summary="",
            budget_remaining={},
            source_refs={},
        ),
    ]

    if control.get("effective_status") == "stopped":
        for row in subsystem_rows:
            if row.subsystem_name in {"local_core", "Hermes", "autoresearch", "Ralph"}:
                row.status = HeartbeatStatus.STOPPED.value
                row.error_summary = "control_state_stopped"
    return subsystem_rows


def build_heartbeat_report(root: Path) -> dict:
    logs_dir = root / "state" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    status = summarize_status(root)

    subsystems = {
        "tasks": _folder_counts(root / "state" / "tasks"),
        "events": _folder_counts(root / "state" / "events"),
        "reviews": _folder_counts(root / "state" / "reviews"),
        "approvals": _folder_counts(root / "state" / "approvals"),
        "approval_checkpoints": _folder_counts(root / "state" / "approval_checkpoints"),
        "artifacts": _folder_counts(root / "state" / "artifacts"),
        "outputs": _folder_counts(root / "workspace" / "out"),
        "logs": _folder_counts(logs_dir),
    }

    degraded_signals: list[str] = []
    if status["counts"].get("revoked_outputs", 0):
        degraded_signals.append("revoked_outputs_present")
    if status["counts"].get("revoked_artifacts", 0):
        degraded_signals.append("revoked_artifacts_present")
    if status["counts"].get("blocked", 0):
        degraded_signals.append("blocked_tasks_present")
    if status["counts"].get("paused_controls", 0):
        degraded_signals.append("paused_controls_present")
    if status["counts"].get("stopped_controls", 0):
        degraded_signals.append("stopped_controls_present")
    if status["counts"].get("degraded_controls", 0):
        degraded_signals.append("degraded_controls_present")
    if status["counts"].get("revoked_controls", 0):
        degraded_signals.append("revoked_controls_present")
    for name, info in subsystems.items():
        if not info["exists"]:
            degraded_signals.append(f"missing_{name}_dir")

    subsystem_heartbeats = _subsystem_heartbeat_rows(root, status, degraded_signals)
    for row in subsystem_heartbeats:
        save_heartbeat_report(row, root=root)
    heartbeat_summary = build_heartbeat_report_summary(root=root)

    heartbeat = {
        "schema_version": "v5.1",
        "generated_at": now_iso(),
        "heartbeat_kind": "jarvis_status_heartbeat",
        "repo_root": str(root),
        "overall_health": "degraded" if degraded_signals else "ok",
        "degraded_signals": degraded_signals,
        "status_counts": status.get("counts", {}),
        "control_state": status.get("control_state", {}),
        "subsystems": subsystems,
        "subsystem_heartbeats": [row.to_dict() for row in subsystem_heartbeats],
        "heartbeat_summary": heartbeat_summary,
        "work_summary": {
            "running": status.get("running_now", []),
            "blocked": status.get("blocked", []),
            "waiting_review": status.get("waiting_review", []),
            "waiting_approval": status.get("waiting_approval", []),
            "ready_to_ship": status.get("ready_to_ship", []),
            "shipped": status.get("shipped", []),
            "impacted_outputs": status.get("impacted_outputs", []),
            "revoked_outputs": status.get("revoked_outputs", []),
            "revoked_artifacts": status.get("revoked_artifacts", []),
        },
        "next_recommended_move": status.get("next_recommended_move", ""),
    }

    out_path = logs_dir / "heartbeat_report.json"
    out_path.write_text(json.dumps(heartbeat, indent=2) + "\n", encoding="utf-8")
    return heartbeat


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a durable repo heartbeat report.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    result = build_heartbeat_report(Path(args.root).resolve())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
