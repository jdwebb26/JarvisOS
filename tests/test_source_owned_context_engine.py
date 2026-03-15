from __future__ import annotations

import tempfile
import sys
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import MemoryEntryRecord, RecordLifecycleState, now_iso
from runtime.gateway.source_owned_context_engine import build_context_packet
from runtime.integrations.openclaw_sessions import build_openclaw_discord_session_integrity_summary
from runtime.memory.governance import save_memory_entry
from runtime.memory.vault_index import load_session_context_summary


def _make_memory_entry(
    *,
    memory_id: str,
    task_id: str,
    structural_type: str,
    memory_class: str,
    memory_type: str,
    title: str,
    summary: str,
    content: str,
) -> MemoryEntryRecord:
    ts = now_iso()
    return MemoryEntryRecord(
        memory_id=memory_id,
        memory_candidate_id=f"cand_{memory_id}",
        task_id=task_id,
        created_at=ts,
        updated_at=ts,
        actor="test",
        lane="discord",
        memory_class=memory_class,
        structural_type=structural_type,
        source_refs={},
        approval_requirement="none",
        confidence_score=0.9,
        confidence_decay_days=30,
        last_retrieved_at=None,
        contradiction_check={},
        superseded_by=None,
        review_state="not_required",
        memory_type=memory_type,
        title=title,
        summary=summary,
        content=content,
        lifecycle_state=RecordLifecycleState.PROMOTED.value,
        execution_backend="memory_spine",
    )


def _discord_turn(index: int, *, tool_blob_chars: int = 0) -> list[dict]:
    rows = [
        {
            "role": "user",
            "content": (
                "Conversation info (untrusted metadata):\n```json\n{\"message_id\":\"m%d\"}\n```\n\n"
                "Sender (untrusted metadata):\n```json\n{\"name\":\"rollan\"}\n```\n\n"
                "Need repo help on item %d? Keep qwen default and preserve fail-closed behavior."
            )
            % (index, index),
        },
        {
            "role": "assistant",
            "content": f"I will inspect the repo and preserve the active model defaults for item {index}.",
        },
    ]
    if tool_blob_chars:
        rows.append(
            {
                "role": "toolResult",
                "toolName": "read",
                "content": "/workspace/state/large.txt\n" + ("X" * tool_blob_chars),
            }
        )
    return rows


def test_long_discord_thread_prompt_budget_stabilizes_and_summary_persists(tmp_path: Path) -> None:
    root = tmp_path
    tools = [
        {"name": "read", "description": "Read file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}},
        {"name": "exec", "description": "Run shell command", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}},
    ]
    save_memory_entry(
        _make_memory_entry(
            memory_id="mem_ep_1",
            task_id="task_ctx",
            structural_type="episodic",
            memory_class="decision_memory",
            memory_type="run_outcome_digest",
            title="Earlier context overflow",
            summary="Previous run overflowed due to repeated tool output blobs.",
            content="Repeated tool output blobs caused prior prompt growth.",
        ),
        root=root,
    )
    save_memory_entry(
        _make_memory_entry(
            memory_id="mem_sem_1",
            task_id="task_ctx",
            structural_type="semantic",
            memory_class="operator_preference_memory",
            memory_type="operator_preference",
            title="Operator preference",
            summary="Keep qwen default and preserve fail-closed routing.",
            content="Keep qwen default and preserve fail-closed routing.",
        ),
        root=root,
    )

    messages: list[dict] = []
    totals: list[int] = []
    packet = {}
    for index in range(1, 13):
        messages.extend(_discord_turn(index, tool_blob_chars=5000))
        packet = build_context_packet(
            root=root,
            session_key="agent:jarvis:discord:channel:test",
            system_prompt="System prompt. " * 200,
            current_prompt=f"reply with only: pong for item {index}",
            messages=messages,
            tools=tools,
            channel="discord",
            context_window_tokens=16000,
            raw_user_turn_window=6,
        )
        totals.append(int(packet["promptBudget"]["estimatedTotalTokens"]))

    assert totals[-1] < totals[5] * 1.35
    assert packet["toolExposure"]["mode"] == "chat-minimal"
    assert packet["promptBudget"]["workingMemory"]["rawUserTurnWindow"] <= 6
    assert packet["promptBudget"]["distillation"]["metadataDistilledCount"] > 0
    assert packet["promptBudget"]["distillation"]["toolResultDistilledCount"] > 0
    assert packet["promptBudget"]["preflightCompaction"]["compacted"] is True
    assert packet["retrievedMemory"]["retrieval"]["episodic_result_count"] >= 1
    assert packet["retrievedMemory"]["retrieval"]["semantic_result_count"] >= 1
    stored_summary = load_session_context_summary("agent:jarvis:discord:channel:test", root=root)
    assert stored_summary["objective"].startswith("Need repo help on item")
    assert any("qwen default" in item.lower() for item in stored_summary["operator_preferences"])


