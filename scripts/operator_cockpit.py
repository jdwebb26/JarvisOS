#!/usr/bin/env python3
"""operator_cockpit — single-command live operator view for the OpenClaw/Jarvis-v5 runtime.

Shows:
  - service health (Gateway, PinchTab, SearXNG, NVIDIA, LM Studio)
  - per-agent live state (status, model/provider, last action, updated)
  - active blockers
  - quick-action CLI hints

Writes machine-readable snapshot to state/logs/cockpit_snapshot.json.

Usage:
    python3 scripts/operator_cockpit.py [--json] [--no-color] [--quiet]

    --json       Print raw JSON snapshot only (no table output)
    --no-color   Plain text output (no ANSI)
    --quiet      Only print WARN/ERROR lines
    --update-watchboard   Append a timestamped status block to live_runtime_watchboard.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

_USE_COLOR = True


def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def green(t: str) -> str:   return _c("32", t)
def yellow(t: str) -> str:  return _c("33", t)
def red(t: str) -> str:     return _c("31", t)
def bold(t: str) -> str:    return _c("1", t)
def dim(t: str) -> str:     return _c("2", t)
def cyan(t: str) -> str:    return _c("36", t)


# ---------------------------------------------------------------------------
# Service health checks (run in parallel threads)
# ---------------------------------------------------------------------------

def _http_ok(url: str, *, timeout: float = 4.0, token: str = "") -> tuple[bool, str]:
    """Returns (ok, detail_string)."""
    try:
        req = urllib.request.Request(url)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode(errors="replace")
            try:
                data = json.loads(body)
                if "status" in data:
                    return True, data["status"]
                if "ok" in data:
                    return True, "ok"
            except Exception:
                pass
            return True, f"http {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        short = str(e)[:50]
        return False, short


def _check_gateway() -> dict[str, Any]:
    ok, detail = _http_ok("http://127.0.0.1:18789/health", timeout=3)
    return {"name": "Gateway", "url": "ws://127.0.0.1:18789", "ok": ok, "detail": detail}


def _check_pinchtab() -> dict[str, Any]:
    token = ""
    cfg_path = Path.home() / ".pinchtab" / "config.json"
    if cfg_path.exists():
        try:
            token = json.loads(cfg_path.read_text()).get("server", {}).get("token", "")
        except Exception:
            pass
    ok, detail = _http_ok("http://127.0.0.1:9867/health", timeout=4, token=token)
    version = "?"
    instances = "?"
    if ok:
        try:
            req = urllib.request.Request("http://127.0.0.1:9867/health")
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read())
                version = data.get("version", "?")
                instances = data.get("instances", "?")
                detail = f"v{version}  {instances} instance"
        except Exception:
            pass
    return {"name": "PinchTab", "url": "http://127.0.0.1:9867", "ok": ok, "detail": detail}


def _check_searxng() -> dict[str, Any]:
    url = os.environ.get("JARVIS_SEARXNG_URL", "http://localhost:8888")
    ok, detail = _http_ok(f"{url.rstrip('/')}/healthz", timeout=3)
    return {"name": "SearXNG", "url": url, "ok": ok, "detail": detail}


def _check_nvidia() -> dict[str, Any]:
    api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not api_key:
        return {"name": "NVIDIA/Kimi", "url": "integrate.api.nvidia.com", "ok": False, "detail": "no NVIDIA_API_KEY"}
    ok, detail = _http_ok(
        "https://integrate.api.nvidia.com/v1/models",
        timeout=8,
        token=api_key,
    )
    if ok:
        detail = "kimi-k2.5 reachable"
    return {"name": "NVIDIA/Kimi", "url": "integrate.api.nvidia.com", "ok": ok, "detail": detail}


def _check_lmstudio() -> dict[str, Any]:
    lm_host = os.environ.get("LMSTUDIO_HOST", "100.70.114.34")
    lm_port = os.environ.get("LMSTUDIO_PORT", "1234")
    url = f"http://{lm_host}:{lm_port}/v1/models"
    ok, detail = _http_ok(url, timeout=5)
    if ok:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                count = len(data.get("data", []))
                detail = f"{count} models loaded"
        except Exception:
            pass
    return {"name": "LM Studio", "url": f"{lm_host}:{lm_port}", "ok": ok, "detail": detail}


def check_services() -> list[dict[str, Any]]:
    """Run all service health checks in parallel."""
    checkers = [_check_gateway, _check_pinchtab, _check_searxng, _check_nvidia, _check_lmstudio]
    results: list[Optional[dict[str, Any]]] = [None] * len(checkers)

    def run(i: int, fn: Any) -> None:
        try:
            results[i] = fn()
        except Exception as exc:
            results[i] = {"name": f"check_{i}", "ok": False, "detail": str(exc)}

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(checkers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    return [r for r in results if r is not None]


# ---------------------------------------------------------------------------
# Agent status
# ---------------------------------------------------------------------------

# Static agent catalogue: (agent_id, display_name, role_tag)
AGENT_CATALOGUE = [
    ("jarvis",     "Jarvis",     "orchestrator"),
    ("hal",        "Hal",        "builder"),
    ("archimedes", "Archimedes", "reviewer"),
    ("anton",      "Anton",      "council"),
    ("scout",      "Scout",      "research"),
    ("hermes",     "Hermes",     "daemon"),
    ("bowser",     "Bowser",     "browser"),
    ("kitt",       "Kitt",       "quant"),
    ("cadence",    "Cadence",    "voice"),
    ("ralph",      "Ralph",      "overflow"),
    ("muse",       "Muse",       "creative"),
]


def _load_routing_policy() -> dict[str, dict[str, str]]:
    """Return {agent_id: {provider, model}} from runtime_routing_policy.json."""
    policy_path = ROOT / "config" / "runtime_routing_policy.json"
    try:
        data = json.loads(policy_path.read_text(encoding="utf-8"))
        agent_policies = data.get("agent_policies", {})
        return {
            aid: {
                "provider": ap.get("preferred_provider", "qwen"),
                "model": ap.get("preferred_model", "?"),
            }
            for aid, ap in agent_policies.items()
            if isinstance(ap, dict)
        }
    except Exception:
        return {}


def _load_agent_status(agent_id: str) -> dict[str, Any]:
    p = ROOT / "state" / "agent_status" / f"{agent_id}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _latest_backend_result(agent_id: str) -> Optional[dict[str, Any]]:
    results_dir = ROOT / "state" / "backend_results"
    if not results_dir.exists():
        return None
    candidates = []
    for p in results_dir.glob("bkres_*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("agent_id") == agent_id:
                candidates.append(d)
        except Exception:
            pass
    if not candidates:
        return None
    candidates.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
    return candidates[0]


def build_agent_rows(routing: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    rows = []
    for agent_id, display, role in AGENT_CATALOGUE:
        status = _load_agent_status(agent_id)
        latest = _latest_backend_result(agent_id)
        route = routing.get(agent_id, {})

        state = status.get("state", "unknown")
        headline = status.get("headline", "")
        updated = status.get("updated_at", "")
        task_id = status.get("current_task_id", "")
        last_result = status.get("last_result", "")

        provider = route.get("provider", "qwen")
        model = route.get("model", "?")

        # Short model label for display
        if provider == "nvidia":
            model_label = "kimi-k2.5 / nvidia"
        elif "browser" in role:
            model_label = "pinchtab / browser"
        elif "voice" in role:
            model_label = "local / voice"
        else:
            short_model = model.replace("Qwen3.5-", "Q3.5-").replace("Qwen3-", "Q3-").replace("moonshotai/", "")
            model_label = f"{short_model} / {provider}"

        # Time-since formatting
        time_label = ""
        if updated:
            try:
                dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                now = datetime.now(tz=timezone.utc)
                delta = now - dt
                mins = int(delta.total_seconds() / 60)
                if mins < 2:
                    time_label = "just now"
                elif mins < 60:
                    time_label = f"{mins}m ago"
                elif mins < 1440:
                    time_label = f"{mins // 60}h ago"
                else:
                    time_label = f"{mins // 1440}d ago"
            except Exception:
                time_label = updated[:16]

        # Last action summary from headline or backend result
        last_action = ""
        if headline:
            last_action = headline[:65]
        elif latest:
            last_action = (latest.get("summary") or "")[:65]

        rows.append({
            "agent_id": agent_id,
            "display": display,
            "role": role,
            "state": state,
            "model_label": model_label,
            "last_action": last_action,
            "last_result": last_result[:80] if last_result else "",
            "time_label": time_label,
            "has_status": bool(status),
            "task_id": task_id,
        })
    return rows


# ---------------------------------------------------------------------------
# Blocker detection
# ---------------------------------------------------------------------------

def check_blockers() -> list[dict[str, str]]:
    blockers = []

    # Discord webhooks — use delivery records as ground truth (env format checks miss expired URLs)
    delivery_dir = ROOT / "state" / "discord_delivery"
    outbox_dir = ROOT / "state" / "discord_outbox"
    failed_deliveries = 0
    pending_outbox = 0
    if delivery_dir.exists():
        for p in delivery_dir.glob("dlv_*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if d.get("status") == "failed" or d.get("http_status", 0) in (403, 404, 410):
                    failed_deliveries += 1
            except Exception:
                pass
    if outbox_dir.exists():
        for p in outbox_dir.glob("outbox_*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if d.get("status") == "pending":
                    pending_outbox += 1
            except Exception:
                pass
    if failed_deliveries > 0 or pending_outbox > 0:
        detail_parts = []
        if failed_deliveries:
            detail_parts.append(f"{failed_deliveries} delivery failures (HTTP 403 — webhooks expired)")
        if pending_outbox:
            detail_parts.append(f"{pending_outbox} pending outbox entries undelivered")
        blockers.append({
            "severity": "WARN",
            "item": "Discord webhooks",
            "detail": "; ".join(detail_parts),
            "fix": "Discord Server Settings → Integrations → create webhooks → set JARVIS_DISCORD_WEBHOOK_* in secrets.env",
        })

    # Anthropic API key
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not anthropic_key or anthropic_key.startswith("REPLACE") or anthropic_key.startswith("sk-ant-REPLACE"):
        blockers.append({
            "severity": "WARN",
            "item": "ANTHROPIC_API_KEY",
            "detail": "Not set — Claude/Anthropic provider offline",
            "fix": "Set ANTHROPIC_API_KEY in ~/.openclaw/secrets.env",
        })

    # Cadence mic
    blockers.append({
        "severity": "INFO",
        "item": "Cadence mic (parked)",
        "detail": "RDPSource unavailable in WSLg — voice stack built but listen loop waiting for mic passthrough",
        "fix": "Windows mic passthrough via RDP audio; no code change needed — daemon retries every 15s",
    })

    return blockers


# ---------------------------------------------------------------------------
# Quick actions
# ---------------------------------------------------------------------------

QUICK_ACTIONS = [
    ("Kitt NQ brief",   "python3 runtime/integrations/kitt_quant_workflow.py --query 'NQ regime' --target-url 'https://finance.yahoo.com/quote/NQ=F' --brief-only"),
    ("Kitt probe",      "python3 runtime/integrations/kitt_quant_workflow.py --probe"),
    ("Bowser navigate", "python3 runtime/integrations/bowser_adapter.py --task-id op_probe --actor operator --lane browser --action-type navigate --target-url https://example.com --execute"),
    ("Validate",        "python3 scripts/validate.py"),
    ("Mission sync",    "python3 scripts/mission_control_sync.py"),
    ("Agent status",    "python3 -m runtime.core.agent_status_store all"),
    ("Recent results",  "python3 -m runtime.core.backend_result_store list --n 10"),
]


# ---------------------------------------------------------------------------
# Snapshot assembly
# ---------------------------------------------------------------------------

def build_snapshot() -> dict[str, Any]:
    ts = datetime.now(tz=timezone.utc).isoformat()
    services = check_services()
    routing = _load_routing_policy()
    agents = build_agent_rows(routing)
    blockers = check_blockers()

    # Kitt brief summary from latest brief file
    kitt_brief_summary = ""
    briefs_dir = ROOT / "state" / "kitt_briefs"
    if briefs_dir.exists():
        briefs = sorted(briefs_dir.glob("kitt_brief_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if briefs:
            try:
                brief_data = json.loads(briefs[0].read_text(encoding="utf-8"))
                bt = brief_data.get("brief_text", "")
                if bt:
                    # First 200 chars of the brief
                    kitt_brief_summary = bt[:200].strip()
            except Exception:
                pass

    return {
        "generated_at": ts,
        "services": services,
        "agents": agents,
        "blockers": blockers,
        "kitt_latest_brief_preview": kitt_brief_summary,
        "quick_actions": [{"label": label, "cmd": cmd} for label, cmd in QUICK_ACTIONS],
    }


def save_snapshot(snap: dict[str, Any]) -> Path:
    logs_dir = ROOT / "state" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    p = logs_dir / "cockpit_snapshot.json"
    p.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Terminal renderer
# ---------------------------------------------------------------------------

_STATE_COLORS = {
    "idle":    green,
    "running": yellow,
    "waiting": yellow,
    "blocked": red,
    "error":   red,
    "unknown": dim,
}


def _state_badge(state: str, has_status: bool = True) -> str:
    if not has_status or state == "unknown":
        return dim("—      ")
    fn = _STATE_COLORS.get(state, dim)
    label = state.upper().ljust(7)
    return fn(label)


def _svc_badge(ok: bool) -> str:
    return green("✓ LIVE ") if ok else red("✗ DOWN ")


def render(snap: dict[str, Any]) -> str:
    lines = []
    ts = snap.get("generated_at", "")[:19].replace("T", " ")

    lines.append(bold("╔══════════════════════════════════════════════════════════════════╗"))
    lines.append(bold("║") + cyan(f"  OpenClaw Mission Control  ·  {ts} UTC") + bold(" " * (35 - len(ts)) + "║"))
    lines.append(bold("╚══════════════════════════════════════════════════════════════════╝"))
    lines.append("")

    # --- SERVICES ---
    lines.append(bold("SERVICES"))
    for svc in snap.get("services", []):
        badge = _svc_badge(svc["ok"])
        name = svc["name"].ljust(14)
        detail = dim(svc.get("detail", ""))
        url = dim(f"  {svc.get('url','')}")
        lines.append(f"  {badge} {name}{detail}")
    lines.append("")

    # --- AGENTS ---
    lines.append(bold("AGENTS"))
    header = (
        dim("  " + "AGENT".ljust(12) + "STATE   " + "MODEL / PROVIDER".ljust(26) + "LAST ACTION")
    )
    lines.append(header)
    lines.append(dim("  " + "─" * 90))

    for ag in snap.get("agents", []):
        state_s = _state_badge(ag["state"], ag["has_status"])
        name_s = ag["display"].ljust(12)
        model_s = ag.get("model_label", "?").ljust(26)
        time_s = dim(ag.get("time_label", "").rjust(9))
        action_s = ag.get("last_action", dim("no status yet"))
        if not ag["has_status"]:
            action_s = dim("— not yet run —")

        # Colour-code action by state
        if ag["state"] == "error":
            action_s = red(action_s) if ag["has_status"] else action_s
        elif ag["state"] in ("running", "waiting"):
            action_s = yellow(action_s) if ag["has_status"] else action_s

        lines.append(f"  {name_s}{state_s} {model_s}{time_s}  {action_s}")

    lines.append("")

    # --- KITT BRIEF ---
    brief = snap.get("kitt_latest_brief_preview", "")
    if brief:
        lines.append(bold("KITT LATEST BRIEF"))
        # Word-wrap to ~80 chars
        words = brief.split()
        line_buf, cur_len = [], 0
        wrapped_lines = []
        for w in words:
            if cur_len + len(w) + 1 > 78:
                wrapped_lines.append("  " + " ".join(line_buf))
                line_buf, cur_len = [w], len(w)
            else:
                line_buf.append(w)
                cur_len += len(w) + 1
        if line_buf:
            wrapped_lines.append("  " + " ".join(line_buf))
        lines.extend(wrapped_lines[:5])  # max 5 lines of brief preview
        if len(wrapped_lines) > 5:
            lines.append(dim("  … (truncated — see state/kitt_briefs/ for full brief)"))
        lines.append("")

    # --- BLOCKERS ---
    blockers = snap.get("blockers", [])
    if blockers:
        lines.append(bold("BLOCKERS"))
        for bl in blockers:
            sev = bl.get("severity", "WARN")
            icon = yellow("⚠") if sev in ("WARN", "INFO") else red("✗")
            item = bl.get("item", "")
            detail = bl.get("detail", "")
            fix = bl.get("fix", "")
            lines.append(f"  {icon} {bold(item)}: {detail}")
            if fix:
                lines.append(f"    {dim('fix: ' + fix[:90])}")
        lines.append("")

    # --- QUICK ACTIONS ---
    lines.append(bold("QUICK ACTIONS"))
    for qa in snap.get("quick_actions", []):
        label = qa["label"].ljust(16)
        cmd = dim(qa["cmd"])
        lines.append(f"  {cyan(label)}  {cmd}")
    lines.append("")

    # --- FOOTER ---
    snap_path = ROOT / "state" / "logs" / "cockpit_snapshot.json"
    lines.append(dim(f"  Snapshot: {snap_path}  ·  run 'python3 scripts/operator_cockpit.py' to refresh"))
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Watchboard update (--update-watchboard flag)
# ---------------------------------------------------------------------------

def update_watchboard(snap: dict[str, Any]) -> None:
    """Append a compact auto-generated status block to live_runtime_watchboard.md."""
    watchboard = ROOT / "docs" / "notes" / "live_runtime_watchboard.md"
    if not watchboard.exists():
        return

    ts = snap.get("generated_at", "")[:10]
    ts_full = snap.get("generated_at", "")[:19].replace("T", " ") + " UTC"

    services_live = [s["name"] for s in snap.get("services", []) if s["ok"]]
    services_down = [s["name"] for s in snap.get("services", []) if not s["ok"]]

    agent_lines = []
    for ag in snap.get("agents", []):
        state = ag["state"]
        if state == "unknown" and not ag["has_status"]:
            state = "—"
        action = ag.get("last_action", "")[:60] or "—"
        agent_lines.append(f"| {ag['display']:<12} | {state:<8} | {ag.get('model_label',''):<28} | {action} |")

    blocker_lines = []
    for bl in snap.get("blockers", []):
        sev = bl["severity"]
        blocker_lines.append(f"- **{bl['item']}** ({sev}): {bl['detail']}")

    block = f"""
