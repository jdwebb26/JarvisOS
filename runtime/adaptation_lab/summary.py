#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Optional

from runtime.adaptation_lab.dataset_store import list_adaptation_datasets
from runtime.adaptation_lab.evaluator import summarize_result_quality
from runtime.adaptation_lab.job_store import list_adaptation_jobs


def summarize_adaptation_lab(*, root: Optional[Path] = None) -> dict:
    datasets = list_adaptation_datasets(root=root)
    jobs = list_adaptation_jobs(root=root)
    quality = summarize_result_quality(root=root)
    status_counts: dict[str, int] = {}
    runtime_status_counts: dict[str, int] = {}
    blocked_count = 0
    for row in jobs:
        status = str(row.get("status") or "unknown")
        runtime_status = str(row.get("runtime_requirement_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        runtime_status_counts[runtime_status] = runtime_status_counts.get(runtime_status, 0) + 1
        if status == "blocked" or runtime_status.startswith("blocked_"):
            blocked_count += 1
    return {
        "dataset_count": len(datasets),
        "job_count": len(jobs),
        "blocked_job_count": blocked_count,
        "job_status_counts": status_counts,
        "runtime_status_counts": runtime_status_counts,
        "latest_dataset": datasets[0] if datasets else None,
        "latest_job": jobs[0] if jobs else None,
        "latest_result": quality.get("latest_result"),
        "promotion_disabled": True,
        "operator_approval_required": True,
        "eval_gate_required": True,
    }
