import json
import subprocess
import sys
from pathlib import Path

from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import request_review
from runtime.core.task_store import create_task
from runtime.integrations.hermes_adapter import execute_hermes_task


ROOT = Path(__file__).resolve().parents[1]


def _run_json(cmd: list[str], *, expect_ok: bool = True) -> dict:
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if expect_ok and completed.returncode != 0:
        raise AssertionError(
            f"Command failed ({completed.returncode}): {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def _seed_review_task(root: Path, *, task_id: str) -> None:
    task = create_task(
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
            review_required=True,
        ),
        root=root,
    )
    execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=root,
        transport=lambda _request: {
            "run_id": f"{task_id}_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": f"{task_id} candidate",
            "summary": f"{task_id} summary",
            "content": "candidate body",
        },
    )
    request_review(
        task_id=task.task_id,
        reviewer_role="operator",
        requested_by="tester",
        lane="review",
        summary=f"Pending review for {task_id}",
        root=root,
    )


def _build_stale_inbox_plan(root: Path, *, task_id: str) -> dict:
    _seed_review_task(root, task_id=task_id)
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(root)])
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(root)])
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(root)])
    return _run_json([sys.executable, str(ROOT / "scripts" / "operator_plan_remediation.py"), "--root", str(root)])["plan"]


def test_remediation_run_happy_path_and_reporting(tmp_path: Path):
    plan = _build_stale_inbox_plan(tmp_path, task_id="task_remediation_happy")
    payload = _run_json([sys.executable, str(ROOT / "scripts" / "operator_run_remediation_plan.py"), "--root", str(tmp_path)])

    assert payload["ok"] is True
    assert payload["remediation_run"]["remediation_plan_id"] == plan["remediation_plan_id"]
    assert payload["remediation_run"]["executed_step_count"] >= 1
    assert payload["executed_steps"]

    listed = _run_json([sys.executable, str(ROOT / "scripts" / "operator_list_remediation_runs.py"), "--root", str(tmp_path)])
    explained = _run_json([sys.executable, str(ROOT / "scripts" / "operator_explain_remediation_run.py"), "--root", str(tmp_path)])
    handoff = _run_json([sys.executable, str(ROOT / "scripts" / "operator_handoff_pack.py"), "--root", str(tmp_path)])["pack"]
    status_payload = _run_json([sys.executable, str(ROOT / "runtime" / "core" / "status.py"), "--root", str(tmp_path)])
    export_payload = _run_json([sys.executable, str(ROOT / "runtime" / "dashboard" / "state_export.py"), "--root", str(tmp_path)])

    assert listed["count"] >= 1
    assert explained["remediation_run"]["remediation_run_id"] == payload["remediation_run"]["remediation_run_id"]
    assert handoff["latest_remediation_run"] is not None
    assert "latest_remediation_run_id" in handoff["remediation_run_summary"]
    assert status_payload["operator_control_plane"]["latest_remediation_run"] is not None
    assert export_payload["counts"]["operator_remediation_runs"] >= 1


def test_remediation_run_dry_run_and_single_step(tmp_path: Path):
    _build_stale_inbox_plan(tmp_path, task_id="task_remediation_dry")
    dry_run = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_run_remediation_plan.py"),
            "--root",
            str(tmp_path),
            "--dry-run",
        ]
    )
    assert dry_run["ok"] is True
    assert dry_run["remediation_run"]["dry_run"] is True
    assert dry_run["remediation_run"]["executed_step_count"] == 0
    assert dry_run["executed_steps"][0]["executed"] is False

    inbound_dir = tmp_path / "state" / "operator_gateway_inbound_messages"
    inbound_dir.mkdir(parents=True, exist_ok=True)
    (inbound_dir / "remediation_gateway_pending.json").write_text(
        json.dumps(
            {
                "source_kind": "gateway",
                "source_lane": "operator",
                "source_channel": "phone",
                "source_message_id": "remediation_gateway_pending",
                "source_user": "operator",
                "raw_text": "A1",
                "apply": True,
                "dry_run": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_plan_remediation.py"), "--root", str(tmp_path)])
    single = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_run_remediation_plan.py"),
            "--root",
            str(tmp_path),
            "--step-index",
            "1",
        ]
    )
    assert single["remediation_run"]["attempted_step_count"] == 1
    assert len(single["executed_steps"]) == 1


def test_remediation_run_blocks_disallowed_command(tmp_path: Path):
    plan = _build_stale_inbox_plan(tmp_path, task_id="task_remediation_invalid")
    plan_path = tmp_path / "state" / "operator_remediation_plans" / f"{plan['remediation_plan_id']}.json"
    tampered = json.loads(plan_path.read_text(encoding="utf-8"))
    tampered["steps"][0]["suggested_command"] = "python3 /bin/echo hacked"
    plan_path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")

    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_run_remediation_plan.py"),
            "--root",
            str(tmp_path),
            "--plan-id",
            plan["remediation_plan_id"],
        ],
        expect_ok=False,
    )

    assert payload["ok"] is False
    assert payload["remediation_run"]["failed_step_count"] >= 1
    assert payload["executed_steps"][0]["ok"] is False
    explained = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_explain_remediation_run.py"),
            "--root",
            str(tmp_path),
            "--run-id",
            payload["remediation_run"]["remediation_run_id"],
        ]
    )
    assert explained["step_runs"][0]["ok"] is False
