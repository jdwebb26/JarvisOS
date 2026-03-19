#!/usr/bin/env python3
"""Atlas ← Strategy Factory Bridge.

Feeds strategy factory results into Atlas for automated candidate generation.
Reads STRATEGIES.jsonl and CANDIDATE_HISTORY.jsonl from the factory workspace,
extracts high-performing families and parameter ranges, and generates Atlas
candidate theses.

This closes the loop: Factory discovers → Atlas refines → Sigma validates →
Factory learns from rejections.

Usage:
    python3 workspace/quant_infra/atlas/factory_bridge.py
    python3 workspace/quant_infra/atlas/factory_bridge.py --status
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QUANT_INFRA = Path(__file__).resolve().parent.parent
REPO_ROOT = QUANT_INFRA.parent.parent
sys.path.insert(0, str(QUANT_INFRA))
sys.path.insert(0, str(REPO_ROOT))

FACTORY_WORKSPACE = Path.home() / ".openclaw" / "workspace"
STRATEGIES_JSONL = FACTORY_WORKSPACE / "STRATEGIES.jsonl"
CANDIDATE_HISTORY_JSONL = FACTORY_WORKSPACE / "CANDIDATE_HISTORY.jsonl"
ARTIFACTS_DIR = FACTORY_WORKSPACE / "artifacts" / "strategy_factory"


def load_factory_strategies() -> list[dict]:
    """Load all strategies from STRATEGIES.jsonl."""
    strategies = []
    if not STRATEGIES_JSONL.exists():
        return strategies
    try:
        for line in STRATEGIES_JSONL.read_text().strip().splitlines():
            if line.strip():
                strategies.append(json.loads(line))
    except (json.JSONDecodeError, OSError):
        pass
    return strategies


def load_candidate_history() -> list[dict]:
    """Load full candidate history from CANDIDATE_HISTORY.jsonl."""
    history = []
    if not CANDIDATE_HISTORY_JSONL.exists():
        return history
    try:
        for line in CANDIDATE_HISTORY_JSONL.read_text().strip().splitlines():
            if line.strip():
                history.append(json.loads(line))
    except (json.JSONDecodeError, OSError):
        pass
    return history


def analyze_factory_output() -> dict:
    """Analyze factory output to extract signals for Atlas.

    Returns:
        {
            "total_strategies": int,
            "total_candidates": int,
            "families": {family: {count, avg_score, best_score, pass_rate, best_params}},
            "top_families": [family_name],  # ranked by best_score
            "struggling_families": [family_name],  # low pass rate
            "parameter_insights": {family: {param: {min, max, mean_best}}}
            "recommendations": [str],
        }
    """
    strategies = load_factory_strategies()
    history = load_candidate_history()

    # Analyze by family
    family_data: dict[str, dict[str, Any]] = {}
    for s in strategies:
        fam = s.get("logic_family_id", "unknown")
        if fam not in family_data:
            family_data[fam] = {
                "count": 0, "scores": [], "pass_count": 0, "fail_count": 0,
                "params_list": [], "best_score": 0, "best_params": {},
            }
        fd = family_data[fam]
        fd["count"] += 1
        score = s.get("score", 0)
        fd["scores"].append(score)
        if s.get("gate_overall") == "PASS":
            fd["pass_count"] += 1
        else:
            fd["fail_count"] += 1
        if score > fd["best_score"]:
            fd["best_score"] = score
            fd["best_params"] = s.get("params", {})
        fd["params_list"].append(s.get("params", {}))

    # Also count rejections from history
    for h in history:
        fam = h.get("family", h.get("logic_family_id", "unknown"))
        if fam not in family_data:
            family_data[fam] = {
                "count": 0, "scores": [], "pass_count": 0, "fail_count": 0,
                "params_list": [], "best_score": 0, "best_params": {},
            }
        if h.get("status") == "rejected":
            family_data[fam]["fail_count"] += 1

    # Build family summaries
    families = {}
    for fam, fd in family_data.items():
        total = fd["pass_count"] + fd["fail_count"]
        pass_rate = fd["pass_count"] / max(total, 1)
        avg_score = sum(fd["scores"]) / len(fd["scores"]) if fd["scores"] else 0

        families[fam] = {
            "candidate_count": fd["count"],
            "avg_score": round(avg_score, 3),
            "best_score": round(fd["best_score"], 3),
            "pass_rate": round(pass_rate, 2),
            "best_params": fd["best_params"],
        }

    # Rank families
    ranked = sorted(families.items(), key=lambda x: -x[1]["best_score"])
    top_families = [f for f, _ in ranked[:3]]
    struggling = [f for f, info in families.items() if info["pass_rate"] < 0.3 and info["candidate_count"] >= 3]

    # Parameter insights: for top families, extract parameter ranges from passing candidates
    param_insights: dict[str, dict] = {}
    for fam, fd in family_data.items():
        if not fd["params_list"]:
            continue
        insights: dict[str, dict] = {}
        # Get all parameter keys
        all_keys: set[str] = set()
        for p in fd["params_list"]:
            all_keys.update(p.keys())
        for key in all_keys:
            vals = [p[key] for p in fd["params_list"] if key in p and isinstance(p[key], (int, float))]
            if vals:
                insights[key] = {
                    "min": round(min(vals), 3),
                    "max": round(max(vals), 3),
                    "mean": round(sum(vals) / len(vals), 3),
                }
        if insights:
            param_insights[fam] = insights

    # Generate recommendations
    recommendations = []
    if top_families:
        recommendations.append(
            f"Prioritize mutations in top families: {', '.join(top_families)}"
        )
    if struggling:
        recommendations.append(
            f"Consider cooldown for struggling families: {', '.join(struggling)}"
        )
    for fam in top_families[:2]:
        if fam in param_insights:
            pi = param_insights[fam]
            param_summary = ", ".join(f"{k}=[{v['min']},{v['max']}]" for k, v in list(pi.items())[:3])
            recommendations.append(f"For {fam}: explore within {param_summary}")

    return {
        "total_strategies": len(strategies),
        "total_candidates": len(history),
        "families": families,
        "top_families": top_families,
        "struggling_families": struggling,
        "parameter_insights": param_insights,
        "recommendations": recommendations,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


def generate_atlas_theses(analysis: dict, max_theses: int = 3) -> list[dict]:
    """Generate Atlas candidate theses from factory analysis.

    Creates theses that leverage factory insights: parameter ranges from
    top-performing families, avoidance of struggling families, and
    mutation directions from parameter insights.
    """
    theses = []
    families = analysis.get("families", {})
    param_insights = analysis.get("parameter_insights", {})
    top = analysis.get("top_families", [])
    struggling = set(analysis.get("struggling_families", []))

    # Map factory families to signal families
    family_map = {
        "ema_crossover": "ema_mean_reversion",
        "ema_crossover_cd": "ema_mean_reversion",
        "mean_reversion": "ema_mean_reversion",
        "breakout": "breakout",
        "momentum": "momentum",
        "trend_following": "trend_following",
        "vwap_reversion": "vwap_reversion",
    }

    for fam in top[:max_theses]:
        if fam in struggling:
            continue

        info = families.get(fam, {})
        params = info.get("best_params", {})
        pi = param_insights.get(fam, {})
        signal_family = family_map.get(fam, fam)

        # Build thesis from factory insights
        param_desc = ", ".join(f"{k}={v}" for k, v in list(params.items())[:4])
        range_desc = ""
        if pi:
            range_desc = " Explore within: " + ", ".join(
                f"{k}=[{v['min']},{v['max']}]" for k, v in list(pi.items())[:3]
            )

        thesis = {
            "strategy_id": f"factory-{fam}-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            "thesis": (
                f"NQ {signal_family} variant derived from factory analysis. "
                f"Best factory score: {info.get('best_score', 0):.3f} with params ({param_desc}). "
                f"Pass rate: {info.get('pass_rate', 0):.0%} across {info.get('candidate_count', 0)} candidates."
                f"{range_desc}"
            ),
            "source": "factory_bridge",
            "factory_family": fam,
            "signal_family": signal_family,
            "base_params": params,
            "confidence": min(0.7, info.get("pass_rate", 0.3) + 0.2),
        }
        theses.append(thesis)

    return theses


def ingest_factory_results() -> dict:
    """Full factory bridge cycle: analyze + generate theses + submit to Atlas.

    Returns summary dict.
    """
    analysis = analyze_factory_output()

    if analysis["total_strategies"] == 0 and analysis["total_candidates"] == 0:
        return {
            "status": "no_data",
            "summary": "No factory results to ingest",
        }

    theses = generate_atlas_theses(analysis)

    # Submit theses to Atlas via exploration_lane
    submitted = 0
    skipped = 0
    try:
        from workspace.quant.atlas.exploration_lane import generate_candidate

        for thesis in theses:
            try:
                pkt, feedback = generate_candidate(
                    root=REPO_ROOT,
                    thesis=thesis["thesis"],
                    strategy_id=thesis["strategy_id"],
                    confidence=thesis["confidence"],
                )
                if feedback.get("status") == "submitted":
                    submitted += 1
                else:
                    skipped += 1
            except Exception as exc:
                print(f"[factory-bridge] Candidate generation error: {exc}")
                skipped += 1
    except ImportError as exc:
        print(f"[factory-bridge] Atlas import error: {exc}")

    # Write bridge artifact
    artifact = {
        "analyzed_at": analysis["analyzed_at"],
        "total_factory_strategies": analysis["total_strategies"],
        "total_factory_candidates": analysis["total_candidates"],
        "top_families": analysis["top_families"],
        "theses_generated": len(theses),
        "submitted_to_atlas": submitted,
        "skipped": skipped,
        "recommendations": analysis["recommendations"],
    }
    bridge_dir = QUANT_INFRA / "research" / "factory_bridge"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    (bridge_dir / "latest.json").write_text(json.dumps(artifact, indent=2) + "\n")

    return {
        "status": "ok",
        "analysis": analysis,
        "theses": len(theses),
        "submitted": submitted,
        "skipped": skipped,
        "summary": (
            f"{analysis['total_strategies']} strategies analyzed, "
            f"{len(theses)} theses generated, "
            f"{submitted} submitted to Atlas"
        ),
    }


def get_status() -> dict:
    """Return factory bridge status."""
    strategies = load_factory_strategies()
    history = load_candidate_history()
    return {
        "strategies_count": len(strategies),
        "history_count": len(history),
        "strategies_file": str(STRATEGIES_JSONL),
        "history_file": str(CANDIDATE_HISTORY_JSONL),
        "strategies_exists": STRATEGIES_JSONL.exists(),
        "history_exists": CANDIDATE_HISTORY_JSONL.exists(),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Atlas ← Factory Bridge")
    parser.add_argument("--status", action="store_true", help="Show bridge status")
    parser.add_argument("--analyze", action="store_true", help="Analyze factory output only")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    if args.status:
        status = get_status()
        print(json.dumps(status, indent=2))
    elif args.analyze:
        analysis = analyze_factory_output()
        if args.json:
            print(json.dumps(analysis, indent=2, default=str))
        else:
            print(f"Strategies: {analysis['total_strategies']}")
            print(f"Candidates: {analysis['total_candidates']}")
            print(f"Top families: {analysis['top_families']}")
            if analysis['recommendations']:
                print("\nRecommendations:")
                for r in analysis['recommendations']:
                    print(f"  - {r}")
    else:
        result = ingest_factory_results()
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"[factory-bridge] {result.get('summary', result.get('status'))}")


if __name__ == "__main__":
    main()
