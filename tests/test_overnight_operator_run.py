import json
import subprocess
import sys
from pathlib import Path

from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.task_store import create_task


ROOT = Path(__file__).resolve().parents[1]


def _make_task(root: Path, *, task_id: str) -> TaskRecord:
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
        ),
        root=root,
    )


def _run_json(cmd: list[str], *, expect_ok: bool = True) -> dict:
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if expect_ok and completed.returncode != 0:
        raise AssertionError(
            f"Command failed ({completed.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"Command did not return JSON: {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        ) from exc


def test_overnight_operator_run_hermes_chain(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_overnight_hermes")
    python = sys.executable

    payload = _run_json(
        [
            python,
            str(ROOT / "scripts" / "overnight_operator_run.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--flow",
            "hermes",
            "--include-candidate-memory",
            "--hermes-response-json",
            json.dumps(
                {
                    "run_id": "overnight_hermes_run",
                    "family": "qwen3.5",
                    "model_name": "Qwen3.5-35B-A3B",
                    "title": "Overnight Hermes candidate",
                    "summary": "bounded overnight summary",
                    "content": "overnight body",
                }
            ),
            "--eval-criteria-json",
            json.dumps({"expected_status": "completed", "require_candidate_artifact": True}),
        ]
    )

    assert payload["ok"] is True
    assert payload["flow"] == "hermes_eval_ralph_memory"
    assert [step["step"] for step in payload["steps"]] == [
        "hermes_execute",
        "replay_eval",
        "ralph_consolidate",
        "memory_retrieve",
    ]
    assert payload["summary"]["trace_id"]
    assert payload["summary"]["digest_artifact_id"]


def test_overnight_operator_run_reports_failed_step(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_overnight_failure")
    python = sys.executable

    payload = _run_json(
        [
            python,
            str(ROOT / "scripts" / "overnight_operator_run.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--flow",
            "hermes",
            "--hermes-response-json",
            json.dumps({"summary": "malformed"}),
        ],
        expect_ok=False,
    )

    assert payload["ok"] is False
    assert payload["failed_step"] in {"replay_eval", "hermes_execute"}
    assert payload["steps"] == []
