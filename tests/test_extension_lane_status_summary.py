from pathlib import Path

from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from scripts.preflight_lib import build_doctor_report


def _row(summary: dict, lane: str) -> dict:
    rows = list(summary.get("rows") or [])
    for row in rows:
        if row.get("lane") == lane:
            return row
    raise AssertionError(f"missing lane row: {lane}")


def test_extension_lane_status_summary_is_honest_by_default(tmp_path: Path):
    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    doctor = build_doctor_report(tmp_path)

    status_summary = status["extension_lane_status_summary"]
    snapshot_summary = snapshot["extension_lane_status_summary"]
    export_summary = export_payload["extension_lane_status_summary"]
    doctor_summary = doctor["extension_lane_status_summary"]

    assert status_summary["summary_kind"] == "extension_lane_status"
    assert snapshot_summary == status_summary
    assert export_summary["classification_counts"] == status_summary["classification_counts"]
    assert doctor_summary["classification_counts"] == status_summary["classification_counts"]

    assert _row(status_summary, "world_ops")["classification"] == "deprecated_alias"
    assert _row(status_summary, "mission_control_adapter")["classification"] == "scaffold_only"
    assert _row(status_summary, "a2a")["classification"] == "scaffold_only"
    assert _row(status_summary, "shadowbroker")["classification"] == "implemented_but_blocked_by_external_runtime"
    assert _row(status_summary, "searxng")["classification"] == "implemented_but_blocked_by_external_runtime"


def test_doctor_report_includes_extension_lane_summary(tmp_path: Path):
    doctor = build_doctor_report(tmp_path)

    summary = doctor["extension_lane_status_summary"]
    counts = summary["classification_counts"]

    assert summary["summary_kind"] == "extension_lane_status"
    assert counts["deprecated_alias"] >= 1
    assert counts["scaffold_only"] >= 1
    assert counts["implemented_but_blocked_by_external_runtime"] >= 1
