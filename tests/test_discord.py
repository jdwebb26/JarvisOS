from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_channels_example_exists_and_mentions_required_lanes():
    path = ROOT / "config" / "channels.example.yaml"
    assert path.exists(), "channels.example.yaml should exist"
    text = path.read_text(encoding="utf-8")

    required_names = [
        "jarvis",
        "tasks",
        "outputs",
        "review",
        "audit",
        "code_review",
        "flowstate",
    ]
    for name in required_names:
        assert f"{name}:" in text, f"Missing channel section for {name}"


def test_chat_first_policy_is_reflected_in_docs():
    path = ROOT / "docs" / "channels.md"
    assert path.exists(), "docs/channels.md should exist"
    text = path.read_text(encoding="utf-8")

    assert "conversation, not execution" in text
    assert "must not silently convert ordinary chat into queued work" in text


def test_review_lane_mentions_short_phone_style_approvals():
    path = ROOT / "docs" / "review-policy.md"
    assert path.exists(), "docs/review-policy.md should exist"
    text = path.read_text(encoding="utf-8")

    assert "yes" in text
    assert "no" in text
    assert "1" in text
    assert "A" in text
