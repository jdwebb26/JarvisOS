#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from runtime.optimizer.variant_store import (
    list_optimizer_runs,
    load_optimizer_run,
    load_optimizer_variant,
    summarize_optimizer_variants,
)


ROOT = Path(__file__).resolve().parents[2]


def compare_to_baseline(
    *,
    candidate_metrics: dict[str, Any],
    baseline_metrics: dict[str, Any],
    primary_metric: str,
) -> dict[str, Any]:
    candidate_value = candidate_metrics.get(primary_metric)
    baseline_value = baseline_metrics.get(primary_metric)
    delta_value = None
    improved = False
    if isinstance(candidate_value, (int, float)) and isinstance(baseline_value, (int, float)):
        delta_value = float(candidate_value) - float(baseline_value)
        improved = delta_value > 0
    return {
        "primary_metric": primary_metric,
        "candidate_value": candidate_value,
        "baseline_value": baseline_value,
        "delta_value": delta_value,
        "improved": improved,
    }


def evaluate_optimizer_promotion(variant_id: str, *, run_id: Optional[str] = None, root: Optional[Path] = None) -> dict[str, Any]:
    variant = load_optimizer_variant(variant_id, root=root)
    if variant is None:
        raise ValueError(f"Optimizer variant not found: {variant_id}")
    run = load_optimizer_run(run_id or str(variant.get("latest_run_id") or ""), root=root) if (run_id or variant.get("latest_run_id")) else None
    eval_gate = {
        "promotion_allowed": False,
        "operator_approval_required": True,
        "eval_required": True,
        "reason": "Optimizer variants remain non-authoritative until eval and operator approval are explicitly complete.",
        "run_status": str((run or {}).get("status") or ""),
        "runtime_status": str((run or {}).get("runtime_status") or ""),
    }
    return eval_gate


def summarize_optimizer_lane(*, root: Optional[Path] = None) -> dict[str, Any]:
    runs = list_optimizer_runs(root=root)
    runtime_status_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    blocked_run_count = 0
    for row in runs:
        status = str(row.get("status") or "unknown")
        runtime_status = str(row.get("runtime_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        runtime_status_counts[runtime_status] = runtime_status_counts.get(runtime_status, 0) + 1
        if status == "blocked":
            blocked_run_count += 1
    return {
        "variant_summary": summarize_optimizer_variants(root=root),
        "optimizer_run_count": len(runs),
        "optimizer_run_status_counts": status_counts,
        "optimizer_runtime_status_counts": runtime_status_counts,
        "blocked_run_count": blocked_run_count,
        "latest_optimizer_run": runs[0] if runs else None,
        "promotion_disabled": True,
        "approval_required": True,
        "notes": [
            "DSPy optimizer runs are bounded experimentation only.",
            "No optimizer variant becomes authoritative without eval and operator approval.",
        ],
    }

