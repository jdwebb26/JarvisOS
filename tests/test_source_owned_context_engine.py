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
from runtime.gateway.source_owned_context_engine import _build_prompt_budget, _extract_text, build_context_packet
from runtime.integrations.openclaw_sessions import build_openclaw_discord_session_integrity_summary
from runtime.memory.governance import save_memory_entry
from runtime.memory.vault_index import load_session_context_summary


def _skills_prompt() -> str:
    # Uses real installed skill names from skill_inventory.json so they survive
    # _normalize_skill_names() filtering.  Each name must appear in the inventory.
    # discord / voice-call → jarvis allowlist only
    # coding-agent         → hal allowlist only
    # session-logs         → jarvis + hal + bowser allowlists (and others)
    # blogwatcher          → hermes/scout allowlists — dropped by jarvis/hal/bowser
    # sag                  → muse allowlist only — dropped by jarvis/hal/bowser
    return (
        "<available_skills>\n"
        "<skill><name>discord</name><description>Manage Discord integration and inbound message routing.</description></skill>\n"
        "<skill><name>voice-call</name><description>Handle voice calls and TTS output.</description></skill>\n"
        "<skill><name>coding-agent</name><description>Delegate coding and implementation tasks to a specialist agent.</description></skill>\n"
        "<skill><name>session-logs</name><description>View session history and conversation logs.</description></skill>\n"
        "<skill><name>blogwatcher</name><description>Monitor blogs, feeds, and news sources.</description></skill>\n"
        "<skill><name>sag</name><description>Run SAG creative generation workflows.</description></skill>\n"
        "</available_skills>"
    )


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

    assert packet["toolExposure"]["mode"] == "agent-scoped-full"
    assert len(packet["visibleTools"]) == 1
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
            {"name": "read", "description": "Read file", "parameters": {"type": "object"}},
            {"name": "web_search", "description": "Search the web", "parameters": {"type": "object"}},
            {"name": "browser", "description": "Browser automation", "parameters": {"type": "object"}},
            {"name": "exec", "description": "Run shell command", "parameters": {"type": "object"}},
        ],
        channel="discord",
        context_window_tokens=12000,
    )

    assert packet["toolExposure"]["mode"] == "agent-scoped-full"
    assert packet["toolExposure"]["agentId"] == "jarvis"
    assert {tool["name"] for tool in packet["visibleTools"]} == {"read"}
    assert packet["toolExposure"]["dropReasons"]["not_in_allowlist"] == 3


