from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.agent_roster import (
    _allowed_skill_names_for_agent,
    _allowed_tool_names_for_agent,
    build_agent_roster_summary,
    build_delegation_receipt,
    filter_skills_prompt_for_agent,
    filter_tools_for_agent,
)
from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export


def test_agent_roster_summary_exposes_canonical_specialists(tmp_path: Path) -> None:
    summary = build_agent_roster_summary(root=tmp_path)
    rows = {row["agent_id"]: row for row in summary["rows"]}

    assert summary["agent_count"] == 9
    assert rows["jarvis"]["status"] == "wired"
    assert rows["hal"]["routing_intent"]["preferred_model"] == "Qwen3.5-35B"
    assert rows["archimedes"]["routing_intent"]["preferred_model"] == "Qwen3.5-122B"
    assert rows["anton"]["routing_intent"]["preferred_model"] == "Qwen3.5-122B"
    assert rows["hermes"]["status"] == "implemented_but_blocked_by_external_runtime"
    assert rows["bowser"]["status"] == "scaffold_only"
    assert rows["ralph"]["status"] == "implemented_but_blocked_by_external_runtime"
    assert summary["review_lane_summary"]["primary_review_channel"] == "review"
    assert summary["review_lane_summary"]["technical_review_channel"] == "code_review"
    assert summary["review_hierarchy"]["implementation_agent"] == "hal"
    assert "hal" in rows["jarvis"]["delegation_targets"]
    assert rows["jarvis"]["skill_policy"]["allowed_skill_names"] == [
        "discord",
        "session-logs",
        "voice-call",
        "sherpa-onnx-tts",
        "model-usage",
    ]
    assert rows["jarvis"]["skill_policy"]["allow_general_by_default"] is False


def test_agent_roster_tool_scoping_keeps_jarvis_leaner_than_specialists() -> None:
    tools = [
        {"name": "read"},
        {"name": "edit"},
        {"name": "write"},
        {"name": "exec"},
        {"name": "process"},
        {"name": "cron"},
        {"name": "message"},
        {"name": "gateway"},
        {"name": "browser"},
        {"name": "web_search"},
        {"name": "web_fetch"},
        {"name": "image"},
        {"name": "subagents"},
        {"name": "sessions_list"},
        {"name": "sessions_history"},
        {"name": "sessions_send"},
        {"name": "sessions_yield"},
        {"name": "sessions_spawn"},
        {"name": "session_status"},
    ]

    jarvis = filter_tools_for_agent("jarvis", tools)
    hal = filter_tools_for_agent("hal", tools)
    archimedes = filter_tools_for_agent("archimedes", tools)
    scout = filter_tools_for_agent("scout", tools)
    bowser = filter_tools_for_agent("bowser", tools)

    assert {tool["name"] for tool in jarvis["tools"]} == {
        "read",
        "message",
        "gateway",
        "sessions_list",
        "sessions_history",
        "sessions_send",
        "sessions_yield",
        "sessions_spawn",
        "session_status",
    }
    assert {tool["name"] for tool in hal["tools"]} == {
        "read",
        "edit",
        "write",
        "exec",
        "process",
        "cron",
        "message",
        "gateway",
        "subagents",
        "sessions_list",
        "sessions_history",
        "sessions_send",
        "sessions_yield",
        "sessions_spawn",
        "session_status",
    }
    assert {tool["name"] for tool in archimedes["tools"]} == {
        "read",
        "sessions_list",
        "sessions_history",
        "session_status",
    }
    assert {tool["name"] for tool in scout["tools"]} == {
        "read",
        "web_search",
        "web_fetch",
        "image",
        "process",
        "sessions_list",
        "sessions_history",
        "sessions_send",
        "sessions_yield",
        "sessions_spawn",
        "session_status",
    }
    assert {tool["name"] for tool in bowser["tools"]} == {
        "browser",
        "process",
        "sessions_list",
        "sessions_history",
        "sessions_send",
        "sessions_yield",
        "sessions_spawn",
        "session_status",
    }


def test_generic_skill_blocks_are_not_implicitly_loaded_for_jarvis() -> None:
    skills_prompt = (
        "<available_skills>\n"
        "<skill><name>coding-agent</name><description>Delegate coding tasks.</description></skill>\n"
        "<skill><name>weather</name><description>Get weather updates.</description></skill>\n"
        "<skill><name>healthcheck</name><description>Run health checks.</description></skill>\n"
        "</available_skills>"
    )

    jarvis = filter_skills_prompt_for_agent("jarvis", skills_prompt)
    hal = filter_skills_prompt_for_agent("hal", skills_prompt)

    assert jarvis["loadedSkillNames"] == []
    assert jarvis["afterCount"] == 0
    assert hal["loadedSkillNames"] == ["coding-agent"]


