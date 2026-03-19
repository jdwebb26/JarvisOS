#!/usr/bin/env python3
"""health_monitor.py — unified health assessment combining OpenClaw gateway + Jarvis runtime.

Distinguishes between:
  - disconnected: gateway or services unreachable
  - stuck: services running but not processing (stale heartbeats, frozen queues)
  - degraded: running but with failures or warnings
  - healthy: everything normal

Designed for overnight autonomy monitoring and operator-on-wake checks.
Does not emit to #jarvis (operator channel stays low-noise).

Usage:
    python3 scripts/health_monitor.py          # terminal summary
    python3 scripts/health_monitor.py --json   # machine-readable
    python3 scripts/health_monitor.py --brief  # one-line verdict + counts
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.heartbeat_reports import (
    build_node_health_summary,
    heartbeat_is_stale,
    list_node_heartbeats,
)


# ── Thresholds ──────────────────────────────────────────────────────────────
GATEWAY_TIMEOUT_S = 5
STALE_HEARTBEAT_SECONDS = 600           # 10 min = stuck indicator
OUTBOX_STUCK_THRESHOLD = 10             # pending outbox entries = stuck
RESTART_COUNT_WARN_THRESHOLD = 3        # restarts in recent window


# ── Data collection ─────────────────────────────────────────────────────────

def _probe_gateway_health() -> dict[str, Any]:
    """Probe the OpenClaw gateway via CLI health endpoint."""
    try:
        r = subprocess.run(
            ["openclaw", "health", "--json"],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(r.stdout)
        return {
            "reachable": True,
            "ok": data.get("ok", False),
            "duration_ms": data.get("durationMs"),
            "discord_ok": data.get("channels", {}).get("discord", {}).get("probe", {}).get("ok"),
        }
    except Exception as exc:
        return {"reachable": False, "ok": False, "error": str(exc)[:100]}


def _probe_http(url: str) -> dict[str, Any]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=GATEWAY_TIMEOUT_S) as resp:
            body = json.loads(resp.read())
            return {"reachable": True, "ok": body.get("ok", False)}
    except Exception as exc:
        return {"reachable": False, "ok": False, "error": str(exc)[:100]}


def _check_systemd_unit(unit: str) -> dict[str, Any]:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True, text=True, timeout=5,
        )
        active = r.stdout.strip() == "active"
        return {"active": active}
    except Exception:
        return {"active": False}


def _systemd_restart_count(unit: str) -> int:
    """Get NRestarts from systemd for a service unit."""
    try:
        r = subprocess.run(
            ["systemctl", "--user", "show", unit, "--property=NRestarts"],
            capture_output=True, text=True, timeout=5,
        )
        parts = r.stdout.strip().split("=")
        return int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        return 0


def _outbox_pending_count(root: Path) -> int:
    outbox_dir = root / "state" / "discord_outbox"
    if not outbox_dir.exists():
        return 0
    pending = 0
    for f in outbox_dir.glob("*.json"):
        try:
            entry = json.loads(f.read_text(encoding="utf-8"))
            if entry.get("status") in ("pending", None):
                pending += 1
        except Exception:
            continue
    return pending


def _failed_task_count(root: Path) -> int:
    tasks_dir = root / "state" / "tasks"
    if not tasks_dir.exists():
        return 0
    count = 0
    for f in tasks_dir.glob("*.json"):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
            if t.get("status") == "failed":
                count += 1
        except Exception:
            continue
    return count


# ── Assessment logic ────────────────────────────────────────────────────────

def assess_health(root: Optional[Path] = None) -> dict[str, Any]:
    resolved_root = Path(root or ROOT).resolve()
    checks: list[dict[str, Any]] = []
    disconnected = False
    stuck = False
    degraded = False

    # 1. Gateway health via CLI
    gw = _probe_gateway_health()
    if not gw["reachable"]:
        checks.append({"check": "gateway_cli", "state": "disconnected", "detail": gw.get("error", "unreachable")})
        disconnected = True
    elif not gw["ok"]:
        checks.append({"check": "gateway_cli", "state": "degraded", "detail": "health check returned ok=false"})
        degraded = True
    else:
        checks.append({"check": "gateway_cli", "state": "healthy", "detail": f"ok, {gw.get('duration_ms', '?')}ms"})

    # 2. HTTP endpoints
    for url, label in [("http://127.0.0.1:18789/health", "gateway_http"), ("http://127.0.0.1:18790/health", "inbound_http")]:
        probe = _probe_http(url)
        if not probe["reachable"]:
            checks.append({"check": label, "state": "disconnected", "detail": probe.get("error", "unreachable")})
            disconnected = True
        elif not probe["ok"]:
            checks.append({"check": label, "state": "degraded", "detail": "ok=false"})
            degraded = True
        else:
            checks.append({"check": label, "state": "healthy", "detail": "ok"})

    # 3. Critical systemd units
    critical_units = [
        ("openclaw-gateway.service", "gateway_service"),
        ("openclaw-inbound-server.service", "inbound_service"),
    ]
    for unit, label in critical_units:
        status = _check_systemd_unit(unit)
        if not status["active"]:
            checks.append({"check": label, "state": "disconnected", "detail": "not active"})
            disconnected = True
        else:
            restarts = _systemd_restart_count(unit)
            if restarts >= RESTART_COUNT_WARN_THRESHOLD:
                checks.append({"check": label, "state": "degraded", "detail": f"active, {restarts} restarts"})
                degraded = True
            else:
                checks.append({"check": label, "state": "healthy", "detail": "active"})

    # 4. Timer units (non-critical but important)
    timer_units = [
        ("openclaw-ralph.timer", "ralph_timer"),
        ("openclaw-review-poller.timer", "review_poller_timer"),
        ("lobster-todo-intake.timer", "todo_intake_timer"),
        ("openclaw-discord-outbox.timer", "outbox_timer"),
    ]
    for unit, label in timer_units:
        status = _check_systemd_unit(unit)
        if not status["active"]:
            checks.append({"check": label, "state": "degraded", "detail": "timer not active"})
            degraded = True
        else:
            checks.append({"check": label, "state": "healthy", "detail": "active"})

    # 5. Node heartbeats (informational)
    #
    # IMPORTANT: Node heartbeats in this system are ON-DEMAND, not from a
    # persistent daemon. They are written during dashboard rebuilds (smoke_test,
    # bootstrap) — not continuously. A "stale" heartbeat means "nobody ran a
    # dashboard rebuild recently", NOT "the runtime is down".
    #
    # Real liveness is covered by checks #1-4 (gateway probe, HTTP endpoints,
    # systemd units). Heartbeat staleness is informational only — it does NOT
    # trigger degraded/stuck verdicts.
    #
    # Nodes that have never sent a heartbeat are registrations that were never
    # activated (scaffolding placeholders).
    try:
        node_health = build_node_health_summary(root=resolved_root, stale_after_seconds=STALE_HEARTBEAT_SECONDS)
        topology = node_health.get("topology_posture", "unknown")

        never_reported = 0
        stale_since_rebuild = 0
        for n in node_health.get("nodes", []):
            if not n.get("stale_heartbeat"):
                continue
            if n.get("last_seen_at") is None:
                never_reported += 1
            else:
                stale_since_rebuild += 1

        parts = [f"topology={topology}"]
        if stale_since_rebuild > 0:
            parts.append(f"{stale_since_rebuild} stale since last rebuild")
        if never_reported > 0:
            parts.append(f"{never_reported} never activated")

        checks.append({"check": "node_heartbeat", "state": "healthy",
                       "detail": ", ".join(parts)})
    except Exception as exc:
        checks.append({"check": "node_heartbeat", "state": "healthy",
                       "detail": f"skipped: {str(exc)[:60]}"})

    # 6. Outbox stuck detection
    outbox_pending = _outbox_pending_count(resolved_root)
    if outbox_pending >= OUTBOX_STUCK_THRESHOLD:
        checks.append({"check": "outbox_backlog", "state": "stuck",
                       "detail": f"{outbox_pending} pending entries"})
        stuck = True
    elif outbox_pending > 0:
        checks.append({"check": "outbox_backlog", "state": "healthy",
                       "detail": f"{outbox_pending} pending (normal)"})
    else:
        checks.append({"check": "outbox_backlog", "state": "healthy", "detail": "0 pending"})

    # 7. Failed task count
    failed = _failed_task_count(resolved_root)
    if failed > 0:
        checks.append({"check": "failed_tasks", "state": "degraded", "detail": f"{failed} failed tasks"})
        degraded = True
    else:
        checks.append({"check": "failed_tasks", "state": "healthy", "detail": "0"})

    # 8. OpenClaw memory index + embedding provider validity
    try:
        r = subprocess.run(
            ["openclaw", "memory", "status", "--json"],
            capture_output=True, text=True, timeout=15,
        )
        mem_data = json.loads(r.stdout)
        dirty_agents = [a["agentId"] for a in mem_data if a.get("status", {}).get("dirty")]
        total_files = sum(a.get("status", {}).get("files", 0) for a in mem_data)

        # Detect whether the embedding provider can actually run.
        embed_usable = True
        embed_reason = ""
        if mem_data:
            s = mem_data[0].get("status", {})
            embed_provider = s.get("provider", "unknown")
            if embed_provider == "openai":
                try:
                    cfg = json.loads(Path.home().joinpath(".openclaw/openclaw.json").read_text(encoding="utf-8"))
                    key = cfg.get("models", {}).get("providers", {}).get("openai", {}).get("apiKey", "")
                    if not key or key == "OPENAI_API_KEY" or key.startswith("REPLACE"):
                        embed_usable = False
                        embed_reason = f"provider={embed_provider} but OPENAI_API_KEY is placeholder"
                except Exception:
                    pass

        if total_files == 0 and dirty_agents:
            if not embed_usable:
                checks.append({"check": "memory_index", "state": "degraded",
                               "detail": f"0 indexed — {embed_reason}. Blocked until key is funded or provider changed."})
            else:
                checks.append({"check": "memory_index", "state": "degraded",
                               "detail": f"0 files indexed, {len(dirty_agents)} dirty — run: openclaw memory index"})
            degraded = True
        elif dirty_agents:
            checks.append({"check": "memory_index", "state": "healthy",
                           "detail": f"{total_files} files, {len(dirty_agents)} dirty"})
        else:
            checks.append({"check": "memory_index", "state": "healthy",
                           "detail": f"{total_files} files indexed"})
    except Exception:
        checks.append({"check": "memory_index", "state": "healthy", "detail": "skipped (cli unavailable)"})

    # ── Verdict ──
    if disconnected:
        verdict = "disconnected"
    elif stuck:
        verdict = "stuck"
    elif degraded:
        verdict = "degraded"
    else:
        verdict = "healthy"

    state_counts = {}
    for c in checks:
        s = c["state"]
        state_counts[s] = state_counts.get(s, 0) + 1

    return {
        "verdict": verdict,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_checks": len(checks),
        "state_counts": state_counts,
        "checks": checks,
    }


# ── Rendering ───────────────────────────────────────────────────────────────

_STATE_MARKS = {
    "healthy": "OK",
    "degraded": "!!",
    "stuck": "??",
    "disconnected": "XX",
}


def render_terminal(result: dict[str, Any]) -> str:
    lines = [f"health_monitor: {result['verdict'].upper()}"]
    counts = result["state_counts"]
    parts = [f"{k}={v}" for k, v in sorted(counts.items())]
    lines.append(f"  {' '.join(parts)}")
    lines.append("")

    for c in result["checks"]:
        mark = _STATE_MARKS.get(c["state"], "??")
        lines.append(f"  [{mark}] {c['check']:<25s} {c['detail']}")

    return "\n".join(lines)


def render_brief(result: dict[str, Any]) -> str:
    counts = result["state_counts"]
    parts = [f"{k}={v}" for k, v in sorted(counts.items())]
    return f"{result['verdict'].upper()} ({' '.join(parts)})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified health monitor — OpenClaw + Jarvis")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--brief", action="store_true", help="One-line verdict")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()

    result = assess_health(root=Path(args.root))

    if args.json:
        print(json.dumps(result, indent=2))
    elif args.brief:
        print(render_brief(result))
    else:
        print(render_terminal(result))

    return 0 if result["verdict"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
