import argparse

from .config import (
    DEFAULT_CONFIG, classify_evidence, select_fold_profile, select_gate_profile,
    check_family_compat,
)
from .analysis import compute_candidate_signature, _get_dataset_id
from .artifacts import (
    ensure_artifact_dir,
    write_candidate_result,
    write_candidate_history,
    write_fold_metrics,
    write_provenance_linkage,
    write_summary,
    write_json,
    append_to_strategy_registry,
)
from .data import (
    generate_synthetic_data, load_ohlcv, load_dataset_metadata,
    load_named_dataset, list_datasets, has_real_data,
)
from .features import compute_max_feature_lookback, compute_features
from .folds import build_folds, validate_purge_gap
from .sim import run_candidate_simulation
from .gates import evaluate_fold_gates, evaluate_all_folds
from .perturbation import run_perturbation_test
from .scoring import compute_score
from .stress import stress_check
from .diversity import compute_fingerprint
from .candidate_gen import generate_candidates, generate_default_candidate, FAMILY_TIMEFRAME
from .optimizer import optimize_params


def _load_data(args):
    """Load data by named dataset, explicit path, or auto-resolve.

    Priority:
        1. --dataset NQ_daily (named dataset with sidecar)
        2. --data-path /explicit/path.csv
        3. auto-resolve NQ_1min.csv (legacy)
        4. --synthetic fallback

    Returns:
        (data, data_meta) where data_meta includes all evidence fields
        plus dataset_id and granularity_source.
    """
    instrument = DEFAULT_CONFIG.get("instrument", "NQ")
    dataset_id = getattr(args, "dataset", None)
    data_path = getattr(args, "data_path", None)
    use_synthetic = getattr(args, "synthetic", False)

    if not use_synthetic:
        # --- Named dataset (preferred) ---
        if dataset_id:
            try:
                data, meta = load_named_dataset(dataset_id)
                return _build_evidence(data, meta, dataset_id)
            except FileNotFoundError:
                print(f"  WARNING: dataset '{dataset_id}' not found, falling back")

        # --- Explicit path ---
        if data_path:
            try:
                data = load_ohlcv(path=data_path)
                meta = load_dataset_metadata(path=data_path)
                return _build_evidence(data, meta, data_path)
            except FileNotFoundError:
                pass

        # --- Auto-resolve legacy canonical ---
        try:
            data = load_ohlcv(instrument=instrument)
            meta = load_dataset_metadata(instrument=instrument)
            return _build_evidence(data, meta, "auto")
        except FileNotFoundError:
            pass

    data = generate_synthetic_data()
    evidence = classify_evidence("synthetic", "synthetic")
    evidence.update({
        "data_source": "synthetic",
        "data_granularity": "synthetic",
        "granularity_source": "synthetic",
        "dataset_id": "synthetic",
    })
    print(f"  data: SYNTHETIC ({len(data)} bars)")
    print(f"  evidence: {evidence['evidence_tier']}"
          f"  promotion_eligible={evidence['promotion_eligible']}")
    return data, evidence


def _build_evidence(data, meta, dataset_id):
    """Build evidence dict from loaded data and its sidecar metadata."""
    if meta and "data_granularity" in meta:
        granularity = meta["data_granularity"]
        gran_source = "metadata"
    else:
        if len(data) > 20000:
            granularity = "1min_bar"
        elif len(data) > 8000:
            granularity = "1h"
        else:
            granularity = "daily"
        gran_source = "heuristic"

    evidence = classify_evidence("real", granularity)
    evidence.update({
        "data_source": "real",
        "data_granularity": granularity,
        "granularity_source": gran_source,
        "dataset_id": str(dataset_id),
    })
    if meta:
        evidence["dataset_meta"] = {
            "instrument": meta.get("instrument"),
            "source_provider": meta.get("source_provider"),
            "coverage_start": meta.get("coverage_start"),
            "coverage_end": meta.get("coverage_end"),
            "row_count": meta.get("row_count"),
        }
    print(f"  data: REAL ({len(data)} bars from {dataset_id})")
    print(f"  granularity: {granularity} (from {gran_source})")
    print(f"  evidence: {evidence['evidence_tier']}"
          f"  promotion_eligible={evidence['promotion_eligible']}")
    return data, evidence


