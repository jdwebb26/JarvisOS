from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from tests.visibility_assertions import assert_notification_visibility


def test_status_export_and_snapshot_surface_notification_summary(tmp_path: Path) -> None:
    status = build_status(tmp_path)
    state_export = build_state_export(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)

    assert_notification_visibility(status)
    assert "dashboard" in status["notification_summary"]["supported_channels"]
    assert "voice" in status["notification_summary"]["supported_channels"]
    assert "mobile_stub" in status["notification_summary"]["supported_channels"]
    assert "discord_stub" in status["notification_summary"]["supported_channels"]

    assert_notification_visibility(state_export)

    assert_notification_visibility(snapshot["status"])


if __name__ == "__main__":
    test_status_export_and_snapshot_surface_notification_summary(Path("tmp_notification_visibility_test"))
