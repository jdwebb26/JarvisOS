import json
from pathlib import Path

from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from scripts.preflight_lib import build_doctor_report


def _write_json(root: Path, relative_path: str, payload: dict) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_openclaw_discord_bridge_summary_is_mirrored_and_visible(tmp_path: Path):
    _write_json(
        tmp_path,
        "state/operator_gateway_inbound_messages/discord_fail.json",
        {
            "created_at": "2026-03-12T10:00:00+00:00",
            "source_kind": "openclaw_gateway",
            "source_lane": "operator",
            "source_channel": "discord_jarvis",
            "source_message_id": "discord_fail",
            "source_user": "operator",
            "provider_id": "lmstudio",
            "model_name": "qwen/qwen3.5-9b",
            "raw_text": "A1",
        },
    )
    _write_json(
        tmp_path,
        "state/operator_imported_reply_messages/opimport_fail.json",
        {
            "import_id": "opimport_fail",
            "created_at": "2026-03-12T10:00:05+00:00",
            "completed_at": "2026-03-12T10:00:06+00:00",
            "source_kind": "openclaw_gateway",
            "source_lane": "operator",
            "source_channel": "discord_jarvis",
            "source_message_id": "discord_fail",
            "source_user": "operator",
            "classification": "importable_compact_reply",
            "imported": True,
        },
    )
    _write_json(
        tmp_path,
        "state/operator_reply_ingress/opreplying_fail.json",
        {
            "ingress_id": "opreplying_fail",
            "created_at": "2026-03-12T10:00:08+00:00",
            "completed_at": "2026-03-12T10:00:09+00:00",
            "source_kind": "openclaw_gateway",
            "source_lane": "operator",
            "source_channel": "discord_jarvis",
            "source_message_id": "discord_fail",
            "source_user": "operator",
            "result_kind": "blocked",
            "result_ref_id": "opreplyapply_fail",
        },
    )
    _write_json(
        tmp_path,
        "state/operator_reply_applies/opreplyapply_fail.json",
        {
            "reply_apply_id": "opreplyapply_fail",
            "started_at": "2026-03-12T10:00:08+00:00",
            "completed_at": "2026-03-12T10:00:09+00:00",
            "ok": False,
            "per_step_results": [
                {
                    "reply_code": "A1",
                    "status": "failed_execution",
                    "payload": {
                        "ok": False,
                        "error_type": "governance_blocked",
                        "message": "review gate uncleared",
                        "blocked": {
                            "blocked_action_id": "block_fail",
                            "action": "publish_output",
                            "task_id": "task_fail",
                            "reason": "review gate uncleared",
                        },
                    },
                }
            ],
        },
    )
    _write_json(
        tmp_path,
        "state/operator_bridge_cycles/opbridge_fail.json",
        {
            "bridge_cycle_id": "opbridge_fail",
            "started_at": "2026-03-12T10:00:10+00:00",
            "completed_at": "2026-03-12T10:00:11+00:00",
            "ok": False,
            "imported_source_message_ids": ["discord_fail"],
        },
    )

    _write_json(
        tmp_path,
        "state/operator_gateway_inbound_messages/discord_success.json",
        {
            "created_at": "2026-03-12T11:00:00+00:00",
            "source_kind": "openclaw_gateway",
            "source_lane": "operator",
            "source_channel": "discord_jarvis",
            "source_message_id": "discord_success",
            "source_user": "operator",
            "provider_id": "lmstudio",
            "model_name": "qwen/qwen3.5-35b-a3b",
            "raw_text": "A2",
        },
    )
    _write_json(
        tmp_path,
        "state/operator_reply_ingress/opreplying_success.json",
        {
            "ingress_id": "opreplying_success",
            "created_at": "2026-03-12T11:00:03+00:00",
            "completed_at": "2026-03-12T11:00:04+00:00",
            "source_kind": "openclaw_gateway",
            "source_lane": "operator",
            "source_channel": "discord_jarvis",
            "source_message_id": "discord_success",
            "source_user": "operator",
            "result_kind": "applied",
            "result_ref_id": "opreplyapply_success",
        },
    )
    _write_json(
        tmp_path,
        "state/operator_reply_applies/opreplyapply_success.json",
        {
            "reply_apply_id": "opreplyapply_success",
            "started_at": "2026-03-12T11:00:03+00:00",
            "completed_at": "2026-03-12T11:00:04+00:00",
            "ok": True,
            "per_step_results": [
                {
                    "reply_code": "A2",
                    "status": "executed",
                    "payload": {"ok": True},
                }
            ],
        },
    )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    report = build_doctor_report(tmp_path)

    bridge = status["openclaw_discord_bridge_summary"]
    assert bridge["summary_kind"] == "mirrored_openclaw_discord_activity"
    assert bridge["authoritative_runtime"] == "openclaw"
    assert bridge["mirrored_only"] is True
    assert bridge["recent_discord_attempt_count"] == 2
    assert bridge["latest_attempt"]["source_message_id"] == "discord_success"
    assert bridge["latest_attempt"]["selected_provider_id"] == "lmstudio"
    assert bridge["latest_attempt"]["selected_model_name"] == "qwen/qwen3.5-35b-a3b"
    assert bridge["latest_failure"]["source_message_id"] == "discord_fail"
    assert bridge["latest_failure"]["failure_class"] == "governance_blocked"
    assert bridge["latest_successful_reply"]["source_message_id"] == "discord_success"

    assert status["discord_live_ops_summary"]["discord_origin_task_count"] == 0
    assert snapshot["openclaw_discord_bridge_summary"]["latest_failure"]["failure_class"] == "governance_blocked"
    assert export_payload["openclaw_discord_bridge_summary"]["latest_successful_reply"]["source_message_id"] == "discord_success"
    assert report["openclaw_discord_bridge_summary"]["latest_failure"]["failure_class"] == "governance_blocked"
    assert any(item["category"] == "openclaw_bridge" for item in report["groups"]["openclaw_bridge"])
