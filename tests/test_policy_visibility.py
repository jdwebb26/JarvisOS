from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export


def test_status_export_and_snapshot_surface_policy_and_voice_route_summaries(tmp_path: Path) -> None:
    status = build_status(tmp_path)
    state_export = build_state_export(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)

    assert status["security_validation_summary"]["validation_layer_present"] is True
    assert status["prompt_caching_policy_summary"]["prompt_caching_policy_present"] is True
    assert status["mcp_policy_summary"]["mcp_policy_present"] is True
    assert status["plugin_policy_summary"]["plugin_policy_present"] is True
    assert status["a2a_policy_summary"]["a2a_policy_present"] is True

    assert status["voice_route_capability_summary"]["voice_route_capability_present"] is True
    assert status["voice_route_capability_summary"]["preview_only_default"] is True
    assert status["voice_route_capability_summary"]["explicit_route_execute"] is True
    assert "browser" in status["voice_route_capability_summary"]["supported_subsystems"]
    assert "spotify" in status["voice_route_capability_summary"]["supported_subsystems"]
    assert "desktop" in status["voice_route_capability_summary"]["supported_subsystems"]
    assert "discord" in status["voice_route_capability_summary"]["supported_subsystems"]
    assert "tradingview" in status["voice_route_capability_summary"]["supported_subsystems"]

    assert state_export["security_validation_summary"]["validation_layer_present"] is True
    assert state_export["prompt_caching_policy_summary"]["prompt_caching_policy_present"] is True
    assert state_export["mcp_policy_summary"]["mcp_policy_present"] is True
    assert state_export["plugin_policy_summary"]["plugin_policy_present"] is True
    assert state_export["a2a_policy_summary"]["a2a_policy_present"] is True
    assert state_export["voice_route_capability_summary"]["preview_only_default"] is True
    assert state_export["voice_route_capability_summary"]["explicit_route_execute"] is True

    assert snapshot["security_validation_summary"]["validation_layer_present"] is True
    assert snapshot["prompt_caching_policy_summary"]["prompt_caching_policy_present"] is True
    assert snapshot["mcp_policy_summary"]["mcp_policy_present"] is True
    assert snapshot["plugin_policy_summary"]["plugin_policy_present"] is True
    assert snapshot["a2a_policy_summary"]["a2a_policy_present"] is True
    assert snapshot["voice_route_capability_summary"]["voice_route_capability_present"] is True
    assert snapshot["voice_route_capability_summary"]["preview_only_default"] is True


if __name__ == "__main__":
    test_status_export_and_snapshot_surface_policy_and_voice_route_summaries(Path("tmp_policy_visibility_test"))
