"""Forward validation analysis and weekly report generation.

Owns:
    - forward_validation.json construction (cross-family analysis)
    - weekly_report.md construction (human-readable operator report)
    - history snapshot helper for delta detection
"""

from datetime import datetime, timezone

from .analysis import (
    best_ideas, _load_history, _get_run_id, _get_dataset_id,
    compute_candidate_signature,
)


# ---------------------------------------------------------------------------
# Idea classification
# ---------------------------------------------------------------------------

def _classify_idea(idea, degraded_sigs):
    """Return a classification label for an idea.

    Labels (mutually exclusive, first match wins):
      - sample_size_illusion: appeared in only 1 run — may not replicate
      - evidence_capped: multi-run survivor but stuck at research tier
      - structural_improvement: multi-run survivor eligible for promotion
    """
    if idea.get("appearances", 0) < 2 or idea.get("distinct_runs", 0) < 2:
        return "sample_size_illusion"
    if not idea.get("promotion_eligible", False):
        return "evidence_capped"
    return "structural_improvement"


def _family_is_honest_failure(fam_summary):
    """True if a family was evaluated but produced zero passes."""
    if fam_summary.get("status") == "no_records":
        return False
    return fam_summary.get("evaluated", 0) > 0 and fam_summary.get("passed", 0) == 0


# ---------------------------------------------------------------------------
# Forward validation analysis
# ---------------------------------------------------------------------------

