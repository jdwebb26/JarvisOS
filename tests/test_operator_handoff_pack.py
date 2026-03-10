import json
import subprocess
import sys
from pathlib import Path

from runtime.core.approval_store import request_approval
from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.task_store import create_task
from runtime.evals.trace_store import replay_trace_to_eval
from runtime.integrations.hermes_adapter import execute_hermes_task, load_hermes_result
from runtime.ralph.consolidator import execute_consolidation


ROOT = Path(__file__).resolve().parents[1]


def _make_task(
    root: Path,
    *,
    task_id: str,
    review_required: bool = False,
    approval_required: bool = False,
) -> TaskRecord:
    return create_task(
        TaskRecord(
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            source_lane="tests",
            source_channel="tests",
            source_message_id=f"{task_id}_msg",
            source_user="tester",
            trigger_type="explicit_task_colon",
            raw_request=f"task: {task_id}",
            normalized_request=task_id,
            task_type="research",
            status=TaskStatus.RUNNING.value,
            execution_backend="qwen_executor",
            review_required=review_required,
            approval_required=approval_required,
        ),
        root=root,
    )


def _run_json(cmd: list[str]) -> dict:
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        raise AssertionError(
            f"Command failed ({completed.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def test_operator_handoff_pack_surfaces_recent_state(tmp_path: Path):
    task_review = _make_task(tmp_path, task_id="task_handoff_review", review_required=True)
    hermes = execute_hermes_task(
        task_id=task_review.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "handoff_hermes_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Handoff candidate",
            "summary": "candidate for handoff pack",
            "content": "candidate body",
        },
    )
    stored_result = load_hermes_result(hermes["result"]["result_id"], root=tmp_path)
    replay_trace_to_eval(
        trace_id=stored_result["trace_id"],
        actor="tester",
        lane="eval",
        evaluator_kind="replay_check",
        objective="Seed a recent eval for handoff",
        root=tmp_path,
    )
    execute_consolidation(task_id=task_review.task_id, actor="tester", lane="ralph", root=tmp_path)

    task_approval = _make_task(tmp_path, task_id="task_handoff_approval", approval_required=True)
    request_approval(
        task_id=task_approval.task_id,
        approval_type=task_approval.task_type,
        requested_by="tester",
        requested_reviewer="operator",
        lane="review",
        summary="Pending approval for handoff pack",
        root=tmp_path,
    )
    action_pack = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_pack["pack"]["pending_approval_commands"][0]["action_ids"]["approve"],
            "--dry-run",
        ]
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_bulk_action_runner.py"),
            "--root",
            str(tmp_path),
            "--category",
            "pending_review",
            "--dry-run",
        ]
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_task_intervene.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task_review.task_id,
            "--dry-run",
        ]
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_safe_autofix.py"),
            "--root",
            str(tmp_path),
            "--dry-run-top-action",
        ]
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_decision_inbox.py"),
            "--root",
            str(tmp_path),
        ]
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_plan.py"),
            "--root",
            str(tmp_path),
            "--reply",
            "A1",
        ]
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_apply_reply.py"),
            "--root",
            str(tmp_path),
            "--reply",
            "A1",
            "--dry-run",
        ]
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_ingest.py"),
            "--root",
            str(tmp_path),
            "--reply",
            "A1",
            "--source-message-id",
            "handoff_msg_1",
            "--apply",
            "--dry-run",
        ]
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_outbound_prompt.py"),
            "--root",
            str(tmp_path),
        ]
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_ack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_enqueue_reply_message.py"),
            "--root",
            str(tmp_path),
            "--raw-text",
            "A1",
            "--source-message-id",
            "handoff_cycle_msg_1",
            "--apply",
            "--dry-run",
        ]
    )
    cycle = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_transport_cycle.py"),
            "--root",
            str(tmp_path),
            "--apply",
            "--dry-run",
            "--continue-on-failure",
        ]
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_replay_transport_cycle.py"),
            "--root",
            str(tmp_path),
            "--cycle-id",
            cycle["transport_cycle"]["transport_cycle_id"],
            "--plan-only",
        ]
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_compare_reply_transport_cycles.py"),
            "--root",
            str(tmp_path),
            "--cycle-id",
            cycle["transport_cycle"]["transport_cycle_id"],
        ]
    )

    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_handoff_pack.py"),
            "--root",
            str(tmp_path),
            "--limit",
            "5",
        ]
    )

    pack = payload["pack"]
    markdown_path = Path(payload["markdown_path"])
    json_path = Path(payload["json_path"])

    assert json_path.exists()
    assert markdown_path.exists()
    assert pack["recent_task_status"]
    assert pack["artifacts"]["candidate"]
    assert pack["latest_trace_summary"]
    assert pack["latest_eval_summary"]
    assert pack["recent_operator_action_executions"]
    assert pack["recent_operator_bulk_runs"]
    assert pack["recent_operator_task_interventions"]
    assert pack["recent_operator_safe_autofix_runs"]
    assert pack["current_action_pack"]["status"] == "valid"
    assert pack["operator_control_plane_counts"]
    assert pack["triage_summary"]["control_plane_health_summary"]
    assert pack["command_center_summary"]["health_label"] in {"green", "yellow", "red"}
    assert "ranked_next_commands" in pack["decision_manifest_summary"]
    assert pack["decision_inbox_summary"]["reply_ready"] in {True, False}
    assert pack["reply_ingress_summary"]["reply_ingest_ready"] in {True, False}
    assert pack["outbound_prompt_summary"]["pack_id"] == pack["decision_inbox_summary"]["pack_id"]
    assert "latest_result_kind" in pack["reply_ack_summary"]
    assert pack["latest_reply_transport_cycle"] is not None
    assert "replay_allowed" in pack["reply_transport_replay_summary"]
    assert pack["latest_compare_reply_transport_cycles"] is not None
    assert pack["latest_reply_plan"] is not None
    assert pack["latest_reply_apply"] is not None
    assert pack["latest_reply_ingress"] is not None
    assert any(
        row.get("last_successful_operator_action") or row.get("last_failed_operator_action")
        for row in pack["recent_task_status"]
    )
    assert any(item["task_id"] == task_review.task_id for item in pack["pending_review_items"])
    assert any(item["task_id"] == task_approval.task_id for item in pack["pending_approval_items"])
    assert pack["ralph_memory_summary"]["latest_memory_candidates"]
    assert pack["recommended_next_actions"]
    assert "## Recommended Next Actions" in markdown_path.read_text(encoding="utf-8")
