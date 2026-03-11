from pathlib import Path

from runtime.core.execution_contracts import (
    record_backend_execution_request,
    record_backend_execution_result,
)
from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.task_events import list_events
from runtime.core.task_store import create_task, load_task
from runtime.core.token_budget import build_token_budget_summary, create_token_budget, list_token_budgets
from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from scripts.operator_handoff_pack import build_operator_handoff_pack


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
            status=TaskStatus.RUNNING.value,
            assigned_model="Qwen3.5-35B",
            execution_backend="qwen_executor",
        ),
        root=root,
    )


def test_token_budget_hard_stop_blocks_new_execution_and_pauses_task(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_token_budget_stop")
    create_token_budget(
        scope="task",
        scope_ref=task.task_id,
        actor="tester",
        lane="tests",
        max_tokens_per_task=100,
        current_usage={"task_tokens": 100, "cycle_tokens": 100, "cycle_cost_usd": 0.0},
        hard_stop_threshold={"tokens_per_task": 100},
        alert_threshold={"tokens_per_task": 80},
        root=tmp_path,
    )

    try:
        record_backend_execution_request(
            task_id=task.task_id,
            actor="tester",
            lane="tests",
            request_kind="token_budget_drill",
            execution_backend="qwen_executor",
            provider_id="qwen",
            model_name="Qwen3.5-35B",
            input_summary="should be blocked",
            root=tmp_path,
        )
        assert False, "Expected TokenBudget hard stop to block execution request."
    except ValueError as exc:
        assert "TokenBudget hard stop exceeded" in str(exc)

    task_after = load_task(task.task_id, root=tmp_path)
    assert task_after is not None
    assert task_after.status == TaskStatus.BLOCKED.value
    assert "TokenBudget hard stop exceeded" in task_after.last_error

    events = list_events(task.task_id, root=tmp_path)
    assert any(event.event_type == "token_budget_hard_stop" for event in events)

    status = build_status(tmp_path)
    assert status["token_budget_summary"]["hard_stop_budget_count"] == 1


def test_token_budget_usage_updates_and_surfaces_in_reporting(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_token_budget_usage")
    create_token_budget(
        scope="task",
        scope_ref=task.task_id,
        actor="tester",
        lane="tests",
        max_tokens_per_task=500,
        max_tokens_per_cycle=1000,
        max_cost_usd_per_cycle=10.0,
        current_usage={"task_tokens": 0, "cycle_tokens": 0, "cycle_cost_usd": 0.0},
        alert_threshold={"tokens_per_task": 250, "tokens_per_cycle": 500, "cost_usd_per_cycle": 5.0},
        hard_stop_threshold={"tokens_per_task": 500, "tokens_per_cycle": 1000, "cost_usd_per_cycle": 10.0},
        root=tmp_path,
    )

    request = record_backend_execution_request(
        task_id=task.task_id,
        actor="tester",
        lane="tests",
        request_kind="token_budget_usage",
        execution_backend="qwen_executor",
        provider_id="qwen",
        model_name="Qwen3.5-35B",
        input_summary="usage tracking",
        root=tmp_path,
    )
    record_backend_execution_result(
        backend_execution_request_id=request.backend_execution_request_id,
        task_id=task.task_id,
        actor="tester",
        lane="tests",
        request_kind="token_budget_usage",
        execution_backend="qwen_executor",
        provider_id="qwen",
        model_name="Qwen3.5-35B",
        status="completed",
        outcome_summary="usage tracked",
        metadata={"token_usage": 120, "cost_usd": 1.5},
        root=tmp_path,
    )

    budgets = list_token_budgets(root=tmp_path)
    assert budgets[0].current_usage["task_tokens"] == 120
    assert budgets[0].current_usage["cycle_tokens"] == 120
    assert budgets[0].current_usage["cycle_cost_usd"] == 1.5

    summary = build_token_budget_summary(root=tmp_path)
    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]

    assert summary["token_budget_count"] == 1
    assert summary["hard_stop_budget_count"] == 0
    assert summary["latest_token_budget"]["scope"] == "task"
    assert status["token_budget_summary"]["latest_token_budget"]["current_usage"]["task_tokens"] == 120
    assert snapshot["token_budget_summary"]["latest_token_budget"]["current_usage"]["cycle_tokens"] == 120
    assert export_payload["counts"]["token_budgets"] == 1
    assert export_payload["token_budget_summary"]["latest_token_budget"]["current_usage"]["cycle_cost_usd"] == 1.5
    assert handoff["token_budget_summary"]["latest_token_budget"]["current_usage"]["task_tokens"] == 120
