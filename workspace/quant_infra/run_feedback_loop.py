#!/usr/bin/env python3
"""Sigma → Atlas Feedback Loop Runner.

Reads the latest Sigma validation packet, extracts structured feedback,
and generates an Atlas experiment proposal. This is the bounded entry
point for the closed-loop between Sigma and Atlas.

Usage:
    .venv/bin/python3 workspace/quant_infra/run_feedback_loop.py
    .venv/bin/python3 workspace/quant_infra/run_feedback_loop.py --submit
    .venv/bin/python3 workspace/quant_infra/run_feedback_loop.py --status
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sigma.feedback_extractor import extract_feedback
from atlas.proposal_generator import generate_proposal
from packets.writer import read_packet


def run_feedback_loop(*, submit_top: bool = False) -> dict:
    """Execute the Sigma → Atlas feedback loop.

    Steps:
    1. Extract structured feedback from Sigma's latest packet
    2. Generate Atlas experiment proposal from that feedback
    3. Optionally submit the top experiment to the Atlas queue

    Returns a summary dict.
    """
    print("=" * 60)
    print("Sigma → Atlas Feedback Loop")
    print("=" * 60)

    # Step 1: Extract Sigma feedback
    print("\n[1/2] Extracting Sigma feedback...")
    feedback = extract_feedback()
    if not feedback:
        return {
            "status": "no_feedback",
            "reason": "Sigma has no actionable issues",
        }

    # Step 2: Generate Atlas proposal
    print("\n[2/2] Generating Atlas experiment proposal...")
    proposal = generate_proposal()
    if not proposal:
        return {
            "status": "no_proposal",
            "reason": "Could not generate proposal from feedback",
            "feedback_extracted": True,
        }

    # Step 3: Optional submit
    if submit_top and proposal["experiments"]:
        from atlas.experiment_surface import submit_experiment

        top = proposal["experiments"][0]
        exp_id = submit_experiment(
            experiment_type=top["experiment_type"],
            hypothesis=top["hypothesis"],
            parameters=top["parameters"],
        )
        proposal["submitted_experiment_id"] = exp_id
        print(f"\n[submit] Top experiment submitted as {exp_id}")

    print("\n" + "=" * 60)
    print(f"Loop complete: {proposal['experiments_proposed']} experiment(s) proposed")
    print("=" * 60)

    return {
        "status": "ok",
        "feedback": {
            "sigma_verdict": feedback["sigma_verdict"],
            "positions_with_issues": feedback["positions_with_issues"],
            "total_failures": feedback["total_failures"],
        },
        "proposal": {
            "proposal_id": proposal["proposal_id"],
            "experiments_proposed": proposal["experiments_proposed"],
            "bottlenecks": [e["bottleneck"] for e in proposal["experiments"]],
        },
    }


def show_status() -> None:
    """Show current state of the feedback loop artifacts."""
    qi = Path(__file__).resolve().parent

    print("\n=== Sigma → Atlas Feedback Loop Status ===\n")

    sigma = read_packet("sigma")
    if sigma:
        print(f"Sigma packet: {sigma.get('packet_type')} @ {sigma.get('timestamp', '?')}")
        print(f"  verdict: {sigma.get('data', {}).get('verdict', 'N/A')}")
    else:
        print("Sigma packet: NOT FOUND")

    atlas = read_packet("atlas")
    if atlas:
        print(f"Atlas packet: {atlas.get('packet_type')} @ {atlas.get('timestamp', '?')}")
        print(f"  summary: {atlas.get('summary', 'N/A')}")
    else:
        print("Atlas packet: NOT FOUND")

    feedback_latest = qi / "research" / "sigma_feedback" / "latest.md"
    if feedback_latest.exists():
        print(f"Sigma feedback artifact: {feedback_latest}")
    else:
        print("Sigma feedback artifact: NOT CREATED")

    proposal_latest = qi / "research" / "atlas_proposals" / "latest.md"
    if proposal_latest.exists():
        print(f"Atlas proposal artifact: {proposal_latest}")
    else:
        print("Atlas proposal artifact: NOT CREATED")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Sigma → Atlas Feedback Loop Runner"
    )
    parser.add_argument("--submit", action="store_true",
                        help="Submit the top experiment to Atlas queue")
    parser.add_argument("--status", action="store_true",
                        help="Show current feedback loop state")
    parser.add_argument("--json", action="store_true",
                        help="Output result as JSON")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    result = run_feedback_loop(submit_top=args.submit)

    if args.json:
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