---

## Auto-generated cockpit snapshot — {ts_full}

> _Generated by `scripts/operator_cockpit.py`. Do not edit this block._

### Services ({len(services_live)} live, {len(services_down)} down)
- Live: {', '.join(services_live) if services_live else 'none'}
- Down: {', '.join(services_down) if services_down else 'none'}

### Agent states

| Agent        | State    | Model / Provider             | Last action                                                  |
|--------------|----------|------------------------------|--------------------------------------------------------------|
""" + "\n".join(agent_lines) + """

### Blockers
""" + "\n".join(blocker_lines)

    with open(watchboard, "a", encoding="utf-8") as f:
        f.write(block + "\n")

    print(f"Watchboard updated: {watchboard}")


# ---------------------------------------------------------------------------
# Discord cockpit message
# ---------------------------------------------------------------------------

_DISCORD_STATE_EMOJI = {
    "idle": "\u2705",       # ✅
    "running": "\u25b6\ufe0f",  # ▶️
    "waiting": "\U0001f552",    # 🕒
    "blocked": "\U0001f6ab",    # 🚫
    "error": "\u274c",          # ❌
}


def format_discord_cockpit(snap: dict[str, Any]) -> str:
    """Render a cockpit snapshot as a compact emoji-first Discord message."""
    ts = snap.get("generated_at", "")[:16].replace("T", " ")
    lines: list[str] = [f"\U0001f4ca **Mission Control** \u2014 {ts} UTC"]  # 📊

    # Services — one line
    svcs = snap.get("services", [])
    live = [s["name"] for s in svcs if s["ok"]]
    down = [s["name"] for s in svcs if not s["ok"]]
    if down:
        lines.append(f"\u26a0\ufe0f Services: {len(live)} live, **{len(down)} down** ({', '.join(down)})")
    else:
        lines.append(f"\u2705 All {len(live)} services live")

    # Agents — compact list, only show agents with status
    lines.append("")
    for ag in snap.get("agents", []):
        if not ag.get("has_status"):
            continue
        state = ag.get("state", "unknown")
        emoji = _DISCORD_STATE_EMOJI.get(state, "\u2796")  # ➖
        name = ag.get("display", ag.get("agent_id", "?"))
        action = ag.get("last_action", "")
        if action:
            action = action[:50]
        model = ag.get("model_label", "")
        time_s = ag.get("time_label", "")
        line = f"{emoji} **{name}** `{model}`"
        if action:
            line += f"\n> {action}"
            if time_s:
                line += f" ({time_s})"
        lines.append(line)

    # Agents with no status — single collapsed line
    no_status = [ag["display"] for ag in snap.get("agents", []) if not ag.get("has_status")]
    if no_status:
        lines.append(f"\u2796 {', '.join(no_status)} \u2014 no turns yet")  # ➖

    # Blockers
    blockers = [b for b in snap.get("blockers", []) if b.get("severity") in ("WARN", "ERROR")]
    if blockers:
        lines.append("")
        for bl in blockers:
            lines.append(f"\u26a0\ufe0f **{bl['item']}**: {bl['detail'][:80]}")

    return "\n".join(lines)


def post_cockpit_to_discord(snap: dict[str, Any]) -> dict[str, Any]:
    """Post cockpit status to the Jarvis Discord channel via event router."""
    text = format_discord_cockpit(snap)
    try:
        from runtime.core.discord_event_router import emit_event
        return emit_event(
            "cockpit_status", "jarvis",
            detail=text,
            root=ROOT,
        )
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    global _USE_COLOR

    parser = argparse.ArgumentParser(
        description="OpenClaw operator cockpit — live mission control view.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON snapshot only")
    parser.add_argument("--no-color", action="store_true", help="Plain text (no ANSI)")
    parser.add_argument("--quiet", action="store_true", help="Only show WARN/ERROR lines")
    parser.add_argument("--update-watchboard", action="store_true",
                        help="Append status block to live_runtime_watchboard.md")
    parser.add_argument("--discord", action="store_true",
                        help="Post cockpit status to #jarvis Discord channel")
    args = parser.parse_args()

    if args.no_color:
        _USE_COLOR = False

    # Load .env if running outside a shell that already sourced it
    for env_path in [
        Path.home() / ".openclaw" / ".env",
        Path.home() / ".openclaw" / "secrets.env",
    ]:
        if env_path.exists():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        k = k.strip()
                        v = v.strip()
                        if k and v and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass

    snap = build_snapshot()
    snap_path = save_snapshot(snap)

    if args.json:
        print(json.dumps(snap, indent=2))
        return 0

    if not args.quiet:
        print(render(snap))
    else:
        # Quiet: only print blockers
        for bl in snap.get("blockers", []):
            if bl.get("severity") in ("WARN", "ERROR"):
                print(f"[{bl['severity']}] {bl['item']}: {bl['detail']}")

    if args.update_watchboard:
        update_watchboard(snap)

    if args.discord:
        result = post_cockpit_to_discord(snap)
        if result.get("error"):
            print(f"Discord post failed: {result['error']}", file=sys.stderr)
        else:
            event_id = result.get("event_id", "")
            entries = len(result.get("outbox_entries", []))
            print(f"Cockpit posted to Discord ({event_id}, {entries} outbox entries)")

    # Return non-zero if any critical service is down
    critical = ["Gateway", "LM Studio"]
    down_critical = [s["name"] for s in snap.get("services", []) if not s["ok"] and s["name"] in critical]
    if down_critical:
        print(dim(f"\n  {len(down_critical)} critical service(s) down: {', '.join(down_critical)}"), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
