#!/usr/bin/env python3
"""Atlas Proposal Generator — consume Sigma feedback and produce bounded
experiment proposals.

Reads the latest Sigma feedback packet and generates an Atlas experiment
proposal that answers:
- What failed
- What should be changed
- What new experiment or mutation is proposed
- Why this is the next best bounded test

Usage:
    .venv/bin/python3 workspace/quant_infra/atlas/proposal_generator.py
    .venv/bin/python3 workspace/quant_infra/atlas/proposal_generator.py --json
    .venv/bin/python3 workspace/quant_infra/atlas/proposal_generator.py --submit
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packets.writer import read_packet, write_packet

QUANT_INFRA = Path(__file__).resolve().parent.parent
PROPOSALS_DIR = QUANT_INFRA / "research" / "atlas_proposals"

# Maps bottleneck classes to concrete experiment templates
_EXPERIMENT_TEMPLATES: dict[str, dict] = {
    "stop_placement": {
        "experiment_type": "parameter_sweep",
        "hypothesis": "Widening stop distance reduces premature stop-outs without significantly increasing max drawdown",
        "parameters": {
            "sweep_target": "stop_distance_multiplier",
            "range": [1.5, 2.0, 2.5, 3.0],
            "unit": "ATR",
            "hold_constant": ["entry_signal", "target_distance"],
        },
        "rationale": "Current stop is too tight relative to position entry. ATR-scaled stops adapt to volatility.",
    },
    "risk_reward": {
        "experiment_type": "parameter_sweep",
        "hypothesis": "Adjusting R/R ratio by extending target or tightening stop improves net expectancy",
        "parameters": {
            "sweep_target": "reward_risk_ratio",
            "range": [1.5, 2.0, 2.5],
            "approach": "extend_target_first",
            "hold_constant": ["entry_signal"],
        },
        "rationale": "R/R below 1.0 indicates the position is structurally unprofitable even with high win rate.",
    },
    "entry_timing": {
        "experiment_type": "filter_addition",
        "hypothesis": "Adding a momentum confirmation filter reduces entries during adverse moves",
        "parameters": {
            "filter_type": "momentum_confirmation",
            "candidates": ["rsi_above_50", "price_above_vwap", "ema_slope_positive"],
            "hold_constant": ["stop_distance", "target_distance"],
        },
        "rationale": "Large unrealized loss at entry suggests entering against short-term momentum.",
    },
    "thesis_alignment": {
        "experiment_type": "regime_gate",
        "hypothesis": "Adding a regime-aware entry gate prevents entries when scenario consensus is bearish",
        "parameters": {
            "gate_type": "scenario_consensus",
            "threshold": "majority_positive",
            "source": "fish_scenarios",
            "hold_constant": ["core_signal", "stop_target"],
        },
        "rationale": "Multiple negative scenarios contradict the trade thesis. A regime gate filters these.",
    },
    "risk_exposure": {
        "experiment_type": "position_sizing",
        "hypothesis": "Volatility-adjusted position sizing reduces stop-out probability without sacrificing upside",
        "parameters": {
            "sizing_method": "vix_scaled",
            "base_risk_pct": 1.0,
            "vix_threshold_reduce": 25,
            "vix_threshold_skip": 35,
            "hold_constant": ["entry_signal", "stop_distance"],
        },
        "rationale": "High stop-out probability suggests the position is too large for current volatility.",
    },
    "target_placement": {
        "experiment_type": "parameter_sweep",
        "hypothesis": "ATR-based target placement improves hit rate vs fixed-point targets",
        "parameters": {
            "sweep_target": "target_distance_multiplier",
            "range": [1.0, 1.5, 2.0, 2.5],
            "unit": "ATR",
            "hold_constant": ["entry_signal", "stop_distance"],
        },
        "rationale": "Target distance should reflect recent volatility, not fixed values.",
    },
}


def generate_proposal() -> dict | None:
    """Read latest Sigma feedback and produce an experiment proposal.

    Returns None if no feedback is available.
    """
    # Read the sigma feedback packet
    sigma_feedback = read_packet("sigma")
    if not sigma_feedback:
        print("[atlas-proposal] No Sigma packet found")
        return None

    # Look for feedback-type packet first, fall back to validation packet
    data = sigma_feedback.get("data", {})
    ptype = sigma_feedback.get("packet_type", "")

    if ptype == "sigma_feedback":
        feedback_items = data.get("feedback", [])
    elif ptype == "sigma_paper_validation":
        # Extract feedback directly from validation checks
        feedback_items = _feedback_from_validation(data)
    else:
        print(f"[atlas-proposal] Unexpected Sigma packet type: {ptype}")
        return None

    if not feedback_items:
        print("[atlas-proposal] No actionable feedback in Sigma packet")
        return None

    now = datetime.now(timezone.utc)
    proposal_id = f"aprop-{uuid.uuid4().hex[:8]}"

    # Generate proposals for each position's issues
    experiments = []
    for item in feedback_items:
        bottleneck = item.get("primary_bottleneck", "unknown")
        template = _EXPERIMENT_TEMPLATES.get(bottleneck)

        if not template:
            experiments.append({
                "position_id": item.get("position_id", "unknown"),
                "bottleneck": bottleneck,
                "experiment_type": "manual_review",
                "hypothesis": f"Investigate {bottleneck} bottleneck — no automatic template available",
                "parameters": {},
                "rationale": f"Bottleneck class '{bottleneck}' requires manual experiment design.",
                "confidence": 0.3,
            })
            continue

        experiments.append({
            "position_id": item.get("position_id", "unknown"),
            "bottleneck": bottleneck,
            "experiment_type": template["experiment_type"],
            "hypothesis": template["hypothesis"],
            "parameters": template["parameters"],
            "rationale": template["rationale"],
            "failed_checks": item.get("failed_checks", []),
            "confidence": item.get("confidence", 0.5),
        })

    # Deduplicate by bottleneck — if same bottleneck appears for multiple
    # positions, keep the one with highest confidence
    seen_bottlenecks: dict[str, dict] = {}
    for exp in experiments:
        bn = exp["bottleneck"]
        if bn not in seen_bottlenecks or exp["confidence"] > seen_bottlenecks[bn]["confidence"]:
            seen_bottlenecks[bn] = exp
    deduped = list(seen_bottlenecks.values())

    proposal = {
        "proposal_id": proposal_id,
        "created_at": now.isoformat(),
        "sigma_verdict": data.get("verdict", data.get("sigma_verdict", "")),
        "sigma_timestamp": sigma_feedback.get("timestamp", ""),
        "experiments_proposed": len(deduped),
        "experiments": deduped,
    }

    # Write atlas proposal packet
    write_packet(
        lane="atlas",
        packet_type="proposal",
        summary=f"Atlas: {len(deduped)} experiment(s) proposed from Sigma feedback | {proposal_id}",
        data=proposal,
        upstream=["sigma_feedback", "sigma_paper_validation"],
        source_module="atlas.proposal_generator",
        confidence=0.5,
    )

    # Write human-readable proposal
    _write_proposal_artifact(proposal, now)

    return proposal


def _feedback_from_validation(data: dict) -> list[dict]:
    """Extract feedback items from a raw Sigma validation packet."""
    verdict = data.get("verdict", "")
    if verdict in ("pass", "no_position", "no_data"):
        return []

    checks = data.get("checks", [])
    failed = [c for c in checks if c.get("status") in ("fail", "warn")]
    if not failed:
        return []

    # Group by position
    positions: dict[str, list[dict]] = {}
    for check in failed:
        pid = check.get("position_id", "unknown")
        positions.setdefault(pid, []).append(check)

    bottleneck_map = {
        "distance_to_stop": "stop_placement",
        "reward_risk_ratio": "risk_reward",
        "unrealized_pnl": "entry_timing",
        "scenario_contradiction": "thesis_alignment",
        "stop_out_probability": "risk_exposure",
        "distance_to_target": "target_placement",
    }

    items = []
    for pid, issues in positions.items():
        primary_check = issues[0]["check"]
        items.append({
            "position_id": pid,
            "primary_bottleneck": bottleneck_map.get(primary_check, "unknown"),
            "failed_checks": [
                {"check": c["check"], "status": c["status"],
                 "value": c.get("value"), "note": c.get("note", "")}
                for c in issues
            ],
            "confidence": 0.7 if any(c["status"] == "fail" for c in issues) else 0.4,
        })
    return items


def _write_proposal_artifact(proposal: dict, now: datetime) -> None:
    """Write human-readable proposal summary."""
    md = f"""# Atlas Experiment Proposal — {now.strftime('%Y-%m-%d %H:%M UTC')}

