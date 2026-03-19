"""Tests for analysis module: compare, signatures, best-ideas, rollup,
watchlist, query, export."""

import json
from pathlib import Path

import strategy_factory.artifacts as art_mod
from strategy_factory.analysis import (
    compute_candidate_signature,
    compare_runs,
    best_ideas,
    research_rollup,
    generate_watchlist,
    query_history,
    list_runs,
    export_candidate_packets,
    _load_history,
    _get_dataset_id,
)


def _write_history(tmp_path, records):
    """Write test records to a temp CANDIDATE_HISTORY.jsonl."""
    hist_path = tmp_path / "CANDIDATE_HISTORY.jsonl"
    with open(hist_path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return hist_path


# ---------------------------------------------------------------------------
# Candidate signatures
# ---------------------------------------------------------------------------

def test_signature_deterministic():
    s1 = compute_candidate_signature("breakout", {"lookback": 20, "atr_stop_mult": 1.5})
    s2 = compute_candidate_signature("breakout", {"lookback": 20, "atr_stop_mult": 1.5})
    assert s1 == s2


def test_signature_key_order_independent():
    s1 = compute_candidate_signature("breakout", {"a": 1.0, "b": 2.0})
    s2 = compute_candidate_signature("breakout", {"b": 2.0, "a": 1.0})
    assert s1 == s2


def test_signature_different_params():
    s1 = compute_candidate_signature("breakout", {"lookback": 20})
    s2 = compute_candidate_signature("breakout", {"lookback": 30})
    assert s1 != s2


def test_signature_different_family():
    s1 = compute_candidate_signature("breakout", {"lookback": 20})
    s2 = compute_candidate_signature("ema_crossover", {"lookback": 20})
    assert s1 != s2


def test_signature_float_rounding():
    """Signatures should match even with floating point noise."""
    s1 = compute_candidate_signature("breakout", {"x": 1.50001})
    s2 = compute_candidate_signature("breakout", {"x": 1.50002})
    assert s1 == s2  # both round to 1.5


def test_signature_length():
    sig = compute_candidate_signature("breakout", {"a": 1.0})
    assert len(sig) == 16  # hex digest prefix


# ---------------------------------------------------------------------------
# Compare runs
# ---------------------------------------------------------------------------

def test_compare_runs_basic(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        {"run_id": "run_a", "candidate_id": "c1", "family": "breakout",
         "params": {}, "status": "PASS", "score": 0.7, "stage": "CANDIDATE",
         "stage_reason": "gate_fail", "evidence": {"evidence_tier": "research"},
         "dataset_id": "NQ_daily"},
        {"run_id": "run_a", "candidate_id": "c2", "family": "breakout",
         "params": {}, "status": "REJECT", "score": 0.0, "stage": "REJECTED",
         "reject_reason": "NO_TRADES", "stage_reason": "NO_TRADES",
         "evidence": {"evidence_tier": "research"}, "dataset_id": "NQ_daily"},
        {"run_id": "run_b", "candidate_id": "c3", "family": "ema_crossover",
         "params": {}, "status": "PASS", "score": 0.8, "stage": "CANDIDATE",
         "stage_reason": "gate_fail", "evidence": {"evidence_tier": "exploratory"},
         "dataset_id": "NQ_hourly"},
    ]
    hist_path = _write_history(tmp_path, records)
    art_mod.CANDIDATE_HISTORY = hist_path

    try:
        result = compare_runs(last_n=2)
        assert "run_a" in result["per_run"]
        assert "run_b" in result["per_run"]
        assert result["per_run"]["run_a"]["passed"] == 1
        assert result["per_run"]["run_a"]["rejected"] == 1
        assert result["per_run"]["run_b"]["passed"] == 1
        assert result["diff"]["score_delta"] == 0.1  # 0.8 - 0.7
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_compare_runs_empty(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = tmp_path / "empty.jsonl"
    try:
        result = compare_runs()
        assert "error" in result
    finally:
        art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# Best ideas
# ---------------------------------------------------------------------------

def test_best_ideas_recurring(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        {"run_id": "run_1", "candidate_id": "c1", "family": "breakout",
         "params": {"lookback": 20}, "status": "PASS", "score": 0.7,
         "stage": "CANDIDATE", "evidence": {"evidence_tier": "research",
         "promotion_eligible": False}},
        {"run_id": "run_2", "candidate_id": "c1_copy", "family": "breakout",
         "params": {"lookback": 20}, "status": "PASS", "score": 0.75,
         "stage": "CANDIDATE", "evidence": {"evidence_tier": "research",
         "promotion_eligible": False}},
        {"run_id": "run_2", "candidate_id": "c2", "family": "ema_crossover",
         "params": {"atr_stop_mult": 2.0}, "status": "PASS", "score": 0.6,
         "stage": "CANDIDATE", "evidence": {"evidence_tier": "research",
         "promotion_eligible": False}},
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)

    try:
        ideas = best_ideas(min_appearances=1)
        assert len(ideas) >= 2

        # The breakout idea with lookback=20 should appear twice
        recurring = [i for i in ideas if i["family"] == "breakout"
                     and i["appearances"] >= 2]
        assert len(recurring) == 1
        assert recurring[0]["best_score"] == 0.75
        assert recurring[0]["distinct_runs"] == 2
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_best_ideas_rejected_excluded(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        {"run_id": "run_1", "candidate_id": "c1", "family": "breakout",
         "params": {"lookback": 20}, "status": "REJECT", "score": 0.0,
         "stage": "REJECTED", "evidence": {}},
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)

    try:
        ideas = best_ideas()
        assert len(ideas) == 0  # rejected candidates not in best ideas
    finally:
        art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# Research rollup
# ---------------------------------------------------------------------------

def test_rollup_by_dataset(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        {"run_id": "run_1", "candidate_id": "c1", "family": "breakout",
         "params": {"lookback": 20}, "status": "PASS", "score": 0.7,
         "stage": "CANDIDATE", "dataset_id": "NQ_daily",
         "evidence_tier": "research",
         "evidence": {"evidence_tier": "research", "promotion_eligible": False}},
        {"run_id": "run_1", "candidate_id": "c2", "family": "ema_crossover",
         "params": {}, "status": "REJECT", "score": 0.0,
         "reject_reason": "NO_TRADES",
         "stage": "REJECTED", "dataset_id": "NQ_daily",
         "evidence": {"evidence_tier": "research", "promotion_eligible": False}},
        {"run_id": "run_2", "candidate_id": "c3", "family": "breakout",
         "params": {"lookback": 15}, "status": "PASS", "score": 0.5,
         "stage": "CANDIDATE", "dataset_id": "NQ_hourly",
         "evidence_tier": "exploratory",
         "evidence": {"evidence_tier": "exploratory", "promotion_eligible": False}},
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)

    try:
        rollup = research_rollup()
        assert "NQ_daily" in rollup["datasets"]
        assert "NQ_hourly" in rollup["datasets"]

        daily = rollup["datasets"]["NQ_daily"]
        assert daily["total_passed"] == 1
        assert daily["total_rejected"] == 1
        assert daily["evidence_tier"] == "research"

        hourly = rollup["datasets"]["NQ_hourly"]
        assert hourly["total_passed"] == 1
        assert hourly["evidence_tier"] == "exploratory"
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_rollup_empty(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = tmp_path / "empty.jsonl"
    try:
        rollup = research_rollup()
        assert rollup["status"] == "no_history"
    finally:
        art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

_WATCHLIST_RECORDS = [
    {"run_id": "run_1", "candidate_id": "c1", "family": "breakout",
     "params": {"lookback": 20}, "status": "PASS", "score": 0.72,
     "stage": "CANDIDATE", "stage_reason": "evidence_tier_cap:research",
     "dataset_id": "NQ_daily", "evidence_tier": "research",
     "fold_profile_used": "research", "gate_profile_used": "research",
     "evidence": {"evidence_tier": "research", "promotion_eligible": False}},
    {"run_id": "run_2", "candidate_id": "c1b", "family": "breakout",
     "params": {"lookback": 20}, "status": "PASS", "score": 0.74,
     "stage": "CANDIDATE", "stage_reason": "evidence_tier_cap:research",
     "dataset_id": "NQ_daily", "evidence_tier": "research",
     "fold_profile_used": "research", "gate_profile_used": "research",
     "evidence": {"evidence_tier": "research", "promotion_eligible": False}},
    {"run_id": "run_3", "candidate_id": "c2", "family": "ema_crossover",
     "params": {"atr_stop_mult": 2.0}, "status": "PASS", "score": 0.5,
     "stage": "CANDIDATE", "stage_reason": "gate_fail",
     "dataset_id": "NQ_hourly", "evidence_tier": "exploratory",
     "fold_profile_used": "exploratory", "gate_profile_used": "exploratory",
     "evidence": {"evidence_tier": "exploratory", "promotion_eligible": False}},
]


def test_watchlist_separates_daily_hourly(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)
    try:
        wl = generate_watchlist()
        assert len(wl["daily"]) >= 1
        assert len(wl["hourly"]) >= 1
        # Daily idea should be the breakout with 2 appearances
        assert wl["daily"][0]["family"] == "breakout"
        assert wl["daily"][0]["appearances"] >= 2
        # Hourly should have ema_crossover
        hourly_families = [i["family"] for i in wl["hourly"]]
        assert "ema_crossover" in hourly_families
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_watchlist_includes_reason(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)
    try:
        wl = generate_watchlist()
        for item in wl["daily"] + wl["hourly"]:
            assert "reason" in item
            assert len(item["reason"]) > 0
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_watchlist_capped_flag(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)
    try:
        wl = generate_watchlist()
        capped_items = [i for i in wl["daily"] if i["capped_by_evidence"]]
        assert len(capped_items) >= 1
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_watchlist_empty(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = tmp_path / "empty.jsonl"
    try:
        wl = generate_watchlist()
        assert wl["status"] == "no_history"
    finally:
        art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def test_query_by_dataset(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)
    try:
        daily = query_history(dataset_id="NQ_daily")
        assert all(_get_dataset_id(r) == "NQ_daily" for r in daily)
        assert len(daily) == 2

        hourly = query_history(dataset_id="NQ_hourly")
        assert len(hourly) == 1
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_query_by_family(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)
    try:
        results = query_history(family="breakout")
        assert all(r["family"] == "breakout" for r in results)
        assert len(results) == 2
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_query_capped_only(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)
    try:
        results = query_history(capped_only=True)
        assert all("evidence_tier_cap" in str(r.get("stage_reason", ""))
                    for r in results)
        assert len(results) == 2
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_list_runs_order(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)
    try:
        runs = list_runs()
        assert len(runs) >= 2
        # Most recent first
        assert runs[0]["run_id"] == "run_3"
    finally:
        art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def test_export_packets(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)
    try:
        packets = export_candidate_packets(top_n=5)
        assert len(packets) >= 1
        p = packets[0]
        assert "candidate_signature" in p
        assert "family" in p
        assert "params" in p
        assert "why_it_matters" in p
        assert "recommended_next_step" in p
        assert len(p["why_it_matters"]) > 0
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_export_capped_next_step(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)
    try:
        packets = export_candidate_packets(top_n=5)
        capped = [p for p in packets if p["capped_by_evidence"]]
        for p in capped:
            assert p["recommended_next_step"] in (
                "review_for_kitt", "blocked_by_evidence"
            )
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_export_packet_fields(tmp_path):
    """Packets should include all enriched fields with consistent naming."""
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)
    try:
        packets = export_candidate_packets(top_n=5)
        p = packets[0]
        for field in ("candidate_signature", "candidate_id", "family", "params",
                       "dataset_ids", "primary_dataset_id", "evidence_tier",
                       "fold_profile_used", "gate_profile_used",
                       "stage", "stage_reason", "capped_by_evidence",
                       "best_score", "avg_score", "appearances", "distinct_runs",
                       "key_metrics", "why_it_matters", "recommended_next_step"):
            assert field in p, f"missing field: {field}"
        # No legacy field names
        assert "datasets" not in p, "should use dataset_ids not datasets"
        assert "dataset_id" not in p, "should use primary_dataset_id not dataset_id"
    finally:
        art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# Watchlist history
# ---------------------------------------------------------------------------

def test_watchlist_history_appends(tmp_path):
    from strategy_factory.analysis import append_watchlist_history
    orig_wh = art_mod.WATCHLIST_HISTORY
    wh_path = tmp_path / "WATCHLIST_HISTORY.jsonl"
    art_mod.WATCHLIST_HISTORY = wh_path

    orig_ch = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)

    try:
        wl = generate_watchlist()
        entries = append_watchlist_history(wl)
        assert len(entries) > 0

        # File should exist
        assert wh_path.exists()
        lines = wh_path.read_text().strip().split("\n")
        assert len(lines) == len(entries)

        # Each entry should have key fields
        first = json.loads(lines[0])
        assert "bucket" in first
        assert "generated_at" in first
        assert "watchlist_run_id" in first
        assert "signature" in first
        assert "family" in first

        # Append again — should double
        append_watchlist_history(wl)
        lines2 = wh_path.read_text().strip().split("\n")
        assert len(lines2) == len(entries) * 2
    finally:
        art_mod.WATCHLIST_HISTORY = orig_wh
        art_mod.CANDIDATE_HISTORY = orig_ch


# ---------------------------------------------------------------------------
# Compare with filters
# ---------------------------------------------------------------------------

def test_compare_with_dataset_filter(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        {"run_id": "run_a", "candidate_id": "c1", "family": "breakout",
         "params": {}, "status": "PASS", "score": 0.7, "stage": "CANDIDATE",
         "dataset_id": "NQ_daily", "evidence": {"evidence_tier": "research"}},
        {"run_id": "run_a", "candidate_id": "c2", "family": "breakout",
         "params": {}, "status": "PASS", "score": 0.6, "stage": "CANDIDATE",
         "dataset_id": "NQ_hourly", "evidence": {"evidence_tier": "exploratory"}},
        {"run_id": "run_b", "candidate_id": "c3", "family": "breakout",
         "params": {}, "status": "PASS", "score": 0.8, "stage": "CANDIDATE",
         "dataset_id": "NQ_daily", "evidence": {"evidence_tier": "research"}},
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)

    try:
        result = compare_runs(dataset_id="NQ_daily")
        # Should only see NQ_daily records
        for rid, summary in result["per_run"].items():
            assert summary["dataset_id"] == "NQ_daily"
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_compare_with_family_filter(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        {"run_id": "run_a", "candidate_id": "c1", "family": "breakout",
         "params": {}, "status": "PASS", "score": 0.7, "stage": "CANDIDATE",
         "dataset_id": "NQ_daily", "evidence": {"evidence_tier": "research"}},
        {"run_id": "run_a", "candidate_id": "c2", "family": "ema_crossover",
         "params": {}, "status": "PASS", "score": 0.6, "stage": "CANDIDATE",
         "dataset_id": "NQ_daily", "evidence": {"evidence_tier": "research"}},
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)

    try:
        result = compare_runs(family="breakout")
        for rid, summary in result["per_run"].items():
            assert summary["families"] == ["breakout"]
    finally:
        art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# Query aggregations
# ---------------------------------------------------------------------------

def test_query_rejection_reasons(tmp_path):
    from strategy_factory.analysis import query_rejection_reasons
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        {"run_id": "r1", "candidate_id": "c1", "family": "breakout",
         "params": {}, "status": "REJECT", "reject_reason": "NO_TRADES",
         "stage": "REJECTED", "dataset_id": "NQ_daily",
         "evidence": {"evidence_tier": "research"}},
        {"run_id": "r1", "candidate_id": "c2", "family": "breakout",
         "params": {}, "status": "REJECT", "reject_reason": "NO_TRADES",
         "stage": "REJECTED", "dataset_id": "NQ_daily",
         "evidence": {"evidence_tier": "research"}},
        {"run_id": "r1", "candidate_id": "c3", "family": "breakout",
         "params": {}, "status": "REJECT", "reject_reason": "DD_BREACH",
         "stage": "REJECTED", "dataset_id": "NQ_hourly",
         "evidence": {"evidence_tier": "exploratory"}},
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)

    try:
        all_reasons = query_rejection_reasons()
        assert all_reasons["NO_TRADES"] == 2
        assert all_reasons["DD_BREACH"] == 1

        daily_reasons = query_rejection_reasons(dataset_id="NQ_daily")
        assert daily_reasons["NO_TRADES"] == 2
        assert "DD_BREACH" not in daily_reasons
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_query_repeated_signatures(tmp_path):
    from strategy_factory.analysis import query_repeated_signatures
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        {"run_id": "r1", "candidate_id": "c1", "family": "breakout",
         "params": {"lookback": 20}, "status": "PASS", "score": 0.7,
         "stage": "CANDIDATE", "dataset_id": "NQ_daily",
         "evidence": {"evidence_tier": "research"}},
        {"run_id": "r2", "candidate_id": "c2", "family": "breakout",
         "params": {"lookback": 20}, "status": "PASS", "score": 0.75,
         "stage": "CANDIDATE", "dataset_id": "NQ_daily",
         "evidence": {"evidence_tier": "research"}},
        {"run_id": "r2", "candidate_id": "c3", "family": "ema_crossover",
         "params": {"x": 1.0}, "status": "PASS", "score": 0.5,
         "stage": "CANDIDATE", "dataset_id": "NQ_daily",
         "evidence": {"evidence_tier": "research"}},
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)

    try:
        repeated = query_repeated_signatures()
        assert len(repeated) == 1
        assert repeated[0]["family"] == "breakout"
        assert repeated[0]["appearances"] == 2

        # Family filter should return nothing for ema_crossover (only 1 appearance)
        ema_repeated = query_repeated_signatures(family="ema_crossover")
        assert len(ema_repeated) == 0
    finally:
        art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------

