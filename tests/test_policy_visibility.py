from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from tests.visibility_assertions import assert_policy_surface_summary, assert_policy_visibility, assert_voice_route_capability_visibility


def test_status_export_and_snapshot_surface_policy_and_voice_route_summaries(tmp_path: Path) -> None:
    status = build_status(tmp_path)
    state_export = build_state_export(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)

    assert_policy_visibility(status)
    assert_voice_route_capability_visibility(status)
    assert_policy_surface_summary(status)

    assert_policy_visibility(state_export)
    assert_voice_route_capability_visibility(state_export)
    assert_policy_surface_summary(state_export)

    assert_policy_visibility(snapshot["status"])
    assert_voice_route_capability_visibility(snapshot["status"])
    assert_policy_surface_summary(snapshot["status"])

    assert_policy_surface_summary(snapshot)
    assert state_export["policy_surface_summary"] == status["policy_surface_summary"]
    assert snapshot["policy_surface_summary"] == status["policy_surface_summary"]


if __name__ == "__main__":
    test_status_export_and_snapshot_surface_policy_and_voice_route_summaries(Path("tmp_policy_visibility_test"))
