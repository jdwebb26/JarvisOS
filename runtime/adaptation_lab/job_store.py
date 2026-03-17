#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import new_id, now_iso


ROOT = Path(__file__).resolve().parents[2]


def adaptation_jobs_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "adaptation_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def adaptation_results_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "adaptation_results"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _job_path(job_id: str, *, root: Optional[Path] = None) -> Path:
    return adaptation_jobs_dir(root) / f"{job_id}.json"


def _result_path(result_id: str, *, root: Optional[Path] = None) -> Path:
    return adaptation_results_dir(root) / f"{result_id}.json"


def create_adaptation_job(
    *,
    actor: str,
    lane: str,
    dataset_id: str,
    base_model: str,
    objective: str,
    adapter_kind: str = "lora",
    train_dataset_path: str = "",
    eval_dataset_path: str = "",
    max_steps: int = 8,
    batch_size: int = 1,
    learning_rate: float = 2e-4,
    target_modules: Optional[list[str]] = None,
    sequence_length: Optional[int] = None,
    training_backend: str = "unsloth",
    hyperparameters: Optional[dict[str, Any]] = None,
    output_dir: str = "",
    metadata: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    payload = {
        "job_id": new_id("adaptjob"),
        "created_at": timestamp,
        "updated_at": timestamp,
        "actor": actor,
        "lane": lane,
        "dataset_id": dataset_id,
        "base_model": base_model,
        "objective": objective,
        "adapter_kind": adapter_kind,
        "train_dataset_path": train_dataset_path,
        "eval_dataset_path": eval_dataset_path,
        "max_steps": int(max_steps),
        "batch_size": int(batch_size),
        "learning_rate": float(learning_rate),
        "target_modules": list(target_modules or []),
        "sequence_length": sequence_length,
        "training_backend": training_backend,
        "hyperparameters": dict(hyperparameters or {}),
        "output_dir": output_dir,
        "metadata": dict(metadata or {}),
        "status": "queued",
        "runtime_requirement_status": "pending",
        "promotion_disabled": True,
        "operator_approval_required": True,
        "eval_gate_required": True,
        "latest_result_id": "",
        "schema_version": "v5.2",
    }
    _job_path(payload["job_id"], root=root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def update_adaptation_job(job_id: str, updates: dict[str, Any], *, root: Optional[Path] = None) -> dict[str, Any]:
    path = _job_path(job_id, root=root)
    if not path.exists():
        raise ValueError(f"Adaptation job not found: {job_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(dict(updates or {}))
    payload["updated_at"] = now_iso()
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_adaptation_job(job_id: str, *, root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    path = _job_path(job_id, root=root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_adaptation_jobs(*, root: Optional[Path] = None, status: Optional[str] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(adaptation_jobs_dir(root).glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if status and str(row.get("status") or "") != status:
            continue
        rows.append(row)
    rows.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    return rows


def record_adaptation_result(
    *,
    job_id: str,
    actor: str,
    lane: str,
    status: str,
    runtime_status: str,
    summary: str,
    metrics: Optional[dict[str, Any]] = None,
    output_refs: Optional[dict[str, Any]] = None,
    error: str = "",
    metadata: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    payload = {
        "result_id": new_id("adaptres"),
        "job_id": job_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "actor": actor,
        "lane": lane,
        "status": status,
        "runtime_status": runtime_status,
        "summary": summary,
        "metrics": dict(metrics or {}),
        "output_refs": dict(output_refs or {}),
        "error": error,
        "metadata": dict(metadata or {}),
        "schema_version": "v5.2",
    }
    _result_path(payload["result_id"], root=root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    update_adaptation_job(
        job_id,
        {
            "status": status,
            "runtime_requirement_status": runtime_status,
            "latest_result_id": payload["result_id"],
        },
        root=root,
    )
    return payload


def list_adaptation_results(*, root: Optional[Path] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(adaptation_results_dir(root).glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    return rows