def test_review_queue(tmp_path):
    from strategy_factory.analysis import generate_review_queue
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)

    try:
        rq = generate_review_queue()
        assert "review_now" in rq
        assert "monitor_only" in rq
        assert "lanes" in rq

        # Flat compat lists still work
        review_sigs = [e["signature"] for e in rq["review_now"]]
        monitor_sigs = [e["signature"] for e in rq["monitor_only"]]
        all_sigs = review_sigs + monitor_sigs
        assert len(all_sigs) >= 1

        for e in rq["review_now"]:
            assert e["priority"] == "review"
        for e in rq["monitor_only"]:
            assert e["priority"] == "monitor"
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_review_queue_lane_separation(tmp_path):
    """Review queue separates daily and hourly into distinct lanes."""
    from strategy_factory.analysis import generate_review_queue
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)

    try:
        rq = generate_review_queue()
        lanes = rq["lanes"]

        # _WATCHLIST_RECORDS has daily (breakout) and hourly (ema_crossover)
        assert "daily" in lanes
        assert "hourly" in lanes

        # Daily lane should contain breakout
        daily_all = lanes["daily"]["review_now"] + lanes["daily"]["monitor_only"]
        daily_families = {e["family"] for e in daily_all}
        assert "breakout" in daily_families

        # Hourly lane should contain ema_crossover
        hourly_all = lanes["hourly"]["review_now"] + lanes["hourly"]["monitor_only"]
        hourly_families = {e["family"] for e in hourly_all}
        assert "ema_crossover" in hourly_families
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_review_queue_has_enriched_fields(tmp_path):
    """Review queue entries should include avg_score, reason, params, dataset_ids."""
    from strategy_factory.analysis import generate_review_queue
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)

    try:
        rq = generate_review_queue()
        all_entries = rq["review_now"] + rq["monitor_only"]
        assert len(all_entries) >= 1
        for e in all_entries:
            assert "avg_score" in e
            assert "reason" in e
            assert "params" in e
            assert "dataset_ids" in e
            assert "primary_dataset_id" in e
            assert len(e["reason"]) > 0
            # No legacy field names
            assert "datasets" not in e, "should use dataset_ids"
    finally:
        art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# Watchlist history enriched fields
