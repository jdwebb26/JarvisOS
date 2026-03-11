import json
from pathlib import Path

from runtime.core.models import ReplayExecutionRecord, ReplayResultKind, ReplayResultRecord, TaskRecord, now_iso
from runtime.core.replay_store import save_replay_execution, save_replay_result
from runtime.core.status import build_status
from runtime.core.task_store import create_task
from runtime.dashboard.state_export import build_state_export
from scripts.operator_handoff_pack import build_operator_handoff_pack


def test_replay_result_persists_trajectory_and_operator_profile(tmp_path: Path):
    task = create_task(
        TaskRecord(
            task_id="task_traj",
            created_at=now_iso(),
            updated_at=now_iso(),
            source_lane="tests",
            source_channel="tests",
            source_message_id="task_traj_msg",
            source_user="tester",
            trigger_type="explicit_task_colon",
            raw_request="task: trajectory",
            normalized_request="trajectory",
            task_type="research",
            execution_backend="planner_backend",
        ),
        root=tmp_path,
    )

    execution = save_replay_execution(
        ReplayExecutionRecord(
            replay_execution_id="rexec_1",
            replay_plan_id="rplan_1",
            replay_kind="route",
            source_record_id="routing_decision_1",
            task_id=task.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor="operator",
            lane="tests",
            mode="plan_only",
            ok=True,
        ),
        root=tmp_path,
    )

    save_replay_result(
        ReplayResultRecord(
            replay_result_id="rres_1",
            replay_execution_id=execution.replay_execution_id,
            replay_kind="route",
            source_record_id="routing_decision_1",
            task_id=task.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            result_kind=ReplayResultKind.MATCH.value,
            expected_snapshot={"tools_used": ["patch_apply"], "trace_id": "trace_1"},
            observed_snapshot={"eval_result_id": "eval_1"},
            drift_fields=[],
            reason="",
        ),
        root=tmp_path,
    )

    trajectory_path = next((tmp_path / "state" / "trajectories").glob("*.json"))
    profile_path = next((tmp_path / "state" / "operator_profiles").glob("*.json"))
    trajectory_row = json.loads(trajectory_path.read_text(encoding="utf-8"))
    profile_row = json.loads(profile_path.read_text(encoding="utf-8"))
    status = build_status(tmp_path)
    exported = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)

    assert trajectory_row["task_id"] == task.task_id
    assert trajectory_row["prompt_class"] == "route"
    assert trajectory_row["task_type"] == "research"
    assert trajectory_row["backend"] == "planner_backend"
    assert trajectory_row["tools_used"] == ["patch_apply"]
    assert trajectory_row["outcome_quality"] == "match"
    assert trajectory_row["replay_result_id"] == "rres_1"
    assert trajectory_row["trace_id"] == "trace_1"
    assert trajectory_row["eval_result_id"] == "eval_1"
    assert trajectory_row["collection_policy"] == "policy_controlled"
    assert trajectory_row["sensitive_collection_enabled"] is False

    assert profile_row["operator_id"] == "operator"
    assert profile_row["approval_surface_preference"] == "default"
    assert profile_row["verbosity_style"] == "standard"

    assert status["trajectory_summary"]["trajectory_count"] == 1
    assert status["operator_profile_summary"]["operator_profile_count"] == 1
    assert exported["counts"]["trajectories"] == 1
    assert exported["counts"]["operator_profiles"] == 1
    assert handoff["pack"]["trajectory_summary"]["latest_trajectory"]["replay_result_id"] == "rres_1"
    assert handoff["pack"]["operator_profile_summary"]["latest_operator_profile"]["operator_id"] == "operator"
