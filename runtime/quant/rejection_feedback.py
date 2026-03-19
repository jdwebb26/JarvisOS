"""Feedback export for downstream lanes (Atlas, Fish, Kitt).

Produces:
  state/quant/rejections/feedback_snapshot.json  — structured
  state/quant/rejections/feedback_snapshot.md     — human-readable
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.quant.rejection_types import RejectionRecord
from runtime.quant.rejection_ledger import RejectionLedger
from runtime.quant.rejection_scoreboard import build_learning_summary


def build_atlas_feedback(records: list[RejectionRecord]) -> dict[str, Any]:
    """Compact feedback for Atlas discovery lane."""
    family_reasons: dict[str, Counter] = defaultdict(Counter)
    family_hints: dict[str, Counter] = defaultdict(Counter)
    near_misses: list[str] = []

    for rec in records:
        f = rec.family or "unknown"
        family_reasons[f][rec.primary_reason] += 1
        if rec.next_action_hint:
            family_hints[f][rec.next_action_hint] += 1
        if rec.next_action_hint == "promising_near_miss":
            near_misses.append(f)

    families: dict[str, Any] = {}
    for f, reasons in family_reasons.items():
        dominant = reasons.most_common(1)[0] if reasons else ("unknown", 0)
        hint = family_hints[f].most_common(1)[0][0] if family_hints[f] else "archive_candidate"
        families[f] = {
            "rejection_count": sum(reasons.values()),
            "dominant_reason": dominant[0],
            "suggested_action": hint,
        }

    cooldown = [f for f, d in families.items() if d["rejection_count"] >= 5 and d["suggested_action"] != "promising_near_miss"]

    return {
        "target": "atlas",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_rejections": len(records),
        "families": families,
        "cooldown_families": cooldown,
        "near_miss_families": list(set(near_misses)),
        "guidance": "Avoid generating candidates from cooldown families. Prioritize mutation of near-miss families.",
    }


def build_fish_feedback(records: list[RejectionRecord]) -> dict[str, Any]:
    """Compact feedback for Fish scenario lane."""
    regime_reasons: dict[str, Counter] = defaultdict(Counter)
    regime_families: dict[str, set] = defaultdict(set)

    for rec in records:
        tags = rec.regime_tags if rec.regime_tags else ["untagged"]
        for tag in tags:
            regime_reasons[tag][rec.primary_reason] += 1
            if rec.family:
                regime_families[tag].add(rec.family)

    regimes: dict[str, Any] = {}
    for tag, reasons in regime_reasons.items():
        dominant = reasons.most_common(1)[0] if reasons else ("unknown", 0)
        regimes[tag] = {
            "rejection_count": sum(reasons.values()),
            "dominant_reason": dominant[0],
            "affected_families": sorted(regime_families.get(tag, set())),
        }

    return {
        "target": "fish",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_rejections": len(records),
        "regimes": regimes,
        "guidance": "Focus scenario modeling on regimes with high rejection counts. Provide calibration data for families that fail in specific regimes.",
    }


def build_kitt_feedback(
    records: list[RejectionRecord],
    promoted_families: set[str] | None = None,
) -> dict[str, Any]:
    """Compact feedback for Kitt quant lead."""
    learning = build_learning_summary(records, promoted_families)

    return {
        "target": "kitt",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_rejections": len(records),
        "top_rejection_reasons": learning["top_rejection_reasons"],
        "top_failing_families": learning["top_failing_families"],
        "top_near_miss_families": learning["top_near_miss_families"],
        "regime_blind_spots": learning["top_regime_blind_spots"],
        "exploration_shifts": learning["recommended_exploration_shifts"],
        "guidance": "Use this to adjust brief priorities and highlight families worth continued investment vs those to deprioritize.",
    }


def build_feedback_snapshot(
    records: list[RejectionRecord],
    promoted_families: set[str] | None = None,
) -> dict[str, Any]:
    """Combined feedback snapshot for all lanes."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "atlas": build_atlas_feedback(records),
        "fish": build_fish_feedback(records),
        "kitt": build_kitt_feedback(records, promoted_families),
    }


def render_feedback_markdown(snapshot: dict[str, Any]) -> str:
    """Render feedback snapshot as operator-readable Markdown."""
    lines: list[str] = []
    lines.append("# Rejection Feedback Snapshot")
    lines.append(f"\nGenerated: {snapshot.get('generated_at', 'unknown')}\n")

    # Atlas
    atlas = snapshot.get("atlas", {})
    lines.append("## Atlas — Discovery Guidance\n")
    lines.append(f"Total rejections analyzed: {atlas.get('total_rejections', 0)}\n")
    if atlas.get("cooldown_families"):
        lines.append(f"**Cooldown families** (>=5 rejections, no near-misses): {', '.join(atlas['cooldown_families'])}\n")
    if atlas.get("near_miss_families"):
        lines.append(f"**Near-miss families** (prioritize mutation): {', '.join(atlas['near_miss_families'])}\n")
    families = atlas.get("families", {})
    if families:
        lines.append("| Family | Rejections | Dominant Reason | Action |")
        lines.append("|--------|-----------|-----------------|--------|")
        for f, d in sorted(families.items(), key=lambda x: -x[1]["rejection_count"]):
            lines.append(f"| {f} | {d['rejection_count']} | {d['dominant_reason']} | {d['suggested_action']} |")
    lines.append("")

    # Fish
    fish = snapshot.get("fish", {})
    lines.append("## Fish — Scenario Guidance\n")
    regimes = fish.get("regimes", {})
    if regimes:
        lines.append("| Regime | Rejections | Dominant Reason | Affected Families |")
        lines.append("|--------|-----------|-----------------|-------------------|")
        for tag, d in sorted(regimes.items(), key=lambda x: -x[1]["rejection_count"]):
            fams = ", ".join(d.get("affected_families", [])[:3])
            lines.append(f"| {tag} | {d['rejection_count']} | {d['dominant_reason']} | {fams} |")
    lines.append("")

    # Kitt
    kitt = snapshot.get("kitt", {})
    lines.append("## Kitt — Quant Lead Brief\n")
    if kitt.get("top_rejection_reasons"):
        lines.append("**Top rejection reasons:**")
        for item in kitt["top_rejection_reasons"]:
            lines.append(f"- {item['reason']} ({item['count']})")
    if kitt.get("exploration_shifts"):
        lines.append("\n**Recommended exploration shifts:**")
        for shift in kitt["exploration_shifts"]:
            lines.append(f"- {shift}")
    lines.append("")

    return "\n".join(lines)


def export_feedback(
    ledger: RejectionLedger | None = None,
    output_dir: Path | str | None = None,
    promoted_families: set[str] | None = None,
) -> dict[str, Path]:
    """Build and write feedback snapshot. Returns paths written."""
    if ledger is None:
        ledger = RejectionLedger()
    records = ledger.read_all()
    out = Path(output_dir) if output_dir else ledger.state_dir

    snapshot = build_feedback_snapshot(records, promoted_families)

    json_path = out / "feedback_snapshot.json"
    json_path.write_text(json.dumps(snapshot, indent=2, default=str) + "\n")

    md_path = out / "feedback_snapshot.md"
    md_path.write_text(render_feedback_markdown(snapshot))

    return {"json": json_path, "md": md_path}
