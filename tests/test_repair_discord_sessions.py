import json
from pathlib import Path
from unittest.mock import patch

from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.integrations.openclaw_sessions import (
    build_openclaw_discord_session_integrity_summary,
    repair_discord_sessions,
    sanitize_user_facing_assistant_reply,
)
from scripts.preflight_lib import build_doctor_report


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_malformed_discord_session_is_detected_and_visible(tmp_path: Path) -> None:
    openclaw_root = tmp_path / ".openclaw"
    session_id = "sess_bad_1"
    session_key = "agent:jarvis:discord:channel:123"
    _write_json(
        openclaw_root / "agents" / "jarvis" / "sessions" / "sessions.json",
        {
            session_key: {
                "sessionId": session_id,
                "providerOverride": "lmstudio",
                "modelOverride": "qwen/qwen3.5-9b",
                "compactionCount": 2,
                "lastChannel": "discord",
                "sessionFile": str(openclaw_root / "agents" / "jarvis" / "sessions" / f"{session_id}.jsonl"),
            }
        },
    )
    _write_jsonl(
        openclaw_root / "agents" / "jarvis" / "sessions" / f"{session_id}.jsonl",
        [
            {"type": "model_change", "provider": "lmstudio", "modelId": "qwen/qwen3.5-9b"},
            {"type": "custom", "customType": "model-snapshot", "data": {"provider": "lmstudio", "modelId": "qwen/qwen3.5-9b"}},
            {
                "type": "message",
                "timestamp": "2026-03-12T18:18:15.484Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": 'Error rendering prompt with jinja template: "No user query found in messages."'}],
                },
            },
        ],
    )

    with patch.dict("os.environ", {"OPENCLAW_HOME": str(openclaw_root)}):
        summary = build_openclaw_discord_session_integrity_summary(repo_root=tmp_path)
        status = build_status(tmp_path)
        snapshot = build_operator_snapshot(tmp_path)
        export_payload = build_state_export(tmp_path)
        doctor = build_doctor_report(tmp_path)

    assert summary["malformed_session_count"] == 1
    latest = summary["latest_malformed_session"]
    assert latest["malformed_reason"] == "malformed_session_template_no_user_query"
    assert latest["compaction_count"] == 2
    assert "repair_discord_sessions.py" in latest["operator_action_required"]
    assert status["openclaw_discord_session_summary"]["malformed_session_count"] == 1
    assert snapshot["openclaw_discord_session_summary"]["latest_malformed_session"]["session_id"] == session_id
    assert export_payload["openclaw_discord_session_summary"]["latest_malformed_session"]["selected_model_name"] == "qwen/qwen3.5-9b"
    assert doctor["openclaw_discord_session_summary"]["latest_malformed_session"]["malformed_reason"] == "malformed_session_template_no_user_query"


def test_repair_discord_sessions_archives_and_unbinds_malformed_session(tmp_path: Path) -> None:
    openclaw_root = tmp_path / ".openclaw"
    session_id = "sess_bad_2"
    session_key = "agent:jarvis:discord:channel:456"
    session_file = openclaw_root / "agents" / "jarvis" / "sessions" / f"{session_id}.jsonl"
    _write_json(
        openclaw_root / "agents" / "jarvis" / "sessions" / "sessions.json",
        {
            session_key: {
                "sessionId": session_id,
                "providerOverride": "lmstudio",
                "modelOverride": "qwen/qwen3.5-9b",
                "compactionCount": 1,
                "lastChannel": "discord",
                "sessionFile": str(session_file),
            }
        },
    )
    _write_jsonl(
        session_file,
        [
            {"type": "model_change", "provider": "lmstudio", "modelId": "qwen/qwen3.5-9b"},
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": 'Error rendering prompt with jinja template: "No user query found in messages."'}],
                },
            },
        ],
    )

    result = repair_discord_sessions(
        repo_root=tmp_path,
        openclaw_root=openclaw_root,
        repair_all_malformed=True,
        apply=True,
    )

    assert result["ok"] is True
    assert result["target_count"] == 1
    repaired = result["repaired_sessions"][0]
    assert repaired["removed_binding"] is True
    assert ".jsonl.malformed_" in repaired["archived_session_file"]
    stored_index = json.loads((openclaw_root / "agents" / "jarvis" / "sessions" / "sessions.json").read_text(encoding="utf-8"))
    assert session_key not in stored_index
    assert not session_file.exists()
    assert Path(repaired["archived_session_file"]).exists()


