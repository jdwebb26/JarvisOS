#!/usr/bin/env python3
"""cron_migration_audit.py — assess systemd timer → OpenClaw cron migration readiness.

Prints a table of all live systemd timers related to OpenClaw/Jarvis,
their current interval, and whether they are candidates for migration
to the upstream OpenClaw cron scheduler (openclaw cron add).

Usage:
    python3 scripts/cron_migration_audit.py          # terminal table
    python3 scripts/cron_migration_audit.py --json   # machine-readable
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


# ── Timer metadata ──────────────────────────────────────────────────────────
# Each entry describes a systemd timer and its migration assessment.

@dataclass
class TimerEntry:
    unit: str
    label: str
    interval: str
    migration_readiness: str   # "ready", "candidate", "keep_systemd", "legacy"
    recommended_cron_flags: str
    notes: str


KNOWN_TIMERS: list[TimerEntry] = [
    TimerEntry(
        unit="openclaw-ralph.timer",
        label="Ralph autonomy cycle",
        interval="10min",
        migration_readiness="candidate",
        recommended_cron_flags=(
            "--agent ralph --every 10m --session-key agent:ralph:main "
            "--light-context --message 'Ralph bounded autonomy cycle' "
            "--timeout-seconds 180"
        ),
        notes=(
            "Good migration candidate. Ralph runs a bounded cycle that "
            "would benefit from session-key binding and light-context. "
            "Requires gateway uptime guarantee."
        ),
    ),
    TimerEntry(
        unit="openclaw-review-poller.timer",
        label="Discord review poller",
        interval="30s",
        migration_readiness="keep_systemd",
        recommended_cron_flags="",
        notes=(
            "Keep as systemd. This is a fast poll (30s) that directly "
            "reads Discord API — not an agent turn. OpenClaw cron is "
            "designed for agent message jobs, not raw API polling."
        ),
    ),
    TimerEntry(
        unit="lobster-todo-intake.timer",
        label="Todo intake poller",
        interval="2min",
        migration_readiness="keep_systemd",
        recommended_cron_flags="",
        notes=(
            "Keep as systemd. Fast poll of Discord #todo channel, not "
            "an agent session job."
        ),
    ),
    TimerEntry(
        unit="openclaw-discord-outbox.timer",
        label="Discord outbox sender",
        interval="60s",
        migration_readiness="keep_systemd",
        recommended_cron_flags="",
        notes=(
            "Keep as systemd. Delivery-side job that flushes pending "
            "outbox entries — not an agent turn."
        ),
    ),
    TimerEntry(
        unit="openclaw-operator-status.timer",
        label="Operator status poster",
        interval="5min",
        migration_readiness="candidate",
        recommended_cron_flags=(
            "--agent jarvis --every 5m --session isolated "
            "--light-context --system-event 'operator_status_check' "
            "--no-deliver --timeout-seconds 30"
        ),
        notes=(
            "Good migration candidate. Posts action summary to #jarvis "
            "only when needed. Session isolation prevents context bleed. "
            "Light-context keeps it cheap."
        ),
    ),
    TimerEntry(
        unit="openclaw-factory-weekly.timer",
        label="Strategy factory weekly batch",
        interval="weekly Sun 02:00",
        migration_readiness="candidate",
        recommended_cron_flags=(
            "--agent hal --cron '0 2 * * 0' --tz America/Chicago "
            "--session-key agent:hal:factory-weekly "
            "--message 'Weekly strategy factory batch run' "
            "--timeout-seconds 7200"
        ),
        notes=(
            "Good migration candidate for named-session cron binding. "
            "Long-running job benefits from persistent session context "
            "across weekly runs. Requires reliable gateway uptime."
        ),
    ),
    TimerEntry(
        unit="quant-lane-b-cycle.timer",
        label="Quant lane B cycle",
        interval="~4h",
        migration_readiness="candidate",
        recommended_cron_flags=(
            "--agent kitt --every 4h --session-key agent:kitt:quant-lane-b "
            "--light-context --message 'Quant lane B cycle' "
            "--timeout-seconds 600"
        ),
        notes=(
            "Good migration candidate for named-session binding. "
            "Kitt-owned quant work with persistent session context."
        ),
    ),
]


def _check_timer_active(unit: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


def _check_openclaw_cron_count() -> int:
    try:
        r = subprocess.run(
            ["openclaw", "cron", "list", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(r.stdout)
        return data.get("total", 0)
    except Exception:
        return -1


def build_audit() -> dict:
    rows = []
    for t in KNOWN_TIMERS:
        active = _check_timer_active(t.unit)
        rows.append({
            "unit": t.unit,
            "label": t.label,
            "interval": t.interval,
            "active": active,
            "migration_readiness": t.migration_readiness,
            "recommended_cron_flags": t.recommended_cron_flags,
            "notes": t.notes,
        })

    cron_count = _check_openclaw_cron_count()
    candidates = [r for r in rows if r["migration_readiness"] == "candidate"]
    keep = [r for r in rows if r["migration_readiness"] == "keep_systemd"]

    return {
        "total_timers_audited": len(rows),
        "active_timers": sum(1 for r in rows if r["active"]),
        "migration_candidates": len(candidates),
        "keep_systemd": len(keep),
        "openclaw_cron_jobs": cron_count,
        "rows": rows,
        "summary": (
            f"{len(candidates)} timer(s) are good candidates for OpenClaw cron migration. "
            f"{len(keep)} timer(s) should remain as systemd (fast-poll or non-agent jobs). "
            f"OpenClaw cron scheduler currently has {cron_count} job(s)."
        ),
    }


def render_terminal(audit: dict) -> str:
    lines = ["Cron Migration Audit", ""]
    lines.append(f"  systemd timers audited: {audit['total_timers_audited']}")
    lines.append(f"  active: {audit['active_timers']}")
    lines.append(f"  migration candidates: {audit['migration_candidates']}")
    lines.append(f"  keep as systemd: {audit['keep_systemd']}")
    lines.append(f"  openclaw cron jobs: {audit['openclaw_cron_jobs']}")
    lines.append("")

    for r in audit["rows"]:
        status = "ACTIVE" if r["active"] else "inactive"
        readiness = r["migration_readiness"].upper()
        lines.append(f"  [{readiness:13s}] {r['label']:<30s} ({r['interval']}) [{status}]")
        if r["recommended_cron_flags"]:
            lines.append(f"                  openclaw cron add {r['recommended_cron_flags']}")
        lines.append(f"                  {r['notes'][:120]}")
        lines.append("")

    lines.append(audit["summary"])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit systemd timer → OpenClaw cron migration readiness")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    audit = build_audit()

    if args.json:
        print(json.dumps(audit, indent=2))
    else:
        print(render_terminal(audit))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