# ---------------------------------------------------------------------------

def test_watchlist_history_semantics(tmp_path):
    """History entries use correct run_id semantics and dataset naming."""
    from strategy_factory.analysis import append_watchlist_history
    orig_wh = art_mod.WATCHLIST_HISTORY
    wh_path = tmp_path / "WATCHLIST_HISTORY.jsonl"
    art_mod.WATCHLIST_HISTORY = wh_path

    orig_ch = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)

    try:
        wl = generate_watchlist()
        entries = append_watchlist_history(wl, watchlist_run_id="wl_test123")
        assert len(entries) > 0

        lines = wh_path.read_text().strip().split("\n")
        for line in lines:
            entry = json.loads(line)
            # Watchlist generation event ID (not a pipeline run_id)
            assert entry["watchlist_run_id"] == "wl_test123"
            # Latest pipeline run that evaluated this candidate
            assert "latest_seen_run_id" in entry
            # No legacy "run_id" or "dataset_id" in history
            assert "run_id" not in entry, "should use watchlist_run_id"
            # Dataset naming: list + primary
            assert "dataset_ids" in entry
            assert isinstance(entry["dataset_ids"], list)
            assert "primary_dataset_id" in entry
            # Core fields
            assert "evidence_tier" in entry
            assert "signature" in entry
            assert "family" in entry
            assert "stage" in entry
            assert "stage_reason" in entry
            assert "reason" in entry
            assert "best_score" in entry
            assert "avg_score" in entry
            assert "appearances" in entry
            assert "distinct_runs" in entry

        # Auto-generated watchlist_run_id when not provided
        entries2 = append_watchlist_history(wl)
        lines2 = wh_path.read_text().strip().split("\n")
        last = json.loads(lines2[-1])
        assert last["watchlist_run_id"].startswith("wl_")
        assert last["watchlist_run_id"] != "wl_test123"
    finally:
        art_mod.WATCHLIST_HISTORY = orig_wh
        art_mod.CANDIDATE_HISTORY = orig_ch


