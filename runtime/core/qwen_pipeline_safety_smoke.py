#!/usr/bin/env python3
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core import qwen_candidate_writer as writer
from runtime.core import qwen_patch_executor as executor


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def setup_case(root: Path) -> tuple[Path, Path, Path]:
    workspace = root / "workspace"
    repo = workspace / "jarvis-v5"
    artifacts = workspace / "artifacts" / "qwen_live" / "2026-03-10"
    (repo / "runtime" / "core").mkdir(parents=True, exist_ok=True)
    (repo / "state" / "tasks").mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)

    target = repo / "runtime" / "core" / "decision_router.py"
    target.write_text(
        "\n".join(
            [
                "def route_task_for_decision(*, task) -> dict:",
                "    if task.review_required:",
                "        if latest_review is None:",
                '            return {"kind": "review_requested", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": "pending"}',
                "",
                "        if latest_review.status == \"pending\":",
                '            return {"kind": "waiting_review", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": latest_review.status, "message": "A review already exists and is still pending."}',
                "",
                "        if latest_review.status != \"approved\":",
                '            return {"kind": "blocked_by_review", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": latest_review.status, "message": "The latest review is not approved, so the task cannot proceed."}',
                "",
                "    if task.approval_required:",
                "        if latest_approval is None:",
                '            return {"kind": "approval_requested", "task_id": task.task_id, "approval_id": "apr_1", "requested_reviewer": "operator", "status": "pending"}',
                "",
                "        if latest_approval.status == \"pending\":",
                '            return {"kind": "waiting_approval", "task_id": task.task_id, "approval_id": "apr_1", "requested_reviewer": "operator", "status": latest_approval.status, "message": "An approval request already exists and is still pending."}',
                "",
                "        if latest_approval.status != \"approved\":",
                '            return {"kind": "blocked_by_approval", "task_id": task.task_id, "approval_id": "apr_1", "requested_reviewer": "operator", "status": latest_approval.status, "message": "The latest approval is not approved, so the task cannot proceed."}',
                "",
                '    return {"kind": "no_action", "task_id": task.task_id, "message": "No new review or approval request was needed."}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    plan = artifacts / "latest_task_task_demo_patch_plan.md"
    plan.write_text(
        "# Plan\n\n- target: /tmp\n- file: /home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/decision_router.py\n- scope: route_task_for_decision\n- leaf-scope: return block under latest_review is None\n",
        encoding="utf-8",
    )
    task = repo / "state" / "tasks" / "task_demo.json"
    write_json(
        task,
        {
            "task_id": "task_demo",
            "status": "ready_to_ship",
            "final_outcome": "",
            "checkpoint_summary": "",
        },
    )
    write_json(repo / "runtime" / "core" / "qwen_approval_state.json", {"approved_task_id": "task_demo", "mode": "dry_run"})
    write_json(
        repo / "runtime" / "core" / "qwen_write_gate.json",
        {
            "enabled": True,
            "mode": "allowlist_only",
            "approved_task_id": "task_demo",
            "allowed_paths": [str(target)],
        },
    )
    return repo, artifacts, target


def run_writer(repo: Path, artifacts: Path, fake_model_output: str, patch_plan_text: str | None = None) -> tuple[dict, dict]:
    target = repo / "runtime" / "core" / "decision_router.py"
    plan_path = artifacts / "latest_task_task_demo_patch_plan.md"
    if patch_plan_text is not None:
        plan_path.write_text(patch_plan_text, encoding="utf-8")
    write_json(
        repo / "state" / "tasks" / "task_demo.json",
        {
            "task_id": "task_demo",
            "status": "ready_to_ship",
            "final_outcome": "",
            "checkpoint_summary": "",
        },
    )
    with patch.object(writer, "WORKSPACE", repo.parent), \
         patch.object(writer, "ARTIFACT_ROOT", artifacts.parent), \
         patch.object(writer, "APPROVAL_PATH", repo / "runtime" / "core" / "qwen_approval_state.json"), \
         patch.object(writer, "WRITE_GATE_PATH", repo / "runtime" / "core" / "qwen_write_gate.json"), \
         patch.object(writer, "TASKS_DIR", repo / "state" / "tasks"), \
         patch.object(writer, "extract_target_files", return_value=[str(target)]), \
         patch.object(writer, "call_model", return_value=fake_model_output), \
         patch("sys.argv", ["qwen_candidate_writer.py", "--patch-plan", str(plan_path), "--json"]):
        outputs = []
        with patch("builtins.print", side_effect=outputs.append):
            writer.main()
        payload = json.loads(outputs[-1])
        task_data = json.loads((repo / "state" / "tasks" / "task_demo.json").read_text(encoding="utf-8"))
        return payload, task_data


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="qwen_pipeline_safety_", dir="/tmp"))
    try:
        repo, artifacts, _target = setup_case(temp_root)

        prose_payload, prose_task = run_writer(
            repo,
            artifacts,
            "The user wants me to apply a patch to this file.",
        )
        invalid_payload, invalid_task = run_writer(
            repo,
            artifacts,
            "            return {\n",
        )
        accepted_payload, accepted_task = run_writer(
            repo,
            artifacts,
            "            return {\"kind\": \"review_requested\", \"task_id\": task.task_id, \"review_id\": \"rev_new\", \"reviewer_role\": \"archimedes\", \"status\": \"pending\"}\n",
        )
        top_level_preserving_payload, top_level_preserving_task = run_writer(
            repo,
            artifacts,
            "\n".join(
                [
                    "def route_task_for_decision(*, task) -> dict:",
                    "    if task.review_required:",
                    "        if latest_review is None:",
                    '            return {"kind": "review_requested", "task_id": task.task_id, "review_id": "rev_new", "reviewer_role": "archimedes", "status": "pending"}',
                    "",
                    "        if latest_review.status == \"pending\":",
                    '            return {"kind": "waiting_review", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": latest_review.status, "message": "A review already exists and is still pending."}',
                    "",
                    "        if latest_review.status != \"approved\":",
                    '            return {"kind": "blocked_by_review", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": latest_review.status, "message": "The latest review is not approved, so the task cannot proceed."}',
                    "",
                    "    if task.approval_required:",
                    "        if latest_approval is None:",
                    '            return {"kind": "approval_requested", "task_id": task.task_id, "approval_id": "apr_1", "requested_reviewer": "operator", "status": "pending"}',
                    "",
                    "        if latest_approval.status == \"pending\":",
                    '            return {"kind": "waiting_approval", "task_id": task.task_id, "approval_id": "apr_1", "requested_reviewer": "operator", "status": latest_approval.status, "message": "An approval request already exists and is still pending."}',
                    "",
                    "        if latest_approval.status != \"approved\":",
                    '            return {"kind": "blocked_by_approval", "task_id": task.task_id, "approval_id": "apr_1", "requested_reviewer": "operator", "status": latest_approval.status, "message": "The latest approval is not approved, so the task cannot proceed."}',
                    "",
                    "    # same contract, small refactor/comment only",
                    '    return {"kind": "no_action", "task_id": task.task_id, "message": "No new review or approval request was needed."}',
                    "",
                ]
            ),
        )
        drift_key_payload, drift_key_task = run_writer(
            repo,
            artifacts,
            "\n".join(
                [
                    "def route_task_for_decision(*, task) -> dict:",
                    "    if task.review_required:",
                    "        if latest_review is None:",
                    '            return {"kind": "review_requested", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": "pending"}',
                    "",
                    "        if latest_review.status == \"pending\":",
                    '            return {"kind": "waiting_review", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": latest_review.status, "message": "A review already exists and is still pending."}',
                    "",
                    "        if latest_review.status != \"approved\":",
                    '            return {"kind": "blocked_by_review", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": latest_review.status, "message": "The latest review is not approved, so the task cannot proceed."}',
                    "",
                    "    if task.approval_required:",
                    "        if latest_approval is None:",
                    '            return {"kind": "approval_requested", "task_id": task.task_id, "approval_id": "apr_1", "approver_role": "operator", "status": "pending"}',
                    "",
                    "        if latest_approval.status == \"pending\":",
                    '            return {"kind": "waiting_approval", "task_id": task.task_id, "approval_id": "apr_1", "approver_role": "operator", "status": latest_approval.status, "message": "An approval request already exists and is still pending."}',
                    "",
                    "        if latest_approval.status != \"approved\":",
                    '            return {"kind": "blocked_by_approval", "task_id": task.task_id, "approval_id": "apr_1", "approver_role": "operator", "status": latest_approval.status, "message": "The latest approval is not approved, so the task cannot proceed."}',
                    "",
                    '    return {"kind": "no_action", "task_id": task.task_id, "message": "No new review or approval request was needed."}',
                    "",
                ]
            ),
        )
        drift_message_payload, drift_message_task = run_writer(
            repo,
            artifacts,
            "\n".join(
                [
                    "def route_task_for_decision(*, task) -> dict:",
                    "    if task.review_required:",
                    "        if latest_review is None:",
                    '            return {"kind": "review_requested", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": "pending"}',
                    "",
                    "        if latest_review.status == \"pending\":",
                    '            return {"kind": "waiting_review", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": latest_review.status, "message": "A review already exists and is still pending."}',
                    "",
                    "        if latest_review.status != \"approved\":",
                    '            return {"kind": "blocked_by_review", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": latest_review.status, "message": "The latest review is not approved, so the task cannot proceed."}',
                    "",
                    "    if task.approval_required:",
                    "        if latest_approval is None:",
                    '            return {"kind": "approval_requested", "task_id": task.task_id, "approval_id": "apr_1", "requested_reviewer": "operator", "status": "pending"}',
                    "",
                    "        if latest_approval.status == \"pending\":",
                    '            return {"kind": "waiting_approval", "task_id": task.task_id, "approval_id": "apr_1", "requested_reviewer": "operator", "status": latest_approval.status, "message": "Approval still pending."}',
                    "",
                    "        if latest_approval.status != \"approved\":",
                    '            return {"kind": "blocked_by_approval", "task_id": task.task_id, "approval_id": "apr_1", "requested_reviewer": "operator", "status": latest_approval.status, "message": "The latest approval is not approved, so the task cannot proceed."}',
                    "",
                    '    return {"kind": "no_action", "task_id": task.task_id, "message": "No new review or approval request was needed."}',
                    "",
                ]
            ),
        )
        allowlisted_payload, allowlisted_task = run_writer(
            repo,
            artifacts,
            "\n".join(
                [
                    "def route_task_for_decision(*, task) -> dict:",
                    "    if task.review_required:",
                    "        if latest_review is None:",
                    '            return {"kind": "review_requested", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": "pending"}',
                    "",
                    "        if latest_review.status == \"pending\":",
                    '            return {"kind": "waiting_review", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": latest_review.status, "message": "A review already exists and is still pending."}',
                    "",
                    "        if latest_review.status != \"approved\":",
                    '            return {"kind": "blocked_by_review", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": latest_review.status, "message": "The latest review is not approved, so the task cannot proceed."}',
                    "",
                    "    if task.approval_required:",
                    "        if latest_approval is None:",
                    '            return {"kind": "approval_requested", "task_id": task.task_id, "approval_id": "apr_1", "approver_role": "operator", "status": "pending"}',
                    "",
                    "        if latest_approval.status == \"pending\":",
                    '            return {"kind": "waiting_approval", "task_id": task.task_id, "approval_id": "apr_1", "requested_reviewer": "operator", "status": latest_approval.status, "message": "An approval request already exists and is still pending."}',
                    "",
                    "        if latest_approval.status != \"approved\":",
                    '            return {"kind": "blocked_by_approval", "task_id": task.task_id, "approval_id": "apr_1", "requested_reviewer": "operator", "status": latest_approval.status, "message": "The latest approval is not approved, so the task cannot proceed."}',
                    "",
                    '    return {"kind": "no_action", "task_id": task.task_id, "message": "No new review or approval request was needed."}',
                    "",
                ]
            ),
            "# Plan\n\n- file: /home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/decision_router.py\n- scope: route_task_for_decision\n- requested_reviewer -> approver_role\n",
        )
        drift_kind_payload, drift_kind_task = run_writer(
            repo,
            artifacts,
            "\n".join(
                [
                    "def route_task_for_decision(*, task) -> dict:",
                    "    if task.review_required:",
                    "        if latest_review is None:",
                    '            return {"kind": "review_requested", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": "pending"}',
                    "",
                    "        if latest_review.status == \"pending\":",
                    '            return {"kind": "waiting_review", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": latest_review.status, "message": "A review already exists and is still pending."}',
                    "",
                    "        if latest_review.status != \"approved\":",
                    '            return {"kind": "blocked_by_review", "task_id": task.task_id, "review_id": "rev_1", "reviewer_role": "archimedes", "status": latest_review.status, "message": "The latest review is not approved, so the task cannot proceed."}',
                    "",
                    "    if task.approval_required:",
                    "        if latest_approval is None:",
                    '            return {"kind": "approval_requested", "task_id": task.task_id, "approval_id": "apr_1", "requested_reviewer": "operator", "status": "pending"}',
                    "",
                    "        if latest_approval.status == \"pending\":",
                    '            return {"kind": "waiting_approval", "task_id": task.task_id, "approval_id": "apr_1", "requested_reviewer": "operator", "status": latest_approval.status, "message": "An approval request already exists and is still pending."}',
                    "",
                    "        if latest_approval.status != \"approved\":",
                    '            return {"kind": "blocked_by_approval", "task_id": task.task_id, "approval_id": "apr_1", "requested_reviewer": "operator", "status": latest_approval.status, "message": "The latest approval is not approved, so the task cannot proceed."}',
                    "",
                    '    return {"kind": "ready", "task_id": task.task_id, "status": "ready"}',
                    "",
                ]
            ),
        )

        with patch.object(writer, "ARTIFACT_ROOT", artifacts.parent), patch.object(executor, "ARTIFACT_ROOT", artifacts.parent):
            selected_plan = executor.latest_patch_plan("task_demo")

        payload = {
            "ok": True,
            "scoped_route_selected": prose_payload["selected_scope_name"] == "route_task_for_decision",
            "leaf_scope_selected": prose_payload["leaf_scope_label"] == "latest_review_missing_return",
            "leaf_scope_attempted": prose_payload["leaf_scope_attempted"],
            "nano_scope_selected": prose_payload["nano_scope_label"] == "latest_review_missing_branch",
            "nano_scope_attempted_after_leaf_failure": prose_payload["nano_scope_attempted"],
            "micro_scope_selected": prose_payload["micro_scope_label"] == "review_required_branch",
            "micro_scope_attempted_after_nano_failure": prose_payload["micro_scope_attempted"],
            "top_level_scope_attempted_after_micro_failure": prose_payload["top_level_scope_attempted"],
            "prose_rejected": prose_payload["output_status"] == "rejected_contamination",
            "prose_fallback": prose_payload["candidate_is_fallback"],
            "prose_task_not_rearmed": prose_task["final_outcome"] == "",
            "invalid_leaf_scope_rejected": invalid_payload["leaf_scope_attempted"] and not invalid_payload["leaf_scope_accepted"],
            "invalid_nano_scope_rejected": invalid_payload["nano_scope_attempted"] and not invalid_payload["nano_scope_accepted"],
            "invalid_scoped_python_fallback": invalid_payload["output_status"] == "fallback_live_baseline_invalid_python",
            "invalid_micro_scope_rejected": invalid_payload["micro_scope_attempted"] and not invalid_payload["micro_scope_accepted"],
            "invalid_python_fallback": invalid_payload["output_status"] == "fallback_live_baseline_invalid_python",
            "invalid_python_task_not_rearmed": invalid_task["final_outcome"] == "",
            "task_bound_patch_plan_selected": str(selected_plan).endswith("latest_task_task_demo_patch_plan.md"),
            "semantic_key_drift_rejected": drift_key_payload["semantic_guard_applied"] and not drift_key_payload["semantic_guard_passed"] and "requested_reviewer" in drift_key_payload["semantic_guard_drifted_tokens"],
            "semantic_key_drift_fallback": drift_key_payload["candidate_is_fallback"],
            "semantic_key_drift_task_not_rearmed": drift_key_task["final_outcome"] == "",
            "semantic_kind_drift_rejected": drift_kind_payload["semantic_guard_applied"] and not drift_kind_payload["semantic_guard_passed"] and "no_action" in drift_kind_payload["semantic_guard_drifted_tokens"],
            "semantic_kind_drift_fallback": drift_kind_payload["candidate_is_fallback"],
            "semantic_kind_drift_task_not_rearmed": drift_kind_task["final_outcome"] == "",
            "semantic_message_drift_rejected": drift_message_payload["semantic_guard_applied"] and not drift_message_payload["semantic_guard_passed"] and any("latest_approval_pending" in item for item in drift_message_payload["semantic_guard_branch_failures"]),
            "semantic_message_drift_fallback": drift_message_payload["candidate_is_fallback"],
            "semantic_message_drift_task_not_rearmed": drift_message_task["final_outcome"] == "",
            "accepted_leaf_scope_real_candidate": accepted_payload["real_candidate"] and accepted_payload["rewrite_level"] == "leaf_scope",
            "accepted_leaf_scope_recorded": accepted_payload["leaf_scope_accepted"] and not accepted_payload["candidate_is_fallback"],
            "accepted_task_armed": accepted_task["final_outcome"] == "candidate_ready_for_live_apply",
            "contract_preserving_top_level_accepted": top_level_preserving_payload["real_candidate"] and top_level_preserving_payload["rewrite_level"] == "top_level_scope" and top_level_preserving_payload["semantic_guard_passed"],
            "contract_preserving_top_level_armed": top_level_preserving_task["final_outcome"] == "candidate_ready_for_live_apply",
            "allowlisted_drift_accepted": allowlisted_payload["real_candidate"] and allowlisted_payload["semantic_guard_passed"] and any("requested_reviewer -> approver_role" in item for item in allowlisted_payload["semantic_guard_allowlisted_changes"]),
            "allowlisted_drift_armed": allowlisted_task["final_outcome"] == "candidate_ready_for_live_apply",
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if all(value for key, value in payload.items() if key != "ok") else 1
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
