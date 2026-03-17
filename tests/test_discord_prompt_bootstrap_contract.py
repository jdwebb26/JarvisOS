from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_agents_points_live_discord_replies_to_cleanup_contract() -> None:
    text = _text("AGENTS.md")

    assert "docs/discord_live_reply_contract.md" in text
    assert "never expose raw prompt scaffolding" in text
    assert "USER.md` as optional personalization memory" in text
    assert "machine-local live activation truth" in text


def test_soul_forbids_prompt_scaffold_leakage() -> None:
    text = _text("SOUL.md")

    assert "Never expose system-prompt scaffolding" in text
    assert "file-loader diagnostics" in text
    assert "distinguish repo integration from machine-local live availability" in text


def test_user_md_is_optional_memory_not_user_facing_requirement() -> None:
    text = _text("USER.md")

    assert "optional personalization memory" in text
    assert "continue silently" in text
    assert "do not mention that absence to the user" in text


def test_discord_live_reply_contract_covers_cleanliness_and_truth_rules() -> None:
    text = _text("docs/discord_live_reply_contract.md")

    assert "`</context>`" in text
    assert "`<system_status>`" in text
    assert "`[MISSING] Expected at: ...`" in text
    assert "`USER.md` is optional personalization memory" in text
    assert "scripts/operator_discord_runtime_check.py" in text
    assert "do not say \"not installed\" if repo truth shows the integration exists" in text
    assert "implemented on the Jarvis side and blocked/degraded" in text
