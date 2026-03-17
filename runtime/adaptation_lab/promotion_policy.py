#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


def evaluate_adaptation_promotion(job: dict[str, Any], result: dict[str, Any] | None) -> dict[str, Any]:
    reasons: list[str] = []
    if not result:
        reasons.append("missing_adaptation_result")
    elif str(result.get("status") or "") != "completed":
        reasons.append("adaptation_result_not_completed")
    if not job.get("eval_gate_required", True):
        reasons.append("eval_gate_misconfigured")
    if job.get("promotion_disabled", True):
        reasons.append("promotion_disabled")
    if job.get("operator_approval_required", True):
        reasons.append("operator_approval_required")
    return {
        "promotion_allowed": False,
        "approval_required": True,
        "eval_gate_required": True,
        "reasons": reasons or ["operator_review_required"],
    }
