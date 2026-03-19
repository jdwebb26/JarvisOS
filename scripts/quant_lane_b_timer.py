#!/usr/bin/env python3
"""Quant Lane B Timer — install, status, enable, disable.

Manages the user-level systemd timer that runs Lane B cycles.

Usage:
    python3 scripts/quant_lane_b_timer.py install   install/update service+timer
    python3 scripts/quant_lane_b_timer.py enable    enable and start timer
    python3 scripts/quant_lane_b_timer.py disable   stop and disable timer
    python3 scripts/quant_lane_b_timer.py status    show timer status
    python3 scripts/quant_lane_b_timer.py run       run one cycle now (manual)
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
SRC_DIR = ROOT / "ops" / "systemd"

SERVICE = "quant-lane-b-cycle.service"
TIMER = "quant-lane-b-cycle.timer"


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def cmd_install(args):
    """Copy service+timer to ~/.config/systemd/user/ and reload."""
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    for name in [SERVICE, TIMER]:
        src = SRC_DIR / name
        dst = UNIT_DIR / name
        if not src.exists():
            print(f"ERROR: {src} not found")
            return
        shutil.copy2(src, dst)
        print(f"Installed {dst}")
    _run(["systemctl", "--user", "daemon-reload"])
    print("Reloaded systemd user daemon")


def cmd_enable(args):
    """Enable and start the timer."""
    r = _run(["systemctl", "--user", "enable", "--now", TIMER], check=False)
    if r.returncode == 0:
        print(f"Timer enabled and started: {TIMER}")
    else:
        print(f"ERROR: {r.stderr.strip()}")


def cmd_disable(args):
    """Stop and disable the timer."""
    r = _run(["systemctl", "--user", "disable", "--now", TIMER], check=False)
    if r.returncode == 0:
        print(f"Timer stopped and disabled: {TIMER}")
    else:
        print(f"ERROR: {r.stderr.strip()}")


def cmd_status(args):
    """Show timer and service status."""
    print(f"=== {TIMER} ===")
    r = _run(["systemctl", "--user", "status", TIMER], check=False)
    print(r.stdout[:500] if r.stdout else "(not found)")

    print(f"\n=== {SERVICE} (last run) ===")
    r2 = _run(["systemctl", "--user", "status", SERVICE], check=False)
    print(r2.stdout[:500] if r2.stdout else "(not found)")

    # Show next trigger time
    r3 = _run(["systemctl", "--user", "list-timers", "--no-pager"], check=False)
    for line in (r3.stdout or "").splitlines():
        if "quant-lane-b" in line:
            print(f"\nNext: {line.strip()}")


def cmd_run(args):
    """Run one cycle manually."""
    r = _run(["systemctl", "--user", "start", SERVICE], check=False)
    if r.returncode == 0:
        print("Cycle triggered via systemd")
        # Show result
        r2 = _run(["journalctl", "--user-unit", SERVICE, "-n", "10", "--no-pager"], check=False)
        print(r2.stdout or "(no output yet)")
    else:
        print(f"ERROR: {r.stderr.strip()}")


def main():
    p = argparse.ArgumentParser(description="Quant Lane B Timer management")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("install", help="Install service+timer")
    sub.add_parser("enable", help="Enable and start timer")
    sub.add_parser("disable", help="Stop and disable timer")
    sub.add_parser("status", help="Show timer status")
    sub.add_parser("run", help="Run one cycle now")

    args = p.parse_args()
    if not args.command:
        p.print_help()
        return

    {"install": cmd_install, "enable": cmd_enable, "disable": cmd_disable,
     "status": cmd_status, "run": cmd_run}[args.command](args)


if __name__ == "__main__":
    main()
