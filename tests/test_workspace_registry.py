from pathlib import Path
import json

from runtime.core.artifact_store import artifact_path, write_text_artifact
from runtime.core.models import TaskRecord, TaskStatus, TaskTriggerType, now_iso
from runtime.core.output_store import output_dir, publish_artifact
from runtime.core.status import build_status
from runtime.core.task_store import create_task, load_task
from runtime.core.workspace_registry import (
    HOME_WORKSPACE_ID,
    grant_workspace_access,
    get_workspace,
    list_workspaces,
    register_workspace,
    revoke_workspace_access,
    resolve_workspace_for_task,
    summarize_workspace_registry,
    update_workspace,
)
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export


def _make_task(task_id: str, *, target_workspace_id: str | None = None, allowed_workspace_ids: list[str] | None = None) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        created_at=now_iso(),
        updated_at=now_iso(),
        source_lane="tests",
        source_channel="tests",
        source_message_id=f"{task_id}_msg",
        source_user="tester",
        trigger_type=TaskTriggerType.EXPLICIT_TASK_COLON.value,
        raw_request=f"task: {task_id}",
        normalized_request=task_id,
        status=TaskStatus.QUEUED.value,
        target_workspace_id=target_workspace_id,
        allowed_workspace_ids=list(allowed_workspace_ids or []),
    )


def test_workspace_registry_registers_updates_and_summarizes(tmp_path: Path):
    record = register_workspace(
        workspace_id="docs_ws",
        label="Docs Workspace",
        absolute_path=str((tmp_path / "external_docs").resolve()),
        purpose="docs_editing",
        allowed_operations=["read", "write"],
        sensitivity="medium",
        default_read_only=False,
        tags=["docs"],
        owner="jarvis",
        runtime_notes="registered external docs workspace",
        root=tmp_path,
    )

    assert record.workspace_id == "docs_ws"
    assert get_workspace(HOME_WORKSPACE_ID, root=tmp_path) is not None
    assert get_workspace("docs_ws", root=tmp_path) is not None

    updated = update_workspace("docs_ws", root=tmp_path, tags=["docs", "shared"], runtime_notes="updated note")
    assert updated.tags == ["docs", "shared"]

    rows = list_workspaces(root=tmp_path)
    summary = summarize_workspace_registry(root=tmp_path)

    assert {row.workspace_id for row in rows} == {HOME_WORKSPACE_ID, "docs_ws"}
    assert summary["default_home_workspace_id"] == HOME_WORKSPACE_ID
    assert summary["workspace_count"] == 2
    assert summary["writable_workspace_count"] >= 1
    assert summary["operator_approved_workspace_count"] == 1


def test_workspace_resolution_respects_read_only_policy(tmp_path: Path):
    register_workspace(
        workspace_id="readonly_ws",
        label="Readonly Workspace",
        absolute_path=str((tmp_path / "readonly").resolve()),
        role="reference",
        purpose="reference_material",
        access_mode="scoped",
        allowed_operations=["read"],
        sensitivity="high",
        default_read_only=True,
        tags=["reference"],
        operator_approved=True,
        approved_lanes=["tests"],
        root=tmp_path,
    )
    register_workspace(
        workspace_id="write_ws",
        label="Writable Workspace",
        absolute_path=str((tmp_path / "writable").resolve()),
        role="project",
        purpose="bounded_editing",
        access_mode="scoped",
        allowed_operations=["read", "write"],
        sensitivity="medium",
        default_read_only=False,
        tags=["work"],
        operator_approved=True,
        approved_lanes=["tests"],
        root=tmp_path,
    )

    readonly_task = create_task(
        _make_task(
            "task_readonly",
            target_workspace_id="readonly_ws",
            allowed_workspace_ids=[HOME_WORKSPACE_ID, "readonly_ws"],
        ),
        root=tmp_path,
    )
    writable_task = create_task(
        _make_task(
            "task_writable",
            target_workspace_id="write_ws",
            allowed_workspace_ids=[HOME_WORKSPACE_ID, "write_ws"],
        ),
        root=tmp_path,
    )

    assert resolve_workspace_for_task(readonly_task, root=tmp_path, operation="read").workspace_id == "readonly_ws"
    try:
        resolve_workspace_for_task(readonly_task, root=tmp_path, operation="write")
    except ValueError as exc:
        assert "read-only" in str(exc)
    else:
        raise AssertionError("Expected read-only workspace write resolution to fail.")

    assert resolve_workspace_for_task(writable_task, root=tmp_path, operation="write").workspace_id == "write_ws"


