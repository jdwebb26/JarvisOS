#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import new_id, now_iso
from runtime.evals.replay_runner import load_eval_run
from runtime.researchlab.experiment_store import (
    build_experiment_summary,
    list_experiment_records,
    load_experiment_record,
    load_frontier_record,
    save_experiment_record,
    save_frontier_record,
)


ROOT = Path(__file__).resolve().parents[2]


def _resolved_root(root: Optional[Path] = None) -> Path:
    return Path(root or ROOT).resolve()


def _fingerprint(*parts: str) -> str:
    basis = "||".join(str(part or "").strip() for part in parts if str(part or "").strip())
    if not basis:
        return ""
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _summarize_scorers(scorer_results: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [float(row.get("score", 0.0)) for row in scorer_results if isinstance(row.get("score"), (int, float))]
    aggregate = sum(scores) / len(scores) if scores else None
    return {
        "scorer_count": len(scorer_results),
        "aggregate_score": aggregate,
        "passed_count": sum(1 for row in scorer_results if row.get("passed")),
        "latest_scorers": scorer_results,
    }


def propose_candidate_variant(
    *,
    actor: str,
    lane: str,
    experiment_kind: str,
    objective: str,
    base_name: str,
    variant_label: str,
    proposal: dict[str, Any],
    summary: str = "",
    source_refs: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    record = {
        "experiment_id": new_id("exp"),
        "created_at": timestamp,
        "updated_at": timestamp,
        "actor": actor,
        "lane": lane,
        "status": "proposed",
        "experiment_kind": experiment_kind,
        "objective": objective,
        "base_name": base_name,
        "variant_label": variant_label,
        "variant_fingerprint": _fingerprint(base_name, variant_label, str(proposal)),
        "summary": summary or f"Proposed {experiment_kind} variant `{variant_label}` for `{base_name}`.",
        "proposal": dict(proposal or {}),
        "source_refs": dict(source_refs or {}),
        "metadata": {
            "promotion_disabled": True,
            "approval_required": True,
            "autonomous_apply_enabled": False,
            **dict(metadata or {}),
        },
        "trace_ids": [],
        "eval_run_ids": [],
        "scorer_results": [],
        "score_summary": {},
        "keep_or_revert": {
            "decision": "pending",
            "reason": "",
            "recorded_at": None,
        },
        "frontier_eligible": False,
        "promotion_disabled": True,
        "approval_required": True,
    }
    return save_experiment_record(record, root=root)


def attach_replay_eval_results(
    experiment_id: str,
    *,
    eval_run_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    scorer_results: Optional[list[dict[str, Any]]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    resolved_root = _resolved_root(root)
    record = load_experiment_record(experiment_id, root=resolved_root)
    if record is None:
        raise ValueError(f"Experiment not found: {experiment_id}")

    resolved_scorers = list(scorer_results or [])
    if eval_run_id:
        eval_run = load_eval_run(eval_run_id, root=resolved_root)
        if eval_run is None:
            raise ValueError(f"Eval run not found: {eval_run_id}")
        resolved_scorers = list(eval_run.get("scoring") or resolved_scorers)
        record["eval_run_ids"] = sorted(set([*list(record.get("eval_run_ids") or []), eval_run_id]))
    if trace_id:
        record["trace_ids"] = sorted(set([*list(record.get("trace_ids") or []), trace_id]))
    record["scorer_results"] = resolved_scorers
    record["score_summary"] = _summarize_scorers(resolved_scorers)
    record["status"] = "scored" if resolved_scorers else record.get("status", "proposed")
    record["updated_at"] = now_iso()
    record["frontier_eligible"] = bool(record["score_summary"].get("aggregate_score") is not None)
    return save_experiment_record(record, root=resolved_root)


def record_keep_or_revert(
    experiment_id: str,
    *,
    decision: str,
    reason: str,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    if decision not in {"keep_candidate", "revert_candidate"}:
        raise ValueError("decision must be `keep_candidate` or `revert_candidate`.")
    resolved_root = _resolved_root(root)
    record = load_experiment_record(experiment_id, root=resolved_root)
    if record is None:
        raise ValueError(f"Experiment not found: {experiment_id}")
    record["keep_or_revert"] = {
        "decision": decision,
        "reason": reason,
        "recorded_at": now_iso(),
    }
    record["promotion_disabled"] = True
    record["approval_required"] = True
    record["status"] = "kept" if decision == "keep_candidate" else "reverted"
    record["updated_at"] = now_iso()
    return save_experiment_record(record, root=resolved_root)


def rebuild_experiment_frontier(*, root: Optional[Path] = None, limit: int = 5) -> dict[str, Any]:
    resolved_root = _resolved_root(root)
    rows = []
    for row in list_experiment_records(root=resolved_root):
        decision = ((row.get("keep_or_revert") or {}).get("decision")) or ""
        aggregate_score = (row.get("score_summary") or {}).get("aggregate_score")
        if decision != "keep_candidate" or not isinstance(aggregate_score, (int, float)):
            continue
        rows.append(row)
    rows.sort(
        key=lambda row: (
            float((row.get("score_summary") or {}).get("aggregate_score", 0.0)),
            str(row.get("updated_at") or ""),
        ),
        reverse=True,
    )
    frontier_rows = [
        {
            "experiment_id": row.get("experiment_id"),
            "experiment_kind": row.get("experiment_kind"),
            "base_name": row.get("base_name"),
            "variant_label": row.get("variant_label"),
            "aggregate_score": (row.get("score_summary") or {}).get("aggregate_score"),
            "eval_run_ids": row.get("eval_run_ids", []),
            "trace_ids": row.get("trace_ids", []),
            "promotion_disabled": True,
            "approval_required": True,
        }
        for row in rows[: max(int(limit), 0)]
    ]
    frontier = {
        "frontier_version": "1",
        "updated_at": now_iso(),
        "promotion_disabled": True,
        "approval_required": True,
        "frontier_size": len(frontier_rows),
        "experiments": frontier_rows,
        "notes": [
            "Frontier tracking is bounded experiment scaffolding only.",
            "No experiment record auto-promotes into production.",
        ],
    }
    return save_frontier_record(frontier, root=resolved_root)


def build_optimizer_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    summary = build_experiment_summary(root=root)
    frontier = load_frontier_record(root=root)
    summary["frontier_preview"] = list(frontier.get("experiments", []))[:3]
    summary["promotion_disabled"] = True
    summary["approval_required"] = True
    return summary
