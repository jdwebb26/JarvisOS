"""Builds family and regime scoreboards from the rejection ledger.

Outputs:
  state/quant/rejections/family_scoreboard.json
  state/quant/rejections/regime_scoreboard.json
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.quant.rejection_types import NextActionHint, RejectionRecord
from runtime.quant.rejection_ledger import RejectionLedger, DEFAULT_STATE_DIR

# Families with this many consecutive rejections get a cooldown flag
COOLDOWN_THRESHOLD = 5


def build_family_scoreboard(
    records: list[RejectionRecord],
    promoted_families: set[str] | None = None,
    paper_families: set[str] | None = None,
) -> dict[str, Any]:
    """Build family-level scoreboard from rejection records.

    Args:
        records: All rejection records.
        promoted_families: Families that have at least one promoted strategy.
        paper_families: Families that have at least one paper-trade approved strategy.
    """
    promoted_families = promoted_families or set()
    paper_families = paper_families or set()

    family_data: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "total_candidates": 0,
        "rejected_count": 0,
        "promoted_count": 0,
        "paper_approved_count": 0,
        "reasons": Counter(),
        "regime_tags": Counter(),
        "near_miss_count": 0,
        "cooldown": False,
    })

    for rec in records:
        f = rec.family or "unknown"
        fd = family_data[f]
        fd["total_candidates"] += 1
        fd["rejected_count"] += 1
        fd["reasons"][rec.primary_reason] += 1
        for tag in rec.regime_tags:
            fd["regime_tags"][tag] += 1
        if rec.next_action_hint == NextActionHint.PROMISING_NEAR_MISS.value:
            fd["near_miss_count"] += 1

    # Enrich with promoted/paper counts
    for f in promoted_families:
        if f in family_data:
            family_data[f]["promoted_count"] += 1
    for f in paper_families:
        if f in family_data:
            family_data[f]["paper_approved_count"] += 1

    # Build output
    scoreboard: dict[str, Any] = {}
    for f, fd in sorted(family_data.items(), key=lambda x: -x[1]["rejected_count"]):
        dominant_reason = fd["reasons"].most_common(1)[0][0] if fd["reasons"] else "none"
        dominant_regimes = [t for t, _ in fd["regime_tags"].most_common(3)]
        cooldown = fd["rejected_count"] >= COOLDOWN_THRESHOLD and fd["promoted_count"] == 0
        scoreboard[f] = {
            "total_candidates": fd["total_candidates"],
            "rejected_count": fd["rejected_count"],
            "promoted_count": fd["promoted_count"],
            "paper_approved_count": fd["paper_approved_count"],
            "dominant_rejection_reason": dominant_reason,
            "dominant_regime_tags": dominant_regimes,
            "near_miss_count": fd["near_miss_count"],
            "cooldown": cooldown,
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_families": len(scoreboard),
        "families": scoreboard,
    }


def build_regime_scoreboard(records: list[RejectionRecord]) -> dict[str, Any]:
    """Build regime-level scoreboard from rejection records."""
    regime_data: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "total_rejections": 0,
        "families": Counter(),
        "reasons": Counter(),
    })

    for rec in records:
        tags = rec.regime_tags if rec.regime_tags else ["untagged"]
        for tag in tags:
            rd = regime_data[tag]
            rd["total_rejections"] += 1
            if rec.family:
                rd["families"][rec.family] += 1
            rd["reasons"][rec.primary_reason] += 1

    scoreboard: dict[str, Any] = {}
    for tag, rd in sorted(regime_data.items(), key=lambda x: -x[1]["total_rejections"]):
        scoreboard[tag] = {
            "total_rejections": rd["total_rejections"],
            "families_most_hurt": [f for f, _ in rd["families"].most_common(5)],
            "dominant_reasons": [r for r, _ in rd["reasons"].most_common(3)],
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_regimes": len(scoreboard),
        "regimes": scoreboard,
    }


def build_learning_summary(
    records: list[RejectionRecord],
    promoted_families: set[str] | None = None,
) -> dict[str, Any]:
    """Build a learning summary for operator and downstream lanes."""
    promoted_families = promoted_families or set()

    reason_counter: Counter = Counter()
    family_counter: Counter = Counter()
    near_miss_families: Counter = Counter()
    regime_counter: Counter = Counter()

    for rec in records:
        reason_counter[rec.primary_reason] += 1
        if rec.family:
            family_counter[rec.family] += 1
            if rec.next_action_hint == NextActionHint.PROMISING_NEAR_MISS.value:
                near_miss_families[rec.family] += 1
        for tag in rec.regime_tags:
            regime_counter[tag] += 1

    # Regime blind spots: regimes with many rejections but no promoted families surviving
    blind_spots: list[str] = []
    regime_families: dict[str, set[str]] = defaultdict(set)
    for rec in records:
        for tag in rec.regime_tags:
            if rec.family:
                regime_families[tag].add(rec.family)
    for tag, families in regime_families.items():
        if not families.intersection(promoted_families):
            blind_spots.append(tag)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_rejections": len(records),
        "top_rejection_reasons": [{"reason": r, "count": c} for r, c in reason_counter.most_common(5)],
        "top_failing_families": [{"family": f, "count": c} for f, c in family_counter.most_common(5)],
        "top_near_miss_families": [{"family": f, "count": c} for f, c in near_miss_families.most_common(5)],
        "top_regime_blind_spots": blind_spots[:5],
        "recommended_exploration_shifts": _recommend_shifts(reason_counter, near_miss_families, family_counter),
    }


def _recommend_shifts(
    reasons: Counter,
    near_misses: Counter,
    families: Counter,
) -> list[str]:
    """Generate concise exploration shift recommendations."""
    shifts: list[str] = []
    top_reason = reasons.most_common(1)[0][0] if reasons else None

    if top_reason == "low_trade_count":
        shifts.append("Increase minimum bar count or use higher-resolution data to boost trade counts.")
    elif top_reason == "low_sharpe":
        shifts.append("Focus mutations on risk-adjusted return improvement; consider tighter stop-loss tuning.")
    elif top_reason == "low_profit_factor":
        shifts.append("Explore entry signal refinement; current exit timing may be leaking edge.")
    elif top_reason == "high_drawdown":
        shifts.append("Prioritize drawdown-aware position sizing or regime filters.")

    if near_misses:
        top_nm = near_misses.most_common(1)[0][0]
        shifts.append(f"Family '{top_nm}' has near-misses — prioritize parameter mutation over new families.")

    # Families with many failures and no near-misses: suggest avoiding
    for fam, count in families.most_common(3):
        if count >= COOLDOWN_THRESHOLD and fam not in near_misses:
            shifts.append(f"Family '{fam}' has {count} rejections with no near-misses — consider cooldown.")

    return shifts


def write_scoreboards(
    ledger: RejectionLedger | None = None,
    output_dir: Path | str | None = None,
    promoted_families: set[str] | None = None,
    paper_families: set[str] | None = None,
) -> dict[str, Path]:
    """Convenience: build and write all scoreboards. Returns paths written."""
    if ledger is None:
        ledger = RejectionLedger()
    records = ledger.read_all()
    out = Path(output_dir) if output_dir else ledger.state_dir

    family = build_family_scoreboard(records, promoted_families, paper_families)
    regime = build_regime_scoreboard(records)
    learning = build_learning_summary(records, promoted_families)

    paths: dict[str, Path] = {}
    for name, data in [("family_scoreboard", family), ("regime_scoreboard", regime), ("learning_summary", learning)]:
        p = out / f"{name}.json"
        p.write_text(json.dumps(data, indent=2, default=str) + "\n")
        paths[name] = p

    return paths