def test_task_turn_keeps_full_tools_and_distills_stale_tool_output(tmp_path: Path) -> None:
    messages = []
    for index in range(1, 9):
        messages.extend(_discord_turn(index, tool_blob_chars=4000))
    packet = build_context_packet(
        root=tmp_path,
        session_key="agent:jarvis:discord:channel:tasky",
        system_prompt="System prompt. " * 150,
        current_prompt="read ./runtime/core/status.py and run pytest to debug the failing shell path",
        messages=messages,
        tools=[
            {"name": "read", "description": "Read file", "parameters": {"type": "object"}},
            {"name": "exec", "description": "Run shell command", "parameters": {"type": "object"}},
        ],
        channel="discord",
        context_window_tokens=12000,
        raw_user_turn_window=6,
    )

    assert packet["toolExposure"]["mode"] == "full"
    assert len(packet["visibleTools"]) == 2
    assert packet["promptBudget"]["distillation"]["toolResultDistilledCount"] > 0


def test_agent_specific_tool_exposure_drops_specialist_tools_for_jarvis(tmp_path: Path) -> None:
    messages = _discord_turn(1, tool_blob_chars=0) + _discord_turn(2, tool_blob_chars=1000)
    packet = build_context_packet(
        root=tmp_path,
        session_key="agent:jarvis:discord:channel:ops",
        system_prompt="System prompt. " * 40,
        current_prompt="read ./runtime/core/status.py and summarize the current operator state",
        messages=messages,
        tools=[
            {"name": "read_file", "description": "Read file", "parameters": {"type": "object"}},
            {"name": "search_web", "description": "Search the web", "parameters": {"type": "object"}},
            {"name": "browser_navigate", "description": "Browser navigation", "parameters": {"type": "object"}},
            {"name": "exec_shell", "description": "Run shell command", "parameters": {"type": "object"}},
        ],
        channel="discord",
        context_window_tokens=12000,
    )

    assert packet["toolExposure"]["mode"] == "agent-scoped-full"
    assert packet["toolExposure"]["agentId"] == "jarvis"
    assert {tool["name"] for tool in packet["visibleTools"]} == {"read_file", "exec_shell"}
    assert packet["toolExposure"]["dropReasons"]["category:research"] == 1
    assert packet["toolExposure"]["dropReasons"]["category:browser"] == 1


def test_hard_threshold_blocks_unsafe_send(tmp_path: Path) -> None:
    messages: list[dict] = []
    for index in range(1, 6):
        messages.extend(_discord_turn(index, tool_blob_chars=12000))
    packet = build_context_packet(
        root=tmp_path,
        session_key="agent:jarvis:discord:channel:blocked",
        system_prompt="System prompt. " * 8000,
        current_prompt="Need a compact answer about the current state.",
        messages=messages,
        tools=[{"name": "read", "description": "Read file", "parameters": {"type": "object"}}],
        channel="discord",
        context_window_tokens=4000,
        raw_user_turn_window=6,
    )

    assert packet["blocked"] is True
    assert packet["blockReason"] == "hard_threshold_exceeded"
    assert packet["promptBudget"]["overHardThreshold"] is True


