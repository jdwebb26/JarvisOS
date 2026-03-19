#!/usr/bin/env python3
"""Sigma paper-trade validator — bounded validation of live paper-trade context.

NOT strategy_factory promotion logic. This is a lightweight validation
packet around the live paper-trade context that evaluates:

- Reward/risk ratio
- Distance to stop/target
- Regime mismatch vs Fish scenario context
- Whether Fish scenarios materially contradict Kitt thesis
- Whether confidence should be reduced / position flagged

Reads Kitt and Fish packets. Writes a Sigma validation packet and
a concise operator-facing markdown note.

Usage:
    python3 workspace/quant_infra/sigma/paper_trade_validator.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packets.writer import write_packet, read_packet

QUANT_INFRA = Path(__file__).resolve().parent.parent
VALIDATION_DIR = QUANT_INFRA / "research" / "sigma_validations"


def validate_paper_trade() -> dict:
    """Run paper-trade validation against current Kitt + Fish state.

    Returns the validation result dict.
    """
    now = datetime.now(timezone.utc)

    # Read latest packets
    kitt_packet = read_packet("kitt")
    fish_packet = read_packet("fish")

    if not kitt_packet:
        return _write_result("no_data", "No Kitt packet available", now)

    kitt_data = kitt_packet.get("data", {})
    open_positions = kitt_data.get("open_positions", [])

    if not open_positions:
        return _write_result("no_position", "No open paper positions to validate", now)

    # Validate each open position
    checks = []
    overall_verdict = "pass"
    flags = []

    for pos in open_positions:
        pos_checks = _validate_position(pos, fish_packet, kitt_packet)
        checks.extend(pos_checks)

        pos_flags = [c for c in pos_checks if c["status"] != "pass"]
        if pos_flags:
            flags.extend(pos_flags)
            # Escalate verdict
            for f in pos_flags:
                if f["status"] == "fail":
                    overall_verdict = "flag"
                elif f["status"] == "warn" and overall_verdict == "pass":
                    overall_verdict = "caution"

    result = {
        "validated_at": now.isoformat(),
        "verdict": overall_verdict,
        "positions_checked": len(open_positions),
        "checks_run": len(checks),
        "flags": len(flags),
        "checks": checks,
        "summary": _build_summary(overall_verdict, open_positions, flags),
    }

    # Write Sigma packet
    write_packet(
        lane="sigma",
        packet_type="paper_validation",
        summary=f"Sigma paper-trade validation: {overall_verdict} | {len(flags)} flag(s) across {len(open_positions)} position(s)",
        data=result,
        upstream=["kitt_quant", "fish_scenario"],
        source_module="sigma.paper_trade_validator",
        confidence=0.7 if overall_verdict == "pass" else 0.5,
    )

    # Write markdown note
    _write_validation_note(result, open_positions, now)

    print(f"[sigma] Paper-trade validation: {overall_verdict} ({len(flags)} flags)")
    return result


def _validate_position(pos: dict, fish_packet: dict | None, kitt_packet: dict) -> list[dict]:
    """Run validation checks against a single position."""
    checks = []
    pos_id = pos.get("id", pos.get("position_id", "unknown"))
    entry = pos.get("entry", pos.get("entry_price"))
    stop = pos.get("stop", pos.get("stop_loss"))
    target = pos.get("target", pos.get("take_profit"))
    mark = pos.get("mark", pos.get("mark_price"))
    direction = pos.get("direction", "unknown")

    # 1. Reward/Risk Ratio
    if entry and stop and target:
        risk = abs(entry - stop)
        reward = abs(target - entry)
        rr_ratio = reward / risk if risk > 0 else 0

        status = "pass"
        note = f"R/R = {rr_ratio:.2f}"
        if rr_ratio < 0.5:
            status = "fail"
            note += " — reward too small relative to risk"
        elif rr_ratio < 1.0:
            status = "warn"
            note += " — below 1:1, marginal"

        checks.append({
            "check": "reward_risk_ratio",
            "position_id": pos_id,
            "status": status,
            "value": round(rr_ratio, 2),
            "note": note,
        })

    # 2. Distance to Stop
    if mark and stop:
        distance_to_stop = abs(mark - stop)
        if direction == "long":
            distance_pct = (mark - stop) / mark * 100 if mark > 0 else 0
            approaching = mark <= stop * 1.005  # within 0.5% of stop
        else:
            distance_pct = (stop - mark) / mark * 100 if mark > 0 else 0
            approaching = mark >= stop * 0.995

        status = "pass"
        note = f"Distance to stop: {distance_to_stop:.2f} pts ({distance_pct:.1f}%)"
        if approaching:
            status = "fail"
            note += " — AT or PAST stop level"
        elif distance_pct < 0.3:
            status = "warn"
            note += " — very close to stop"

        checks.append({
            "check": "distance_to_stop",
            "position_id": pos_id,
            "status": status,
            "value": round(distance_to_stop, 2),
            "note": note,
        })

    # 3. Distance to Target
    if mark and target:
        distance_to_target = abs(target - mark)
        if direction == "long":
            distance_pct = (target - mark) / mark * 100 if mark > 0 else 0
        else:
            distance_pct = (mark - target) / mark * 100 if mark > 0 else 0

        status = "pass"
        note = f"Distance to target: {distance_to_target:.2f} pts ({distance_pct:.1f}%)"
        if distance_pct < 0.1:
            status = "pass"
            note += " — near target, consider taking profit"

        checks.append({
            "check": "distance_to_target",
            "position_id": pos_id,
            "status": status,
            "value": round(distance_to_target, 2),
            "note": note,
        })

    # 4. Unrealized P&L direction check
    if mark and entry:
        if direction == "long":
            unrealized = mark - entry
        else:
            unrealized = entry - mark

        status = "pass"
        note = f"Unrealized: {unrealized:.2f} pts"
        if unrealized < -200:
            status = "warn"
            note += " — significant drawdown"
        elif unrealized < -400:
            status = "fail"
            note += " — deep drawdown, review thesis"

        checks.append({
            "check": "unrealized_pnl",
            "position_id": pos_id,
            "status": status,
            "value": round(unrealized, 2),
            "note": note,
        })

    # 5. Fish scenario contradiction check
    if fish_packet:
        fish_data = fish_packet.get("data", {})
        scenarios = fish_data.get("scenarios", [])

        # Find scenarios linked to this position
        pos_scenarios = [s for s in scenarios if s.get("position_id") == pos_id]
        if not pos_scenarios:
            pos_scenarios = scenarios  # use all if none are position-specific

        # Check for high-probability negative scenarios
        negative_high_prob = [
            s for s in pos_scenarios
            if s.get("impact") == "negative" and (s.get("probability", 0) or 0) >= 0.25
        ]

        status = "pass"
        note = f"{len(pos_scenarios)} scenarios evaluated"
        if len(negative_high_prob) >= 3:
            status = "fail"
            note = f"{len(negative_high_prob)} high-probability negative scenarios — thesis under pressure"
        elif len(negative_high_prob) >= 2:
            status = "warn"
            note = f"{len(negative_high_prob)} high-probability negative scenarios — monitor closely"

        checks.append({
            "check": "scenario_contradiction",
            "position_id": pos_id,
            "status": status,
            "value": len(negative_high_prob),
            "note": note,
        })

        # 6. Stop-out scenario probability
        stop_scenarios = [s for s in pos_scenarios if s.get("type") == "stop_out"]
        if stop_scenarios:
            stop_prob = max(s.get("probability", 0) or 0 for s in stop_scenarios)
            status = "pass"
            note = f"Stop-out probability: {stop_prob:.0%}"
            if stop_prob >= 0.40:
                status = "fail"
                note += " — elevated stop-out risk"
            elif stop_prob >= 0.30:
                status = "warn"
                note += " — moderate stop-out risk"

            checks.append({
                "check": "stop_out_probability",
                "position_id": pos_id,
                "status": status,
                "value": round(stop_prob, 2),
                "note": note,
            })

    return checks


def _build_summary(verdict: str, positions: list, flags: list) -> str:
    """Build operator-facing summary string."""
    if verdict == "pass":
        return f"All checks pass across {len(positions)} position(s). No action needed."
    elif verdict == "caution":
        flag_types = ", ".join(set(f["check"] for f in flags))
        return f"Caution: {len(flags)} warning(s) across {len(positions)} position(s). Watch: {flag_types}."
    else:
        flag_types = ", ".join(set(f["check"] for f in flags))
        return f"Flagged: {len(flags)} issue(s) across {len(positions)} position(s). Review: {flag_types}."


def _write_validation_note(result: dict, positions: list, now: datetime) -> None:
    """Write operator-facing validation markdown."""
    md = f"""# Sigma Paper-Trade Validation — {now.strftime('%Y-%m-%d %H:%M UTC')}

