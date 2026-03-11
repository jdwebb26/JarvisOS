from pathlib import Path

from runtime.core.execution_contracts import build_execution_contract_summary
from runtime.core.intake import create_task_from_message
from runtime.core.qwen_candidate_applier import record_qwen_live_apply_execution
from runtime.core.qwen_candidate_writer import record_qwen_candidate_generation_execution
from runtime.core.replay_store import build_backend_execution_replay_plan, execute_replay_plan
from runtime.core.task_store import load_task, save_task


def _seed_qwen_task(tmp_path: Path, *, message_id: str) -> str:
    created = create_task_from_message(
        text="task: write a code patch for the runtime",
        user="tester",
        lane="tests",
        channel="tests",
        message_id=message_id,
        root=tmp_path,
    )
    task_id = created["task_id"]
    task = load_task(task_id, root=tmp_path)
    task.assigned_model = "Qwen3.5-35B"
    task.execution_backend = "qwen_executor"
    task.backend_metadata.setdefault("routing", {})
    task.backend_metadata["routing"]["provider_id"] = "qwen"
    save_task(task, root=tmp_path)
    return task_id


def test_qwen_candidate_generation_uses_shared_execution_contracts(tmp_path: Path):
    task_id = _seed_qwen_task(tmp_path, message_id="msg_qwen_writer_exec")

    execution_contract = record_qwen_candidate_generation_execution(
        task_id=task_id,
        target_file=str(tmp_path / "runtime.py"),
        candidate_file=str(tmp_path / "candidate.py"),
        patch_plan="tight patch plan",
        artifact_path=str(tmp_path / "candidate_artifact.md"),
        generation_mode="scope_rewrite",
        model_candidate_accepted=True,
        output_status="completed",
        rejection_reason="",
        generation_error="",
        root=tmp_path,
    )

    task = load_task(task_id, root=tmp_path)
    summary = build_execution_contract_summary(root=tmp_path)
    plan = build_backend_execution_replay_plan(
        backend_execution_request_id=execution_contract["backend_execution_request_id"],
        actor="tester",
        lane="tests",
        root=tmp_path,
    )
    replay = execute_replay_plan(
        replay_plan_id=plan.replay_plan_id,
        actor="tester",
        lane="tests",
        root=tmp_path,
    )

    assert execution_contract["backend_execution_request_id"]
    assert execution_contract["backend_execution_result_id"]
    assert task.backend_metadata["execution_contracts"]["latest_backend_execution_request_id"] == execution_contract["backend_execution_request_id"]
    assert summary["latest_backend_execution_result"]["request_kind"] == "qwen_candidate_generation"
    assert replay["replay_result"]["result_kind"] == "match"


def test_qwen_live_apply_replay_detects_drift_when_task_backend_changes(tmp_path: Path):
    task_id = _seed_qwen_task(tmp_path, message_id="msg_qwen_apply_exec")

    execution_contract = record_qwen_live_apply_execution(
        task_id=task_id,
        target_file=str(tmp_path / "runtime.py"),
        candidate_file=str(tmp_path / "candidate.py"),
        smoke_cmd="python3 -m py_compile runtime.py",
        dry_run=True,
        ready=True,
        live_apply_ok=True,
        live_apply_result={"ok": True, "applied": False, "rolled_back": False},
        linked_live_apply_artifact=None,
        artifact_path=str(tmp_path / "candidate_apply.md"),
        root=tmp_path,
    )

    plan = build_backend_execution_replay_plan(
        backend_execution_request_id=execution_contract["backend_execution_request_id"],
        actor="tester",
        lane="tests",
        root=tmp_path,
    )
    before = execute_replay_plan(
        replay_plan_id=plan.replay_plan_id,
        actor="tester",
        lane="tests",
        root=tmp_path,
    )
    task = load_task(task_id, root=tmp_path)
    task.execution_backend = "qwen_planner"
    save_task(task, root=tmp_path)
    after = execute_replay_plan(
        replay_plan_id=plan.replay_plan_id,
        actor="tester",
        lane="tests",
        root=tmp_path,
    )

    assert before["replay_result"]["result_kind"] == "match"
    assert after["replay_result"]["result_kind"] == "drift"
    assert "execution_backend" in after["replay_result"]["drift_fields"]