def build_forward_validation(cycle_id, run_ids, art_dir, n_candidates):
    """Build the forward_validation.json artifact.

    Answers all required questions using candidate history.
    """
    records = _load_history()

    # Partition this cycle's records
    rid_set = set(run_ids) if run_ids else set()
    cycle_records = [r for r in records if _get_run_id(r) in rid_set]

    daily_ema = [r for r in cycle_records
                 if r.get("family") == "ema_crossover"
                 and _get_dataset_id(r) == "NQ_daily"]
    daily_cd = [r for r in cycle_records
                if r.get("family") == "ema_crossover_cd"
                and _get_dataset_id(r) == "NQ_daily"]
    daily_brk = [r for r in cycle_records
                 if r.get("family") == "breakout"
                 and _get_dataset_id(r) == "NQ_daily"]
    hourly_all = [r for r in cycle_records
                  if _get_dataset_id(r) == "NQ_hourly"]

    def _family_summary(recs, label):
        if not recs:
            return {"label": label, "status": "no_records"}
        passed = [r for r in recs if r.get("status") == "PASS"]
        rejected = [r for r in recs if r.get("status") != "PASS"]
        scores = sorted([r.get("score", 0) for r in passed], reverse=True)
        reject_reasons = {}
        for r in rejected:
            reason = r.get("reject_reason") or r.get("stage_reason") or "unknown"
            reject_reasons[reason] = reject_reasons.get(reason, 0) + 1
        return {
            "label": label,
            "evaluated": len(recs),
            "passed": len(passed),
            "rejected": len(rejected),
            "top_score": round(scores[0], 4) if scores else 0.0,
            "median_score": round(scores[len(scores)//2], 4) if scores else 0.0,
            "top_5_scores": [round(s, 4) for s in scores[:5]],
            "rejection_reasons": reject_reasons,
        }

    ema_summary = _family_summary(daily_ema, "ema_crossover_daily")
    cd_summary = _family_summary(daily_cd, "ema_crossover_cd_daily")
    brk_summary = _family_summary(daily_brk, "breakout_daily")
    hourly_summary = _family_summary(hourly_all, "hourly_all_families")

    # --- Q1: Did cd outperform baseline? ---
    cd_vs_ema = "insufficient_data"
    if ema_summary.get("top_score", 0) > 0 and cd_summary.get("top_score", 0) > 0:
        if cd_summary["top_score"] > ema_summary["top_score"]:
            cd_vs_ema = "cd_higher_top_score"
        elif cd_summary.get("median_score", 0) > ema_summary.get("median_score", 0):
            cd_vs_ema = "cd_higher_median"
        else:
            cd_vs_ema = "baseline_higher"

    # --- Q2: Cooldown-help regime ---
    cooldown_regime_present = "unknown"
    if cd_summary.get("median_score", 0) > ema_summary.get("median_score", 0):
        cooldown_regime_present = "likely_yes"
    elif cd_summary.get("top_score", 0) > 0:
        cooldown_regime_present = "likely_no"

    # --- Q3: Breakout unique fold coverage ---
    brk_coverage = "unknown"
    if brk_summary.get("passed", 0) > 0:
        brk_coverage = "breakout_has_survivors"
    elif brk_summary.get("evaluated", 0) > 0:
        brk_coverage = "breakout_all_fail"
    else:
        brk_coverage = "no_breakout_data"

    # --- Q4: Hourly depth ---
    hourly_status = "no_data"
    if hourly_summary.get("evaluated", 0) > 0:
        if hourly_summary.get("top_score", 0) > 0.5:
            hourly_status = "showing_signal"
        else:
            hourly_status = "still_shallow"

    # --- Q5/Q6: Priority and monitor recommendations ---
    priority_family = "ema_crossover"
    monitor_family = "breakout"
    if cd_summary.get("median_score", 0) > ema_summary.get("median_score", 0):
        priority_family = "ema_crossover_cd"
        monitor_family = "ema_crossover"

    # --- Build per-signature lookup of this cycle's scores ---
    cycle_sig_scores = {}
    for r in cycle_records:
        if r.get("status") != "PASS":
            continue
        sig = (r.get("candidate_signature")
               or compute_candidate_signature(
                   r.get("family", ""), r.get("params", {})))
        cycle_sig_scores.setdefault(sig, []).append(r.get("score", 0))

    # --- Q7: New shortlist entries ---
    ideas = best_ideas(min_appearances=1, top_n=20)
    new_this_cycle = [idea for idea in ideas
                      if idea.get("appearances", 0) == 1
                      and idea["signature"] in cycle_sig_scores]

    # --- Q8: Degraded prior ideas ---
    degraded_ideas = []
    for idea in ideas:
        if idea.get("appearances", 0) < 2:
            continue
        sig = idea["signature"]
        if sig not in cycle_sig_scores:
            continue
        cycle_best = max(cycle_sig_scores[sig])
        hist_avg = idea.get("avg_score", 0)
        if hist_avg > 0 and cycle_best < hist_avg * 0.85:
            degraded_ideas.append({
                "signature": sig,
                "family": idea["family"],
                "this_cycle_score": round(cycle_best, 4),
                "historical_avg": hist_avg,
                "drop_pct": round((1 - cycle_best / hist_avg) * 100, 1),
            })

    degraded_sigs = {d["signature"] for d in degraded_ideas}

    # --- Classify ideas ---
    classified_top_5 = []
    for i in ideas[:5]:
        classified_top_5.append({
            "signature": i["signature"],
            "family": i["family"],
            "appearances": i["appearances"],
            "distinct_runs": i["distinct_runs"],
            "best_score": i["best_score"],
            "classification": _classify_idea(i, degraded_sigs),
        })

    # --- Honest failures (families evaluated but zero passes) ---
    families_summary = {
        "ema_crossover_daily": ema_summary,
        "ema_crossover_cd_daily": cd_summary,
        "breakout_daily": brk_summary,
        "hourly_all": hourly_summary,
    }
    honest_failures = [k for k, v in families_summary.items()
                       if _family_is_honest_failure(v)]

    # --- Drop family: family that is an honest failure this cycle ---
    drop_family = honest_failures[0] if honest_failures else None

    # --- Strongest / weakest dataset ---
    dataset_scores = {}
    for key, summ in families_summary.items():
        ds = "NQ_hourly" if key == "hourly_all" else "NQ_daily"
        score = summ.get("top_score", 0) if summ.get("status") != "no_records" else 0
        dataset_scores.setdefault(ds, []).append(score)
    dataset_best = {ds: max(scores) for ds, scores in dataset_scores.items()}
    strongest_dataset = max(dataset_best, key=dataset_best.get) if dataset_best else None
    weakest_dataset = min(dataset_best, key=dataset_best.get) if dataset_best else None
    # If all tied, weakest == strongest is fine — signals no differentiation

    # --- Notable change ---
    if degraded_ideas:
        worst = max(degraded_ideas, key=lambda d: d["drop_pct"])
        notable_change = (f"degraded: {worst['signature'][:16]} "
                          f"dropped {worst['drop_pct']}%")
    elif new_this_cycle:
        notable_change = f"{len(new_this_cycle)} new shortlist entries"
    else:
        notable_change = "stable"

    # --- Review-worthy: multi-run survivor with best_score >= 0.5 ---
    review_worthy_now = any(
        i.get("appearances", 0) >= 2
        and i.get("distinct_runs", 0) >= 2
        and i.get("best_score", 0) >= 0.5
        for i in ideas
    )

    # --- Build summary block ---
    summary = {
        "priority_family": priority_family,
        "monitor_family": monitor_family,
        "drop_family": drop_family,
        "review_worthy_now": review_worthy_now,
        "strongest_dataset": strongest_dataset,
        "weakest_dataset": weakest_dataset,
        "notable_change": notable_change,
        "degraded_count": len(degraded_ideas),
        "honest_failures": honest_failures,
    }

    return {
        "cycle_id": cycle_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_candidates_per_family": n_candidates,
        "run_ids": sorted(rid_set),
        "summary": summary,
        "families_run": families_summary,
        "questions": {
            "cd_vs_baseline": cd_vs_ema,
            "cooldown_regime_present": cooldown_regime_present,
            "breakout_coverage": brk_coverage,
            "hourly_status": hourly_status,
            "priority_family": priority_family,
            "monitor_family": monitor_family,
            "new_shortlist_entries": len(new_this_cycle),
            "new_entry_signatures": [i["signature"] for i in new_this_cycle[:5]],
            "degraded_prior_ideas": degraded_ideas,
        },
        "shortlist_snapshot": {
            "total_ideas": len(ideas),
            "top_5": classified_top_5,
        },
    }


# ---------------------------------------------------------------------------
# Weekly report (human-readable)
# ---------------------------------------------------------------------------

def build_weekly_report(fv, art_dir):
    """Build a human-readable weekly operator report."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    q = fv["questions"]
    fam = fv["families_run"]
    summary = fv["summary"]

    lines = [
        f"# Weekly Research Report — {ts}",
        "",
        f"Cycle: {fv['cycle_id']}",
        f"Candidates per family: {fv['n_candidates_per_family']}",
        f"Runs: {', '.join(fv['run_ids'])}",
        "",
    ]

    # --- Decision Summary (new, near the top) ---
    lines += [
        "## Decision Summary",
        "",
    ]
    if summary["review_worthy_now"]:
        lines.append("**Review-worthy candidates exist.** Check Top Ideas below.")
    else:
        lines.append("**Nothing is review-worthy right now.** "
                      "No multi-run survivor with score >= 0.5.")
    lines.append("")
    lines.append(f"- **Priority this week**: {summary['priority_family']}")
    lines.append(f"- **Monitor only**: {summary['monitor_family']}")
    if summary["drop_family"]:
        lines.append(f"- **Drop / deprioritize**: {summary['drop_family']}")
    else:
        lines.append("- **Drop / deprioritize**: none")
    lines.append(f"- **Strongest dataset**: {summary['strongest_dataset']}")
    lines.append(f"- **Weakest dataset**: {summary['weakest_dataset']}")
    lines.append(f"- **Notable change**: {summary['notable_change']}")
    lines.append("")

    if summary["honest_failures"]:
        lines.append("### Honest Failures")
        lines.append("")
        for hf in summary["honest_failures"]:
            f_summ = fam.get(hf, {})
            lines.append(f"- **{hf}**: {f_summ.get('evaluated', 0)} evaluated, "
                          f"0 passed — all candidates failed gates")
        lines.append("")

    # --- Family Results ---
    lines += [
        "## Family Results",
        "",
        "| family | evaluated | passed | rejected | top score | median |",
        "|--------|-----------|--------|----------|-----------|--------|",
    ]
    for key in ["ema_crossover_daily", "ema_crossover_cd_daily",
                "breakout_daily", "hourly_all"]:
        f = fam.get(key, {})
        if f.get("status") == "no_records":
            lines.append(f"| {key} | — | — | — | — | — |")
        else:
            lines.append(
                f"| {key} | {f.get('evaluated',0)} | {f.get('passed',0)} "
                f"| {f.get('rejected',0)} | {f.get('top_score',0):.4f} "
                f"| {f.get('median_score',0):.4f} |")

    lines += [
        "",
        "## Forward Validation Questions",
        "",
        f"- **cd vs baseline**: {q['cd_vs_baseline']}",
        f"- **cooldown regime present**: {q['cooldown_regime_present']}",
        f"- **breakout coverage**: {q['breakout_coverage']}",
        f"- **hourly status**: {q['hourly_status']}",
        f"- **priority family**: {q['priority_family']}",
        f"- **monitor family**: {q['monitor_family']}",
        f"- **new shortlist entries**: {q['new_shortlist_entries']}",
    ]

    degraded = q.get("degraded_prior_ideas", [])
    if degraded:
        lines.append("")
        lines.append("### Degraded Prior Ideas")
        lines.append("")
        for d in degraded[:5]:
            lines.append(
                f"- `{d['signature']}` ({d['family']}) — "
                f"dropped {d['drop_pct']}% "
                f"(this cycle: {d['this_cycle_score']:.4f}, "
                f"hist avg: {d['historical_avg']:.4f})")
    else:
        lines.append(f"- **degraded prior ideas**: none detected")

    # --- Top Ideas with classification ---
    lines += [
        "",
        "## Top Ideas",
        "",
        "| sig | family | appearances | runs | best_score | classification |",
        "|-----|--------|-------------|------|------------|----------------|",
    ]
    for idea in fv["shortlist_snapshot"]["top_5"]:
        cls = idea.get("classification", "unknown")
        lines.append(
            f"| {idea['signature'][:16]} | {idea['family']} "
            f"| {idea['appearances']} | {idea['distinct_runs']} "
            f"| {idea['best_score']:.4f} | {cls} |")

    if not fv["shortlist_snapshot"]["top_5"]:
        lines.append("| — | — | — | — | — | — |")

    # --- Classification legend ---
    lines += [
        "",
        "**Classification key:**",
        "- `structural_improvement` — multi-run survivor, eligible for promotion",
        "- `evidence_capped` — multi-run survivor, stuck at research tier",
        "- `sample_size_illusion` — single-run only, may not replicate",
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Operator packet
# ---------------------------------------------------------------------------

def build_operator_packet(fv, art_dir):
    """Build operator_packet.json — compact handoff for Jarvis/Kitt/Discord.

    Derives everything from the forward_validation dict so no extra
    history loads are needed.
    """
    summary = fv["summary"]
    snapshot = fv["shortlist_snapshot"]

    # --- top_ideas: max 3 ---
    top_ideas = []
    for idea in snapshot["top_5"][:3]:
        top_ideas.append({
            "signature": idea["signature"],
            "family": idea["family"],
            "best_score": idea["best_score"],
            "appearances": idea["appearances"],
            "distinct_runs": idea["distinct_runs"],
            "classification": idea["classification"],
        })

    # --- operator_status ---
    if summary["review_worthy_now"]:
        operator_status = "review"
    elif snapshot["total_ideas"] > 0:
        operator_status = "monitor"
    else:
        operator_status = "hold"

    # --- action_recommendation ---
    if operator_status == "review":
        action_recommendation = (
            f"Review {summary['priority_family']} candidates this week."
        )
    elif operator_status == "hold":
        action_recommendation = (
            "No candidate is review-worthy. "
            "Cycle produced mostly failures. Hold until next run."
        )
    else:
        action_recommendation = (
            "No candidate is review-worthy. Continue weekly monitoring."
        )

    if summary["drop_family"]:
        action_recommendation += (
            f" Deprioritize {summary['drop_family']} until conditions improve."
        )

    # --- supporting_artifacts (relative filenames) ---
    supporting_artifacts = {
        "forward_validation": "forward_validation.json",
        "weekly_report": "weekly_report.md",
        "watchlist": "watchlist.json",
        "review_queue": "review_queue.json",
        "candidate_packets": "candidate_packets.json",
    }

    return {
        "cycle_id": fv["cycle_id"],
        "generated_at": fv["generated_at"],
        "priority_family": summary["priority_family"],
        "monitor_family": summary["monitor_family"],
        "drop_family": summary["drop_family"],
        "review_worthy_now": summary["review_worthy_now"],
        "strongest_dataset": summary["strongest_dataset"],
        "weakest_dataset": summary["weakest_dataset"],
        "notable_change": summary["notable_change"],
        "degraded_count": summary["degraded_count"],
        "honest_failures": summary["honest_failures"],
        "top_ideas": top_ideas,
        "action_recommendation": action_recommendation,
        "operator_status": operator_status,
        "supporting_artifacts": supporting_artifacts,
    }


# ---------------------------------------------------------------------------
# Snapshot helper
# ---------------------------------------------------------------------------

def history_snapshot():
    """Capture current run IDs and record count for delta detection."""
    records = _load_history()
    run_ids = set(_get_run_id(r) for r in records)
    return {"count": len(records), "run_ids": run_ids}