def _run(args):
    import uuid as _uuid

    data, data_meta = _load_data(args)
    data_source = data_meta["data_source"]
    evidence_tier = data_meta["evidence_tier"]
    data_granularity = data_meta["data_granularity"]
    run_id = f"run_{_uuid.uuid4().hex[:12]}"

    # --- Metadata-driven fold profile selection ---
    if args.sentinel:
        from copy import deepcopy
        fold_spec = deepcopy(DEFAULT_CONFIG["fold_spec"])
        fold_profile_name = "sentinel"
    else:
        fold_spec, fold_profile_name = select_fold_profile(evidence_tier)
    print(f"  fold_profile: {fold_profile_name}")

    max_lb = compute_max_feature_lookback(DEFAULT_CONFIG["features"])
    validate_purge_gap(fold_spec["purge_len"], max_lb, sentinel_mode=args.sentinel)
    folds = build_folds(len(data), fold_spec, max_lb, sentinel_mode=args.sentinel)

    # --- Metadata-driven gate profile selection ---
    gate_profile, gate_profile_name = select_gate_profile(evidence_tier)
    print(f"  gate_profile: {gate_profile_name}")

    # Build run config with fold-spec overrides
    run_config = dict(DEFAULT_CONFIG)
    if "minimum_any_fold_trades" in fold_spec:
        run_config["minimum_any_fold_trades"] = fold_spec["minimum_any_fold_trades"]

    # Evidence classification — immutable for this run
    evidence = {
        "data_source": data_meta["data_source"],
        "data_granularity": data_meta["data_granularity"],
        "granularity_source": data_meta.get("granularity_source", "unknown"),
        "source_class": data_meta["source_class"],
        "evidence_tier": data_meta["evidence_tier"],
        "promotion_eligible": data_meta["promotion_eligible"],
        "max_stage": data_meta["max_stage"],
        "fold_profile_used": fold_profile_name,
        "gate_profile_used": gate_profile_name,
        "dataset_id": data_meta.get("dataset_id", "unknown"),
        "run_id": run_id,
    }

    # Generate candidates — filter by family/dataset compatibility
    if args.family:
        families = [args.family]
    else:
        families = ["ema_crossover", "ema_crossover_cd", "mean_reversion", "breakout"]

    # Check compatibility and filter
    compatible_families = []
    skipped_families = []
    for fam in families:
        ok, reason = check_family_compat(fam, data_granularity)
        if ok:
            compatible_families.append(fam)
        else:
            skipped_families.append({"family": fam, "reason": reason})
            print(f"  SKIP: {fam} — {reason}")

    if not compatible_families:
        print("  ERROR: no compatible families for this dataset")
        return

    n_per = int(args.n_candidates) if args.n_candidates else 3
    candidates = generate_candidates(families=compatible_families, n_per_family=n_per, seed=42)

    for fam in compatible_families:
        candidates.append(generate_default_candidate(fam))

    art_dir = ensure_artifact_dir()
    all_results = []

    # Per-fold refit is ON by default (true walk-forward).
    # Sentinel mode disables refit (test scaffolding).
    use_refit = not args.sentinel

    for ci, candidate in enumerate(candidates):
        family_id = candidate["logic_family_id"]

        # --- WALK-FORWARD: per-fold train→optimise→OOS in sim ---
        result = run_candidate_simulation(
            candidate, data, folds, run_config, refit=use_refit,
        )

        gate_results = {}
        all_fold_gates = {}
        tf_bucket = FAMILY_TIMEFRAME.get(family_id, run_config["timeframe_bucket"])
        if result["fold_results"]:
            gate_results = evaluate_fold_gates(
                result["fold_results"][0], tf_bucket,
                gate_profile=gate_profile,
            )
            all_fold_gates = evaluate_all_folds(
                result["fold_results"], tf_bucket,
                gate_profile=gate_profile,
            )

        # Perturbation (only for candidates that passed sim)
        perturbation_report = {"status": "SKIP", "robust": False}
        if result["status"] == "PASS":
            perturbation_report = run_perturbation_test(
                candidate, data, folds, run_config,
                sim_fn=run_candidate_simulation,
                n_trials=5, jitter_pct=0.10, seed=42,
            )

        # Stress
        stress_report = {"status": "SKIP", "overall": "FAIL"}
        if result["status"] == "PASS":
            stress_report = stress_check(
                candidate, data, folds, run_config,
                sim_fn=run_candidate_simulation,
            )

        # Scoring
        score_result = compute_score(
            result.get("fold_results", []), run_config,
            perturbation_report=perturbation_report,
            stress_report=stress_report,
        )

        fingerprint = compute_fingerprint(result.get("fold_results", []))

        all_results.append({
            "candidate": candidate,
            "result": result,
            "gate_results": gate_results,
            "all_fold_gates": all_fold_gates,
            "perturbation": perturbation_report,
            "stress": stress_report,
            "score": score_result,
            "fingerprint": fingerprint,
        })

    # Rank by score
    all_results.sort(key=lambda r: r["score"].get("score", 0), reverse=True)

    # --- Compute stage for EVERY candidate ---
    max_stage = evidence["max_stage"]
    batch_summary = []
    history_entries = []

    for rank, entry in enumerate(all_results):
        cid = entry["candidate"]["candidate_id"]
        result = entry["result"]
        score_result = entry["score"]
        agg = entry["all_fold_gates"].get("aggregate", {})

        gate_pass = agg.get("overall") == "PASS"
        robust = entry["perturbation"].get("robust", False)
        stress_pass = entry["stress"].get("overall") == "PASS"

        # Stage determination (same logic, per candidate)
        if result["status"] == "PASS" and gate_pass and robust and stress_pass:
            stage = "BACKTESTED" if max_stage == "BACKTESTED" else "CANDIDATE"
            if max_stage != "BACKTESTED":
                stage_reason = f"evidence_tier_cap:{evidence['evidence_tier']}"
            else:
                stage_reason = "all_gates_passed"
        elif result["status"] == "PASS":
            stage = "CANDIDATE"
            reasons = []
            if not gate_pass:
                reasons.append("gate_fail")
            if not robust:
                reasons.append("perturbation_fail")
            if not stress_pass:
                reasons.append("stress_fail")
            stage_reason = ",".join(reasons) if reasons else "partial_pass"
        else:
            stage = "REJECTED"
            stage_reason = result.get("reject_reason", "unknown")

        batch_summary.append({
            "rank": rank + 1,
            "candidate_id": cid,
            "family": entry["candidate"]["logic_family_id"],
            "status": result["status"],
            "reject_reason": result.get("reject_reason"),
            "stage": stage,
            "stage_reason": stage_reason,
            "score": score_result.get("score", 0),
            "gate_overall": agg.get("overall"),
            "avg_pf": score_result.get("averages", {}).get("avg_pf"),
            "perturbation_robust": robust,
            "stress_overall": entry["stress"].get("overall"),
            "evidence_tier": evidence["evidence_tier"],
            "promotion_eligible": evidence["promotion_eligible"],
        })

        family_id_h = entry["candidate"]["logic_family_id"]
        params_h = entry["candidate"]["params"]
        history_entries.append({
            "run_id": run_id,
            "dataset_id": evidence.get("dataset_id", "unknown"),
            "candidate_id": cid,
            "candidate_signature": compute_candidate_signature(family_id_h, params_h),
            "family": family_id_h,
            "params": params_h,
            "status": result["status"],
            "reject_reason": result.get("reject_reason"),
            "stage": stage,
            "stage_reason": stage_reason,
            "score": score_result.get("score", 0),
            "gate_overall": agg.get("overall"),
            "evidence_tier": evidence["evidence_tier"],
            "fold_profile_used": fold_profile_name,
            "gate_profile_used": gate_profile_name,
            "perturbation_robust": robust,
            "stress_overall": entry["stress"].get("overall"),
        })

    # Write batch results
    write_json(art_dir / "batch_results.json", batch_summary)

    # Write durable history for ALL candidates
    write_candidate_history(art_dir, history_entries, evidence)

    # Write top candidate artifacts in detail
    if all_results:
        best = all_results[0]
        result = best["result"]
        best_stage = batch_summary[0]["stage"]
        best_stage_reason = batch_summary[0]["stage_reason"]

        write_summary(art_dir, {
            "command": "run",
            "candidate_id": result["candidate_id"],
            "family": best["candidate"]["logic_family_id"],
            "params": best["candidate"]["params"],
            "fold_count": len(folds),
            "status": result["status"],
            "reject_reason": result.get("reject_reason"),
            "stage": best_stage,
            "stage_reason": best_stage_reason,
            "gate_overall": best["all_fold_gates"].get("aggregate", {}).get("overall"),
            "score": best["score"].get("score"),
            "perturbation_robust": best["perturbation"].get("robust"),
            "stress_overall": best["stress"].get("overall"),
            "sentinel": args.sentinel,
            "total_candidates": len(candidates),
            "refit": use_refit,
            **evidence,
        })

        write_candidate_result(art_dir, result, best["gate_results"])
        write_fold_metrics(art_dir, result.get("fold_results", []))
        write_json(art_dir / "gate_results.json", best["all_fold_gates"])
        write_json(art_dir / "perturbation_report.json", best["perturbation"])
        write_json(art_dir / "stress_results.json", best["stress"])
        write_json(art_dir / "score.json", best["score"])
        write_json(art_dir / "diversity_fingerprint.json", {
            "candidate_id": result["candidate_id"],
            "fingerprint": best["fingerprint"],
            "dimensions": 34,
        })

        write_provenance_linkage(
            art_dir,
            candidate_id=result["candidate_id"],
            status=result["status"],
            gate_overall=best["all_fold_gates"].get("aggregate", {}).get("overall"),
            fold_count=len(folds),
            reject_reason=result.get("reject_reason"),
            evidence=evidence,
        )

        # Append winner to STRATEGIES.jsonl (non-rejected only)
        if best_stage != "REJECTED":
            agg = best["all_fold_gates"].get("aggregate", {})
            append_to_strategy_registry(
                candidate_id=result["candidate_id"],
                logic_family_id=best["candidate"]["logic_family_id"],
                params=best["candidate"]["params"],
                stage=best_stage,
                score=best["score"].get("score", 0),
                gate_overall=agg.get("overall"),
                artifact_dir=art_dir,
                data_source=data_source,
                fold_count=len(folds),
                perturbation_robust=best["perturbation"].get("robust", False),
                stress_overall=best["stress"].get("overall", "FAIL"),
                per_fold_params=result.get("per_fold_params"),
                evidence=evidence,
            )

    # --- Write research summary ---
    n_passed = sum(1 for r in all_results if r["result"]["status"] == "PASS")
    n_rejected = len(all_results) - n_passed
    survivors = [e for e in batch_summary if e["status"] == "PASS"]
    rejects = [e for e in batch_summary if e["status"] != "PASS"]

    research_summary = {
        "run_id": run_id,
        "dataset_id": evidence.get("dataset_id", "unknown"),
        "data_granularity": evidence["data_granularity"],
        "evidence_tier": evidence["evidence_tier"],
        "promotion_eligible": evidence["promotion_eligible"],
        "fold_profile_used": fold_profile_name,
        "gate_profile_used": gate_profile_name,
        "families_evaluated": compatible_families,
        "families_skipped": skipped_families,
        "candidates_total": len(candidates),
        "candidates_passed": n_passed,
        "candidates_rejected": n_rejected,
        "rejection_reasons": {},
        "survivors": [],
        "top_candidate": None,
    }

    # Tally rejection reasons
    for e in rejects:
        reason = e.get("reject_reason") or "unknown"
        research_summary["rejection_reasons"][reason] = (
            research_summary["rejection_reasons"].get(reason, 0) + 1
        )

    # Survivor details
    for e in survivors[:5]:
        research_summary["survivors"].append({
            "candidate_id": e["candidate_id"],
            "family": e["family"],
            "score": e["score"],
            "stage": e["stage"],
            "stage_reason": e["stage_reason"],
            "gate_overall": e["gate_overall"],
            "avg_pf": e.get("avg_pf"),
        })

    if survivors:
        top = survivors[0]
        research_summary["top_candidate"] = {
            "candidate_id": top["candidate_id"],
            "family": top["family"],
            "score": top["score"],
            "stage": top["stage"],
            "stage_reason": top["stage_reason"],
            "promotable": evidence["promotion_eligible"] and top["stage"] == "BACKTESTED",
        }

    write_json(art_dir / "research_summary.json", research_summary)

    # Print summary
    print(f"run complete -> {art_dir}")
    print(f"  run_id: {run_id}")
    print(f"  dataset: {evidence.get('dataset_id')}  [{evidence['data_granularity']}]")
    print(f"  evidence_tier: {evidence['evidence_tier']}"
          f"  promotion_eligible: {evidence['promotion_eligible']}")
    print(f"  candidates: {len(candidates)} evaluated"
          f"  ({n_passed} passed, {n_rejected} rejected)")
    if skipped_families:
        print(f"  families skipped: {[s['family'] for s in skipped_families]}")
    print()
    for entry in batch_summary[:10]:
        status_mark = "PASS" if entry["status"] == "PASS" else "REJ"
        gate = entry.get("gate_overall", "N/A")
        print(f"  #{entry['rank']} [{status_mark}] {entry['candidate_id']}"
              f"  score={entry['score']:.4f}"
              f"  gate={gate}"
              f"  stage={entry['stage']}")