## Verdict: {result['verdict'].upper()}

{result['summary']}

## Checks

| Check | Position | Status | Value | Note |
|-------|----------|--------|-------|------|
"""
    for c in result["checks"]:
        status_icon = {"pass": "OK", "warn": "!!", "fail": "XX"}.get(c["status"], "?")
        md += f"| {c['check']} | {c['position_id'][:16]} | [{status_icon}] | {c.get('value', '')} | {c['note']} |\n"

    if result["flags"] > 0:
        md += f"""
## Flags ({result['flags']})

"""
        for c in result["checks"]:
            if c["status"] != "pass":
                md += f"- **{c['check']}** ({c['position_id'][:16]}): {c['note']}\n"

    md += f"""
## Context
- Positions checked: {result['positions_checked']}
- Total checks: {result['checks_run']}
- Validated at: {result['validated_at']}

---
*Paper-trade context validation. Not a promotion gate.*
"""

    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    (VALIDATION_DIR / "latest.md").write_text(md)
    ts = now.strftime("%Y%m%dT%H%M%S")
    (VALIDATION_DIR / f"validation_{ts}.md").write_text(md)
    print(f"[sigma] Validation note -> {VALIDATION_DIR / 'latest.md'}")


def _write_result(verdict: str, summary: str, now: datetime) -> dict:
    """Write a minimal result when there's nothing to validate."""
    result = {
        "validated_at": now.isoformat(),
        "verdict": verdict,
        "positions_checked": 0,
        "checks_run": 0,
        "flags": 0,
        "checks": [],
        "summary": summary,
    }

    write_packet(
        lane="sigma",
        packet_type="paper_validation",
        summary=f"Sigma paper-trade validation: {verdict} — {summary}",
        data=result,
        upstream=["kitt_quant"],
        source_module="sigma.paper_trade_validator",
        confidence=0.5,
    )

    print(f"[sigma] Paper-trade validation: {verdict} — {summary}")
    return result


def main():
    result = validate_paper_trade()
    print(f"\n[sigma] Verdict: {result['verdict']} | {result['flags']} flag(s)")


if __name__ == "__main__":
    main()
