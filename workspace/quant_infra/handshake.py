#!/usr/bin/env python3
"""Quant Event Handshake — orchestrates the full chain:

    Kitt event -> Salmon/Fish scenario refresh -> Sigma validation
    -> Rejection intelligence -> Jarvis summary

Each step is bounded, idempotent, and auditable. Safe to rerun.

Usage:
    python3 workspace/quant_infra/handshake.py                    # full chain
    python3 workspace/quant_infra/handshake.py --step salmon      # single step
    python3 workspace/quant_infra/handshake.py --step sigma
    python3 workspace/quant_infra/handshake.py --step rejection
    python3 workspace/quant_infra/handshake.py --step jarvis
    python3 workspace/quant_infra/handshake.py --status           # show chain state
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

QUANT_INFRA = Path(__file__).resolve().parent
HANDSHAKE_LOG = QUANT_INFRA / "logs" / "handshake"


def run_chain() -> dict:
    """Run the full handshake chain. Returns summary dict."""
    now = datetime.now(timezone.utc)
    results = {"started_at": now.isoformat(), "steps": {}}

    print("=" * 60)
    print(f"  QUANT EVENT HANDSHAKE — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # Step 1: Consume Kitt events -> Salmon scenario refresh
    print("\n[1/7] Salmon: consuming Kitt events + scenario refresh...")
    results["steps"]["salmon"] = _run_salmon()

    # Step 2: Sigma paper-trade validation
    print("\n[2/7] Sigma: paper-trade validation...")
    results["steps"]["sigma"] = _run_sigma()

    # Step 3: Sigma→Atlas feedback loop (automated)
    print("\n[3/7] Feedback loop: Sigma→Atlas experiment proposals...")
    results["steps"]["feedback_loop"] = _run_feedback_loop()

    # Step 4: Rejection intelligence — ingest + feedback export + scoreboard rebuild
    print("\n[4/7] Rejection intelligence: ingest + feedback export...")
    results["steps"]["rejection"] = _run_rejection_intelligence()

    # Step 5: Atlas — generate candidates from rejection feedback (cadence-gated)
    print("\n[5/7] Atlas: rejection-aware candidate generation...")
    results["steps"]["atlas"] = _run_atlas()

    # Step 6: Fish calibration — compare prior forecasts to outcomes
    print("\n[6/7] Fish: calibration sweep...")
    results["steps"]["calibration"] = _run_fish_calibration()

    # Step 7: Jarvis operator summary refresh + truth pack
    print("\n[7/7] Jarvis: operator summary + truth pack...")
    results["steps"]["jarvis"] = _run_jarvis()

    # Write handshake log
    results["completed_at"] = datetime.now(timezone.utc).isoformat()
    _write_handshake_log(results)

    print("\n" + "=" * 60)
    print("  HANDSHAKE COMPLETE")
    for step, info in results["steps"].items():
        status = info.get("status", "unknown")
        icon = "OK" if status == "ok" else "!!"
        print(f"  [{icon}] {step}: {info.get('summary', status)}")
    print("=" * 60)

    return results


def _run_salmon() -> dict:
    """Run Salmon event consumer + scenario refresh."""
    try:
        from salmon.event_consumer import consume_kitt_events
        count = consume_kitt_events()
        return {"status": "ok", "events_processed": count,
                "summary": f"{count} event(s) processed"}
    except Exception as exc:
        print(f"[handshake] Salmon error: {exc}")
        return {"status": "error", "error": str(exc), "summary": f"error: {exc}"}


def _run_sigma() -> dict:
    """Run Sigma paper-trade validation."""
    try:
        from sigma.paper_trade_validator import validate_paper_trade
        result = validate_paper_trade()
        return {"status": "ok", "verdict": result["verdict"],
                "flags": result["flags"],
                "summary": f"verdict={result['verdict']}, {result['flags']} flag(s)"}
    except Exception as exc:
        print(f"[handshake] Sigma error: {exc}")
        return {"status": "error", "error": str(exc), "summary": f"error: {exc}"}


def _run_feedback_loop() -> dict:
    """Run the Sigma→Atlas feedback loop automatically.

    Reads the latest Sigma validation packet, extracts structured feedback,
    and generates Atlas experiment proposals. Does NOT auto-submit experiments
    (that requires operator review).
    """
    try:
        from run_feedback_loop import run_feedback_loop
        result = run_feedback_loop(submit_top=False)
        status = result.get("status", "unknown")

        if status == "no_feedback":
            return {"status": "ok",
                    "summary": "no actionable Sigma feedback — skipped"}
        if status == "no_proposal":
            return {"status": "ok",
                    "summary": "feedback extracted but no proposal generated"}

        fb = result.get("feedback", {})
        pr = result.get("proposal", {})
        parts = [f"{pr.get('experiments_proposed', 0)} experiment(s) proposed"]
        if pr.get("bottlenecks"):
            parts.append(f"bottlenecks: {', '.join(pr['bottlenecks'][:3])}")
        if fb.get("total_failures"):
            parts.append(f"from {fb['total_failures']} Sigma failure(s)")

        return {"status": "ok", "feedback_result": result,
                "summary": "; ".join(parts)}
    except Exception as exc:
        print(f"[handshake] Feedback loop error: {exc}")
        return {"status": "error", "error": str(exc), "summary": f"error: {exc}"}


def _run_atlas() -> dict:
    """Run Atlas candidate generation, gated by governor cadence.

    Atlas only generates if enough time has elapsed since the last batch
    (per governor cadence_multiplier). This prevents every handshake from
    triggering a full Atlas cycle — spec §2 says Atlas cadence is 4-8h.
    """
    try:
        REPO_ROOT = QUANT_INFRA.parent.parent
        sys.path.insert(0, str(REPO_ROOT))
        from workspace.quant.shared.governor import get_lane_params

        params = get_lane_params(REPO_ROOT, "atlas")
        if params.get("paused"):
            return {"status": "ok", "summary": "atlas paused by governor — skipped"}

        # Cadence gate: check if atlas last ran recently enough
        # Default cadence = 4h, multiplier adjusts it
        base_cadence_seconds = 4 * 3600  # 4 hours
        multiplier = params.get("cadence_multiplier", 1.0)
        required_gap = base_cadence_seconds * multiplier

        # Read latest atlas health summary for last run time
        health_path = REPO_ROOT / "workspace" / "quant" / "shared" / "latest" / "atlas_health_summary.json"
        if health_path.exists():
            import json as _json
            try:
                health = _json.loads(health_path.read_text())
                last_run = health.get("created_at", "")
                if last_run:
                    last_ts = datetime.fromisoformat(last_run)
                    elapsed = (datetime.now(timezone.utc) - last_ts).total_seconds()
                    if elapsed < required_gap:
                        return {"status": "ok",
                                "summary": (f"atlas cadence gate: {elapsed/3600:.1f}h since last run, "
                                            f"need {required_gap/3600:.1f}h — skipped")}
            except (ValueError, OSError):
                pass

        # Run Atlas batch via exploration_lane
        from workspace.quant.atlas.exploration_lane import (
            generate_candidate_batch, ingest_rejections,
        )
        import hashlib

        knowledge = ingest_rejections(REPO_ROOT)
        avoidance = knowledge.get("avoidance_patterns", [])
        avoidance_str = ", ".join(avoidance[:3]) if avoidance else "none"

        # Generate a small batch of candidates
        batch_size = params.get("batch_size", 1)
        ts_hash = hashlib.sha256(datetime.now(timezone.utc).isoformat().encode()).hexdigest()[:8]
        stubs = []
        for i in range(batch_size):
            stubs.append({
                "strategy_id": f"atlas-auto-{ts_hash}-{i}",
                "thesis": f"NQ mean-reversion variant {i} (rejection-aware, avoidance: {avoidance_str})",
            })

        batch_pkt, candidates, info = generate_candidate_batch(REPO_ROOT, stubs)
        generated = info.get("generated", 0)
        skipped = info.get("skipped", 0)
        dedup = info.get("dedup_blocked", 0)

        summary = f"{generated} candidate(s) generated"
        if skipped:
            summary += f", {skipped} skipped"
        if dedup:
            summary += f", {dedup} dedup-blocked"
        if avoidance:
            summary += f"; avoiding: {avoidance_str}"

        return {"status": "ok", "generated": generated, "summary": summary}

    except Exception as exc:
        print(f"[handshake] Atlas error: {exc}")
        return {"status": "error", "error": str(exc), "summary": f"error: {exc}"}


def _run_fish_calibration() -> dict:
    """Run Fish calibration sweep — compare past forecasts to actual outcomes.

    Per spec §6: Fish periodically compares forecasts to outcomes and
    adjusts confidence weights via calibration_packet.
    """
    try:
        REPO_ROOT = QUANT_INFRA.parent.parent
        sys.path.insert(0, str(REPO_ROOT))
        from workspace.quant.fish.scenario_lane import (
            get_pending_forecasts, build_calibration_state,
        )

        # Check for forecasts that haven't been calibrated yet
        pending = get_pending_forecasts(REPO_ROOT)
        if not pending:
            # Even without pending forecasts, build state for confidence tracking
            cal_state = build_calibration_state(REPO_ROOT)
            confidence = cal_state.get("track_record_confidence", 1.0)
            return {"status": "ok",
                    "summary": f"no pending forecasts; track confidence={confidence:.2f}"}

        # Build calibration state (this compares forecasts to outcomes)
        cal_state = build_calibration_state(REPO_ROOT)
        confidence = cal_state.get("track_record_confidence", 1.0)
        calibrated = cal_state.get("calibration_count", 0)
        pending_count = len(pending)

        summary = (f"{pending_count} forecast(s) pending calibration; "
                   f"{calibrated} calibrated; confidence={confidence:.2f}")

        return {"status": "ok", "calibrated": calibrated,
                "pending": pending_count, "confidence": confidence,
                "summary": summary}

    except Exception as exc:
        print(f"[handshake] Fish calibration error: {exc}")
        return {"status": "error", "error": str(exc), "summary": f"error: {exc}"}


def _run_rejection_intelligence() -> dict:
    """Run rejection intelligence: ingest new packets + export feedback + rebuild scoreboards."""
    try:
        from rejection_ingest import run_full
        result = run_full()
        ingest = result["ingest"]
        export = result["export"]
        parts = [f"{ingest['new_records']} new rejection(s) ingested"]
        if export.get("exported"):
            parts.append(f"feedback exported ({export['total_records']} total)")
            if export.get("atlas_cooldown_families"):
                parts.append(f"cooldown: {export['atlas_cooldown_families']}")
        else:
            parts.append(f"no feedback: {export.get('reason', '')}")

        # Auto-rebuild scoreboards after ingest (consumption plan Step 4)
        scoreboard_rebuilt = False
        try:
            REPO_ROOT = QUANT_INFRA.parent.parent
            sys.path.insert(0, str(REPO_ROOT))
            from runtime.quant.rejection_ledger import RejectionLedger
            from runtime.quant.rejection_scoreboard import write_scoreboards
            ledger = RejectionLedger()
            records = ledger.read_all()
            if records:
                scoreboard_dir = REPO_ROOT / "state" / "quant" / "rejections"
                scoreboard_dir.mkdir(parents=True, exist_ok=True)
                write_scoreboards(ledger, output_dir=scoreboard_dir)
                scoreboard_rebuilt = True
                parts.append("scoreboards rebuilt")
        except Exception as sb_exc:
            print(f"[handshake] Scoreboard rebuild warning: {sb_exc}")

        summary = "; ".join(parts)
        return {"status": "ok", "ingest": ingest, "export": export,
                "scoreboard_rebuilt": scoreboard_rebuilt,
                "summary": summary}
    except Exception as exc:
        print(f"[handshake] Rejection intelligence error: {exc}")
        return {"status": "error", "error": str(exc), "summary": f"error: {exc}"}


def _run_jarvis() -> dict:
    """Run Jarvis operator summary refresh + truth pack generation."""
    parts = []
    try:
        from jarvis.observability import generate_operator_report
        report = generate_operator_report()

        # Write report
        logs_dir = QUANT_INFRA / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        (logs_dir / "latest_operator_report.txt").write_text(report)
        ts = now.strftime("%Y%m%dT%H%M%S")
        (logs_dir / f"operator_report_{ts}.txt").write_text(report)
        parts.append("operator report refreshed")

        # Generate unified truth pack
        try:
            from jarvis.truth_pack import build_truth_pack, write_truth_pack
            pack = build_truth_pack()
            json_path, md_path = write_truth_pack(pack)
            parts.append("truth pack generated")
        except Exception as tp_exc:
            print(f"[handshake] Truth pack warning: {tp_exc}")
            parts.append(f"truth pack error: {tp_exc}")

        return {"status": "ok", "summary": "; ".join(parts)}
    except Exception as exc:
        print(f"[handshake] Jarvis error: {exc}")
        return {"status": "error", "error": str(exc), "summary": f"error: {exc}"}


def get_chain_status() -> dict:
    """Show current state of the handshake chain."""
    from packets.writer import read_packet
    from events.emitter import read_pending, get_latest_event

    status = {}

    # Kitt events
    pending = read_pending("kitt")
    latest = get_latest_event("kitt")
    status["kitt_events"] = {
        "pending_count": len(pending),
        "latest_event": {
            "event_id": latest["event_id"],
            "event_type": latest["event_type"],
            "timestamp": latest["timestamp"],
        } if latest else None,
    }

    # Lane packets
    for lane in ["kitt", "fish", "sigma"]:
        pkt = read_packet(lane)
        if pkt:
            status[f"{lane}_packet"] = {
                "type": pkt.get("packet_type"),
                "timestamp": pkt.get("timestamp"),
                "summary": pkt.get("summary", "")[:80],
            }
        else:
            status[f"{lane}_packet"] = None

    # Latest handshake log
    log_dir = HANDSHAKE_LOG
    if log_dir.exists():
        logs = sorted(log_dir.glob("*.json"), reverse=True)
        if logs:
            try:
                latest_log = json.loads(logs[0].read_text())
                status["last_handshake"] = {
                    "started_at": latest_log.get("started_at"),
                    "completed_at": latest_log.get("completed_at"),
                    "steps": {
                        k: v.get("status") for k, v in latest_log.get("steps", {}).items()
                    },
                }
            except (json.JSONDecodeError, OSError):
                pass

    return status


def _write_handshake_log(results: dict) -> None:
    """Write handshake run log."""
    HANDSHAKE_LOG.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S")
    path = HANDSHAKE_LOG / f"handshake_{ts}.json"
    path.write_text(json.dumps(results, indent=2, default=str) + "\n")
    (HANDSHAKE_LOG / "latest.json").write_text(json.dumps(results, indent=2, default=str) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Quant Event Handshake")
    parser.add_argument("--step", type=str,
                        choices=["salmon", "sigma", "feedback_loop", "rejection",
                                 "atlas", "calibration", "jarvis"],
                        help="Run a single step")
    parser.add_argument("--status", action="store_true", help="Show chain status")
    args = parser.parse_args()

    if args.status:
        status = get_chain_status()
        print(json.dumps(status, indent=2, default=str))
    elif args.step == "salmon":
        _run_salmon()
    elif args.step == "sigma":
        _run_sigma()
    elif args.step == "feedback_loop":
        _run_feedback_loop()
    elif args.step == "rejection":
        _run_rejection_intelligence()
    elif args.step == "atlas":
        _run_atlas()
    elif args.step == "calibration":
        _run_fish_calibration()
    elif args.step == "jarvis":
        _run_jarvis()
    else:
        run_chain()


if __name__ == "__main__":
    main()