def _lambda_sweep(args):
    from .lambda_sweep import lambda_sweep

    data, data_meta = _load_data(args)
    max_lb = compute_max_feature_lookback(DEFAULT_CONFIG["features"])
    fold_spec, _ = select_fold_profile(data_meta["evidence_tier"])
    validate_purge_gap(fold_spec["purge_len"], max_lb)
    folds = build_folds(len(data), fold_spec, max_lb)

    if args.family:
        candidate = generate_default_candidate(args.family)
    else:
        candidate = generate_default_candidate("ema_crossover")

    sweep_result = lambda_sweep(candidate, data, folds, DEFAULT_CONFIG)

    art_dir = ensure_artifact_dir()
    write_summary(art_dir, {
        "command": "lambda-sweep",
        "best_lambda": sweep_result["best_lambda"],
        "best_score": sweep_result["best_score"],
        "status": sweep_result["status"],
    })
    write_json(art_dir / "lambda_sweep.json", sweep_result)

    print(f"lambda-sweep complete -> {art_dir}")
    print(f"  best_lambda: {sweep_result['best_lambda']}")
    print(f"  best_score: {sweep_result['best_score']}")


def _stress(args):
    data, data_meta = _load_data(args)
    max_lb = compute_max_feature_lookback(DEFAULT_CONFIG["features"])
    fold_spec, _ = select_fold_profile(data_meta["evidence_tier"])
    validate_purge_gap(fold_spec["purge_len"], max_lb)
    folds = build_folds(len(data), fold_spec, max_lb)

    if args.family:
        candidate = generate_default_candidate(args.family)
    else:
        candidate = generate_default_candidate("ema_crossover")

    if args.candidate_id:
        candidate["candidate_id"] = args.candidate_id

    stress_report = stress_check(
        candidate, data, folds, DEFAULT_CONFIG,
        sim_fn=run_candidate_simulation,
    )

    art_dir = ensure_artifact_dir()
    write_summary(art_dir, {
        "command": "stress",
        "candidate_id": candidate["candidate_id"],
        "overall": stress_report.get("overall"),
        "status": stress_report["status"],
    })
    write_json(art_dir / "stress_results.json", stress_report)

    print(f"stress complete -> {art_dir}")
    print(f"  overall: {stress_report.get('overall')}")
    for regime, info in stress_report.get("regimes", {}).items():
        print(f"  {regime}: trades={info.get('trades', 0)} "
              f"pf={info.get('profit_factor', 'N/A')} "
              f"gate={'PASS' if info.get('gate_pass') else 'FAIL'}")


