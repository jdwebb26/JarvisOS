from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from tests.visibility_assertions import assert_voice_route_safety_visibility


def test_status_export_and_snapshot_surface_route_safety_summary(tmp_path: Path) -> None:
    status = build_status(tmp_path)
    state_export = build_state_export(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)

    assert_voice_route_safety_visibility(status)
    assert "tradingview_trade_execution" in status["voice_route_safety_summary"]["known_flagged_route_classes"]
    assert "discord_message_like_routes" in status["voice_route_safety_summary"]["known_flagged_route_classes"]

    assert_voice_route_safety_visibility(state_export)

    assert_voice_route_safety_visibility(snapshot["status"])


if __name__ == "__main__":
    test_status_export_and_snapshot_surface_route_safety_summary(Path("tmp_route_safety_visibility_test"))
