from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.browser.policy import evaluate_browser_action
from runtime.core.browser_control_allowlist import save_browser_control_allowlist
from runtime.core.models import BrowserControlAllowlistRecord, new_id, now_iso


def _seed_allowlist(root: Path) -> BrowserControlAllowlistRecord:
    return save_browser_control_allowlist(
        BrowserControlAllowlistRecord(
            browser_control_allowlist_id=new_id("browserallow"),
            created_at=now_iso(),
            updated_at=now_iso(),
            actor="tester",
            lane="tests",
            allowed_apps=[],
            allowed_sites=["example.com"],
            allowed_paths=[],
            blocked_apps=[],
            blocked_sites=["blocked.example.com"],
            blocked_paths=[],
            destructive_actions_require_confirmation=True,
            secret_entry_requires_manual_control=True,
        ),
        root=root,
    )


def test_allowlisted_low_risk_navigation_action() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        allowlist = _seed_allowlist(root)
        result = evaluate_browser_action("navigate_allowlisted_page", "https://example.com/docs", root=root)
        assert result["allowed"] is True
        assert result["risk_tier"] == "low"
        assert result["review_required"] is False
        assert result["allowlist_ref"] == allowlist.browser_control_allowlist_id


def test_blocked_non_allowlisted_target_url() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        result = evaluate_browser_action("inspect_page", "https://not-allowed.example.org", root=root)
        assert result["allowed"] is False
        assert result["reason"] == "target_url_not_allowlisted"


def test_high_risk_action_requiring_review() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        result = evaluate_browser_action("send_external_message", "https://example.com/compose", root=root)
        assert result["allowed"] is True
        assert result["risk_tier"] == "high"
        assert result["review_required"] is True


if __name__ == "__main__":
    test_allowlisted_low_risk_navigation_action()
    test_blocked_non_allowlisted_target_url()
    test_high_risk_action_requiring_review()