def _compare(args):
    from .analysis import compare_runs
    run_ids = args.run_id.split(",") if getattr(args, "run_id", None) else None
    dataset_filter = getattr(args, "dataset", None)
    family_filter = getattr(args, "family", None)
    result = compare_runs(
        run_ids=run_ids,
        last_n=int(args.last_n) if args.last_n else 2,
        dataset_id=dataset_filter,
        family=family_filter,
    )
    if "error" in result:
        print(f"  {result['error']}")
        return

    # Echo active filters
    filters = []
    if dataset_filter:
        filters.append(f"dataset={dataset_filter}")
    if family_filter:
        filters.append(f"family={family_filter}")
    if filters:
        print(f"  filters: {', '.join(filters)}")
        print()

    for rid, summary in result["per_run"].items():
        print(f"=== {rid} ===")
        print(f"  dataset: {summary['dataset_id']}  evidence: {summary['evidence_tier']}")
        print(f"  families: {summary['families']}")
        print(f"  pass/total: {summary['passed']}/{summary['total']}"
              f"  top_score: {summary['top_score']}")
        for c in summary["top_candidates"]:
            print(f"    {c['candidate_id']}  score={c['score']}"
                  f"  stage={c['stage']}")
        if summary["rejection_reasons"]:
            print(f"  rejections: {summary['rejection_reasons']}")
        print()

    if result.get("diff"):
        d = result["diff"]
        print("=== diff ===")
        print(f"  score_delta: {d['score_delta']:+.4f}")
        print(f"  pass_rate: {d['pass_rate_a']} -> {d['pass_rate_b']}")
        if d.get("dataset_change"):
            print(f"  dataset changed")
        if d.get("new_families_in_b"):
            print(f"  new families: {d['new_families_in_b']}")
        if d.get("dropped_families_in_b"):
            print(f"  dropped families: {d['dropped_families_in_b']}")


