from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.prompt_caching_policy import (
    build_prompt_caching_policy_summary,
    classify_prompt_cacheability,
    split_prompt_for_cacheability,
)


def test_high_cacheability_split() -> None:
    result = classify_prompt_cacheability(
        system_prompt="System rules. " * 30,
        developer_prompt="Stable developer guidance. " * 20,
        task_context="Reusable task scaffold. " * 10,
        volatile_suffix="Operator says rerun this one failing check.",
    )
    assert result["cacheability"] == "high"
    assert result["stable_prefix_char_count"] > result["volatile_suffix_char_count"]


def test_low_cacheability_for_mostly_volatile_text() -> None:
    result = classify_prompt_cacheability(
        volatile_suffix="current task status rerun now latest output at 2026-03-11T10:00:00 code: pineapple",
    )
    assert result["cacheability"] == "low"
    assert result["reason"] == "no_stable_prefix_material"


def test_medium_cacheability_case() -> None:
    result = classify_prompt_cacheability(
        system_prompt="Stable system prompt." * 4,
        developer_prompt="Stable developer prompt." * 3,
        task_context="Short scaffold.",
        volatile_suffix="Latest status snippet for this run.",
    )
    assert result["cacheability"] == "medium"


def test_timestamp_in_stable_prefix_gets_flagged() -> None:
    result = classify_prompt_cacheability(
        system_prompt="Stable instructions generated at 2026-03-11 for this run.",
        developer_prompt="Normal developer prompt.",
    )
    assert "timestamp_in_stable_prefix" in result["findings"]
    assert result["cacheability"] == "low"


def test_approval_code_in_stable_prefix_gets_flagged() -> None:
    result = classify_prompt_cacheability(
        system_prompt="Use approval code: pineapple before continuing.",
        developer_prompt="Normal developer prompt.",
    )
    assert "approval_code_in_stable_prefix" in result["findings"]
    assert result["cacheability"] == "low"


def test_summary_builds_cleanly() -> None:
    result = build_prompt_caching_policy_summary(root=ROOT)
    assert result["prompt_caching_policy_present"] is True
    assert "stable_prefix_split" in result["supported_checks"]


def test_split_prompt_reports_counts() -> None:
    result = split_prompt_for_cacheability(
        system_prompt="sys",
        developer_prompt="dev",
        task_context="ctx",
        volatile_suffix="volatile",
    )
    assert result["stable_prefix"] == "sys\n\ndev\n\nctx"
    assert result["volatile_suffix"] == "volatile"


if __name__ == "__main__":
    test_high_cacheability_split()
    test_low_cacheability_for_mostly_volatile_text()
    test_medium_cacheability_case()
    test_timestamp_in_stable_prefix_gets_flagged()
    test_approval_code_in_stable_prefix_gets_flagged()
    test_summary_builds_cleanly()
    test_split_prompt_reports_counts()