def test_unknown_agent_is_fail_closed_in_filter_functions() -> None:
    # Regression: _allowed_*_for_agent previously called infer_agent_id() which
    # falls back to "jarvis" for unknowns, silently giving unknown agents jarvis's
    # allowlist. filter_tools/skills also fell back to jarvis's profile.
    tools = [
        {"name": "read"},
        {"name": "exec"},
        {"name": "message"},
        {"name": "browser"},
    ]
    skills_prompt = (
        "<available_skills>\n"
        "<skill><name>discord</name><description>Post to Discord.</description></skill>\n"
        "<skill><name>coding-agent</name><description>Delegate coding.</description></skill>\n"
        "</available_skills>"
    )

    # Internal helpers must return empty for unknowns
    assert _allowed_tool_names_for_agent("totally_unknown_bot") == []
    assert _allowed_skill_names_for_agent("totally_unknown_bot") == []

    # Public filter functions must return empty/fail-closed for unknowns
    tool_result = filter_tools_for_agent("totally_unknown_bot", tools)
    assert tool_result["tools"] == [], "unknown agent must get zero tools"
    assert tool_result["afterCount"] == 0
    assert "unknown_agent" in tool_result["dropReasons"]

    skill_result = filter_skills_prompt_for_agent("totally_unknown_bot", skills_prompt)
    assert skill_result["loadedSkillNames"] == [], "unknown agent must get zero skills"
    assert skill_result["afterCount"] == 0
    assert "unknown_agent" in skill_result["dropReasons"]

    # Sanity: jarvis must still work normally
    jarvis_tools = filter_tools_for_agent("jarvis", tools)
    assert {t["name"] for t in jarvis_tools["tools"]} == {"read", "message"}


def test_build_delegation_receipt_verified_and_unverified() -> None:
    # Verified: session_key matches agent:<to_agent>:*
    receipt = build_delegation_receipt(
        from_agent="jarvis",
        to_agent="scout",
        method="message_tool",
        session_key="agent:scout:discord:channel:1471376970259628032",
        session_id="a0cfbbd1",
        model_id="lmstudio/qwen3.5-35b-a3b",
        provider_id="lmstudio",
        visible_tools=["read", "web_search", "web_fetch"],
        evidence_summary="Scout Discord session confirmed",
    )
    assert receipt["verified"] is True
    assert receipt["fromAgent"] == "jarvis"
    assert receipt["toAgent"] == "scout"
    assert receipt["method"] == "message_tool"
    assert "web_search" in receipt["visibleTools"]

    # Unverified: generic jarvis subagent session_key
    fake = build_delegation_receipt(
        from_agent="jarvis",
        to_agent="anton",
        method="sessions_spawn_agentId",
        session_key="agent:jarvis:subagent:de58e956-6909-4a73-9f86-e3bfcc6aecde",
        model_id="lmstudio/qwen/qwen3.5-9b",
    )
    assert fake["verified"] is False
    assert "does not match" in fake["verifiedReason"]

    # Unverified: no session_key at all
    empty = build_delegation_receipt(from_agent="jarvis", to_agent="hal", method="message_tool")
    assert empty["verified"] is False
    assert "no session_key provided" in empty["verifiedReason"]

    # DELEGATION_WIRING has delegation_method field on all entries
    from runtime.core.agent_roster import DELEGATION_WIRING
    for entry in DELEGATION_WIRING:
        assert "delegation_method" in entry, f"DELEGATION_WIRING entry missing delegation_method: {entry}"


def test_status_snapshot_and_export_surface_agent_roster_summary(tmp_path: Path) -> None:
    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export = build_state_export(tmp_path)

    assert status["agent_roster_summary"]["agent_count"] == 9
    assert snapshot["agent_roster_summary"]["review_hierarchy"]["technical_reviewer"] == "archimedes"
    assert export["agent_roster_summary"]["review_hierarchy"]["supreme_reviewer"] == "anton"


if __name__ == "__main__":
    test_agent_roster_summary_exposes_canonical_specialists(Path("tmp_agent_roster_one"))
    test_agent_roster_tool_scoping_keeps_jarvis_leaner_than_specialists()
    test_generic_skill_blocks_are_not_implicitly_loaded_for_jarvis()
    test_unknown_agent_is_fail_closed_in_filter_functions()
    test_build_delegation_receipt_verified_and_unverified()
    test_status_snapshot_and_export_surface_agent_roster_summary(Path("tmp_agent_roster_two"))
    print("test_agent_roster: PASS")