def _best_ideas(args):
    from .analysis import best_ideas
    ideas = best_ideas(top_n=int(args.top_n) if args.top_n else 10)
    if not ideas:
        print("  no ideas in history")
        return

    print(f"{'sig':>18}  {'family':<18} {'app':>3} {'runs':>4} {'best':>7}"
          f" {'avg':>7} {'stage':<12} {'datasets'}")
    print("-" * 100)
    for idea in ideas:
        print(f"{idea['signature']:>18}  {idea['family']:<18}"
              f" {idea['appearances']:>3} {idea['distinct_runs']:>4}"
              f" {idea['best_score']:>7.4f} {idea['avg_score']:>7.4f}"
              f" {idea['best_stage']:<12}"
              f" {','.join(idea['distinct_datasets'])}")


def _rollup(args):
    from .analysis import research_rollup
    rollup = research_rollup()
    if rollup.get("status") == "no_history":
        print("  no history")
        return

    print(f"Research rollup: {rollup['total_records']} records,"
          f" {rollup['distinct_runs']} runs\n")

    for did, ds in rollup["datasets"].items():
        print(f"=== {did} [{ds['evidence_tier']}]"
              f"  promotion_eligible={ds['promotion_eligible']} ===")
        print(f"  evaluated: {ds['total_evaluated']}"
              f"  passed: {ds['total_passed']}"
              f"  rejected: {ds['total_rejected']}")
        if ds["rejection_reasons"]:
            print(f"  rejection reasons: {ds['rejection_reasons']}")
        if ds["recently_failed_families"]:
            print(f"  recently failed: {ds['recently_failed_families']}")
        print(f"  top ideas:")
        for idea in ds["top_ideas"]:
            print(f"    {idea['signature']}  {idea['family']:<18}"
                  f"  x{idea['appearances']}"
                  f"  score={idea['best_score']:.4f}"
                  f"  stage={idea['stage']}")
        print()


