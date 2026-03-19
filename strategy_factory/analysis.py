"""Cross-run comparison, candidate signatures, and best-ideas extraction.

Reads CANDIDATE_HISTORY.jsonl to provide:
- compare_runs(): side-by-side run comparison
- compute_candidate_signature(): stable fingerprint for param dedup
- best_ideas(): recurring survivors across runs
- research_rollup(): operator-facing summary of current research state
"""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from . import artifacts as _art_mod


def _load_history():
    """Load all candidate history records.

    Reads from artifacts.CANDIDATE_HISTORY (mutable for testing).
    """
    path = _art_mod.CANDIDATE_HISTORY
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _get_run_id(record):
    """Extract run_id, falling back to artifact_dir for older records."""
    return record.get("run_id") or record.get("artifact_dir", "unknown")


def _get_dataset_id(record):
    """Extract dataset_id, falling back to evidence block for older records."""
    if "dataset_id" in record:
        return record["dataset_id"]
    ev = record.get("evidence", {})
    gran = ev.get("data_granularity", "unknown")
    if gran == "daily":
        return "NQ_daily"
    if gran in ("1h", "hourly"):
        return "NQ_hourly"
    if gran in ("4h", "4hr"):
        return "NQ_4h"
    if gran in ("15m", "15min"):
        return "NQ_15m"
    return ev.get("data_source", "unknown")


# ---------------------------------------------------------------------------
# Candidate signatures
# ---------------------------------------------------------------------------

