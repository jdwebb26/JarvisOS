from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.agent_roster import build_agent_roster_summary, filter_tools_for_agent
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


def test_agent_roster_tool_scoping_keeps_jarvis_leaner_than_specialists() -> None:
    tools = [
        {"name": "read_file", "description": "Read repository files"},
        {"name": "search_web", "description": "Search the web"},
        {"name": "browser_navigate", "description": "Navigate a browser tab"},
        {"name": "queue_cleanup", "description": "Drain queue backlog"},
        {"name": "exec_shell", "description": "Run shell commands"},
    ]

    jarvis = filter_tools_for_agent("jarvis", tools)
    hal = filter_tools_for_agent("hal", tools)
    scout = filter_tools_for_agent("scout", tools)
    bowser = filter_tools_for_agent("bowser", tools)

    assert {tool["name"] for tool in jarvis["tools"]} == {"read_file", "exec_shell"}
    assert {tool["name"] for tool in hal["tools"]} == {"read_file", "exec_shell"}
    assert {tool["name"] for tool in scout["tools"]} == {"search_web"}
    assert {tool["name"] for tool in bowser["tools"]} == {"browser_navigate"}


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
    test_status_snapshot_and_export_surface_agent_roster_summary(Path("tmp_agent_roster_two"))
    print("test_agent_roster: PASS")