def _watchlist(args):
    from .analysis import generate_watchlist, append_watchlist_history
    wl = generate_watchlist(top_n=int(args.top_n) if args.top_n else 10)
    if wl.get("status") == "no_history":
        print("  no history")
        return

    for bucket, label in [("daily", "NQ Daily Research"),
                           ("hourly", "NQ Hourly Exploratory"),
                           ("other", "Other")]:
        items = wl.get(bucket, [])
        if not items:
            continue
        print(f"=== {label} ({len(items)} ideas) ===")
        for item in items:
            print(f"  {item['signature']}  {item['family']:<18}"
                  f"  x{item['appearances']} ({item['distinct_runs']} runs)"
                  f"  score={item['best_score']:.4f}"
                  f"  stage={item['stage']}")
            print(f"    {item['reason']}")
        print()

    # Write per-run artifact
    art_dir = ensure_artifact_dir()
    write_json(art_dir / "watchlist.json", wl)
    # Append to durable history
    entries = append_watchlist_history(wl)
    print(f"watchlist -> {art_dir / 'watchlist.json'}"
          f"  ({len(entries)} entries to history)")


def _query(args):
    from .analysis import (query_history, list_runs,
                            query_rejection_reasons, query_repeated_signatures,
                            query_capped_by_dataset, query_top_survivors)

    dataset_filter = getattr(args, "dataset", None)
    family_filter = getattr(args, "family", None)
    capped = getattr(args, "capped", False)
    mode = getattr(args, "mode", None)

    # Aggregation modes
    if mode == "rejections":
        reasons = query_rejection_reasons(dataset_id=dataset_filter)
        if not reasons:
            print("  no rejections")
            return
        print(f"Rejection reasons{' for ' + dataset_filter if dataset_filter else ''}:")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {count:>4}  {reason}")
        return

    if mode == "repeated":
        sigs = query_repeated_signatures(family=family_filter, min_appearances=2)
        if not sigs:
            print("  no repeated signatures")
            return
        print(f"{'signature':<18} {'family':<18} {'app':>3} {'best':>7} datasets")
        print("-" * 70)
        for s in sigs[:15]:
            print(f"{s['signature']:<18} {s['family']:<18}"
                  f" {s['appearances']:>3} {s['best_score']:>7.4f}"
                  f" {','.join(s['datasets'])}")
        return

    if mode == "capped":
        by_ds = query_capped_by_dataset(dataset_id=dataset_filter)
        if not by_ds:
            print("  no capped candidates")
            return
        for did, info in by_ds.items():
            print(f"=== {did} ({info['count']} capped, {info['unique_signatures']} unique) ===")
            for t in info["top"]:
                print(f"  {t['signature']}  {t['family']:<18}"
                      f"  x{t['appearances']}  score={t['best_score']:.4f}"
                      f"  [{t['evidence_tier']}]")
            print()
        return

    if mode == "survivors":
        survivors = query_top_survivors(
            dataset_id=dataset_filter,
            family=family_filter,
            top_n=int(args.top_n) if args.top_n else 10,
        )
        if not survivors:
            print("  no survivors")
            return
        label = dataset_filter or "all datasets"
        print(f"Top survivors for {label}:")
        print(f"{'signature':<18} {'family':<18} {'runs':>4} {'best':>7}"
              f" {'avg':>7} {'stage':<12} cap")
        print("-" * 85)
        for s in survivors:
            cap = "YES" if s["capped_by_evidence"] else ""
            print(f"{s['signature']:<18} {s['family']:<18}"
                  f" {s['distinct_runs']:>4} {s['best_score']:>7.4f}"
                  f" {s['avg_score']:>7.4f} {s['stage']:<12} {cap}")
        return

    if mode == "latest":
        runs = list_runs()
        if not runs:
            print("  no runs in history")
            return
        n = int(args.last_n) if args.last_n else 5
        print(f"Latest {n} runs:")
        print(f"{'run_id':<22} {'dataset':<12} {'evidence':<14} {'pass':>4}/{' total':<5}"
              f" {'top_score':>9}")
        print("-" * 75)
        for r in runs[:n]:
            print(f"{r['run_id']:<22} {r['dataset_id']:<12} {r['evidence_tier']:<14}"
                  f" {r['passed']:>4}/ {r['total']:<5}"
                  f" {r['top_score']:>9.4f}")
        return

    # Default: list runs or filtered records
    if not dataset_filter and not family_filter and not capped:
        runs = list_runs()
        if not runs:
            print("  no runs in history")
            return
        print(f"{'run_id':<22} {'dataset':<12} {'evidence':<14} {'pass':>4}/{' total':<5}"
              f" {'top_score':>9}")
        print("-" * 75)
        for r in runs[:10]:
            print(f"{r['run_id']:<22} {r['dataset_id']:<12} {r['evidence_tier']:<14}"
                  f" {r['passed']:>4}/ {r['total']:<5}"
                  f" {r['top_score']:>9.4f}")
        return

    records = query_history(
        dataset_id=dataset_filter,
        family=family_filter,
        capped_only=capped,
    )
    if not records:
        print("  no matching records")
        return

    print(f"  {len(records)} records match")
    passed = [r for r in records if r.get("status") == "PASS"]
    rejected = [r for r in records if r.get("status") != "PASS"]
    print(f"  {len(passed)} PASS, {len(rejected)} REJECT")
    if passed:
        scores = [r.get("score", 0) for r in passed]
        print(f"  top_score: {max(scores):.4f}  avg: {sum(scores)/len(scores):.4f}")
    print()
    for r in sorted(passed, key=lambda x: x.get("score", 0), reverse=True)[:5]:
        sig = (r.get("candidate_signature")
               or compute_candidate_signature(r.get("family", ""), r.get("params", {})))
        print(f"  {sig[:16]}  {r.get('family',''):<18}"
              f"  score={r.get('score',0):.4f}"
              f"  stage={r.get('stage')}"
              f"  [{_get_dataset_id(r)}]")