def test_sanitize_user_facing_assistant_reply_strips_scaffold_and_missing_noise() -> None:
    raw = """
</context>
<system_status>
[MISSING] Expected at: /home/rollan/.openclaw/workspace/jarvis-v5/USER.md
I've read SOUL.md and checked AGENTS.md.
ShadowBroker is not installed.
""".strip()

    sanitized = sanitize_user_facing_assistant_reply(raw)

    assert sanitized["was_sanitized"] is True
    assert "</context>" not in sanitized["clean_text"]
    assert "<system_status>" not in sanitized["clean_text"]
    assert "[MISSING] Expected at:" not in sanitized["clean_text"]
    assert "read SOUL.md" not in sanitized["clean_text"]
    assert sanitized["clean_text"] == "ShadowBroker is not installed."


def test_session_summary_exposes_clean_reply_separately_from_raw_diagnostics(tmp_path: Path) -> None:
    openclaw_root = tmp_path / ".openclaw"
    session_id = "sess_reply_1"
    session_key = "agent:jarvis:discord:channel:789"
    session_file = openclaw_root / "agents" / "jarvis" / "sessions" / f"{session_id}.jsonl"
    _write_json(
        openclaw_root / "agents" / "jarvis" / "sessions" / "sessions.json",
        {
            session_key: {
                "sessionId": session_id,
                "providerOverride": "lmstudio",
                "modelOverride": "qwen/qwen3.5-9b",
                "compactionCount": 0,
                "lastChannel": "discord",
                "sessionFile": str(session_file),
            }
        },
    )
    _write_jsonl(
        session_file,
        [
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "do we have access to shadowbroker yet"}],
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "</context>\n<system_instructions>\n[MISSING] Expected at: /tmp/USER.md\nShadowBroker is not installed.",
                        }
                    ],
                },
            },
        ],
    )

    summary = build_openclaw_discord_session_integrity_summary(repo_root=tmp_path, openclaw_root=openclaw_root)
    latest = dict(summary["recent_discord_sessions"][0])

    assert latest["latest_assistant_reply_raw"].startswith("</context>")
    assert latest["latest_user_facing_reply"] == "ShadowBroker is not installed."
    assert latest["latest_assistant_reply_contaminated"] is True
    assert any(fragment == "</context>" for fragment in latest["latest_assistant_reply_findings"])


def test_session_summary_exposes_prompt_budget_and_tool_exposure(tmp_path: Path) -> None:
    openclaw_root = tmp_path / ".openclaw"
    session_id = "sess_budget_1"
    session_key = "agent:jarvis:discord:channel:999"
    session_file = openclaw_root / "agents" / "jarvis" / "sessions" / f"{session_id}.jsonl"
    _write_json(
        openclaw_root / "agents" / "jarvis" / "sessions" / "sessions.json",
        {
            session_key: {
                "sessionId": session_id,
                "providerOverride": "lmstudio",
                "modelOverride": "qwen/qwen3.5-35b-a3b",
                "compactionCount": 3,
                "lastChannel": "discord",
                "sessionFile": str(session_file),
                "systemPromptReport": {
                    "toolExposure": {
                        "mode": "chat-minimal",
                        "reason": "simple_discord_chat",
                    },
                    "promptBudget": {
                        "estimatedTotalTokens": 18123,
                        "safeThresholdTokens": 22000,
                        "hardThresholdTokens": 25000,
                        "overSafeThreshold": False,
                        "overHardThreshold": False,
                        "categories": {
                            "metadataWrappers": {"tokens": 1200},
                            "rawToolOutputs": {"tokens": 3200},
                            "retrievedMemory": {"tokens": 600},
                        },
                        "workingMemory": {
                            "rawUserTurnWindow": 6,
                            "userTurnsInSession": 9,
                        },
                        "preflightCompaction": {
                            "requested": True,
                            "reason": "raw_turn_window",
                            "compacted": True,
                        },
                    },
                },
            }
        },
    )
    _write_jsonl(
        session_file,
        [
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "reply with only: pong"}],
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "pong"}],
                },
            },
        ],
    )

    summary = build_openclaw_discord_session_integrity_summary(repo_root=tmp_path, openclaw_root=openclaw_root)
    latest = dict(summary["recent_discord_sessions"][0])

    assert latest["tool_exposure_mode"] == "chat-minimal"
    assert latest["tool_exposure_reason"] == "simple_discord_chat"
    assert latest["latest_prompt_budget"]["estimated_total_tokens"] == 18123
    assert latest["latest_prompt_budget"]["raw_user_turn_window"] == 6
    assert latest["latest_prompt_budget"]["user_turns_in_session"] == 9
    assert latest["latest_prompt_budget"]["metadata_wrapper_tokens"] == 1200
    assert latest["latest_prompt_budget"]["raw_tool_output_tokens"] == 3200
    assert latest["latest_prompt_budget"]["retrieved_memory_tokens"] == 600
    assert latest["latest_prompt_budget"]["preflight_compaction"]["compacted"] is True
