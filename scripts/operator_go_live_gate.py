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

from runtime.core.status import build_status
from scripts.preflight_lib import write_report


def _load_report(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _lane_activation_row(summary: dict[str, Any], lane: str) -> dict[str, Any]:
    for row in list(summary.get("rows") or []):
        if row.get("lane") == lane:
            return row
    return {}


def _classify_blocked_lane(
    row: dict[str, Any],
    activation_row: dict[str, Any],
    *,
    lane: str,
    shadowbroker_summary: dict[str, Any],
    research_backend_summary: dict[str, Any],
    hermes_summary: dict[str, Any],
    autoresearch_summary: dict[str, Any],
    local_model_lane_proof_summary: dict[str, Any],
) -> str:
    activation_status = str(activation_row.get("latest_activation_status") or "not_run").lower()
    activation_runtime_status = str(activation_row.get("latest_runtime_status") or "").lower()
    reason = " ".join(
        [
            str(row.get("reason") or ""),
            activation_runtime_status,
            str(activation_row.get("error") or ""),
            str(activation_row.get("details") or ""),
        ]
    ).lower()
    if lane == "shadowbroker":
        backend_status = str(shadowbroker_summary.get("backend_status") or "").lower()
        if not shadowbroker_summary.get("configured") or backend_status == "blocked_shadowbroker_not_configured":
            return "BLOCKED BY CONFIG"
        if backend_status == "blocked_shadowbroker_invalid_config":
            return "BLOCKED BY CONFIG"
        if shadowbroker_summary.get("configured") and not shadowbroker_summary.get("healthy"):
            return "BLOCKED BY EXTERNAL RUNTIME"
        return "BLOCKED BY CONFIG"
    if lane == "searxng":
        latest_checks = list(research_backend_summary.get("latest_backend_healthchecks") or [])
        latest = latest_checks[0] if latest_checks else {}
        text = " ".join([reason, str(latest.get("status") or ""), str(latest.get("details") or "")]).lower()
        if "not configured" in text or "missing" in text:
            return "BLOCKED BY CONFIG"
        return "BLOCKED BY EXTERNAL RUNTIME"
    if lane == "hermes_bridge":
        latest_result = dict(hermes_summary.get("latest_hermes_result") or {})
        latest_status = str(latest_result.get("status") or "").lower()
        failure_category = str(latest_result.get("failure_category") or "").lower()
        text = " ".join([reason, latest_status, failure_category])
        if any(token in text for token in ("not configured", "missing", "invalid_request_contract")):
            return "BLOCKED BY CONFIG"
        return "BLOCKED BY EXTERNAL RUNTIME"
    if lane == "autoresearch_upstream_bridge":
        latest_runtime = dict(autoresearch_summary.get("latest_upstream_runtime") or {})
        latest_status = str(latest_runtime.get("status") or "").lower()
        latest_runtime_status = str(latest_runtime.get("runtime_status") or "").lower()
        text = " ".join([reason, latest_status, latest_runtime_status])
        if any(token in text for token in ("not configured", "invalid_request_contract", "blocked", "missing")):
            return "BLOCKED BY CONFIG"
        return "BLOCKED BY EXTERNAL RUNTIME"
    if lane in {"adaptation_lab_unsloth", "optimizer_dspy"}:
        proof_rows = {
            str(entry.get("lane") or ""): entry
            for entry in list(local_model_lane_proof_summary.get("rows") or [])
        }
        proof_row = proof_rows.get(lane, {})
        proof_status = str(proof_row.get("latest_runtime_status") or activation_runtime_status).lower()
        if activation_status == "not_run":
            return "BLOCKED BY CONFIG"
        if any(token in proof_status for token in ("blocked_missing", "invalid_base_model_ref", "invalid_dataset_contract")):
            return "BLOCKED BY CONFIG"
        return "BLOCKED BY EXTERNAL RUNTIME"
    if any(token in reason for token in ("not configured", "missing_", "blocked_missing", "no tiny proof model", "set ")):
        return "BLOCKED BY CONFIG"
    return "BLOCKED BY EXTERNAL RUNTIME"


def build_operator_go_live_gate(*, root: Path) -> dict[str, Any]:
    status = build_status(root)
    routing = dict(status.get("routing_control_plane_summary") or {})
    extension = dict(status.get("extension_lane_status_summary") or {})
    activation = dict(status.get("lane_activation_summary") or {})
    local_proof = dict(status.get("local_model_lane_proof_summary") or {})
    workspaces = dict(status.get("workspace_registry_summary") or {})
    shadowbroker = dict(status.get("shadowbroker_summary") or {})
    research_backend = dict(status.get("research_backend_summary") or {})
    hermes = dict(status.get("hermes_summary") or {})
    autoresearch = dict(status.get("autoresearch_summary") or {})
    adaptation = dict(status.get("adaptation_lab_summary") or {})
    optimizer = dict(status.get("optimizer_summary") or {})

    validate_report = _load_report(root / "state" / "logs" / "validate_report.json")
    smoke_report = _load_report(root / "state" / "logs" / "smoke_test_report.json")
    validate_ok = bool((validate_report or {}).get("ok"))
    smoke_ok = bool((smoke_report or {}).get("ok"))

    live_lanes: list[dict[str, Any]] = []
    blocked_lanes: list[dict[str, Any]] = []
    scaffold_lanes: list[dict[str, Any]] = []
    deprecated_aliases: list[dict[str, Any]] = []
    categories = {
        "READY NOW": [],
        "BLOCKED BY CONFIG": [],
        "BLOCKED BY EXTERNAL RUNTIME": [],
        "SCAFFOLD ONLY": [],
        "DEPRECATED ALIAS": [],
    }

    for row in list(extension.get("rows") or []):
        lane = str(row.get("lane") or "")
        classification = str(row.get("classification") or "")
        activation_row = _lane_activation_row(activation, lane)
        lane_entry = {
            "lane": lane,
            "classification": classification,
            "reason": str(row.get("reason") or ""),
            "activation": activation_row,
        }
        if classification == "live_and_usable":
            live_lanes.append(lane_entry)
            categories["READY NOW"].append(lane_entry)
        elif classification == "implemented_but_blocked_by_external_runtime":
            bucket = _classify_blocked_lane(
                row,
                activation_row,
                lane=lane,
                shadowbroker_summary=shadowbroker,
                research_backend_summary=research_backend,
                hermes_summary=hermes,
                autoresearch_summary=autoresearch,
                local_model_lane_proof_summary=local_proof,
            )
            lane_entry["bucket"] = bucket
            blocked_lanes.append(lane_entry)
            categories[bucket].append(lane_entry)
        elif classification == "scaffold_only":
            scaffold_lanes.append(lane_entry)
            categories["SCAFFOLD ONLY"].append(lane_entry)
        elif classification == "deprecated_alias":
            deprecated_aliases.append(lane_entry)
            categories["DEPRECATED ALIAS"].append(lane_entry)

    required_actions: list[str] = []
    blocking_reasons: list[str] = []

    if not validate_ok:
        required_actions.append("Run python3 scripts/validate.py and clear any failing findings.")
        blocking_reasons.append("Repo validate posture is not currently green.")
    if not smoke_ok:
        required_actions.append("Run python3 scripts/smoke_test.py and clear any failing smoke checks.")
        blocking_reasons.append("Repo smoke posture is not currently green.")
    if str(routing.get("primary_runtime_posture") or "") != "healthy":
        required_actions.append("Restore the primary runtime lane before treating this machine as operator-usable.")
        blocking_reasons.append("Primary runtime posture is not healthy.")
    if not str(workspaces.get("default_home_workspace_id") or ""):
        required_actions.append("Restore the home runtime workspace registration.")
        blocking_reasons.append("No default home runtime workspace is registered.")
    if not live_lanes:
        required_actions.append("Activate at least one non-scaffold lane with a real completed proof or external activation.")
        blocking_reasons.append("No extension lane is currently live on this machine.")

    overall_ready = validate_ok and smoke_ok and str(routing.get("primary_runtime_posture") or "") == "healthy" and bool(workspaces.get("default_home_workspace_id")) and bool(live_lanes)

    return {
        "summary_kind": "operator_go_live_gate",
        "checked_at": status.get("generated_at"),
        "overall_ready": overall_ready,
        "required_actions": required_actions,
        "blocking_reasons": blocking_reasons,
        "live_lanes": live_lanes,
        "blocked_lanes": blocked_lanes,
        "scaffold_lanes": scaffold_lanes,
        "deprecated_aliases": deprecated_aliases,
        "routing_control_plane_summary": {
            "latest_route_state": routing.get("latest_route_state"),
            "latest_route_legality": routing.get("latest_route_legality"),
            "primary_runtime_posture": routing.get("primary_runtime_posture"),
            "burst_capacity_posture": routing.get("burst_capacity_posture"),
            "fallback_blocked_for_safety": routing.get("fallback_blocked_for_safety"),
        },
        "lane_activation_summary": activation,
        "local_model_lane_proof_summary": local_proof,
        "workspace_registry_summary": {
            "workspace_count": workspaces.get("workspace_count"),
            "default_home_workspace_id": workspaces.get("default_home_workspace_id"),
            "operator_approved_workspace_count": workspaces.get("operator_approved_workspace_count"),
        },
        "validate_ok": validate_ok,
        "smoke_ok": smoke_ok,
        "repo_side_blockers": [
            reason
            for reason in blocking_reasons
            if "Repo " in reason or "workspace" in reason.lower()
        ],
        "machine_side_blockers": [
            reason
            for reason in blocking_reasons
            if reason not in {
                "Repo validate posture is not currently green.",
                "Repo smoke posture is not currently green.",
            }
        ],
        "categories": categories,
        "source_refs": {
            "shadowbroker_summary": {
                "configured": shadowbroker.get("configured"),
                "healthy": shadowbroker.get("healthy"),
                "backend_status": shadowbroker.get("backend_status"),
            },
            "research_backend_summary": {
                "healthy_research_backend_count": research_backend.get("healthy_research_backend_count"),
            },
            "hermes_summary": {
                "latest_hermes_result": hermes.get("latest_hermes_result"),
            },
            "autoresearch_summary": {
                "latest_upstream_runtime": autoresearch.get("latest_upstream_runtime"),
            },
            "adaptation_lab_summary": {
                "latest_result": adaptation.get("latest_result"),
            },
            "optimizer_summary": {
                "latest_optimizer_run": optimizer.get("latest_optimizer_run"),
            },
        },
    }


def render_operator_go_live_gate(report: dict[str, Any]) -> str:
    lines = [
        f"operator_go_live_gate: {'READY NOW' if report.get('overall_ready') else 'NOT READY'}",
        f"checked_at: {report.get('checked_at')}",
    ]
    for label in ("READY NOW", "BLOCKED BY CONFIG", "BLOCKED BY EXTERNAL RUNTIME", "SCAFFOLD ONLY", "DEPRECATED ALIAS"):
        rows = list((report.get("categories") or {}).get(label) or [])
        lines.append(f"{label}: {len(rows)}")
        for row in rows[:10]:
            lines.append(f"- {row.get('lane')}: {row.get('reason') or row.get('activation', {}).get('latest_runtime_status') or 'n/a'}")
    if report.get("required_actions"):
        lines.append("required_actions:")
        for action in list(report.get("required_actions") or [])[:10]:
            lines.append(f"- {action}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render one honest operator go-live gate for this machine.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    report = build_operator_go_live_gate(root=root)
    write_report(root, "operator_go_live_gate.json", report)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_operator_go_live_gate(report))
    return 0 if report.get("overall_ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