def _export(args):
    from .analysis import export_candidate_packets
    packets = export_candidate_packets(top_n=int(args.top_n) if args.top_n else 5)
    if not packets:
        print("  no candidates to export")
        return

    art_dir = ensure_artifact_dir()
    write_json(art_dir / "candidate_packets.json", packets)

    print(f"Exported {len(packets)} candidate packets -> {art_dir / 'candidate_packets.json'}")
    print()
    for p in packets:
        print(f"  {p['candidate_signature']}  {p['family']:<18}"
              f"  score={p['best_score']:.4f}"
              f"  x{p['appearances']} ({p['distinct_runs']} runs)")
        print(f"    {p['why_it_matters']}")
        print(f"    next: {p['recommended_next_step']}")
        print()


def _review_queue(args):
    from .analysis import generate_review_queue
    rq = generate_review_queue(top_n=int(args.top_n) if args.top_n else 5)
    if not rq.get("review_now") and not rq.get("monitor_only"):
        print("  no candidates for review")
        return

    art_dir = ensure_artifact_dir()
    write_json(art_dir / "review_queue.json", rq)

    # Print per-lane if lanes exist
    lanes = rq.get("lanes", {})
    if lanes:
        for lane_name in ("daily", "hourly", "other"):
            lane = lanes.get(lane_name)
            if not lane:
                continue
            review = lane.get("review_now", [])
            monitor = lane.get("monitor_only", [])
            if not review and not monitor:
                continue

            label = {"daily": "NQ Daily", "hourly": "NQ Hourly",
                     "other": "Other"}.get(lane_name, lane_name)

            if review:
                print(f"=== {label} — REVIEW NOW ({len(review)}) ===")
                for e in review:
                    cap = " [CAPPED]" if e["capped_by_evidence"] else ""
                    ds = ",".join(e.get("dataset_ids", []))
                    print(f"  {e['signature']}  {e['family']:<18}"
                          f"  score={e['best_score']:.4f}"
                          f"  x{e['appearances']} ({e['distinct_runs']} runs)"
                          f"  [{ds}]{cap}")
                    if e.get("reason"):
                        print(f"    {e['reason']}")
                print()

            if monitor:
                print(f"=== {label} — MONITOR ({len(monitor)}) ===")
                for e in monitor:
                    ds = ",".join(e.get("dataset_ids", []))
                    print(f"  {e['signature']}  {e['family']:<18}"
                          f"  score={e['best_score']:.4f}"
                          f"  x{e['appearances']}"
                          f"  [{ds}]")
                    if e.get("reason"):
                        print(f"    {e['reason']}")
                print()
    else:
        # Flat fallback
        if rq["review_now"]:
            print(f"=== REVIEW NOW ({len(rq['review_now'])}) ===")
            for e in rq["review_now"]:
                cap = " [CAPPED]" if e["capped_by_evidence"] else ""
                ds = ",".join(e.get("dataset_ids", e.get("datasets", [])))
                print(f"  {e['signature']}  {e['family']:<18}"
                      f"  score={e['best_score']:.4f}"
                      f"  x{e['appearances']} ({e['distinct_runs']} runs)"
                      f"  [{ds}]{cap}")
            print()

        if rq["monitor_only"]:
            print(f"=== MONITOR ({len(rq['monitor_only'])}) ===")
            for e in rq["monitor_only"]:
                ds = ",".join(e.get("dataset_ids", e.get("datasets", [])))
                print(f"  {e['signature']}  {e['family']:<18}"
                      f"  score={e['best_score']:.4f}"
                      f"  x{e['appearances']}"
                      f"  [{ds}]")
            print()

    print(f"review_queue -> {art_dir / 'review_queue.json'}")


