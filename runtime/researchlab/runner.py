#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import (
    ExperimentRunRecord,
    MetricResultRecord,
    ResearchCampaignRecord,
    ResearchRecommendationRecord,
    now_iso,
)


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def research_campaigns_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("research_campaigns", root=root)


def experiment_runs_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("experiment_runs", root=root)


def metric_results_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("metric_results", root=root)


def research_recommendations_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("research_recommendations", root=root)


def research_workspace_dir(sandbox_root: str, *, root: Optional[Path] = None) -> Path:
    path = (Path(root or ROOT).resolve() / str(sandbox_root or "").strip()).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def standard_run_outputs_dir(run_id: str, *, sandbox_root: str, root: Optional[Path] = None) -> Path:
    path = research_workspace_dir(sandbox_root, root=root) / run_id / "standard_run_outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _record_path(folder: Path, record_id: str) -> Path:
    return folder / f"{record_id}.json"


def save_research_campaign(record: ResearchCampaignRecord, *, root: Optional[Path] = None) -> ResearchCampaignRecord:
    record.updated_at = now_iso()
    _record_path(research_campaigns_dir(root), record.campaign_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_research_campaign(campaign_id: str, *, root: Optional[Path] = None) -> Optional[ResearchCampaignRecord]:
    path = _record_path(research_campaigns_dir(root), campaign_id)
    if not path.exists():
        return None
    return ResearchCampaignRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_experiment_run(record: ExperimentRunRecord, *, root: Optional[Path] = None) -> ExperimentRunRecord:
    record.updated_at = now_iso()
    _record_path(experiment_runs_dir(root), record.run_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_experiment_run(run_id: str, *, root: Optional[Path] = None) -> Optional[ExperimentRunRecord]:
    path = _record_path(experiment_runs_dir(root), run_id)
    if not path.exists():
        return None
    return ExperimentRunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_experiment_runs_for_campaign(campaign_id: str, *, root: Optional[Path] = None) -> list[ExperimentRunRecord]:
    rows: list[ExperimentRunRecord] = []
    for path in experiment_runs_dir(root).glob("*.json"):
        try:
            row = ExperimentRunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if row.campaign_id == campaign_id:
            rows.append(row)
    rows.sort(key=lambda row: (row.pass_index, row.updated_at))
    return rows


def save_metric_result(record: MetricResultRecord, *, root: Optional[Path] = None) -> MetricResultRecord:
    record.updated_at = now_iso()
    _record_path(metric_results_dir(root), record.metric_result_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def list_metric_results_for_run(run_id: str, *, root: Optional[Path] = None) -> list[MetricResultRecord]:
    rows: list[MetricResultRecord] = []
    for path in metric_results_dir(root).glob("*.json"):
        try:
            row = MetricResultRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if row.run_id == run_id:
            rows.append(row)
    rows.sort(key=lambda row: (row.metric_name, row.updated_at))
    return rows


def save_research_recommendation(
    record: ResearchRecommendationRecord,
    *,
    root: Optional[Path] = None,
) -> ResearchRecommendationRecord:
    record.updated_at = now_iso()
    _record_path(research_recommendations_dir(root), record.recommendation_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_research_recommendation(
    recommendation_id: str,
    *,
    root: Optional[Path] = None,
) -> Optional[ResearchRecommendationRecord]:
    path = _record_path(research_recommendations_dir(root), recommendation_id)
    if not path.exists():
        return None
    return ResearchRecommendationRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
