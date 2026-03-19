#!/usr/bin/env python3
"""Sigma Feedback Extractor — normalize Sigma validation results into
structured feedback that Atlas can consume.

Reads the latest Sigma packet and produces a feedback artifact with:
- source position/candidate ID
- verdict and failed checks
- bottleneck classification
- suggested mutation direction
- confidence

Usage:
    .venv/bin/python3 workspace/quant_infra/sigma/feedback_extractor.py
    .venv/bin/python3 workspace/quant_infra/sigma/feedback_extractor.py --json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packets.writer import read_packet, write_packet

QUANT_INFRA = Path(__file__).resolve().parent.parent
FEEDBACK_DIR = QUANT_INFRA / "research" / "sigma_feedback"

# Maps check names to bottleneck classes and mutation hints
_BOTTLENECK_MAP: dict[str, dict[str, str]] = {
    "distance_to_stop": {
        "bottleneck": "stop_placement",
        "mutation": "widen stop or tighten entry criteria",
    },
    "reward_risk_ratio": {
        "bottleneck": "risk_reward",
        "mutation": "increase target distance or reduce stop distance",
    },
    "unrealized_pnl": {
        "bottleneck": "entry_timing",
        "mutation": "improve entry signal or add confirmation filter",
    },
    "scenario_contradiction": {
        "bottleneck": "thesis_alignment",
        "mutation": "add scenario-aware entry filter or regime gate",
    },
    "stop_out_probability": {
        "bottleneck": "risk_exposure",
        "mutation": "reduce position size or add volatility filter",
    },
    "distance_to_target": {
        "bottleneck": "target_placement",
        "mutation": "adjust target based on recent range or ATR",
    },
}


def extract_feedback() -> dict | None:
    """Read latest Sigma packet and produce structured feedback.

    Returns None if no Sigma packet exists or verdict is 'pass'.
    """
    sigma = read_packet("sigma")
    if not sigma:
        print("[sigma-feedback] No Sigma packet found")
        return None

    data = sigma.get("data", {})
    verdict = data.get("verdict", "")

    if verdict == "pass":
        print("[sigma-feedback] Sigma verdict is pass — no feedback needed")
        return None

    if verdict == "no_position":
        print("[sigma-feedback] No open positions — no feedback needed")
        return None

    checks = data.get("checks", [])
    failed_checks = [c for c in checks if c.get("status") == "fail"]
    warned_checks = [c for c in checks if c.get("status") == "warn"]

    if not failed_checks and not warned_checks:
        print("[sigma-feedback] No failed or warned checks — no feedback needed")
        return None

    now = datetime.now(timezone.utc)

    # Group failures by position
    positions: dict[str, list[dict]] = {}
    for check in failed_checks + warned_checks:
        pid = check.get("position_id", "unknown")
        positions.setdefault(pid, []).append(check)

    feedback_items = []
    for position_id, issues in positions.items():
        # Determine primary bottleneck from the worst failure
        primary_check = issues[0]
        check_name = primary_check.get("check", "unknown")
        mapping = _BOTTLENECK_MAP.get(check_name, {})

        bottleneck = mapping.get("bottleneck", "unknown")
        mutation_hint = mapping.get("mutation", "review manually")

        # Gather all bottleneck classes
        all_bottlenecks = []
        for issue in issues:
            cn = issue.get("check", "")
            m = _BOTTLENECK_MAP.get(cn, {})
            if m.get("bottleneck"):
                all_bottlenecks.append(m["bottleneck"])

        feedback_items.append({
            "position_id": position_id,
            "verdict": verdict,
            "failed_checks": [
                {
                    "check": c["check"],
                    "status": c["status"],
                    "value": c.get("value"),
                    "note": c.get("note", ""),
                }
                for c in issues
            ],
            "primary_bottleneck": bottleneck,
            "all_bottlenecks": list(dict.fromkeys(all_bottlenecks)),
            "suggested_mutation": mutation_hint,
            "confidence": 0.7 if any(c["status"] == "fail" for c in issues) else 0.4,
        })

    feedback = {
        "extracted_at": now.isoformat(),
        "sigma_verdict": verdict,
        "sigma_timestamp": sigma.get("timestamp", ""),
        "positions_with_issues": len(feedback_items),
        "total_failures": len(failed_checks),
        "total_warnings": len(warned_checks),
        "feedback": feedback_items,
    }

    # Write feedback packet
    write_packet(
        lane="sigma",
        packet_type="feedback",
        summary=f"Sigma feedback: {len(feedback_items)} position(s) with issues | {len(failed_checks)} failures, {len(warned_checks)} warnings",
        data=feedback,
        upstream=["sigma_paper_validation"],
        source_module="sigma.feedback_extractor",
        confidence=0.6,
    )

    # Write human-readable artifact
    _write_feedback_artifact(feedback, now)

    return feedback


def _write_feedback_artifact(feedback: dict, now: datetime) -> None:
    """Write human-readable feedback summary."""
    md = f"""# Sigma Feedback — {now.strftime('%Y-%m-%d %H:%M UTC')}

## Summary
- **Verdict**: {feedback['sigma_verdict']}
- **Positions with issues**: {feedback['positions_with_issues']}
- **Total failures**: {feedback['total_failures']}
- **Total warnings**: {feedback['total_warnings']}

## Issues by Position

"""
    for item in feedback["feedback"]:
        md += f"""### Position `{item['position_id']}`
- **Primary bottleneck**: {item['primary_bottleneck']}
- **Suggested mutation**: {item['suggested_mutation']}
- **Confidence**: {item['confidence']:.0%}
- **Failed checks**:
"""
        for check in item["failed_checks"]:
            md += f"  - `{check['check']}` [{check['status']}]: {check['note']}\n"
        md += "\n"

    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    (FEEDBACK_DIR / "latest.md").write_text(md)
    ts = now.strftime("%Y%m%dT%H%M%S")
    (FEEDBACK_DIR / f"feedback_{ts}.md").write_text(md)
    print(f"[sigma-feedback] Wrote feedback artifact → {FEEDBACK_DIR / 'latest.md'}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Sigma Feedback Extractor")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    args = parser.parse_args()

    feedback = extract_feedback()
    if feedback and args.json:
        print(json.dumps(feedback, indent=2, default=str))
    elif not feedback:
        print("[sigma-feedback] No actionable feedback to extract")


if __name__ == "__main__":
    main()
