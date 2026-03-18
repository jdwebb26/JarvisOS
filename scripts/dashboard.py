#!/usr/bin/env python3
"""dashboard — unified operator dashboard for Jarvis/OpenClaw.

Serves a browser-facing page that aggregates all operator surfaces
into one view: health, next action, approvals, failures, queue, outputs.

Usage:
    python3 scripts/dashboard.py                # serve on :18792
    python3 scripts/dashboard.py --port 8080    # custom port
    python3 scripts/dashboard.py --json         # dump data JSON to stdout and exit
    python3 scripts/dashboard.py --snapshot     # write snapshot to state/logs/dashboard.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# env loader (same pattern as other operator scripts)
# ---------------------------------------------------------------------------

def _load_env() -> None:
    for env_path in [
        Path.home() / ".openclaw" / "secrets.env",
        Path.home() / ".openclaw" / ".env",
    ]:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# Data aggregation — calls existing operator scripts
# ---------------------------------------------------------------------------

def collect_dashboard_data() -> dict[str, Any]:
    """Aggregate data from all operator surfaces into one blob."""
    ts = datetime.now(tz=timezone.utc).isoformat()[:19] + "Z"

    result: dict[str, Any] = {"generated_at": ts}

    # 1. Runtime health (from runtime_doctor)
    try:
        from scripts.runtime_doctor import run_all_checks
        doctor = run_all_checks()
        result["health"] = {
            "verdict": doctor.get("verdict", "UNKNOWN"),
            "pass": doctor.get("pass", 0),
            "warn": doctor.get("warn", 0),
            "fail": doctor.get("fail", 0),
            "checks": [
                {
                    "label": c.get("label", ""),
                    "level": c.get("level", ""),
                    "detail": c.get("detail", ""),
                    "fix": c.get("fix", ""),
                }
                for c in doctor.get("checks", [])
                if c.get("level") in ("warn", "fail")
            ],
        }
    except Exception as e:
        result["health"] = {"verdict": "ERROR", "error": str(e)}

    # 2. Next action (from operator_next)
    try:
        from scripts.operator_next import compute_actions
        actions = compute_actions()
        result["next_actions"] = actions[:5]
    except Exception as e:
        result["next_actions"] = [{"summary": f"Error: {e}", "category": "error"}]

    # 3. Task state (from operator_status)
    try:
        from scripts.operator_status import collect
        status = collect()
        result["approvals"] = status.get("approvals", [])
        result["failed"] = status.get("failed", [])
        result["blocked"] = status.get("blocked", [])
        result["queued"] = status.get("queued", [])
        result["outbox"] = status.get("outbox", {})
    except Exception as e:
        result["approvals"] = []
        result["failed"] = []
        result["blocked"] = []
        result["queued"] = []
        result["outbox"] = {"error": str(e)}

    # 4. Recent promoted outputs (from promote_output)
    try:
        from scripts.promote_output import list_promotable
        promotable = list_promotable(root=ROOT)
        result["promotable_outputs"] = promotable[:10]
    except Exception as e:
        result["promotable_outputs"] = []

    return result


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenClaw Dashboard</title>
<style>
:root { --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #c9d1d9;
        --dim: #8b949e; --green: #3fb950; --yellow: #d29922; --red: #f85149;
        --blue: #58a6ff; --mono: 'SF Mono', 'Fira Code', monospace; }
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: var(--bg); color: var(--text); padding: 16px; max-width: 900px; margin: 0 auto; }
h1 { font-size: 1.3em; margin-bottom: 4px; }
.ts { color: var(--dim); font-size: 0.85em; }
.section { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
           padding: 14px; margin: 12px 0; }
.section h2 { font-size: 1em; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.8em;
         font-weight: 600; }
.badge-pass { background: #1a3a2a; color: var(--green); }
.badge-warn { background: #3a2a1a; color: var(--yellow); }
.badge-fail { background: #3a1a1a; color: var(--red); }
.badge-count { background: var(--border); color: var(--text); }
.item { padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 0.9em; }
.item:last-child { border-bottom: none; }
.item-id { font-family: var(--mono); font-size: 0.8em; color: var(--blue); }
.item-label { color: var(--dim); font-size: 0.8em; }
.cmd { font-family: var(--mono); font-size: 0.78em; color: var(--dim); background: #0d1117;
       padding: 2px 6px; border-radius: 3px; display: inline-block; margin-top: 3px;
       word-break: break-all; cursor: pointer; }
.cmd:hover { color: var(--text); }
.next-box { background: #1a2233; border: 1px solid var(--blue); border-radius: 8px;
            padding: 14px; margin: 12px 0; }
.next-box h2 { color: var(--blue); font-size: 1em; margin-bottom: 6px; }
.empty { color: var(--dim); font-style: italic; font-size: 0.9em; }
.check-row { display: flex; gap: 8px; align-items: baseline; padding: 3px 0; font-size: 0.85em; }
.check-label { min-width: 60px; }
.loading { color: var(--dim); text-align: center; padding: 40px; }
</style>
</head>
<body>
<h1>&#x1F41E; OpenClaw Dashboard</h1>
<div class="ts" id="ts">Loading...</div>

<div id="app" class="loading">Fetching live state...</div>

<script>
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function badge(level) {
  const cls = level === 'PASS' ? 'badge-pass' : level === 'WARN' ? 'badge-warn' : 'badge-fail';
  return `<span class="badge ${cls}">${esc(level)}</span>`;
}

function countBadge(n) { return `<span class="badge badge-count">${n}</span>`; }

function cmd(c) { return `<span class="cmd" title="Click to copy" onclick="navigator.clipboard.writeText('${esc(c)}')">${esc(c)}</span>`; }

function renderHealth(h) {
  let html = `<div class="section"><h2>Runtime Health ${badge(h.verdict)}</h2>`;
  if (h.checks && h.checks.length > 0) {
    h.checks.forEach(c => {
      const lvl = c.level === 'fail' ? 'var(--red)' : 'var(--yellow)';
      html += `<div class="check-row"><span class="check-label" style="color:${lvl}">${esc(c.level.toUpperCase())}</span> <span>${esc(c.label)}: ${esc(c.detail)}</span></div>`;
      if (c.fix) html += `<div style="margin-left:68px">${cmd(c.fix)}</div>`;
    });
  } else if (h.verdict === 'PASS') {
    html += `<div class="empty">All checks passing</div>`;
  }
  html += '</div>';
  return html;
}

function renderNext(actions) {
  if (!actions || actions.length === 0) return `<div class="next-box"><h2>&#x2714;&#xfe0f; Next Action</h2><div class="empty">Nothing needs attention right now.</div></div>`;
  const a = actions[0];
  let html = `<div class="next-box"><h2>&#x27a1;&#xfe0f; Next Action</h2>`;
  html += `<div>${esc(a.summary || a.category || '')}</div>`;
  if (a.command) html += `<div style="margin-top:6px">${cmd(a.command)}</div>`;
  if (actions.length > 1) {
    html += `<div style="margin-top:10px;color:var(--dim);font-size:0.85em">Also:</div>`;
    actions.slice(1, 4).forEach(x => {
      html += `<div class="item"><span>${esc(x.summary || x.category || '')}</span>`;
      if (x.command) html += `<br>${cmd(x.command)}`;
      html += '</div>';
    });
  }
  html += '</div>';
  return html;
}

function renderList(title, items, idField, labelField, cmdPrefix, emoji) {
  let html = `<div class="section"><h2>${emoji} ${esc(title)} ${countBadge(items.length)}</h2>`;
  if (items.length === 0) {
    html += `<div class="empty">None</div>`;
  } else {
    items.slice(0, 8).forEach(item => {
      const id = item[idField] || item.task_id || '';
      const shortId = id.substring(0, 16);
      const label = item[labelField] || item.request || item.error || '';
      html += `<div class="item"><span class="item-id">${esc(shortId)}</span> ${esc(label.substring(0, 60))}`;
      if (cmdPrefix) {
        const fullId = item.task_id || id;
        html += `<br>${cmd(cmdPrefix + fullId)}`;
      }
      html += '</div>';
    });
    if (items.length > 8) html += `<div class="item-label">+${items.length - 8} more</div>`;
  }
  html += '</div>';
  return html;
}

function renderOutputs(items) {
  let html = `<div class="section"><h2>&#x1F4E6; Promotable Outputs ${countBadge(items.length)}</h2>`;
  if (items.length === 0) {
    html += `<div class="empty">No unpromoted outputs</div>`;
  } else {
    items.slice(0, 5).forEach(item => {
      const tid = (item.task_id || '').substring(0, 16);
      html += `<div class="item"><span class="item-id">${esc(tid)}</span> ${esc((item.request || item.preview || '').substring(0, 55))}`;
      if (item.task_id) html += `<br>${cmd('python3 scripts/promote_output.py --promote ' + item.task_id)}`;
      html += '</div>';
    });
  }
  html += '</div>';
  return html;
}

function render(data) {
  document.getElementById('ts').textContent = data.generated_at + ' UTC';
  let html = '';
  html += renderHealth(data.health || {});
  html += renderNext(data.next_actions || []);
  html += renderList('Pending Approvals', data.approvals || [], 'task_id', 'request',
                      'python3 scripts/run_ralph_v1.py --approve ', '&#x1F514;');
  html += renderList('Failed (Retryable)', data.failed || [], 'task_id', 'error',
                      'python3 scripts/run_ralph_v1.py --retry ', '&#x274C;');
  html += renderList('Blocked', data.blocked || [], 'task_id', 'request',
                      'python3 scripts/run_ralph_v1.py --retry ', '&#x1F6AB;');
  html += renderList('Queued', data.queued || [], 'task_id', 'request', '', '&#x1F4E5;');
  html += renderOutputs(data.promotable_outputs || []);
  document.getElementById('app').innerHTML = html;
}

async function refresh() {
  try {
    const resp = await fetch('/api/data');
    const data = await resp.json();
    render(data);
  } catch(e) {
    document.getElementById('app').innerHTML = `<div style="color:var(--red)">Error: ${e.message}</div>`;
  }
}

refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    root: Path

    def log_message(self, fmt, *args):
        pass  # suppress request logging

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")

        if path in ("", "/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", DASHBOARD_HTML.encode())
            return

        if path == "/api/data":
            try:
                data = collect_dashboard_data()
                body = json.dumps(data, indent=2, default=str).encode()
                self._send(200, "application/json", body)
            except Exception as e:
                body = json.dumps({"error": str(e)}).encode()
                self._send(500, "application/json", body)
            return

        self._send(404, "text/plain", b"Not Found")


# ---------------------------------------------------------------------------
# Snapshot mode
# ---------------------------------------------------------------------------

def write_snapshot() -> Path:
    data = collect_dashboard_data()
    logs_dir = ROOT / "state" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    out = logs_dir / "dashboard.json"
    out.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Unified operator dashboard")
    parser.add_argument("--port", type=int, default=18792, help="HTTP port (default 18792)")
    parser.add_argument("--json", action="store_true", help="Dump JSON to stdout")
    parser.add_argument("--snapshot", action="store_true", help="Write snapshot file")
    args = parser.parse_args()

    _load_env()

    if args.json:
        data = collect_dashboard_data()
        print(json.dumps(data, indent=2, default=str))
        return 0

    if args.snapshot:
        path = write_snapshot()
        print(f"Snapshot written to {path}")
        return 0

    server = HTTPServer(("127.0.0.1", args.port), DashboardHandler)
    server.root = ROOT
    print(f"Dashboard: http://127.0.0.1:{args.port}/", flush=True)
    print(f"API:       http://127.0.0.1:{args.port}/api/data", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
