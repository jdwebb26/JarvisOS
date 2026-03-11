#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.controls.control_store import apply_control_action
from runtime.core.models import (
    ControlAction,
    ControlScopeType,
    TaskStatus,
    TokenBudgetRecord,
    new_id,
    now_iso,
)
from runtime.core.task_events import append_event, make_event
from runtime.core.task_store import load_task, save_task


def token_budgets_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "token_budgets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(token_budget_id: str, *, root: Optional[Path] = None) -> Path:
    return token_budgets_dir(root) / f"{token_budget_id}.json"


def save_token_budget(record: TokenBudgetRecord, *, root: Optional[Path] = None) -> TokenBudgetRecord:
    record.updated_at = now_iso()
    _path(record.token_budget_id, root=root).write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return record


def load_token_budget(token_budget_id: str, *, root: Optional[Path] = None) -> Optional[TokenBudgetRecord]:
    path = _path(token_budget_id, root=root)
    if not path.exists():
        return None
    return TokenBudgetRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_token_budgets(root: Optional[Path] = None) -> list[TokenBudgetRecord]:
    items: list[TokenBudgetRecord] = []
    for path in token_budgets_dir(root).glob("*.json"):
        try:
            items.append(TokenBudgetRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    items.sort(key=lambda row: row.updated_at, reverse=True)
    return items


def create_token_budget(
    *,
    scope: str,
    actor: str,
    lane: str,
    scope_ref: Optional[str] = None,
    max_tokens_per_task: int = 0,
    max_tokens_per_cycle: int = 0,
    max_cost_usd_per_cycle: float = 0.0,
    current_usage: Optional[dict] = None,
    alert_threshold: Optional[dict] = None,
    hard_stop_threshold: Optional[dict] = None,
    root: Optional[Path] = None,
) -> TokenBudgetRecord:
    return save_token_budget(
        TokenBudgetRecord(
            token_budget_id=new_id("budget"),
            scope=scope,
            scope_ref=scope_ref,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            max_tokens_per_task=max_tokens_per_task,
            max_tokens_per_cycle=max_tokens_per_cycle,
            max_cost_usd_per_cycle=max_cost_usd_per_cycle,
            current_usage=dict(current_usage or {}),
            alert_threshold=dict(alert_threshold or {}),
            hard_stop_threshold=dict(hard_stop_threshold or {}),
        ),
        root=root,
    )


def _usage_value(record: TokenBudgetRecord, key: str) -> float:
    value = record.current_usage.get(key, 0)
    try:
        return float(value)
    except Exception:
        return 0.0


def _threshold_value(record: TokenBudgetRecord, key: str, fallback: float) -> float:
    value = record.hard_stop_threshold.get(key)
    if value is None:
        return float(fallback)
    try:
        parsed = float(value)
    except Exception:
        return float(fallback)
    if parsed <= 0:
        return float(fallback)
    return parsed


def _alert_value(record: TokenBudgetRecord, key: str, fallback: float) -> float:
    value = record.alert_threshold.get(key)
    if value is None:
        return float(fallback)
    try:
        parsed = float(value)
    except Exception:
        return float(fallback)
    if parsed <= 0:
        return float(fallback)
    return parsed


def _evaluate_budget(record: TokenBudgetRecord) -> dict:
    reasons: list[str] = []
    alerts: list[str] = []

    if record.scope == "task":
        task_tokens = _usage_value(record, "task_tokens")
        task_hard_stop = _threshold_value(record, "tokens_per_task", record.max_tokens_per_task)
        task_alert = _alert_value(record, "tokens_per_task", task_hard_stop)
        if task_hard_stop > 0 and task_tokens >= task_hard_stop:
            reasons.append(f"task_tokens {int(task_tokens)} >= hard_stop {int(task_hard_stop)}")
        elif task_alert > 0 and task_tokens >= task_alert:
            alerts.append(f"task_tokens {int(task_tokens)} >= alert {int(task_alert)}")

    cycle_tokens = _usage_value(record, "cycle_tokens")
    cycle_hard_stop = _threshold_value(record, "tokens_per_cycle", record.max_tokens_per_cycle)
    cycle_alert = _alert_value(record, "tokens_per_cycle", cycle_hard_stop)
    if cycle_hard_stop > 0 and cycle_tokens >= cycle_hard_stop:
        reasons.append(f"cycle_tokens {int(cycle_tokens)} >= hard_stop {int(cycle_hard_stop)}")
    elif cycle_alert > 0 and cycle_tokens >= cycle_alert:
        alerts.append(f"cycle_tokens {int(cycle_tokens)} >= alert {int(cycle_alert)}")

    cycle_cost = _usage_value(record, "cycle_cost_usd")
    cost_hard_stop = _threshold_value(record, "cost_usd_per_cycle", record.max_cost_usd_per_cycle)
    cost_alert = _alert_value(record, "cost_usd_per_cycle", cost_hard_stop)
    if cost_hard_stop > 0 and cycle_cost >= cost_hard_stop:
        reasons.append(f"cycle_cost_usd {cycle_cost:.4f} >= hard_stop {cost_hard_stop:.4f}")
    elif cost_alert > 0 and cycle_cost >= cost_alert:
        alerts.append(f"cycle_cost_usd {cycle_cost:.4f} >= alert {cost_alert:.4f}")

    return {
        "hard_stop_exceeded": bool(reasons),
        "alert_exceeded": bool(alerts),
        "reasons": reasons,
        "alerts": alerts,
    }


def _applicable_budgets(*, task_id: Optional[str], execution_backend: Optional[str], root: Optional[Path] = None) -> list[TokenBudgetRecord]:
    rows = list_token_budgets(root=root)
    applicable: list[TokenBudgetRecord] = []
    for row in rows:
        if row.scope == "global":
            applicable.append(row)
        elif row.scope == "task" and task_id and row.scope_ref == task_id:
            applicable.append(row)
        elif row.scope == "subsystem" and execution_backend and row.scope_ref == execution_backend:
            applicable.append(row)
    return applicable


def _pause_task_for_budget(
    *,
    task_id: str,
    actor: str,
    lane: str,
    execution_backend: Optional[str],
    reason: str,
    budget_ids: list[str],
    root: Optional[Path] = None,
) -> None:
    apply_control_action(
        action=ControlAction.PAUSE.value,
        actor=actor,
        lane=lane,
        scope_type=ControlScopeType.TASK.value,
        scope_id=task_id,
        reason=reason,
        metadata={"budget_ids": budget_ids, "budget_kind": "token_budget_hard_stop"},
        root=root,
    )
    task = load_task(task_id, root=root)
    if task is None:
        return
    from_status = task.status
    task.status = TaskStatus.BLOCKED.value
    task.error_count += 1
    task.last_error = reason
    save_task(task, root=root)
    append_event(
        make_event(
            task_id=task_id,
            event_type="token_budget_hard_stop",
            actor=actor,
            lane=lane,
            summary=reason,
            from_status=from_status,
            to_status=TaskStatus.BLOCKED.value,
            reason=reason,
            execution_backend=execution_backend or task.execution_backend,
            backend_run_id=task.backend_run_id,
            from_lifecycle_state=task.lifecycle_state,
            to_lifecycle_state=task.lifecycle_state,
        ),
        root=root,
    )


def assert_token_budget_allows_execution(
    *,
    task_id: str,
    actor: str,
    lane: str,
    execution_backend: Optional[str],
    root: Optional[Path] = None,
) -> None:
    applicable = _applicable_budgets(task_id=task_id, execution_backend=execution_backend, root=root)
    blocked: list[str] = []
    budget_ids: list[str] = []
    for row in applicable:
        evaluation = _evaluate_budget(row)
        if evaluation["hard_stop_exceeded"]:
            budget_ids.append(row.token_budget_id)
            blocked.append(f"{row.scope}:{row.scope_ref or row.scope} -> {'; '.join(evaluation['reasons'])}")
    if not blocked:
        return
    reason = "TokenBudget hard stop exceeded: " + " | ".join(blocked)
    _pause_task_for_budget(
        task_id=task_id,
        actor=actor,
        lane=lane,
        execution_backend=execution_backend,
        reason=reason,
        budget_ids=budget_ids,
        root=root,
    )
    raise ValueError(reason)


def apply_budget_usage(
    *,
    task_id: str,
    execution_backend: Optional[str],
    token_usage: int = 0,
    cost_usd: float = 0.0,
    root: Optional[Path] = None,
) -> None:
    if token_usage <= 0 and cost_usd <= 0:
        return
    applicable = _applicable_budgets(task_id=task_id, execution_backend=execution_backend, root=root)
    for row in applicable:
        current_usage = dict(row.current_usage or {})
        current_usage["cycle_tokens"] = int(current_usage.get("cycle_tokens", 0)) + int(token_usage)
        current_usage["cycle_cost_usd"] = float(current_usage.get("cycle_cost_usd", 0.0)) + float(cost_usd)
        if row.scope == "task":
            current_usage["task_tokens"] = int(current_usage.get("task_tokens", 0)) + int(token_usage)
        row.current_usage = current_usage
        save_token_budget(row, root=root)


def extract_usage_from_metadata(metadata: Optional[dict]) -> tuple[int, float]:
    meta = dict(metadata or {})
    token_usage = meta.get("token_usage")
    if token_usage is None:
        token_usage = meta.get("token_usage_total")
    if token_usage is None:
        token_usage = int(meta.get("prompt_tokens", 0)) + int(meta.get("completion_tokens", 0))
    cost_usd = meta.get("cost_usd", 0.0)
    try:
        token_usage_int = int(token_usage or 0)
    except Exception:
        token_usage_int = 0
    try:
        cost_usd_float = float(cost_usd or 0.0)
    except Exception:
        cost_usd_float = 0.0
    return token_usage_int, cost_usd_float


def build_token_budget_summary(root: Optional[Path] = None) -> dict:
    rows = list_token_budgets(root=root)
    latest = rows[0].to_dict() if rows else None
    hard_stop_count = 0
    alert_count = 0
    statuses: dict[str, int] = {}
    for row in rows:
        evaluation = _evaluate_budget(row)
        if evaluation["hard_stop_exceeded"]:
            status = "hard_stop"
            hard_stop_count += 1
        elif evaluation["alert_exceeded"]:
            status = "alert"
            alert_count += 1
        else:
            status = "ok"
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "token_budget_count": len(rows),
        "token_budget_status_counts": statuses,
        "hard_stop_budget_count": hard_stop_count,
        "alert_budget_count": alert_count,
        "latest_token_budget": latest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current TokenBudget summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_token_budget_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
