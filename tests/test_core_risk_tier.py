from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.risk_tier import (
    evaluate_risk_tier,
    load_risk_tier_policy,
    requires_operator_confirmation,
)


def test_policy_loads_from_repo_config():
    policy = load_risk_tier_policy(root=ROOT)
    assert policy["high_risk_requires_text_confirmation"] is True
    assert policy["medium_risk_voice_allowed"] is True
    assert policy["low_risk_auto_execute"] is False


def test_evaluate_risk_tier_uses_requested_baseline():
    assert evaluate_risk_tier("show_status", "reporter", {}) == {
        "tier": "low",
        "required_confirmation_level": "none",
        "reason": "low_risk_action:show_status",
    }
    assert evaluate_risk_tier("create_draft_artifact", "artifact_spine", {}) == {
        "tier": "medium",
        "required_confirmation_level": "voice_ok",
        "reason": "medium_risk_action:create_draft_artifact",
    }
    assert evaluate_risk_tier("push_code", "coder", {}) == {
        "tier": "high",
        "required_confirmation_level": "text_required",
        "reason": "high_risk_action:push_code",
    }


def test_confirmation_rules_follow_policy():
    policy = {
        "high_risk_requires_text_confirmation": True,
        "medium_risk_voice_allowed": True,
        "low_risk_auto_execute": False,
    }

    assert requires_operator_confirmation("high", "voice", policy=policy) is True
    assert requires_operator_confirmation("high", "text", policy=policy) is False

    assert requires_operator_confirmation("medium", "voice", policy=policy) is False
    assert requires_operator_confirmation("medium", "system", policy=policy) is True

    assert requires_operator_confirmation("low", "system", policy=policy) is True
    assert requires_operator_confirmation("low", "text", policy=policy) is False


if __name__ == "__main__":
    test_policy_loads_from_repo_config()
    test_evaluate_risk_tier_uses_requested_baseline()
    test_confirmation_rules_follow_policy()