def test_agent_specific_skill_loading_filters_before_prompt_assembly(tmp_path: Path) -> None:
    # Tool names must exactly match AGENT_TOOL_ALLOWLIST entries (name-based allowlist, not category).
    # read + exec: in hal's allowlist, NOT in bowser's
    # browser: in bowser's allowlist, NOT in hal's
    # jarvis uses discord channel → chat-minimal → no tools exposed regardless
    tools = [
        {"name": "read", "description": "Read file", "parameters": {"type": "object"}},
        {"name": "exec", "description": "Run shell command", "parameters": {"type": "object"}},
        {"name": "browser", "description": "Browser automation", "parameters": {"type": "object"}},
    ]
    jarvis_packet = build_context_packet(
        root=tmp_path,
        session_key="agent:jarvis:discord:channel:skills",
        system_prompt="System prompt. " * 20,
        current_prompt="summarize the current session state",
        messages=_discord_turn(1, tool_blob_chars=0),
        tools=tools,
        skills_prompt=_skills_prompt(),
        agent_id="jarvis",
        channel="discord",
        provider_id="qwen",
        model_id="Qwen3.5-9B",
        context_window_tokens=12000,
    )
    hal_packet = build_context_packet(
        root=tmp_path,
        session_key="agent:hal:tasks",
        system_prompt="System prompt. " * 20,
        current_prompt="patch the failing file and run tests",
        messages=_discord_turn(1, tool_blob_chars=0),
        tools=tools,
        skills_prompt=_skills_prompt(),
        agent_id="hal",
        channel="tasks",
        provider_id="qwen",
        model_id="Qwen3.5-35B",
        context_window_tokens=12000,
    )
    bowser_packet = build_context_packet(
        root=tmp_path,
        session_key="agent:bowser:tasks",
        system_prompt="System prompt. " * 20,
        current_prompt="open the target site and complete the browser workflow",
        messages=_discord_turn(1, tool_blob_chars=0),
        tools=tools,
        skills_prompt=_skills_prompt(),
        agent_id="bowser",
        channel="tasks",
        provider_id="qwen",
        model_id="Qwen3.5-35B",
        context_window_tokens=12000,
    )

    # jarvis (discord, simple prompt): discord + voice-call + session-logs pass its allowlist
    #   (in prompt order); coding-agent/blogwatcher/sag are not in jarvis's allowlist;
    #   chat-minimal mode → no tools exposed regardless
    assert jarvis_packet["loadedSkills"]["loadedSkillNames"] == ["discord", "voice-call", "session-logs"]
    assert jarvis_packet["loadedSkills"]["loadedSkillCount"] == 3
    assert "coding-agent" not in jarvis_packet["filteredSkillsPrompt"]
    assert jarvis_packet["systemPromptReport"]["agentRuntimeLoadout"]["modelId"] == "Qwen3.5-9B"
    assert jarvis_packet["systemPromptReport"]["loadedTools"]["visibleToolNames"] == []
    # hal (tasks channel): coding-agent + session-logs pass hal's allowlist; read+exec pass tools allowlist
    assert hal_packet["loadedSkills"]["loadedSkillNames"] == ["coding-agent", "session-logs"]
    assert hal_packet["systemPromptReport"]["loadedTools"]["visibleToolNames"] == ["read", "exec"]
    assert hal_packet["systemPromptReport"]["agentRuntimeLoadout"]["providerId"] == "qwen"
    # bowser (tasks channel): only session-logs passes bowser's skill allowlist; only browser passes tool allowlist
    assert bowser_packet["loadedSkills"]["loadedSkillNames"] == ["session-logs"]
    assert bowser_packet["systemPromptReport"]["loadedTools"]["visibleToolNames"] == ["browser"]


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
        "skills_prompt": _skills_prompt(),
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
    assert "loadedSkills" in packet["systemPromptReport"]
    assert "loadedTools" in packet["systemPromptReport"]
    assert "agentRuntimeLoadout" in packet["systemPromptReport"]


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


def test_prompt_budget_large_tool_output_not_underestimated() -> None:
    # Regression: _build_prompt_budget previously called estimate_tokens(integer) which
    # stringified the number before measuring length — e.g. estimate_tokens(215728) = 2 tokens.
    # Fix: direct integer division (chars + 3) // 4.
    # A 200K-char tool result must register as ~50K tokens, not ~2 tokens.
    BIG = 200_000  # chars
    messages = [
        {"role": "user", "content": "what is the current state?"},
        {"role": "toolResult", "toolName": "read", "content": "X" * BIG},
    ]
    budget = _build_prompt_budget(
        system_prompt="System. " * 50,
        recent_messages=messages,
        current_prompt="summarize",
        tools=[],
        retrieved_episodic=[],
        retrieved_semantic=[],
        rolling_summary={},
        context_window_tokens=200_000,
        raw_user_turn_window=6,
        total_user_turns=1,
        distillation={},
        tool_exposure={"mode": "none", "reason": "no_tools", "beforeCount": 0, "afterCount": 0, "agentId": "jarvis", "tools": []},
    )
    raw_tool_tokens = budget["categories"]["rawToolOutputs"]["tokens"]
    # Must be in the right order of magnitude: 200000/4 = 50000. Old bug returned ~2.
    assert raw_tool_tokens > 40_000, f"expected ~50000, got {raw_tool_tokens} — integer underestimation bug is back"
    # With a 32K token context window, safe threshold = 0.72 * 32000 = 23040 tokens.
    # 200K-char tool output alone is ~50K tokens, so it must trip the threshold.
    tight_budget = _build_prompt_budget(
        system_prompt="System.",
        recent_messages=messages,
        current_prompt="summarize",
        tools=[],
        retrieved_episodic=[],
        retrieved_semantic=[],
        rolling_summary={},
        context_window_tokens=32_000,
        raw_user_turn_window=6,
        total_user_turns=1,
        distillation={},
        tool_exposure={"mode": "none", "reason": "no_tools", "beforeCount": 0, "afterCount": 0, "agentId": "jarvis", "tools": []},
    )
    assert tight_budget["overSafeThreshold"] is True, "200K-char tool output must trip safe threshold at 32K context window"