# ---------------------------------------------------------------------------
# Export key_metrics and rerun_intraday
# ---------------------------------------------------------------------------

def test_export_packet_has_key_metrics(tmp_path):
    """Packets should include key_metrics dict."""
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)
    try:
        packets = export_candidate_packets(top_n=5)
        assert len(packets) >= 1
        for p in packets:
            assert "key_metrics" in p
            assert isinstance(p["key_metrics"], dict)
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_export_rerun_intraday_step(tmp_path):
    """Candidates on both daily and hourly but not intraday get rerun_intraday."""
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        {"run_id": "r1", "candidate_id": "c1", "family": "breakout",
         "params": {"lookback": 20}, "status": "PASS", "score": 0.6,
         "stage": "CANDIDATE", "stage_reason": "gate_fail",
         "dataset_id": "NQ_daily", "evidence_tier": "research",
         "evidence": {"evidence_tier": "research", "promotion_eligible": False}},
        {"run_id": "r2", "candidate_id": "c1b", "family": "breakout",
         "params": {"lookback": 20}, "status": "PASS", "score": 0.65,
         "stage": "CANDIDATE", "stage_reason": "gate_fail",
         "dataset_id": "NQ_hourly", "evidence_tier": "exploratory",
         "evidence": {"evidence_tier": "exploratory", "promotion_eligible": False}},
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
    try:
        packets = export_candidate_packets(top_n=5)
        assert len(packets) >= 1
        # Candidate appears on daily and hourly — next step should be rerun_intraday
        p = packets[0]
        assert p["recommended_next_step"] == "rerun_intraday"
    finally:
        art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# Query: capped by dataset
