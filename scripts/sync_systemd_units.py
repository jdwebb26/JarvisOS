#!/usr/bin/env python3
"""sync_systemd_units — install and enable repo systemd user units.

Copies *.service and *.timer files from repo systemd/user/ into
~/.config/systemd/user/, runs daemon-reload, and enables/starts
the core operator-loop units.

Usage:
    python3 scripts/sync_systemd_units.py              # install + enable + start
    python3 scripts/sync_systemd_units.py --dry-run    # show what would change
    python3 scripts/sync_systemd_units.py --status     # show current state only
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_UNITS = ROOT / "systemd" / "user"
LIVE_DIR = Path.home() / ".config" / "systemd" / "user"

# Units that should be enabled and started for the operator loop.
# Order: persistent services first, then timers (which trigger oneshot services).
CORE_UNITS: list[tuple[str, str]] = [
    # Persistent services (enable + start)
    ("openclaw-gateway.service",          "enable"),
    ("openclaw-inbound-server.service",   "enable"),
    ("pinchtab.service",                  "enable"),
    # Timers (enable + start the timer, not the service)
    ("openclaw-ralph.timer",              "enable"),
    ("openclaw-review-poller.timer",      "enable"),
    ("lobster-todo-intake.timer",         "enable"),
    ("openclaw-discord-outbox.timer",     "enable"),
    ("openclaw-operator-status.timer",    "enable"),
    ("openclaw-dashboard.service",        "enable"),
]


def _run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15)


def _is_active(unit: str) -> bool:
    r = _run(["systemctl", "--user", "is-active", unit])
    return r.stdout.strip() == "active"


def _is_enabled(unit: str) -> bool:
    r = _run(["systemctl", "--user", "is-enabled", unit])
    return r.stdout.strip() == "enabled"


def discover_repo_units() -> list[Path]:
    """Find all .service and .timer files in repo systemd/user/."""
    if not REPO_UNITS.is_dir():
        return []
    units = sorted(REPO_UNITS.glob("*.service")) + sorted(REPO_UNITS.glob("*.timer"))
    return units


def compute_plan(repo_units: list[Path]) -> list[dict]:
    """Compare repo units against installed live units and return a plan."""
    plan = []
    for repo_path in repo_units:
        name = repo_path.name
        live_path = LIVE_DIR / name
        if not live_path.exists():
            plan.append({"name": name, "action": "install", "repo": repo_path, "live": live_path})
        elif not filecmp.cmp(str(repo_path), str(live_path)):
            plan.append({"name": name, "action": "update", "repo": repo_path, "live": live_path})
        # else: match, nothing to do
    return plan


def install_units(plan: list[dict], dry_run: bool = False) -> int:
    """Copy units to live dir, return count of changes."""
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    changed = 0
    for item in plan:
        action = item["action"]
        name = item["name"]
        if dry_run:
            print(f"  [DRY-RUN] {action}: {name}")
        else:
            shutil.copy2(str(item["repo"]), str(item["live"]))
            print(f"  {action}: {name}")
        changed += 1
    return changed


def daemon_reload(dry_run: bool = False) -> None:
    if dry_run:
        print("  [DRY-RUN] systemctl --user daemon-reload")
        return
    r = _run(["systemctl", "--user", "daemon-reload"])
    if r.returncode != 0:
        print(f"  WARNING: daemon-reload failed: {r.stderr.strip()}")
    else:
        print("  daemon-reload OK")


def enable_and_start(dry_run: bool = False) -> list[dict]:
    """Enable and start core units. Returns status list."""
    results = []
    for unit, action in CORE_UNITS:
        enabled = _is_enabled(unit)
        active = _is_active(unit)

        if enabled and active:
            results.append({"unit": unit, "action": "already running", "ok": True})
            continue

        if dry_run:
            needed = []
            if not enabled:
                needed.append("enable")
            if not active:
                needed.append("start")
            results.append({"unit": unit, "action": f"[DRY-RUN] would {'+'.join(needed)}", "ok": True})
            continue

        if not enabled:
            r = _run(["systemctl", "--user", "enable", unit])
            if r.returncode != 0:
                results.append({"unit": unit, "action": f"enable FAILED: {r.stderr.strip()[:60]}", "ok": False})
                continue

        if not active:
            r = _run(["systemctl", "--user", "start", unit])
            if r.returncode != 0:
                results.append({"unit": unit, "action": f"start FAILED: {r.stderr.strip()[:60]}", "ok": False})
                continue

        results.append({"unit": unit, "action": "enabled+started", "ok": True})

    return results


def print_status() -> None:
    """Print current state of all repo units."""
    repo_units = discover_repo_units()
    print(f"{'Unit':<45s} {'Installed':>10s} {'Enabled':>8s} {'Active':>7s}")
    print("-" * 75)
    for repo_path in repo_units:
        name = repo_path.name
        live_path = LIVE_DIR / name
        installed = live_path.exists()
        if installed:
            match = filecmp.cmp(str(repo_path), str(live_path))
            inst_str = "match" if match else "DRIFT"
        else:
            inst_str = "MISSING"
        enabled = _is_enabled(name) if installed else False
        active = _is_active(name) if installed else False
        print(f"{name:<45s} {inst_str:>10s} {'yes' if enabled else '-':>8s} {'yes' if active else '-':>7s}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install and enable repo systemd user units",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without making changes")
    parser.add_argument("--status", action="store_true",
                        help="Show current installed/enabled/active state and exit")
    args = parser.parse_args()

    if args.status:
        print_status()
        return 0

    repo_units = discover_repo_units()
    if not repo_units:
        print("No units found in systemd/user/")
        return 1

    print(f"Found {len(repo_units)} repo units in systemd/user/\n")

    # 1. Compute install plan
    plan = compute_plan(repo_units)
    if plan:
        print(f"Step 1: Install/update {len(plan)} unit(s)")
        install_units(plan, dry_run=args.dry_run)
    else:
        print(f"Step 1: All {len(repo_units)} units already installed and match repo")

    # 2. Daemon reload
    if plan or args.dry_run:
        print("\nStep 2: Reload systemd")
        daemon_reload(dry_run=args.dry_run)
    else:
        print("\nStep 2: Reload systemd (skipped — no changes)")

    # 3. Enable + start core units
    print(f"\nStep 3: Enable/start {len(CORE_UNITS)} core units")
    results = enable_and_start(dry_run=args.dry_run)
    for r in results:
        mark = "OK" if r["ok"] else "!!"
        print(f"  [{mark}] {r['unit']:<45s} {r['action']}")

    # Summary
    ok_count = sum(1 for r in results if r["ok"])
    fail_count = len(results) - ok_count
    print(f"\nDone: {len(repo_units)} units installed, "
          f"{ok_count}/{len(CORE_UNITS)} core units OK"
          f"{f', {fail_count} FAILED' if fail_count else ''}")

    return 1 if fail_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