def compute_candidate_signature(family, params):
    """Compute a stable signature for a (family, params) combination.

    Normalizes param values to 4 decimal places and sorts keys for
    deterministic hashing.  Two candidates with the same family and
    effectively the same params will produce the same signature.
    """
    norm_params = {}
    for k in sorted(params.keys()):
        v = params[k]
        if isinstance(v, float):
            norm_params[k] = round(v, 4)
        elif isinstance(v, int):
            norm_params[k] = v
        else:
            norm_params[k] = v

    payload = json.dumps({"family": family, "params": norm_params}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Compare runs
# ---------------------------------------------------------------------------

def compare_runs(run_ids=None, last_n=2, dataset_id=None, family=None):
    """Compare candidate results across runs.

    Args:
        run_ids: explicit list of run_ids to compare.
        last_n: if run_ids not given, compare the last N distinct runs.
        dataset_id: filter records to only this dataset before comparing.
        family: filter records to only this family before comparing.

    Returns:
        dict with per-run summaries and a diff section.
    """
    records = _load_history()
    if not records:
        return {"error": "no history"}

    # Apply pre-filters
    if dataset_id:
        records = [r for r in records if _get_dataset_id(r) == dataset_id]
    if family:
        records = [r for r in records if r.get("family") == family]
    if not records:
        return {"error": "no records after filter"}

    # Discover distinct runs (ordered by first appearance)
    seen_runs = []
    seen_set = set()
    for r in records:
        rid = _get_run_id(r)
        if rid not in seen_set:
            seen_runs.append(rid)
            seen_set.add(rid)

    if run_ids:
        target_runs = [r for r in run_ids if r in seen_set]
    else:
        target_runs = seen_runs[-last_n:]

    if len(target_runs) < 1:
        return {"error": "no matching runs"}

    run_summaries = {}
    for rid in target_runs:
        run_records = [r for r in records if _get_run_id(r) == rid]
        ds = _get_dataset_id(run_records[0]) if run_records else "unknown"
        evidence_tier = (run_records[0].get("evidence_tier")
                         or run_records[0].get("evidence", {}).get("evidence_tier", "unknown"))

        passed = [r for r in run_records if r.get("status") == "PASS"]
        rejected = [r for r in run_records if r.get("status") != "PASS"]
        families_seen = set(r.get("family") for r in run_records)
        scores = [r.get("score", 0) for r in passed]
        top_score = max(scores) if scores else 0.0
        top_candidates = sorted(passed, key=lambda r: r.get("score", 0), reverse=True)[:3]

        run_summaries[rid] = {
            "run_id": rid, "dataset_id": ds, "evidence_tier": evidence_tier,
            "families": sorted(families_seen),
            "total": len(run_records), "passed": len(passed), "rejected": len(rejected),
            "top_score": round(top_score, 4),
            "top_candidates": [{
                "candidate_id": c.get("candidate_id"), "family": c.get("family"),
                "score": round(c.get("score", 0), 4),
                "stage": c.get("stage"), "stage_reason": c.get("stage_reason"),
            } for c in top_candidates],
            "rejection_reasons": _tally_reasons(rejected),
        }

    diff = {}
    if len(target_runs) == 2:
        a, b = target_runs
        sa, sb = run_summaries[a], run_summaries[b]
        diff = {
            "runs": [a, b],
            "dataset_change": sa["dataset_id"] != sb["dataset_id"],
            "evidence_change": sa["evidence_tier"] != sb["evidence_tier"],
            "score_delta": round(sb["top_score"] - sa["top_score"], 4),
            "pass_rate_a": f"{sa['passed']}/{sa['total']}",
            "pass_rate_b": f"{sb['passed']}/{sb['total']}",
            "new_families_in_b": sorted(set(sb["families"]) - set(sa["families"])),
            "dropped_families_in_b": sorted(set(sa["families"]) - set(sb["families"])),
        }

    return {
        "runs_compared": target_runs,
        "filters": {"dataset_id": dataset_id, "family": family},
        "per_run": run_summaries,
        "diff": diff,
    }


def _tally_reasons(records):
    tally = {}
    for r in records:
        reason = r.get("reject_reason") or r.get("stage_reason") or "unknown"
        tally[reason] = tally.get(reason, 0) + 1
    return tally


# ---------------------------------------------------------------------------
# Best ideas
# ---------------------------------------------------------------------------

def best_ideas(min_appearances=1, top_n=10):
    """Extract recurring survivor candidates from history.

    Groups candidates by (family, signature) across all runs.
    Candidates that appear in multiple runs as PASS with decent scores
    are the strongest research ideas.

    Returns:
        list of idea dicts, sorted by recurrence then best score.
    """
    records = _load_history()
    if not records:
        return []

    # Group by signature
    sig_groups = defaultdict(list)
    for r in records:
        if r.get("status") != "PASS":
            continue
        family = r.get("family", "unknown")
        params = r.get("params", {})
        sig = compute_candidate_signature(family, params)
        sig_groups[sig].append(r)

    ideas = []
    for sig, appearances in sig_groups.items():
        if len(appearances) < min_appearances:
            continue

        best = max(appearances, key=lambda r: r.get("score", 0))
        run_ids = sorted(set(_get_run_id(r) for r in appearances))
        dataset_ids = sorted(set(_get_dataset_id(r) for r in appearances))
        scores = [r.get("score", 0) for r in appearances]

        ideas.append({
            "signature": sig,
            "family": best.get("family"),
            "params": best.get("params"),
            "appearances": len(appearances),
            "distinct_runs": len(run_ids),
            "distinct_datasets": dataset_ids,
            "best_score": round(max(scores), 4),
            "avg_score": round(sum(scores) / len(scores), 4),
            "best_stage": best.get("stage"),
            "stage_reason": best.get("stage_reason"),
            "evidence_tier": (best.get("evidence_tier")
                              or best.get("evidence", {}).get("evidence_tier")),
            "fold_profile_used": best.get("fold_profile_used"),
            "gate_profile_used": best.get("gate_profile_used"),
            "promotion_eligible": best.get("evidence", {}).get("promotion_eligible", False),
            "first_seen_run": run_ids[0] if run_ids else None,
            "latest_seen_run": run_ids[-1] if run_ids else None,
        })

    # Sort by appearances desc, then best score desc
    ideas.sort(key=lambda x: (-x["appearances"], -x["best_score"]))
    return ideas[:top_n]


# ---------------------------------------------------------------------------
# Research rollup
# ---------------------------------------------------------------------------

def research_rollup():
    """Produce an operator-facing research rollup from all history.

    Returns a dict organized by dataset, showing:
    - top recurring survivors per dataset
    - recently failed families
    - evidence tier constraints
    """
    records = _load_history()
    if not records:
        return {"status": "no_history"}

    # Group by dataset
    by_dataset = defaultdict(list)
    for r in records:
        did = _get_dataset_id(r)
        by_dataset[did].append(r)

    rollup = {
        "total_records": len(records),
        "distinct_runs": len(set(_get_run_id(r) for r in records)),
        "datasets": {},
    }

    for dataset_id, ds_records in sorted(by_dataset.items()):
        passed = [r for r in ds_records if r.get("status") == "PASS"]
        rejected = [r for r in ds_records if r.get("status") != "PASS"]

        # Evidence tier (from most recent record)
        latest = ds_records[-1]
        evidence_tier = (latest.get("evidence_tier")
                         or latest.get("evidence", {}).get("evidence_tier", "unknown"))
        promotion_eligible = latest.get("evidence", {}).get("promotion_eligible", False)

        # Top ideas for this dataset
        sig_groups = defaultdict(list)
        for r in passed:
            sig = compute_candidate_signature(r.get("family", ""), r.get("params", {}))
            sig_groups[sig].append(r)

        top_ideas = []
        for sig, apps in sig_groups.items():
            best = max(apps, key=lambda r: r.get("score", 0))
            top_ideas.append({
                "signature": sig,
                "family": best.get("family"),
                "appearances": len(apps),
                "best_score": round(max(r.get("score", 0) for r in apps), 4),
                "stage": best.get("stage"),
                "stage_reason": best.get("stage_reason"),
            })
        top_ideas.sort(key=lambda x: (-x["appearances"], -x["best_score"]))

        # Families that failed in recent runs
        recent_run_ids = sorted(set(_get_run_id(r) for r in ds_records))[-3:]
        recent_rejects = [r for r in rejected if _get_run_id(r) in recent_run_ids]
        failed_families = sorted(set(r.get("family") for r in recent_rejects))

        rollup["datasets"][dataset_id] = {
            "evidence_tier": evidence_tier,
            "promotion_eligible": promotion_eligible,
            "total_evaluated": len(ds_records),
            "total_passed": len(passed),
            "total_rejected": len(rejected),
            "top_ideas": top_ideas[:5],
            "recently_failed_families": failed_families,
            "rejection_reasons": _tally_reasons(rejected),
        }

    return rollup


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

def generate_watchlist(top_n=10):
    """Generate an actionable shortlist from history, separated by dataset.

    Each entry includes an operator-readable ``reason`` explaining why
    it's on the watchlist (recurring survivor, high score, capped by
    evidence, etc.).

    Returns:
        dict with ``daily``, ``hourly``, ``other`` lists and metadata.
    """
    records = _load_history()
    if not records:
        return {"status": "no_history", "daily": [], "hourly": [], "other": []}

    # Build ideas grouped by signature
    sig_groups = defaultdict(list)
    for r in records:
        if r.get("status") != "PASS":
            continue
        sig = (r.get("candidate_signature")
               or compute_candidate_signature(r.get("family", ""), r.get("params", {})))
        sig_groups[sig].append(r)

    # Classify each idea into a watchlist bucket
    daily_items = []
    hourly_items = []
    other_items = []

    for sig, apps in sig_groups.items():
        best = max(apps, key=lambda r: r.get("score", 0))
        run_ids = sorted(set(_get_run_id(r) for r in apps))
        dataset_ids = sorted(set(_get_dataset_id(r) for r in apps))
        scores = [r.get("score", 0) for r in apps]
        n_runs = len(run_ids)

        stage = best.get("stage", "unknown")
        stage_reason = best.get("stage_reason", "")
        evidence_tier = (best.get("evidence_tier")
                         or best.get("evidence", {}).get("evidence_tier", "unknown"))
        capped = "evidence_tier_cap" in str(stage_reason)

        # Generate operator reason
        reasons = []
        if n_runs >= 3:
            reasons.append("recurring survivor")
        elif n_runs >= 2:
            reasons.append("confirmed across runs")
        if len(dataset_ids) >= 2:
            reasons.append(f"survives on {','.join(dataset_ids)}")
        if max(scores) >= 0.7:
            reasons.append("high score")
        if capped:
            reasons.append(f"capped by {evidence_tier} evidence")
        if not reasons:
            reasons.append("single-run survivor")

        item = {
            "signature": sig,
            "family": best.get("family"),
            "params": best.get("params"),
            "appearances": len(apps),
            "distinct_runs": n_runs,
            "datasets": dataset_ids,
            "best_score": round(max(scores), 4),
            "avg_score": round(sum(scores) / len(scores), 4),
            "stage": stage,
            "stage_reason": stage_reason,
            "evidence_tier": evidence_tier,
            "fold_profile_used": best.get("fold_profile_used"),
            "gate_profile_used": best.get("gate_profile_used"),
            "capped_by_evidence": capped,
            "reason": "; ".join(reasons),
            "first_seen": run_ids[0] if run_ids else None,
            "latest_seen": run_ids[-1] if run_ids else None,
        }

        # Route to bucket
        if "NQ_daily" in dataset_ids:
            daily_items.append(item)
        if "NQ_hourly" in dataset_ids:
            hourly_items.append(item)
        if not any(d in dataset_ids for d in ("NQ_daily", "NQ_hourly")):
            other_items.append(item)

    for lst in (daily_items, hourly_items, other_items):
        lst.sort(key=lambda x: (-x["distinct_runs"], -x["best_score"]))

    return {
        "daily": daily_items[:top_n],
        "hourly": hourly_items[:top_n],
        "other": other_items[:top_n],
        "total_ideas": len(sig_groups),
        "generated_from_records": len(records),
    }


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def query_history(dataset_id=None, family=None, status=None,
                  capped_only=False, last_n_runs=None):
    """Filter and return history records matching criteria.

    Args:
        dataset_id: filter by dataset (e.g., "NQ_daily")
        family: filter by strategy family
        status: filter by status ("PASS", "REJECT")
        capped_only: if True, only return candidates capped by evidence tier
        last_n_runs: if set, only consider the last N distinct runs

    Returns:
        list of matching records.
    """
    records = _load_history()
    if not records:
        return []

    # Apply run filter first
    if last_n_runs:
        seen_runs = []
        seen_set = set()
        for r in records:
            rid = _get_run_id(r)
            if rid not in seen_set:
                seen_runs.append(rid)
                seen_set.add(rid)
        target_runs = set(seen_runs[-last_n_runs:])
        records = [r for r in records if _get_run_id(r) in target_runs]

    if dataset_id:
        records = [r for r in records if _get_dataset_id(r) == dataset_id]

    if family:
        records = [r for r in records if r.get("family") == family]

    if status:
        records = [r for r in records if r.get("status") == status]

    if capped_only:
        records = [r for r in records
                   if "evidence_tier_cap" in str(r.get("stage_reason", ""))]

    return records


def list_runs():
    """List all distinct runs with summary stats.

    Returns list of run summaries, most recent first.
    """
    records = _load_history()
    if not records:
        return []

    run_order = []
    run_set = set()
    for r in records:
        rid = _get_run_id(r)
        if rid not in run_set:
            run_order.append(rid)
            run_set.add(rid)

    summaries = []
    for rid in reversed(run_order):
        run_records = [r for r in records if _get_run_id(r) == rid]
        passed = sum(1 for r in run_records if r.get("status") == "PASS")
        total = len(run_records)
        dataset = _get_dataset_id(run_records[0]) if run_records else "unknown"
        evidence = (run_records[0].get("evidence_tier")
                    or run_records[0].get("evidence", {}).get("evidence_tier", "unknown"))
        scores = [r.get("score", 0) for r in run_records if r.get("status") == "PASS"]
        top_score = round(max(scores), 4) if scores else 0.0

        summaries.append({
            "run_id": rid,
            "dataset_id": dataset,
            "evidence_tier": evidence,
            "total": total,
            "passed": passed,
            "top_score": top_score,
        })

    return summaries


# ---------------------------------------------------------------------------
# Candidate packet export
# ---------------------------------------------------------------------------

def _extract_key_metrics(record):
    """Extract key performance metrics from a history record.

    Pulls from fold results, gate results, or top-level fields.
    Returns only metrics that are present.
    """
    metrics = {}
    for field in ("profit_factor", "sharpe", "sortino", "max_drawdown",
                  "win_rate", "total_trades", "avg_pf"):
        if field in record:
            metrics[field] = record[field]
    # Check nested evidence/gate data
    ev = record.get("evidence", {})
    for field in ("profit_factor", "sharpe", "sortino"):
        if field in ev and field not in metrics:
            metrics[field] = ev[field]
    # Gate overall as a metric
    if "gate_overall" in record:
        metrics["gate_overall"] = record["gate_overall"]
    if "perturbation_robust" in record:
        metrics["perturbation_robust"] = record["perturbation_robust"]
    if "stress_overall" in record:
        metrics["stress_overall"] = record["stress_overall"]
    return metrics


def export_candidate_packets(top_n=5):
    """Export structured candidate packets for downstream review.

    Each packet includes full context for Kitt/Jarvis review with
    a recommended_next_step and key_metrics from history.
    """
    watchlist = generate_watchlist(top_n=top_n * 2)
    records = _load_history()
    packets = []

    # Build a lookup of best history record per signature for extra fields
    sig_best = {}
    for r in records:
        if r.get("status") != "PASS":
            continue
        sig = (r.get("candidate_signature")
               or compute_candidate_signature(r.get("family", ""), r.get("params", {})))
        if sig not in sig_best or r.get("score", 0) > sig_best[sig].get("score", 0):
            sig_best[sig] = r

    seen = set()
    all_items = (watchlist.get("daily", []) + watchlist.get("hourly", [])
                 + watchlist.get("other", []))
    for item in all_items:
        sig = item["signature"]
        if sig in seen:
            continue
        seen.add(sig)

        best_rec = sig_best.get(sig, {})

        # why_it_matters
        matters = []
        if item["distinct_runs"] >= 3:
            matters.append(f"Survived {item['distinct_runs']} runs — consistent performer")
        elif item["distinct_runs"] >= 2:
            matters.append(f"Confirmed across {item['distinct_runs']} runs")
        if len(item["datasets"]) >= 2:
            matters.append(f"Works on {', '.join(item['datasets'])}")
        if item["capped_by_evidence"]:
            matters.append(f"All gates passed but capped by {item['evidence_tier']} data")
        if item["best_score"] >= 0.7:
            matters.append(f"High score ({item['best_score']})")
        if not matters:
            matters.append("Research survivor — monitor")

        # recommended_next_step
        datasets = item["datasets"]
        has_hourly = "NQ_hourly" in datasets
        has_daily = "NQ_daily" in datasets
        has_intraday = any(d for d in datasets
                          if d not in ("NQ_daily", "NQ_hourly", "synthetic"))

        if item["capped_by_evidence"] and item["distinct_runs"] >= 2:
            next_step = "review_for_kitt"
        elif item["capped_by_evidence"]:
            next_step = "blocked_by_evidence"
        elif has_hourly and not has_daily and not has_intraday:
            next_step = "rerun_daily"
        elif has_daily and not has_hourly and not has_intraday:
            next_step = "rerun_hourly"
        elif (has_daily or has_hourly) and not has_intraday:
            next_step = "rerun_intraday"
        elif item["distinct_runs"] >= 2:
            next_step = "monitor"
        else:
            next_step = "monitor"

        ds_ids = item["datasets"]
        packets.append({
            "candidate_signature": sig,
            "candidate_id": best_rec.get("candidate_id"),
            "family": item["family"],
            "params": item["params"],
            "dataset_ids": ds_ids,
            "primary_dataset_id": ds_ids[0] if ds_ids else None,
            "evidence_tier": item["evidence_tier"],
            "fold_profile_used": best_rec.get("fold_profile_used"),
            "gate_profile_used": best_rec.get("gate_profile_used"),
            "stage": item["stage"],
            "stage_reason": item["stage_reason"],
            "capped_by_evidence": item["capped_by_evidence"],
            "best_score": item["best_score"],
            "avg_score": item["avg_score"],
            "appearances": item["appearances"],
            "distinct_runs": item["distinct_runs"],
            "first_seen": item["first_seen"],
            "latest_seen": item["latest_seen"],
            "key_metrics": _extract_key_metrics(best_rec),
            "why_it_matters": " | ".join(matters),
            "recommended_next_step": next_step,
        })

    packets.sort(key=lambda x: (-x["distinct_runs"], -x["best_score"]))
    return packets[:top_n]


# ---------------------------------------------------------------------------
# Watchlist history (durable)
# ---------------------------------------------------------------------------

def append_watchlist_history(watchlist, watchlist_run_id=None):
    """Append current watchlist entries to durable WATCHLIST_HISTORY.jsonl.

    Each entry records:
    - watchlist_run_id: identifies this watchlist generation event
    - latest_seen_run_id: the most recent pipeline run that evaluated
      this candidate
    - dataset_ids: full list of datasets the candidate survived on
    - primary_dataset_id: first dataset (for quick filtering)

    The file accumulates across runs.
    """
    import uuid as _uuid
    from datetime import datetime, timezone
    path = _art_mod.WATCHLIST_HISTORY
    now = datetime.now(timezone.utc).isoformat()

    if watchlist_run_id is None:
        watchlist_run_id = f"wl_{_uuid.uuid4().hex[:12]}"

    entries = []
    for bucket in ("daily", "hourly", "other"):
        for item in watchlist.get(bucket, []):
            ds_ids = item.get("datasets", [])
            entry = {
                "bucket": bucket,
                "generated_at": now,
                "watchlist_run_id": watchlist_run_id,
                "latest_seen_run_id": item.get("latest_seen"),
                "dataset_ids": ds_ids,
                "primary_dataset_id": ds_ids[0] if ds_ids else None,
                **{k: v for k, v in item.items()
                   if k not in ("params", "datasets",
                                "first_seen", "latest_seen")},
            }
            entries.append(entry)

    with open(path, "a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    return entries


# ---------------------------------------------------------------------------
# Query aggregations
# ---------------------------------------------------------------------------

def query_rejection_reasons(dataset_id=None):
    """Tally rejection reasons, optionally filtered by dataset."""
    records = _load_history()
    if dataset_id:
        records = [r for r in records if _get_dataset_id(r) == dataset_id]
    rejected = [r for r in records if r.get("status") != "PASS"]
    return _tally_reasons(rejected)


def query_capped_by_dataset(dataset_id=None):
    """Aggregate capped candidates grouped by dataset.

    Args:
        dataset_id: if set, only return results for this dataset.

    Returns a dict keyed by dataset_id, each with count and top
    candidates.
    """
    records = _load_history()
    capped = [r for r in records
              if "evidence_tier_cap" in str(r.get("stage_reason", ""))
              and r.get("status") == "PASS"]
    if dataset_id:
        capped = [r for r in capped if _get_dataset_id(r) == dataset_id]
    if not capped:
        return {}

    by_dataset = defaultdict(list)
    for r in capped:
        by_dataset[_get_dataset_id(r)].append(r)

    result = {}
    for did, recs in sorted(by_dataset.items()):
        sig_groups = defaultdict(list)
        for r in recs:
            sig = (r.get("candidate_signature")
                   or compute_candidate_signature(r.get("family", ""), r.get("params", {})))
            sig_groups[sig].append(r)

        top = []
        for sig, apps in sig_groups.items():
            best = max(apps, key=lambda r: r.get("score", 0))
            top.append({
                "signature": sig,
                "family": best.get("family"),
                "appearances": len(apps),
                "best_score": round(max(r.get("score", 0) for r in apps), 4),
                "evidence_tier": (best.get("evidence_tier")
                                  or best.get("evidence", {}).get("evidence_tier")),
            })
        top.sort(key=lambda x: (-x["appearances"], -x["best_score"]))

        result[did] = {"count": len(recs), "unique_signatures": len(sig_groups),
                       "top": top[:5]}
    return result


def query_top_survivors(dataset_id=None, family=None, top_n=10):
    """Return top PASS candidates aggregated by signature.

    Unlike best_ideas (which is cross-dataset), this focuses on a
    single dataset and/or family and returns richer per-signature detail.
    """
    records = _load_history()
    passed = [r for r in records if r.get("status") == "PASS"]
    if dataset_id:
        passed = [r for r in passed if _get_dataset_id(r) == dataset_id]
    if family:
        passed = [r for r in passed if r.get("family") == family]
    if not passed:
        return []

    sig_groups = defaultdict(list)
    for r in passed:
        sig = (r.get("candidate_signature")
               or compute_candidate_signature(r.get("family", ""), r.get("params", {})))
        sig_groups[sig].append(r)

    survivors = []
    for sig, apps in sig_groups.items():
        best = max(apps, key=lambda r: r.get("score", 0))
        scores = [r.get("score", 0) for r in apps]
        run_ids = sorted(set(_get_run_id(r) for r in apps))
        capped = "evidence_tier_cap" in str(best.get("stage_reason", ""))
        survivors.append({
            "signature": sig,
            "family": best.get("family"),
            "appearances": len(apps),
            "distinct_runs": len(run_ids),
            "best_score": round(max(scores), 4),
            "avg_score": round(sum(scores) / len(scores), 4),
            "stage": best.get("stage"),
            "capped_by_evidence": capped,
            "evidence_tier": (best.get("evidence_tier")
                              or best.get("evidence", {}).get("evidence_tier")),
        })

    survivors.sort(key=lambda x: (-x["distinct_runs"], -x["best_score"]))
    return survivors[:top_n]


def query_repeated_signatures(family=None, min_appearances=2):
    """Find signatures that appear multiple times as PASS.

    Returns list of (signature, family, appearances, best_score, datasets).
    """
    records = _load_history()
    passed = [r for r in records if r.get("status") == "PASS"]
    if family:
        passed = [r for r in passed if r.get("family") == family]

    sig_groups = defaultdict(list)
    for r in passed:
        sig = (r.get("candidate_signature")
               or compute_candidate_signature(r.get("family", ""), r.get("params", {})))
        sig_groups[sig].append(r)

    results = []
    for sig, apps in sig_groups.items():
        if len(apps) < min_appearances:
            continue
        best = max(apps, key=lambda r: r.get("score", 0))
        datasets = sorted(set(_get_dataset_id(r) for r in apps))
        results.append({
            "signature": sig,
            "family": best.get("family"),
            "appearances": len(apps),
            "best_score": round(max(r.get("score", 0) for r in apps), 4),
            "datasets": datasets,
        })

    results.sort(key=lambda x: (-x["appearances"], -x["best_score"]))
    return results


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------

def generate_review_queue(top_n=5):
    """Generate a prioritized review queue for operator/Kitt/Jarvis.

    Organises output by dataset lane (daily / hourly / other) so that
    daily-research and hourly-exploratory candidates are never mixed
    into one leaderboard.  Within each lane, entries are split into
    ``review_now`` and ``monitor_only``.

    Items in review_now are candidates that:
    - appear in 2+ runs, OR
    - are capped by evidence with best_score >= 0.7

    Everything else goes to monitor_only.

    Returns:
        dict with per-lane queues and metadata.
    """
    ideas = best_ideas(min_appearances=1, top_n=top_n * 8)
    if not ideas:
        return {"lanes": {}, "review_now": [], "monitor_only": [], "total": 0}

    # Build entries with priority
    all_entries = []
    for idea in ideas:
        capped = "evidence_tier_cap" in str(idea.get("stage_reason", ""))

        # Generate reason
        reasons = []
        if idea["distinct_runs"] >= 3:
            reasons.append("recurring survivor")
        elif idea["distinct_runs"] >= 2:
            reasons.append("confirmed across runs")
        if idea["best_score"] >= 0.7:
            reasons.append("high score")
        if capped:
            reasons.append(f"capped by {idea['evidence_tier']} evidence")
        if not reasons:
            reasons.append("single-run survivor")

        is_review = (idea["distinct_runs"] >= 2
                     or (capped and idea["best_score"] >= 0.7))

        entry = {
            "signature": idea["signature"],
            "family": idea["family"],
            "params": idea.get("params"),
            "best_score": idea["best_score"],
            "avg_score": idea["avg_score"],
            "appearances": idea["appearances"],
            "distinct_runs": idea["distinct_runs"],
            "dataset_ids": idea["distinct_datasets"],
            "primary_dataset_id": (idea["distinct_datasets"][0]
                                   if idea["distinct_datasets"] else None),
            "stage": idea["best_stage"],
            "evidence_tier": idea["evidence_tier"],
            "fold_profile_used": idea.get("fold_profile_used"),
            "gate_profile_used": idea.get("gate_profile_used"),
            "capped_by_evidence": capped,
            "promotion_eligible": idea["promotion_eligible"],
            "reason": "; ".join(reasons),
            "priority": "review" if is_review else "monitor",
        }
        all_entries.append(entry)

    # Route to dataset lanes
    lanes = defaultdict(lambda: {"review_now": [], "monitor_only": []})
    for entry in all_entries:
        ds_ids = entry["dataset_ids"]
        if not ds_ids:
            ds_ids = ["other"]
        for did in ds_ids:
            if did in ("NQ_daily",):
                lane = "daily"
            elif did in ("NQ_hourly",):
                lane = "hourly"
            else:
                lane = "other"
            bucket = "review_now" if entry["priority"] == "review" else "monitor_only"
            if entry not in lanes[lane][bucket]:
                lanes[lane][bucket].append(entry)

    # Cap per lane
    for lane in lanes.values():
        lane["review_now"] = lane["review_now"][:top_n]
        lane["monitor_only"] = lane["monitor_only"][:top_n]

    # Flat compat lists (union across lanes, capped)
    flat_review = [e for e in all_entries if e["priority"] == "review"][:top_n]
    flat_monitor = [e for e in all_entries if e["priority"] == "monitor"][:top_n]

    return {
        "lanes": dict(lanes),
        "review_now": flat_review,
        "monitor_only": flat_monitor,
        "total": len(all_entries),
    }
