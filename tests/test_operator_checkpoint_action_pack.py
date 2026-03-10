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


def test_operator_checkpoint_action_pack_produces_commands(tmp_path: Path):
    review_task = _make_task(tmp_path, task_id="task_checkpoint_review", review_required=True)
    hermes = execute_hermes_task(
        task_id=review_task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "checkpoint_hermes_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Checkpoint candidate",
            "summary": "candidate for checkpoint action pack",
            "content": "candidate body",
        },
    )
    stored_result = load_hermes_result(hermes["result"]["result_id"], root=tmp_path)
    replay_trace_to_eval(
        trace_id=stored_result["trace_id"],
        actor="tester",
        lane="eval",
        evaluator_kind="replay_check",
        objective="Seed eval context",
        root=tmp_path,
    )
    execute_consolidation(task_id=review_task.task_id, actor="tester", lane="ralph", root=tmp_path)

    approval_task = _make_task(tmp_path, task_id="task_checkpoint_approval", approval_required=True)
    request_approval(
        task_id=approval_task.task_id,
        approval_type=approval_task.task_type,
        requested_by="tester",
        requested_reviewer="operator",
        lane="review",
        summary="Pending approval for checkpoint action pack",
        root=tmp_path,
    )

    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
            "--limit",
            "5",
        ]
    )

    pack = payload["pack"]
    assert Path(payload["json_path"]).exists()
    assert Path(payload["markdown_path"]).exists()
    assert pack["action_pack_id"].startswith("opack_")
    assert len(pack["action_pack_fingerprint"]) == 64
    assert pack["recommended_ttl_seconds"] > 0
    assert pack["expires_at"]
    assert pack["stale_after_reason"]
    assert pack["pending_review_commands"]
    assert pack["pending_approval_commands"]
    assert pack["memory_decision_commands"]
    assert pack["artifact_followup_commands"]
    assert pack["recommended_execution_order"]
    assert "runtime/gateway/review_decision.py" in pack["pending_review_commands"][0]["commands"]["approve"]["command"]
    assert "runtime/gateway/approval_decision.py" in pack["pending_approval_commands"][0]["commands"]["approve"]["command"]
    assert "runtime/gateway/memory_decision.py" in pack["memory_decision_commands"][0]["commands"]["promote"]["command"]
