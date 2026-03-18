#!/usr/bin/env python3
"""Regression scorers for Ralph HAL/Archimedes execution traces.

Each scorer takes a trace dict and returns {scorer, score, passed, notes}.
Scorers are designed to catch silent regressions from model/routing changes.
"""
from __future__ import annotations

from typing import Any


def build_scorer_catalog() -> list[dict[str, str]]:
    return [
        {
            "scorer": "output_completeness",
            "status": "live",
            "description": "Checks whether the model produced a non-empty, non-truncated response.",
        },
        {
            "scorer": "model_match",
            "status": "live",
            "description": "Checks whether the realized model matches the expected model from the trace.",
        },
        {
            "scorer": "token_efficiency",
            "status": "live",
            "description": "Checks whether token usage is within reasonable bounds for the task type.",
        },
        {
            "scorer": "routing_correctness",
            "status": "live",
            "description": "Checks whether lane and execution_backend are set correctly.",
        },
    ]


def score_output_completeness(trace: dict[str, Any]) -> dict[str, Any]:
    """Check the response has content and isn't truncated."""
    resp = dict(trace.get("response_payload") or {})
    content_length = int(resp.get("content_length") or 0)
    ok = resp.get("ok")
    approved = resp.get("approved")
    elapsed = float(resp.get("elapsed") or 0)

    # For HAL: ok must be True and content must exist
    # For Archimedes: approved must be non-None (True or False is fine — it means it worked)
    if ok is not None:
        has_output = bool(ok) and content_length > 50
    elif approved is not None:
        has_output = approved is not None and content_length > 10
    else:
        has_output = content_length > 0

    # Truncation heuristic: if content_length is exactly at a round boundary, may be truncated.
    # Exception: review traces cap reason at 500 chars — that's by design, not truncation.
    is_review = approved is not None
    likely_truncated = content_length in (1500, 2048, 4096) or (content_length == 500 and not is_review)

    passed = has_output and not likely_truncated
    notes = []
    if not has_output:
        notes.append(f"No usable output (content_length={content_length}, ok={ok}, approved={approved})")
    if likely_truncated:
        notes.append(f"Output may be truncated at {content_length} chars")
    if elapsed > 60:
        notes.append(f"Slow response: {elapsed}s")

    return {
        "scorer": "output_completeness",
        "score": 1.0 if passed else 0.0,
        "passed": passed,
        "content_length": content_length,
        "elapsed": elapsed,
        "notes": notes,
    }


def score_model_match(
    trace: dict[str, Any], *, expected_model: str = "",
) -> dict[str, Any]:
    """Check the realized model matches expectations."""
    req = dict(trace.get("request_payload") or {})
    resp = dict(trace.get("response_payload") or {})
    realized_model = resp.get("model") or req.get("model") or ""
    expected = expected_model or req.get("model") or ""

    if not expected or not realized_model:
        return {
            "scorer": "model_match",
            "score": 0.5,
            "passed": True,
            "notes": ["No model expectation to check against"],
            "expected": expected,
            "realized": realized_model,
        }

    match = realized_model.lower() == expected.lower() or expected.lower() in realized_model.lower()
    return {
        "scorer": "model_match",
        "score": 1.0 if match else 0.0,
        "passed": match,
        "expected": expected,
        "realized": realized_model,
        "notes": [] if match else [f"Model drift: expected={expected}, got={realized_model}"],
    }


def score_token_efficiency(trace: dict[str, Any]) -> dict[str, Any]:
    """Check token usage is within reasonable bounds."""
    resp = dict(trace.get("response_payload") or {})
    prompt_tokens = int(resp.get("prompt_tokens") or 0)
    completion_tokens = int(resp.get("completion_tokens") or 0)
    total = prompt_tokens + completion_tokens

    if total == 0:
        return {
            "scorer": "token_efficiency",
            "score": 0.5,
            "passed": True,
            "notes": ["No token usage data available"],
            "total_tokens": 0,
        }

    # Reasonable bounds: 50-8000 tokens for a typical task
    within_bounds = 50 <= total <= 8000
    notes = []
    if total > 8000:
        notes.append(f"High token usage: {total} (prompt={prompt_tokens}, completion={completion_tokens})")
    if total < 50:
        notes.append(f"Suspiciously low token count: {total}")

    return {
        "scorer": "token_efficiency",
        "score": 1.0 if within_bounds else 0.5,
        "passed": within_bounds,
        "total_tokens": total,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "notes": notes,
    }


def score_routing_correctness(trace: dict[str, Any]) -> dict[str, Any]:
    """Check lane and execution_backend are set."""
    passed = bool(trace.get("lane")) and bool(trace.get("execution_backend"))
    return {
        "scorer": "routing_correctness",
        "score": 1.0 if passed else 0.0,
        "passed": passed,
        "lane": trace.get("lane"),
        "execution_backend": trace.get("execution_backend"),
        "notes": [] if passed else ["Missing lane or execution_backend"],
    }


def run_all_scorers(
    trace: dict[str, Any], *, expected_model: str = "",
) -> list[dict[str, Any]]:
    """Run all live scorers against a trace. Returns list of score results."""
    return [
        score_output_completeness(trace),
        score_model_match(trace, expected_model=expected_model),
        score_token_efficiency(trace),
        score_routing_correctness(trace),
    ]


# Keep backward-compat alias for replay_runner imports
run_scaffolding_scorers = run_all_scorers