# ---------------------------------------------------------------------------

def test_query_capped_by_dataset(tmp_path):
    from strategy_factory.analysis import query_capped_by_dataset
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)
    try:
        result = query_capped_by_dataset()
        assert "NQ_daily" in result
        daily = result["NQ_daily"]
        assert daily["count"] >= 1
        assert daily["unique_signatures"] >= 1
        assert len(daily["top"]) >= 1
        assert "signature" in daily["top"][0]
        assert "family" in daily["top"][0]
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_query_capped_empty(tmp_path):
    from strategy_factory.analysis import query_capped_by_dataset
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        {"run_id": "r1", "candidate_id": "c1", "family": "breakout",
         "params": {}, "status": "PASS", "score": 0.7,
         "stage": "CANDIDATE", "stage_reason": "gate_fail",
         "dataset_id": "NQ_daily", "evidence": {"evidence_tier": "research"}},
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
    try:
        result = query_capped_by_dataset()
        assert result == {}  # no capped candidates
    finally:
        art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# Query: top survivors
# ---------------------------------------------------------------------------

def test_query_top_survivors(tmp_path):
    from strategy_factory.analysis import query_top_survivors
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)
    try:
        survivors = query_top_survivors(dataset_id="NQ_daily")
        assert len(survivors) >= 1
        s = survivors[0]
        assert "signature" in s
        assert "family" in s
        assert "distinct_runs" in s
        assert "best_score" in s
        assert "avg_score" in s
        assert "capped_by_evidence" in s
        # The breakout on NQ_daily has 2 appearances
        assert s["family"] == "breakout"
        assert s["appearances"] >= 2
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_query_top_survivors_all_datasets(tmp_path):
    from strategy_factory.analysis import query_top_survivors
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)
    try:
        survivors = query_top_survivors()  # no dataset filter
        assert len(survivors) >= 2  # breakout + ema_crossover
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_query_top_survivors_empty(tmp_path):
    from strategy_factory.analysis import query_top_survivors
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = tmp_path / "empty.jsonl"
    try:
        survivors = query_top_survivors()
        assert survivors == []
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_query_survivors_with_dataset_and_family(tmp_path):
    """Survivors mode should honor both --dataset and --family together."""
    from strategy_factory.analysis import query_top_survivors
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        {"run_id": "r1", "candidate_id": "c1", "family": "breakout",
         "params": {"lookback": 20}, "status": "PASS", "score": 0.7,
         "stage": "CANDIDATE", "dataset_id": "NQ_daily",
         "evidence": {"evidence_tier": "research"}},
        {"run_id": "r2", "candidate_id": "c2", "family": "breakout",
         "params": {"lookback": 20}, "status": "PASS", "score": 0.75,
         "stage": "CANDIDATE", "dataset_id": "NQ_daily",
         "evidence": {"evidence_tier": "research"}},
        {"run_id": "r1", "candidate_id": "c3", "family": "ema_crossover",
         "params": {"x": 1.0}, "status": "PASS", "score": 0.5,
         "stage": "CANDIDATE", "dataset_id": "NQ_daily",
         "evidence": {"evidence_tier": "research"}},
        {"run_id": "r1", "candidate_id": "c4", "family": "breakout",
         "params": {"lookback": 30}, "status": "PASS", "score": 0.6,
         "stage": "CANDIDATE", "dataset_id": "NQ_hourly",
         "evidence": {"evidence_tier": "exploratory"}},
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)

    try:
        # Both filters: only breakout on NQ_daily
        survivors = query_top_survivors(dataset_id="NQ_daily", family="breakout")
        assert len(survivors) >= 1
        for s in survivors:
            assert s["family"] == "breakout"
        # ema_crossover should be excluded
        assert all(s["family"] != "ema_crossover" for s in survivors)

        # Family only
        all_breakout = query_top_survivors(family="breakout")
        assert len(all_breakout) >= 2  # daily + hourly breakout sigs

        # Dataset only
        daily_all = query_top_survivors(dataset_id="NQ_daily")
        families = {s["family"] for s in daily_all}
        assert "breakout" in families
        assert "ema_crossover" in families
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_query_capped_with_dataset_filter(tmp_path):
    """Capped mode should honor --dataset filter."""
    from strategy_factory.analysis import query_capped_by_dataset
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        {"run_id": "r1", "candidate_id": "c1", "family": "breakout",
         "params": {"lookback": 20}, "status": "PASS", "score": 0.7,
         "stage": "CANDIDATE", "stage_reason": "evidence_tier_cap:research",
         "dataset_id": "NQ_daily", "evidence_tier": "research",
         "evidence": {"evidence_tier": "research"}},
        {"run_id": "r1", "candidate_id": "c2", "family": "ema_crossover",
         "params": {"x": 1.0}, "status": "PASS", "score": 0.5,
         "stage": "CANDIDATE", "stage_reason": "evidence_tier_cap:exploratory",
         "dataset_id": "NQ_hourly", "evidence_tier": "exploratory",
         "evidence": {"evidence_tier": "exploratory"}},
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)

    try:
        # All capped
        all_capped = query_capped_by_dataset()
        assert "NQ_daily" in all_capped
        assert "NQ_hourly" in all_capped

        # Filter to NQ_daily only
        daily_only = query_capped_by_dataset(dataset_id="NQ_daily")
        assert "NQ_daily" in daily_only
        assert "NQ_hourly" not in daily_only
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_review_queue_no_legacy_datasets_field(tmp_path):
    """Review queue entries should use dataset_ids, not datasets."""
    from strategy_factory.analysis import generate_review_queue
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)

    try:
        rq = generate_review_queue()
        # Check lane entries too
        for lane in rq.get("lanes", {}).values():
            for e in lane.get("review_now", []) + lane.get("monitor_only", []):
                assert "dataset_ids" in e
                assert "primary_dataset_id" in e
                assert "datasets" not in e
    finally:
        art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# Profile-field parity
