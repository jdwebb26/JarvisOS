#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Optional

from runtime.adaptation_lab.job_store import list_adaptation_results


def compare_to_baseline(
    *,
    candidate_metrics: dict[str, Any],
    baseline_metrics: dict[str, Any],
    primary_metric: str,
) -> dict[str, Any]:
    candidate = candidate_metrics.get(primary_metric)
    baseline = baseline_metrics.get(primary_metric)
    delta = None
    improved = False
    if isinstance(candidate, (int, float)) and isinstance(baseline, (int, float)):
        delta = float(candidate) - float(baseline)
        improved = delta > 0
    return {
        "primary_metric": primary_metric,
        "candidate_value": candidate,
        "baseline_value": baseline,
        "delta": delta,
        "improved": improved,
    }


def summarize_result_quality(*, root: Optional[object] = None) -> dict[str, Any]:
    results = list_adaptation_results(root=root)
    status_counts: dict[str, int] = {}
    runtime_status_counts: dict[str, int] = {}
    for row in results:
        status = str(row.get("status") or "unknown")
        runtime_status = str(row.get("runtime_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        runtime_status_counts[runtime_status] = runtime_status_counts.get(runtime_status, 0) + 1
    return {
        "result_count": len(results),
        "result_status_counts": status_counts,
        "runtime_status_counts": runtime_status_counts,
        "latest_result": results[0] if results else None,
    }