def test_emergency_tool_distill_fires_when_compacted_window_still_oversized(tmp_path: Path) -> None:
    # When the compacted 3-turn window is still over safe threshold, the emergency pass must
    # distill all remaining tool results and set compaction.reason = "emergency_tool_distill".
    BIG = 120_000  # chars per tool result; 3 turns × 4 results = 480K chars raw
    messages = []
    for i in range(1, 11):
        messages.extend(_discord_turn(i, tool_blob_chars=BIG))
    packet = build_context_packet(
        root=tmp_path,
        session_key="agent:jarvis:discord:channel:emergency",
        system_prompt="System prompt. " * 200,
        current_prompt="what is the current state? read ./runtime/core/status.py",
        messages=messages,
        tools=[{"name": "read", "description": "Read file", "parameters": {"type": "object"}}],
        channel="discord",
        context_window_tokens=200_000,
        raw_user_turn_window=6,
    )
    compaction = packet["promptBudget"]["preflightCompaction"]
    assert compaction["compacted"] is True
    assert compaction["reason"] == "emergency_tool_distill", (
        f"expected emergency_tool_distill, got {compaction['reason']!r} — "
        f"emergency pass did not fire; budget={packet['promptBudget']['estimatedTotalTokens']}"
    )
    assert packet["blocked"] is False, "emergency distill should keep packet below hard threshold"
    # Verify working memory tool results are distilled stubs, not raw blobs
    tool_results_in_window = [
        m for m in packet["workingMemoryMessages"] if str(m.get("role") or "") == "toolResult"
    ]
    assert tool_results_in_window, "expected tool results in working memory"
    for msg in tool_results_in_window:
        content = str(msg.get("content") or "")
        assert content.startswith("[tool result distilled"), (
            f"tool result not distilled in emergency window: {content[:80]!r}"
        )


def test_extract_text_adjacent_duplicate_collapse() -> None:
    # Regression: adjacent identical text items must be collapsed; non-adjacent repeats preserved.
    reply = "pong\nWant to try spawning them as subagents instead?"

    # Adjacent identical dicts — the duplication scenario from streaming assembly
    assert _extract_text([{"type": "text", "text": reply}, {"type": "text", "text": reply}]) == reply
    # Adjacent identical raw strings
    assert _extract_text([reply, reply]) == reply
    # Adjacent str then identical dict
    assert _extract_text([reply, {"type": "text", "text": reply}]) == reply
    # Non-adjacent A B A must be preserved
    assert _extract_text([{"type": "text", "text": "A"}, {"type": "text", "text": "B"}, {"type": "text", "text": "A"}]) == "A\nB\nA"
    # Two distinct items unchanged
    assert _extract_text([{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]) == "first\nsecond"
    # Plain string passthrough
    assert _extract_text(reply) == reply


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp_one:
        test_long_discord_thread_prompt_budget_stabilizes_and_summary_persists(Path(tmp_one))
    with tempfile.TemporaryDirectory() as tmp_two:
        test_task_turn_keeps_full_tools_and_distills_stale_tool_output(Path(tmp_two))
    with tempfile.TemporaryDirectory() as tmp_three:
        test_agent_specific_tool_exposure_drops_specialist_tools_for_jarvis(Path(tmp_three))
    with tempfile.TemporaryDirectory() as tmp_four:
        test_agent_specific_skill_loading_filters_before_prompt_assembly(Path(tmp_four))
    with tempfile.TemporaryDirectory() as tmp_five:
        test_hard_threshold_blocks_unsafe_send(Path(tmp_five))
    with tempfile.TemporaryDirectory() as tmp_six:
        test_cli_bridge_returns_source_owned_engine_fields(Path(tmp_six))
    with tempfile.TemporaryDirectory() as tmp_seven:
        test_persisted_session_store_exposes_source_owned_report_fields_end_to_end(Path(tmp_seven))
    test_extract_text_adjacent_duplicate_collapse()
    test_prompt_budget_large_tool_output_not_underestimated()
    with tempfile.TemporaryDirectory() as tmp_eight:
        test_emergency_tool_distill_fires_when_compacted_window_still_oversized(Path(tmp_eight))
    print("test_source_owned_context_engine: PASS")