# ---------------------------------------------------------------------------

def test_watchlist_carries_profile_fields(tmp_path):
    """Watchlist items should include fold_profile_used and gate_profile_used."""
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)
    try:
        wl = generate_watchlist()
        for bucket in ("daily", "hourly"):
            for item in wl.get(bucket, []):
                assert "fold_profile_used" in item, f"missing fold_profile_used in {bucket}"
                assert "gate_profile_used" in item, f"missing gate_profile_used in {bucket}"
                # Values should be non-None since fixture has them
                assert item["fold_profile_used"] is not None
                assert item["gate_profile_used"] is not None
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_watchlist_history_carries_profile_fields(tmp_path):
    """Watchlist history entries should include profile fields from watchlist."""
    from strategy_factory.analysis import append_watchlist_history
    orig_wh = art_mod.WATCHLIST_HISTORY
    wh_path = tmp_path / "WATCHLIST_HISTORY.jsonl"
    art_mod.WATCHLIST_HISTORY = wh_path

    orig_ch = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)

    try:
        wl = generate_watchlist()
        append_watchlist_history(wl)

        lines = wh_path.read_text().strip().split("\n")
        for line in lines:
            entry = json.loads(line)
            assert "fold_profile_used" in entry
            assert "gate_profile_used" in entry
            assert entry["fold_profile_used"] is not None
            assert entry["gate_profile_used"] is not None
    finally:
        art_mod.WATCHLIST_HISTORY = orig_wh
        art_mod.CANDIDATE_HISTORY = orig_ch


