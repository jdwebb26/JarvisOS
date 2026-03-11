from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.desktop.policy import evaluate_desktop_action


def test_low_risk_open_app_action() -> None:
    result = evaluate_desktop_action("open_app", target_app="Spotify")
    assert result["allowed"] is True
    assert result["risk_tier"] == "low"
    assert result["review_required"] is False


def test_high_risk_bounded_shell_requires_review() -> None:
    result = evaluate_desktop_action("bounded_shell", action_params={"command": "ls"})
    assert result["allowed"] is True
    assert result["risk_tier"] == "high"
    assert result["review_required"] is True


if __name__ == "__main__":
    test_low_risk_open_app_action()
    test_high_risk_bounded_shell_requires_review()