def test_workspace_registry_is_default_deny_and_strategy_workspace_grants_are_explicit(tmp_path: Path):
    register_workspace(
        workspace_id="strategy_ws",
        label="Strategy Workspace",
        absolute_path=str((tmp_path / "strategy").resolve()),
        role="strategy",
        purpose="bounded_strategy_work",
        access_mode="scoped",
        allowed_operations=["read", "write"],
        sensitivity="high",
        default_read_only=False,
        tags=["strategy"],
        root=tmp_path,
    )

    strategy_task = create_task(
        _make_task(
            "task_strategy",
            target_workspace_id="strategy_ws",
            allowed_workspace_ids=[HOME_WORKSPACE_ID, "strategy_ws"],
        ),
        root=tmp_path,
    )

    try:
        resolve_workspace_for_task(strategy_task, root=tmp_path, operation="read")
    except ValueError as exc:
        assert "not operator-approved" in str(exc)
    else:
        raise AssertionError("Expected unapproved strategy workspace to be denied by default.")

    grant_workspace_access("strategy_ws", lane="jarvis", root=tmp_path)
    granted = resolve_workspace_for_task(strategy_task, root=tmp_path, operation="read", lane="jarvis")
    assert granted.workspace_id == "strategy_ws"

    try:
        resolve_workspace_for_task(strategy_task, root=tmp_path, operation="read", lane="ralph")
    except ValueError as exc:
        assert "not approved" in str(exc)
    else:
        raise AssertionError("Expected non-granted lane to be denied.")

    revoke_workspace_access("strategy_ws", lane="jarvis", root=tmp_path)
    try:
        resolve_workspace_for_task(strategy_task, root=tmp_path, operation="read", lane="jarvis")
    except ValueError as exc:
        assert "not approved" in str(exc)
    else:
        raise AssertionError("Expected revoked lane to be denied.")

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    summary = status["workspace_registry_summary"]
    assert summary["workspace_count"] == 2
    assert summary["operator_approved_workspace_count"] == 1
    strategy_row = next(row for row in summary["registered_workspaces"] if row["workspace_id"] == "strategy_ws")
    assert strategy_row["operator_approved"] is True
    assert strategy_row["approved_lanes"] == []
    assert snapshot["workspace_registry_summary"]["operator_approved_workspace_count"] == 1
    assert export_payload["workspace_registry_summary"]["workspace_access_mode_counts"]["home"] == 1


def test_workspace_touch_provenance_flows_through_task_artifact_and_output(tmp_path: Path):
    register_workspace(
        workspace_id="project_ws",
        label="Project Workspace",
        absolute_path=str((tmp_path / "project").resolve()),
        role="project",
        purpose="bounded_project_work",
        access_mode="scoped",
        allowed_operations=["read", "write"],
        sensitivity="medium",
        default_read_only=False,
        tags=["project"],
        operator_approved=True,
        approved_lanes=["tests"],
        root=tmp_path,
    )

    created_task = create_task(
        _make_task(
            "task_workspace_touch",
            target_workspace_id="project_ws",
            allowed_workspace_ids=[HOME_WORKSPACE_ID, "project_ws"],
        ),
        root=tmp_path,
    )
    stored_task = load_task("task_workspace_touch", root=tmp_path)
    artifact = write_text_artifact(
        task_id=created_task.task_id,
        artifact_type="report",
        title="Workspace-touched artifact",
        summary="summary",
        content="content",
        actor="tester",
        lane="artifacts",
        root=tmp_path,
    )
    output = publish_artifact(
        task_id=created_task.task_id,
        artifact_id=artifact["artifact_id"],
        actor="tester",
        lane="outputs",
        root=tmp_path,
    )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    artifact_payload = json.loads(artifact_path(artifact["artifact_id"], root=tmp_path).read_text(encoding="utf-8"))
    output_payload = json.loads((output_dir(root=tmp_path) / f"{output['output_id']}.json").read_text(encoding="utf-8"))

    assert stored_task.home_runtime_workspace == HOME_WORKSPACE_ID
    assert stored_task.target_workspace_id == "project_ws"
    assert set(stored_task.touched_workspace_ids) == {HOME_WORKSPACE_ID, "project_ws"}
    assert artifact_payload["home_runtime_workspace"] == HOME_WORKSPACE_ID
    assert artifact_payload["target_workspace_id"] == "project_ws"
    assert set(artifact_payload["touched_workspace_ids"]) == {HOME_WORKSPACE_ID, "project_ws"}
    assert output_payload["home_runtime_workspace"] == HOME_WORKSPACE_ID
    assert output_payload["target_workspace_id"] == "project_ws"
    assert set(output_payload["touched_workspace_ids"]) == {HOME_WORKSPACE_ID, "project_ws"}
    assert status["workspace_registry_summary"]["default_home_workspace_id"] == HOME_WORKSPACE_ID
    assert status["workspace_registry_summary"]["recent_task_workspace_rows"][0]["task_id"] == created_task.task_id
    assert "project_ws" in status["workspace_registry_summary"]["recent_task_workspace_rows"][0]["touched_workspace_ids"]
    assert snapshot["workspace_registry_summary"]["recent_output_workspace_rows"][0]["output_id"] == output["output_id"]
    assert export_payload["workspace_registry_summary"]["recent_artifact_workspace_rows"][0]["artifact_id"] == artifact["artifact_id"]