def _ingest_bootstrap(args):
    from .ingest import bootstrap
    bootstrap(data_dir=getattr(args, "data_dir", None))


def _ingest_update(args):
    from .ingest import update
    update(data_dir=getattr(args, "data_dir", None))


def _ingest_inspect(args):
    from .ingest import inspect
    inspect(data_dir=getattr(args, "data_dir", None))


def main():
    parser = argparse.ArgumentParser(prog="strategy_factory", description="NQ Strategy Factory v2.1")
    parser.add_argument("command", choices=[
        "run", "lambda-sweep", "stress",
        "compare", "best-ideas", "rollup", "watchlist", "query", "export",
        "review-queue",
        "ingest-bootstrap", "ingest-update", "ingest-inspect",
        "weekly-run",
    ])
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--candidate-id", default=None)
    parser.add_argument("--family", default=None, help="Strategy family (ema_crossover, ema_crossover_cd, mean_reversion, breakout)")
    parser.add_argument("--n-candidates", default=None, help="Candidates per family")
    parser.add_argument("--sentinel", action="store_true")
    parser.add_argument("--dataset", default=None,
                        help="Named dataset (e.g., NQ_daily, NQ_hourly)")
    parser.add_argument("--data-path", default=None,
                        help="Explicit path to OHLCV data file (parquet or csv)")
    parser.add_argument("--data-dir", default=None,
                        help="Override data directory for ingest commands")
    parser.add_argument("--synthetic", action="store_true",
                        help="Force synthetic data even if real data exists")
    parser.add_argument("--last-n", default=None,
                        help="Number of recent runs to compare (default: 2)")
    parser.add_argument("--top-n", default=None,
                        help="Number of best ideas to show (default: 10)")
    parser.add_argument("--run-id", default=None,
                        help="Comma-separated run IDs for compare")
    parser.add_argument("--capped", action="store_true",
                        help="Filter to candidates capped by evidence tier")
    parser.add_argument("--mode", default=None,
                        help="Query mode: rejections, repeated, capped, survivors, latest")
    parser.add_argument("--extended-intraday", action="store_true",
                        help="weekly-run: also include NQ_15m and NQ_4h datasets")
    args = parser.parse_args()

    if args.command == "run":
        _run(args)
    elif args.command == "lambda-sweep":
        _lambda_sweep(args)
    elif args.command == "stress":
        _stress(args)
    elif args.command == "compare":
        _compare(args)
    elif args.command == "best-ideas":
        _best_ideas(args)
    elif args.command == "rollup":
        _rollup(args)
    elif args.command == "watchlist":
        _watchlist(args)
    elif args.command == "query":
        _query(args)
    elif args.command == "export":
        _export(args)
    elif args.command == "review-queue":
        _review_queue(args)
    elif args.command == "ingest-bootstrap":
        _ingest_bootstrap(args)
    elif args.command == "ingest-update":
        _ingest_update(args)
    elif args.command == "ingest-inspect":
        _ingest_inspect(args)
    elif args.command == "weekly-run":
        from .weekly_runner import run_weekly
        n = int(args.n_candidates) if args.n_candidates else 10
        run_weekly(n_candidates=n,
                   extended_intraday=getattr(args, "extended_intraday", False))


if __name__ == "__main__":
    main()
