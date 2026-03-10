import json
import subprocess
import sys
from pathlib import Path

from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.task_store import create_task


ROOT = Path(__file__).resolve().parents[1]


def _make_task(root: Path, *, task_id: str, task_type: str = "research") -> TaskRecord:
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
            task_type=task_type,
            status=TaskStatus.RUNNING.value,
            execution_backend="qwen_executor",
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
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"Command did not return JSON: {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        ) from exc


def test_gateway_hermes_eval_ralph_memory_chain(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_gateway_chain")
    python = sys.executable

    hermes = _run_json(
        [
            python,
            str(ROOT / "runtime" / "gateway" / "hermes_execute.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--actor",
            "operator",
            "--lane",
            "hermes",
            "--response-json",
            json.dumps(
                {
                    "run_id": "gw_hermes_run",
                    "family": "qwen3.5",
                    "model_name": "Qwen3.5-35B-A3B",
                    "title": "Gateway Hermes candidate",
                    "summary": "Gateway-produced candidate artifact",
                    "content": "Gateway Hermes body",
                }
            ),
        ]
    )
    trace_id = hermes["result"]["result"]["trace_id"]

    replay_eval = _run_json(
        [
            python,
            str(ROOT / "runtime" / "gateway" / "replay_eval.py"),
            "--root",
            str(tmp_path),
            "--trace-id",
            trace_id,
            "--actor",
            "operator",
            "--lane",
            "eval",
            "--objective",
            "Confirm the Hermes trace is replayable",
            "--criteria-json",
            json.dumps({"expected_status": "completed", "require_candidate_artifact": True}),
        ]
    )

    ralph = _run_json(
        [
            python,
            str(ROOT / "runtime" / "gateway" / "ralph_consolidate.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--actor",
            "operator",
            "--lane",
            "ralph",
        ]
    )
    memory_candidate_id = ralph["result"]["memory_candidate_ids"][0]

    promote = _run_json(
        [
            python,
            str(ROOT / "runtime" / "gateway" / "memory_decision.py"),
            "--root",
            str(tmp_path),
            "--action",
            "promote",
            "--memory-candidate-id",
            memory_candidate_id,
            "--actor",
            "operator",
            "--lane",
            "memory",
            "--reason",
            "Useful overnight digest",
            "--confidence-score",
            "0.88",
        ]
    )

    retrieval = _run_json(
        [
            python,
            str(ROOT / "runtime" / "gateway" / "memory_retrieve.py"),
            "--root",
            str(tmp_path),
            "--actor",
            "operator",
            "--lane",
            "memory",
            "--task-id",
            task.task_id,
            "--memory-type",
            "task_digest",
        ]
    )

    assert hermes["ack"]["kind"] == "hermes_execute_ack"
    assert hermes["result"]["candidate_artifact_id"]
    assert replay_eval["ack"]["kind"] == "replay_eval_ack"
    assert replay_eval["result"]["eval_result"]["passed"] is True
    assert ralph["ack"]["kind"] == "ralph_consolidation_ack"
    assert ralph["result"]["digest_artifact_id"]
    assert promote["ack"]["kind"] == "memory_decision_ack"
    assert promote["result"]["memory_candidate"]["decision_status"] == "promoted"
    assert retrieval["ack"]["kind"] == "memory_retrieval_ack"
    assert retrieval["ack"]["result_count"] == 1
    assert retrieval["result"]["items"][0]["memory_candidate_id"] == memory_candidate_id


def test_gateway_autoresearch_ralph_memory_chain(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_gateway_research")
    python = sys.executable

    autoresearch = _run_json(
        [
            python,
            str(ROOT / "runtime" / "gateway" / "autoresearch_campaign.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--actor",
            "operator",
            "--lane",
            "research",
            "--objective",
            "Increase simulated benchmark score",
            "--objective-metric",
            "accuracy",
            "--primary-metric",
            "accuracy",
            "--max-passes",
            "2",
            "--max-budget-units",
            "2",
            "--response-json",
            json.dumps(
                [
                    {
                        "run_id": "lab_run_1",
                        "summary": "First pass improves baseline.",
                        "hypothesis": "Tighter prompt helps.",
                        "metrics": {"accuracy": 0.72},
                        "comparison_summary": "Accuracy +0.02 vs baseline.",
                        "recommendation_hint": "keep_iterating",
                    },
                    {
                        "run_id": "lab_run_2",
                        "summary": "Second pass improves again.",
                        "hypothesis": "Structured rubric helps.",
                        "metrics": {"accuracy": 0.79},
                        "comparison_summary": "Accuracy +0.09 vs baseline.",
                        "recommendation_hint": "promote_candidate",
                    },
                ]
            ),
        ]
    )

    ralph = _run_json(
        [
            python,
            str(ROOT / "runtime" / "gateway" / "ralph_consolidate.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--actor",
            "operator",
            "--lane",
            "ralph",
        ]
    )

    memory_candidate_id = ralph["result"]["memory_candidate_ids"][0]
    promote = _run_json(
        [
            python,
            str(ROOT / "runtime" / "gateway" / "memory_decision.py"),
            "--root",
            str(tmp_path),
            "--action",
            "promote",
            "--memory-candidate-id",
            memory_candidate_id,
            "--actor",
            "operator",
            "--lane",
            "memory",
            "--reason",
            "Research digest is useful",
            "--confidence-score",
            "0.91",
        ]
    )

    retrieval = _run_json(
        [
            python,
            str(ROOT / "runtime" / "gateway" / "memory_retrieve.py"),
            "--root",
            str(tmp_path),
            "--actor",
            "operator",
            "--lane",
            "memory",
            "--task-id",
            task.task_id,
        ]
    )

    assert autoresearch["ack"]["kind"] == "autoresearch_campaign_ack"
    assert autoresearch["result"]["candidate_artifact_id"]
    assert autoresearch["result"]["recommendation"]["execution_backend"] == "autoresearch_adapter"
    assert ralph["result"]["digest_artifact_id"]
    assert promote["result"]["memory_candidate"]["decision_status"] == "promoted"
    assert retrieval["ack"]["result_count"] >= 1
    assert retrieval["result"]["items"][0]["lifecycle_state"] == "promoted"