def test_cli_bridge_returns_source_owned_engine_fields(tmp_path: Path) -> None:
    payload = {
        "root": str(tmp_path),
        "session_key": "agent:jarvis:discord:channel:cli",
        "system_prompt": "System prompt. " * 20,
        "current_prompt": "reply with only: pong",
        "messages": _discord_turn(1, tool_blob_chars=0) + _discord_turn(2, tool_blob_chars=3000),
        "tools": [
            {"name": "read", "description": "Read file", "parameters": {"type": "object"}},
            {"name": "exec", "description": "Run shell command", "parameters": {"type": "object"}},
        ],
        "channel": "discord",
        "context_window_tokens": 12000,
    }
    result = subprocess.run(
        ["python3", str(ROOT / "scripts" / "source_owned_context_engine_cli.py")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    packet = json.loads(result.stdout)
    assert packet["toolExposure"]["mode"] == "chat-minimal"
    assert "promptBudget" in packet["systemPromptReport"]
    assert "rollingSummary" in packet["systemPromptReport"]
    assert "retrieval" in packet["systemPromptReport"]


def test_persisted_session_store_exposes_source_owned_report_fields_end_to_end(tmp_path: Path) -> None:
    packet = build_context_packet(
        root=tmp_path,
        session_key="agent:jarvis:discord:channel:integration",
        system_prompt="System prompt. " * 20,
        current_prompt="reply with only: pong",
        messages=_discord_turn(1, tool_blob_chars=0) + _discord_turn(2, tool_blob_chars=3000),
        tools=[
            {"name": "read", "description": "Read file", "parameters": {"type": "object"}},
            {"name": "exec", "description": "Run shell command", "parameters": {"type": "object"}},
        ],
        channel="discord",
        context_window_tokens=12000,
    )
    openclaw_root = tmp_path / ".openclaw"
    session_id = "sess_integration"
    session_file = openclaw_root / "agents" / "jarvis" / "sessions" / f"{session_id}.jsonl"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(
        "\n".join(
            [
                json.dumps({"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "reply with only: pong"}]}}),
                json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "pong"}]}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (openclaw_root / "agents" / "jarvis" / "sessions" / "sessions.json").write_text(
        json.dumps(
            {
                "agent:jarvis:discord:channel:integration": {
                    "sessionId": session_id,
                    "lastChannel": "discord",
                    "sessionFile": str(session_file),
                    "systemPromptReport": packet["systemPromptReport"],
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = build_openclaw_discord_session_integrity_summary(repo_root=tmp_path, openclaw_root=openclaw_root)
    latest = dict(summary["recent_discord_sessions"][0])

    assert latest["latest_prompt_budget"]["estimated_total_tokens"] > 0
    assert latest["tool_exposure_mode"] == "chat-minimal"
    assert latest["rolling_summary_stats"]["chars"] > 0
    assert latest["retrieval_stats"]["remaining_budget_tokens"] >= 0


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp_one:
        test_long_discord_thread_prompt_budget_stabilizes_and_summary_persists(Path(tmp_one))
    with tempfile.TemporaryDirectory() as tmp_two:
        test_task_turn_keeps_full_tools_and_distills_stale_tool_output(Path(tmp_two))
    with tempfile.TemporaryDirectory() as tmp_three:
        test_agent_specific_tool_exposure_drops_specialist_tools_for_jarvis(Path(tmp_three))
    with tempfile.TemporaryDirectory() as tmp_four:
        test_hard_threshold_blocks_unsafe_send(Path(tmp_four))
    with tempfile.TemporaryDirectory() as tmp_five:
        test_cli_bridge_returns_source_owned_engine_fields(Path(tmp_five))
    with tempfile.TemporaryDirectory() as tmp_six:
        test_persisted_session_store_exposes_source_owned_report_fields_end_to_end(Path(tmp_six))
    print("test_source_owned_context_engine: PASS")
