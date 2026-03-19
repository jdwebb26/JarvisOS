import json
import datetime
import uuid
from pathlib import Path

STRATEGIES_REGISTRY = Path("/home/rollan/.openclaw/workspace/STRATEGIES.jsonl")
CANDIDATE_HISTORY = Path("/home/rollan/.openclaw/workspace/CANDIDATE_HISTORY.jsonl")
WATCHLIST_HISTORY = Path("/home/rollan/.openclaw/workspace/WATCHLIST_HISTORY.jsonl")

ARTIFACT_ROOT = Path("/home/rollan/.openclaw/workspace/artifacts/strategy_factory")


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _today_stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def ensure_artifact_dir():
    out = ARTIFACT_ROOT / _today_stamp()
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def write_summary(artifact_dir, summary_obj):
    md = artifact_dir / "summary.md"
    lines = ["# Strategy Factory Summary", ""]
    for k, v in summary_obj.items():
        lines.append(f"- **{k}**: {v}")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Machine-readable JSON — both manifest.json (legacy) and summary.json
    write_json(artifact_dir / "manifest.json", summary_obj)
    write_json(artifact_dir / "summary.json", summary_obj)


def write_candidate_result(artifact_dir, sim_result, gate_results):
    """Persist the full candidate result alongside the summary."""
    payload = {
        "candidate_id": sim_result.get("candidate_id"),
        "logic_family_id": sim_result.get("logic_family_id"),
        "status": sim_result.get("status"),
        "reject_reason": sim_result.get("reject_reason"),
        "fold_count": len(sim_result.get("fold_results", [])),
        "gate_results": gate_results or {},
        "produced_at": _now_iso(),
    }
    write_json(artifact_dir / "candidate_result.json", payload)
    return payload


def write_fold_metrics(artifact_dir, fold_results):
    """Persist per-fold metric breakdown."""
    payload = {
        "fold_count": len(fold_results),
        "folds": fold_results,
        "produced_at": _now_iso(),
    }
    write_json(artifact_dir / "fold_metrics.json", payload)
    return payload


def _collect_evidence_files(artifact_dir):
    """Return relative paths of evidence files present in the artifact dir."""
    evidence_names = [
        "candidate_result.json",
        "fold_metrics.json",
        "manifest.json",
        "summary.md",
    ]
    return [name for name in evidence_names if (artifact_dir / name).exists()]


def write_provenance_linkage(artifact_dir, *, candidate_id, status, gate_overall,
                              fold_count, reject_reason=None, evidence=None):
    """Write a provenance_linkage.json stub that the Jarvis runtime can ingest."""
    linkage_id = f"flink_{uuid.uuid4().hex[:12]}"
    evidence_files = _collect_evidence_files(artifact_dir)
    payload = {
        "linkage_id": linkage_id,
        "source": "strategy_factory",
        "candidate_id": candidate_id,
        "artifact_dir": str(artifact_dir),
        "status": status,
        "gate_overall": gate_overall,
        "fold_count": fold_count,
        "reject_reason": reject_reason,
        "evidence_files": evidence_files,
        "produced_at": _now_iso(),
        "ingested": False,
    }
    if evidence:
        payload["evidence"] = evidence
    write_json(artifact_dir / "provenance_linkage.json", payload)
    return payload


def append_to_strategy_registry(*, candidate_id, logic_family_id, params,
                                 stage, score, gate_overall, artifact_dir,
                                 data_source, fold_count,
                                 perturbation_robust=False,
                                 stress_overall="FAIL",
                                 per_fold_params=None,
                                 evidence=None):
    """Append a strategy entry to STRATEGIES.jsonl.

    Follows the lifecycle: IDEA → CANDIDATE → BACKTESTED → PROMOTED → …
    Stage is capped by evidence tier — only execution-grade intraday data
    can produce BACKTESTED entries.  All other data tiers cap at CANDIDATE.

    Returns:
        The entry dict that was appended.
    """
    entry = {
        "candidate_id": candidate_id,
        "logic_family_id": logic_family_id,
        "params": params,
        "stage": stage,
        "score": score,
        "gate_overall": gate_overall,
        "artifact_dir": str(artifact_dir),
        "data_source": data_source,
        "fold_count": fold_count,
        "perturbation_robust": perturbation_robust,
        "stress_overall": stress_overall,
        "produced_at": _now_iso(),
    }
    if per_fold_params:
        entry["per_fold_params"] = per_fold_params
    if evidence:
        entry["evidence"] = evidence

    with open(STRATEGIES_REGISTRY, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    return entry


def write_candidate_history(artifact_dir, all_entries, evidence):
    """Write durable history for ALL evaluated candidates in a batch.

    Unlike STRATEGIES.jsonl (which only records non-rejected winners),
    CANDIDATE_HISTORY.jsonl records every single candidate that was
    evaluated, including rejected ones.  This creates a queryable
    audit trail of what was tried and why it failed.

    Also writes candidate_history.json in the artifact dir for
    per-run inspection.

    Args:
        artifact_dir: Path to artifact directory for this run.
        all_entries: list of dicts, one per candidate, each with:
            candidate_id, family, params, status, reject_reason,
            stage, stage_reason, score, gate_overall, evidence_tier,
            promotion_eligible
        evidence: the run-level evidence classification dict.
    """
    records = []
    for entry in all_entries:
        record = {
            **entry,
            "artifact_dir": str(artifact_dir),
            "evidence": evidence,
            "produced_at": _now_iso(),
        }
        records.append(record)

    # Append to durable JSONL history
    with open(CANDIDATE_HISTORY, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    # Also write per-run artifact
    write_json(artifact_dir / "candidate_history.json", records)

    return records