def test_review_queue_carries_profile_fields(tmp_path):
    """Review queue entries should include fold_profile_used and gate_profile_used."""
    from strategy_factory.analysis import generate_review_queue
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)

    try:
        rq = generate_review_queue()
        all_entries = rq["review_now"] + rq["monitor_only"]
        assert len(all_entries) >= 1
        for e in all_entries:
            assert "fold_profile_used" in e
            assert "gate_profile_used" in e
            assert e["fold_profile_used"] is not None
            assert e["gate_profile_used"] is not None

        # Also check lane entries
        for lane in rq.get("lanes", {}).values():
            for e in lane.get("review_now", []) + lane.get("monitor_only", []):
                assert "fold_profile_used" in e
                assert "gate_profile_used" in e
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_best_ideas_carries_profile_fields(tmp_path):
    """best_ideas should propagate profile fields from best record."""
    from strategy_factory.analysis import best_ideas
    orig = art_mod.CANDIDATE_HISTORY
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, _WATCHLIST_RECORDS)

    try:
        ideas = best_ideas(min_appearances=1)
        assert len(ideas) >= 1
        for idea in ideas:
            assert "fold_profile_used" in idea
            assert "gate_profile_used" in idea
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_profile_fields_null_when_absent(tmp_path):
    """Profile fields should be None when source records lack them."""
    from strategy_factory.analysis import best_ideas
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        {"run_id": "r1", "candidate_id": "c1", "family": "breakout",
         "params": {"lookback": 20}, "status": "PASS", "score": 0.7,
         "stage": "CANDIDATE", "dataset_id": "NQ_daily",
         "evidence": {"evidence_tier": "research"}},
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)

    try:
        ideas = best_ideas(min_appearances=1)
        assert len(ideas) == 1
        assert ideas[0]["fold_profile_used"] is None
        assert ideas[0]["gate_profile_used"] is None
    finally:
        art_mod.CANDIDATE_HISTORY = orig
