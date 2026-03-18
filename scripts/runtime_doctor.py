#!/usr/bin/env python3
"""runtime_doctor — live health check for the OpenClaw operator loop.

One command that proves the runtime is actually working right now.

Usage:
    python3 scripts/runtime_doctor.py          # terminal summary
    python3 scripts/runtime_doctor.py --json   # machine-readable
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Check definitions
# ---------------------------------------------------------------------------

# (unit_name, human_label, kind)
# kind: "service" = must be active; "timer" = timer must be active
REQUIRED_UNITS = [
    ("openclaw-gateway.service",          "Gateway",          "service"),
    ("openclaw-inbound-server.service",   "Inbound server",   "service"),
    ("openclaw-ralph.timer",              "Ralph timer",       "timer"),
    ("openclaw-review-poller.timer",      "Review poller",     "timer"),
    ("lobster-todo-intake.timer",         "Todo poller",       "timer"),
    ("openclaw-discord-outbox.timer",     "Outbox sender",     "timer"),
    ("openclaw-operator-status.timer",    "Status timer",      "timer"),
]

HTTP_ENDPOINTS = [
    ("http://127.0.0.1:18789/health", "Gateway API"),
    ("http://127.0.0.1:18790/health", "Inbound server API"),
]

OUTBOX_FAIL_WARN = 5
OUTBOX_FAIL_CRIT = 20


# ---------------------------------------------------------------------------
# Individual checks — each returns a check result dict
# ---------------------------------------------------------------------------

def _systemctl(cmd: list[str]) -> str:
    try:
        r = subprocess.run(
            ["systemctl", "--user"] + cmd,
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def check_units() -> list[dict[str, Any]]:
    results = []
    for unit, label, kind in REQUIRED_UNITS:
        active = _systemctl(["is-active", unit]) == "active"
        level = "pass" if active else "fail"
        fix = f"systemctl --user start {unit}" if not active else ""
        results.append({
            "check": f"unit:{unit}",
            "label": label,
            "level": level,
            "detail": "active" if active else "not active",
            "fix": fix,
        })
    return results


def check_http() -> list[dict[str, Any]]:
    results = []
    for url, label in HTTP_ENDPOINTS:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())
                ok = body.get("ok", False)
        except Exception as exc:
            ok = False
            body = {"error": str(exc)[:80]}

        level = "pass" if ok else "fail"
        detail = "ok=true" if ok else body.get("error", "unreachable")[:60]
        results.append({
            "check": f"http:{url}",
            "label": label,
            "level": level,
            "detail": detail,
            "fix": "",
        })
    return results


def check_systemd_drift() -> list[dict[str, Any]]:
    from scripts.sync_systemd_units import compute_plan, discover_repo_units

    repo_units = discover_repo_units()
    plan = compute_plan(repo_units)

    if not plan:
        return [{
            "check": "systemd_drift",
            "label": "Repo/live unit sync",
            "level": "pass",
            "detail": f"{len(repo_units)} units, 0 drifted",
            "fix": "",
        }]

    names = [item["name"] for item in plan]
    level = "warn"
    return [{
        "check": "systemd_drift",
        "label": "Repo/live unit sync",
        "level": level,
        "detail": f"{len(plan)} drifted: {', '.join(names[:5])}",
        "fix": "python3 scripts/sync_systemd_units.py",
    }]


def check_outbox() -> list[dict[str, Any]]:
    from scripts.operator_status import _outbox_health

    health = _outbox_health()
    failed = health["failed"]
    pending = health["pending"]

    if failed >= OUTBOX_FAIL_CRIT:
        level = "fail"
    elif failed >= OUTBOX_FAIL_WARN:
        level = "warn"
    else:
        level = "pass"

    return [{
        "check": "outbox",
        "label": "Discord outbox",
        "level": level,
        "detail": f"{pending} pending, {failed} failed",
        "fix": "python3 -c 'from runtime.core.discord_outbox_sender import send_pending; send_pending()'" if failed else "",
    }]


def check_action_backlog() -> list[dict[str, Any]]:
    from scripts.operator_status import _pending_approvals, _actionable_tasks

    approvals = _pending_approvals()
    tasks = _actionable_tasks()
    failed = tasks["failed"]

    results = []

    # Pending approvals — warn if any, they need human action
    if approvals:
        results.append({
            "check": "approvals",
            "label": "Pending approvals",
            "level": "warn",
            "detail": f"{len(approvals)} waiting",
            "fix": f"python3 scripts/run_ralph_v1.py --approve {approvals[0]['task_id']}" if approvals else "",
        })
    else:
        results.append({
            "check": "approvals",
            "label": "Pending approvals",
            "level": "pass",
            "detail": "0",
            "fix": "",
        })

    # Failed tasks — warn if any
    if failed:
        results.append({
            "check": "failed_tasks",
            "label": "Failed tasks",
            "level": "warn",
            "detail": f"{len(failed)} retryable",
            "fix": f"python3 scripts/run_ralph_v1.py --retry {failed[0]['task_id']}" if failed else "",
        })
    else:
        results.append({
            "check": "failed_tasks",
            "label": "Failed tasks",
            "level": "pass",
            "detail": "0",
            "fix": "",
        })

    return results


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_all_checks() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.extend(check_units())
    checks.extend(check_http())
    checks.extend(check_systemd_drift())
    checks.extend(check_outbox())
    checks.extend(check_action_backlog())

    fails = [c for c in checks if c["level"] == "fail"]
    warns = [c for c in checks if c["level"] == "warn"]
    passes = [c for c in checks if c["level"] == "pass"]

    if fails:
        verdict = "FAIL"
    elif warns:
        verdict = "WARN"
    else:
        verdict = "PASS"

    return {
        "verdict": verdict,
        "pass": len(passes),
        "warn": len(warns),
        "fail": len(fails),
        "total": len(checks),
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_MARKS = {"pass": "OK", "warn": "!!", "fail": "XX"}
_ICONS = {"pass": "\u2705", "warn": "\u26a0\ufe0f", "fail": "\u274c"}


def render_terminal(result: dict[str, Any]) -> str:
    lines: list[str] = []
    v = result["verdict"]
    lines.append(f"runtime_doctor: {v}")
    lines.append(f"  pass={result['pass']}  warn={result['warn']}  fail={result['fail']}")
    lines.append("")

    for c in result["checks"]:
        mark = _MARKS[c["level"]]
        lines.append(f"  [{mark}] {c['label']:<25s} {c['detail']}")
        if c["fix"] and c["level"] != "pass":
            lines.append(f"       fix: {c['fix']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Live runtime health check")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    result = run_all_checks()

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render_terminal(result))

    if result["verdict"] == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