## Proposal `{proposal['proposal_id']}`

- **Sigma verdict**: {proposal['sigma_verdict']}
- **Experiments proposed**: {proposal['experiments_proposed']}
- **Source Sigma packet**: {proposal['sigma_timestamp']}

## Proposed Experiments

"""
    for i, exp in enumerate(proposal["experiments"], 1):
        md += f"""### {i}. {exp['experiment_type']} — {exp['bottleneck']}
- **Position**: `{exp['position_id']}`
- **Hypothesis**: {exp['hypothesis']}
- **Rationale**: {exp['rationale']}
- **Confidence**: {exp['confidence']:.0%}
"""
        if exp.get("parameters"):
            md += "- **Parameters**:\n"
            for k, v in exp["parameters"].items():
                md += f"  - `{k}`: {v}\n"

        if exp.get("failed_checks"):
            md += "- **Triggering failures**:\n"
            for c in exp["failed_checks"]:
                md += f"  - `{c['check']}` [{c['status']}]: {c.get('note', '')}\n"
        md += "\n"

    md += """## Next Steps

1. Review proposed experiments for feasibility
2. Submit approved experiments via `atlas/experiment_surface.py --submit`
3. Run experiments and feed results back through Sigma validation
"""

    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    (PROPOSALS_DIR / "latest.md").write_text(md)
    ts = now.strftime("%Y%m%dT%H%M%S")
    (PROPOSALS_DIR / f"proposal_{ts}.md").write_text(md)
    print(f"[atlas-proposal] Wrote proposal artifact → {PROPOSALS_DIR / 'latest.md'}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Atlas Proposal Generator")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    parser.add_argument("--submit", action="store_true",
                        help="Also submit top experiment to Atlas queue")
    args = parser.parse_args()

    proposal = generate_proposal()
    if not proposal:
        print("[atlas-proposal] No proposal generated")
        return

    if args.json:
        print(json.dumps(proposal, indent=2, default=str))

    if args.submit and proposal["experiments"]:
        from atlas.experiment_surface import submit_experiment

        top = proposal["experiments"][0]
        exp_id = submit_experiment(
            experiment_type=top["experiment_type"],
            hypothesis=top["hypothesis"],
            parameters=top["parameters"],
        )
        print(f"[atlas-proposal] Submitted top experiment as {exp_id}")


if __name__ == "__main__":
    main()
