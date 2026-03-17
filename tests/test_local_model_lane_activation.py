from pathlib import Path
from unittest.mock import patch

from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.integrations.lane_activation import (
    record_lane_activation_attempt,
    record_lane_activation_result,
)
from scripts.operator_activate_local_model_lanes import activate_local_model_lanes
from scripts.preflight_lib import build_doctor_report


def _lane_row(summary: dict, lane: str) -> dict:
    for row in list(summary.get("rows") or []):
        if row.get("lane") == lane:
            return row
    raise AssertionError(f"missing lane row: {lane}")


def test_local_model_lane_activation_blocks_when_runtime_unavailable(tmp_path: Path) -> None:
    with patch(
        "scripts.operator_activate_local_model_lanes.run_unsloth_proof",
        return_value={
            "status": "blocked",
            "runtime_status": "blocked_missing_unsloth",
            "summary": "missing unsloth",
            "error": "missing",
            "metadata": {},
            "output_refs": {},
        },
    ), patch(
        "scripts.operator_activate_local_model_lanes.run_dspy_proof",
        return_value={
            "status": "blocked",
            "runtime_status": "blocked_missing_dspy",
            "summary": "missing dspy",
            "error": "missing",
            "metadata": {},
            "output_refs": {},
        },
    ):
        result = activate_local_model_lanes(root=tmp_path)

    proof_summary = result["local_model_lane_proof_summary"]
    unsloth = _lane_row(proof_summary, "adaptation_lab_unsloth")
    dspy = _lane_row(proof_summary, "optimizer_dspy")
    assert unsloth["latest_activation_status"] == "blocked"
    assert unsloth["latest_runtime_status"] == "blocked_missing_unsloth"
    assert "Unsloth" in unsloth["operator_action_required"]
    assert dspy["latest_activation_status"] == "blocked"
    assert dspy["latest_runtime_status"] == "blocked_missing_dspy"
    assert "DSPy" in dspy["operator_action_required"]


def test_local_model_lane_activation_persists_mocked_success_and_visibility(tmp_path: Path) -> None:
    with patch(
        "scripts.operator_activate_local_model_lanes.run_unsloth_proof",
        return_value={
            "status": "completed",
            "runtime_status": "completed",
            "summary": "unsloth proof completed",
            "error": "",
            "result_id": "adaptres_1",
            "metadata": {"proof_dataset_id": "ds1", "proof_job_id": "job1"},
            "output_refs": {
                "output_dir": str((tmp_path / "unsloth_out").resolve()),
                "run_config_path": str((tmp_path / "unsloth_out" / "run_config.json").resolve()),
                "trainer_metrics_path": str((tmp_path / "unsloth_out" / "trainer_metrics.json").resolve()),
            },
        },
    ), patch(
        "scripts.operator_activate_local_model_lanes.run_dspy_proof",
        return_value={
            "status": "completed",
            "runtime_status": "completed",
            "summary": "dspy proof completed",
            "error": "",
            "metadata": {"response_preview": "pong"},
            "output_refs": {"model": "qwen/qwen3.5-9b", "api_base": "http://127.0.0.1:1234/v1"},
        },
    ):
        activate_local_model_lanes(root=tmp_path)

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    doctor = build_doctor_report(tmp_path)

    proof_summary = status["local_model_lane_proof_summary"]
    unsloth = _lane_row(proof_summary, "adaptation_lab_unsloth")
    dspy = _lane_row(proof_summary, "optimizer_dspy")
    assert unsloth["currently_live_on_this_machine"] is True
    assert unsloth["evidence_refs"]["result_id"] == "adaptres_1"
    assert dspy["currently_live_on_this_machine"] is True
    assert snapshot["local_model_lane_proof_summary"]["live_proof_count"] == 2
    assert export_payload["local_model_lane_proof_summary"]["live_proof_count"] == 2
    assert doctor["local_model_lane_proof_summary"]["live_proof_count"] == 2


def test_extension_lane_classification_only_changes_when_proof_exists(tmp_path: Path) -> None:
    baseline = build_status(tmp_path)
    assert _lane_row(baseline["extension_lane_status_summary"], "adaptation_lab_unsloth")["classification"] == "implemented_but_blocked_by_external_runtime"
    assert _lane_row(baseline["extension_lane_status_summary"], "optimizer_dspy")["classification"] == "implemented_but_blocked_by_external_runtime"

    unsloth_attempt = record_lane_activation_attempt(
        lane="adaptation_lab_unsloth",
        command_or_endpoint="run_unsloth_proof",
        root=tmp_path,
    )
    record_lane_activation_result(
        activation_run_id=unsloth_attempt["activation_run_id"],
        lane="adaptation_lab_unsloth",
        status="completed",
        runtime_status="completed",
        configured=True,
        healthy=True,
        command_or_endpoint="run_unsloth_proof",
        root=tmp_path,
    )
    dspy_attempt = record_lane_activation_attempt(
        lane="optimizer_dspy",
        command_or_endpoint="run_dspy_proof",
        root=tmp_path,
    )
    record_lane_activation_result(
        activation_run_id=dspy_attempt["activation_run_id"],
        lane="optimizer_dspy",
        status="completed",
        runtime_status="completed",
        configured=True,
        healthy=True,
        command_or_endpoint="run_dspy_proof",
        root=tmp_path,
    )

    status = build_status(tmp_path)
    assert _lane_row(status["extension_lane_status_summary"], "adaptation_lab_unsloth")["classification"] == "live_and_usable"
    assert _lane_row(status["extension_lane_status_summary"], "optimizer_dspy")["classification"] == "live_and_usable"
