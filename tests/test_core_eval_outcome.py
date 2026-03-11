import json
from pathlib import Path

from runtime.core.models import TaskRecord, now_iso
from runtime.core.task_store import create_task
from runtime.core.status import build_status
from runtime.dashboard.state_export import build_state_export
from runtime.evals.trace_store import record_run_trace, replay_trace_to_eval
from scripts.operator_handoff_pack import build_operator_handoff_pack


def test_replay_eval_persists_eval_outcome_and_summary(tmp_path: Path):
    create_task(
        TaskRecord(
            task_id="task_eval_outcome",
            created_at=now_iso(),
            updated_at=now_iso(),
            source_lane="tests",
            source_channel="tests",
            source_message_id="eval_outcome_msg",
            source_user="tester",
            trigger_type="explicit_task_colon",
            raw_request="task: eval outcome",
            normalized_request="eval outcome",
            task_type="general",
            execution_backend="planner_backend",
        ),
        root=tmp_path,
    )

    trace = record_run_trace(
        task_id="task_eval_outcome",
        trace_kind="hermes_task",
        actor="tester",
        lane="tests",
        execution_backend="planner_backend",
        status="completed",
        request_summary="request",
        response_summary="response",
        decision_summary="decision",
        response_payload={"title": "t", "summary": "s", "content": "c"},
        replay_payload={"metrics": {"score": 1.0}},
        source_refs={"replay_result_id": "rres_eval"},
        candidate_artifact_id="artifact_eval",
        root=tmp_path,
    )

    result = replay_trace_to_eval(
        trace_id=trace.trace_id,
        actor="eval",
        lane="tests",
        evaluator_kind="replay_eval",
        objective="Check outcome durability",
        root=tmp_path,
    )

    outcome_path = next((tmp_path / "state" / "eval_outcomes").glob("*.json"))
    outcome_row = json.loads(outcome_path.read_text(encoding="utf-8"))
    status = build_status(tmp_path)
    exported = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)

    assert outcome_row["task_id"] == "task_eval_outcome"
    assert outcome_row["eval_result_id"] == result["eval_result"]["eval_result_id"]
    assert outcome_row["profile_id"] == result["eval_result"]["profile_id"]
    assert outcome_row["replay_result_id"] == "rres_eval"
    assert outcome_row["trace_id"] == trace.trace_id
    assert outcome_row["pass_fail"] is True
    assert outcome_row["derived_outcome"] == "promotable"
    assert "trace_status_completed" in outcome_row["veto_results"]
    assert outcome_row["quality_scores"]["score"] == 1.0
    assert outcome_row["source_refs"]["evaluator_kind"] == "replay_eval"

    assert status["eval_outcome_summary"]["eval_outcome_count"] == 1
    assert status["eval_outcome_summary"]["latest_eval_outcome"]["eval_result_id"] == result["eval_result"]["eval_result_id"]
    assert exported["counts"]["eval_outcomes"] == 1
    assert exported["eval_outcome_summary"]["latest_eval_outcome"]["replay_result_id"] == "rres_eval"
    assert handoff["pack"]["eval_outcome_summary"]["latest_eval_outcome"]["derived_outcome"] == "promotable"
