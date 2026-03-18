"""Tests for regression scorers and budget tracking in Ralph."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.evals.scorers import (
    run_all_scorers,
    score_model_match,
    score_output_completeness,
    score_routing_correctness,
    score_token_efficiency,
)


def _hal_trace(*, content_length=800, ok=True, model="qwen3.5-35b-a3b",
               prompt_tokens=200, completion_tokens=600, elapsed=25.0):
    return {
        "trace_kind": "ralph_hal_proxy",
        "execution_backend": "ralph_hal_proxy",
        "lane": "ralph_loop",
        "request_payload": {
            "normalized_request": "Write a function...",
            "task_type": "code",
            "model": model,
        },
        "response_payload": {
            "ok": ok,
            "content_length": content_length,
            "elapsed": elapsed,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }


def _archimedes_trace(*, approved=True, content_length=200, model="qwen3.5-35b-a3b"):
    return {
        "trace_kind": "ralph_archimedes_proxy",
        "execution_backend": "ralph_archimedes_proxy",
        "lane": "ralph_loop",
        "request_payload": {"task_type": "code", "model": model},
        "response_payload": {
            "approved": approved,
            "content_length": content_length,
            "elapsed": 8.0,
            "model": model,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        },
    }


# ── Output completeness ──

def test_complete_output_passes():
    result = score_output_completeness(_hal_trace(content_length=800, ok=True))
    assert result["passed"]
    assert result["score"] == 1.0


def test_empty_output_fails():
    result = score_output_completeness(_hal_trace(content_length=0, ok=False))
    assert not result["passed"]


def test_truncated_output_fails():
    result = score_output_completeness(_hal_trace(content_length=1500))
    assert not result["passed"]
    assert "truncated" in result["notes"][0].lower()


def test_archimedes_output_passes():
    result = score_output_completeness(_archimedes_trace(approved=True))
    assert result["passed"]


# ── Model match ──

def test_model_match_passes():
    result = score_model_match(_hal_trace(), expected_model="qwen3.5-35b-a3b")
    assert result["passed"]
    assert result["score"] == 1.0


def test_model_drift_detected():
    result = score_model_match(
        _hal_trace(model="qwen3.5-35b-a3b"),
        expected_model="qwen/qwen3-coder-next",
    )
    assert not result["passed"]
    assert result["score"] == 0.0
    assert "drift" in result["notes"][0].lower()


# ── Token efficiency ──

def test_normal_usage_passes():
    result = score_token_efficiency(_hal_trace(prompt_tokens=200, completion_tokens=600))
    assert result["passed"]
    assert result["total_tokens"] == 800


def test_excessive_usage_flagged():
    result = score_token_efficiency(_hal_trace(prompt_tokens=5000, completion_tokens=5000))
    assert not result["passed"]
    assert "high" in result["notes"][0].lower()


def test_no_usage_data_passes_with_warning():
    result = score_token_efficiency(_hal_trace(prompt_tokens=0, completion_tokens=0))
    assert result["passed"]
    assert result["score"] == 0.5


# ── Routing correctness ──

def test_routing_correct():
    result = score_routing_correctness(_hal_trace())
    assert result["passed"]


def test_routing_missing_lane():
    trace = _hal_trace()
    trace["lane"] = ""
    result = score_routing_correctness(trace)
    assert not result["passed"]


# ── Full regression suite ──

def test_all_scorers_pass_on_good_trace():
    results = run_all_scorers(_hal_trace())
    assert all(r["passed"] for r in results)
    assert len(results) == 4


def test_all_scorers_detect_failure():
    results = run_all_scorers(
        _hal_trace(content_length=0, ok=False),
        expected_model="different-model",
    )
    failed = [r for r in results if not r["passed"]]
    assert len(failed) >= 2  # output_completeness + model_match


# ── Token budget tracking ──

def test_budget_apply_usage():
    from runtime.core.token_budget import (
        apply_budget_usage,
        create_token_budget,
        load_token_budget,
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        budget = create_token_budget(
            scope="global",
            actor="test",
            lane="test",
            max_tokens_per_cycle=100000,
            root=root,
        )
        apply_budget_usage(
            task_id="task_test",
            execution_backend="ralph_hal_proxy",
            token_usage=800,
            root=root,
        )
        after = load_token_budget(budget.token_budget_id, root=root)
        assert after.current_usage.get("cycle_tokens") == 800


def test_budget_hard_stop():
    from runtime.core.token_budget import (
        apply_budget_usage,
        assert_token_budget_allows_execution,
        create_token_budget,
    )
    import pytest
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "state" / "tasks").mkdir(parents=True)
        (root / "state" / "events").mkdir(parents=True)
        (root / "state" / "controls").mkdir(parents=True)
        create_token_budget(
            scope="global",
            actor="test",
            lane="test",
            max_tokens_per_cycle=500,
            hard_stop_threshold={"tokens_per_cycle": 500},
            root=root,
        )
        # Fill up
        apply_budget_usage(
            task_id="task_test",
            execution_backend="test",
            token_usage=600,
            root=root,
        )
        # This should raise
        with pytest.raises(ValueError, match="hard stop"):
            assert_token_budget_allows_execution(
                task_id="task_test",
                actor="test",
                lane="test",
                execution_backend="test",
                root=root,
            )
