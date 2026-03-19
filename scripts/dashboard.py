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
        result["quant_live_queued"] = status.get("quant_live_queued", [])
    except Exception as e:
        result["approvals"] = []
        result["failed"] = []
        result["blocked"] = []
        result["queued"] = []
        result["outbox"] = {"error": str(e)}
        result["quant_live_queued"] = []

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
<title>OpenClaw Ops</title>
<style>
:root {
  --bg: #0b0e14; --surface: #141820; --surface2: #1a1f2b;
  --border: #252b37; --border-hover: #3a4258;
  --text: #d4dae4; --text2: #9aa3b4; --dim: #626d82;
  --green: #4ade80; --green-bg: rgba(74,222,128,.08); --green-border: rgba(74,222,128,.18);
  --yellow: #facc15; --yellow-bg: rgba(250,204,21,.08); --yellow-border: rgba(250,204,21,.18);
  --red: #f87171; --red-bg: rgba(248,113,113,.06); --red-border: rgba(248,113,113,.15);
  --blue: #60a5fa; --blue-bg: rgba(96,165,250,.08); --blue-border: rgba(96,165,250,.18);
  --purple: #a78bfa; --purple-bg: rgba(167,139,250,.08); --purple-border: rgba(167,139,250,.15);
  --orange: #fb923c; --orange-bg: rgba(251,146,60,.08); --orange-border: rgba(251,146,60,.15);
  --mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  --sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  --radius: 10px; --radius-sm: 6px;
}
*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
html { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }
body {
  font-family: var(--sans); background: var(--bg); color: var(--text);
  padding: 20px 16px 40px; max-width: 720px; margin: 0 auto;
  line-height: 1.5; font-size: 14px;
}

/* --- Header --- */
.header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 20px; }
.header h1 { font-size: 17px; font-weight: 700; letter-spacing: -.01em; white-space: nowrap; }
.header .meta { font-size: 12px; color: var(--dim); font-family: var(--mono); }
.refresh-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%;
  background: var(--green); margin-right: 6px; vertical-align: middle;
  animation: pulse 2s ease-in-out infinite; }
@keyframes pulse { 0%,100% { opacity: .4; } 50% { opacity: 1; } }

/* --- Status strip --- */
.status-strip {
  display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap;
}
.stat {
  flex: 1; min-width: 80px; padding: 10px 12px;
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm);
  text-align: center;
}
.stat-value { font-size: 22px; font-weight: 700; font-family: var(--mono); line-height: 1.2; }
.stat-label { font-size: 10px; text-transform: uppercase; letter-spacing: .06em;
  color: var(--dim); margin-top: 2px; }
.stat-pass .stat-value { color: var(--green); }
.stat-warn .stat-value { color: var(--yellow); }
.stat-fail .stat-value { color: var(--red); }

/* --- Cards --- */
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  margin-bottom: 12px; overflow: hidden;
}
.card-header {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 16px; border-bottom: 1px solid var(--border);
  font-size: 13px; font-weight: 600;
}
.card-header .icon { font-size: 15px; line-height: 1; }
.card-header .count {
  margin-left: auto; font-family: var(--mono); font-size: 11px; font-weight: 500;
  padding: 2px 8px; border-radius: 10px;
  background: var(--surface2); color: var(--text2);
}
.card-body { padding: 0; }
.card-empty { padding: 16px; color: var(--dim); font-size: 13px; }

/* --- Next Action (hero) --- */
.hero {
  background: var(--blue-bg); border: 1px solid var(--blue-border);
  border-radius: var(--radius); padding: 16px; margin-bottom: 12px;
}
.hero-label { font-size: 10px; text-transform: uppercase; letter-spacing: .08em;
  color: var(--blue); font-weight: 600; margin-bottom: 6px; }
.hero-text { font-size: 14px; color: var(--text); line-height: 1.45; }
.hero-action { margin-top: 10px; }
.hero-also { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--blue-border); }
.hero-also-label { font-size: 10px; text-transform: uppercase; letter-spacing: .06em;
  color: var(--dim); margin-bottom: 6px; }

/* --- Row items --- */
.row {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 10px 16px; border-bottom: 1px solid var(--border);
  transition: background .12s;
}
.row:last-child { border-bottom: none; }
.row:hover { background: var(--surface2); }
.row-id { font-family: var(--mono); font-size: 11px; color: var(--dim);
  flex-shrink: 0; min-width: 85px; padding-top: 1px; }
.row-body { flex: 1; min-width: 0; }
.row-text { font-size: 13px; color: var(--text); display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.row-error { font-size: 12px; color: var(--red); margin-top: 2px;
  display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
.row-actions { display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }

/* --- Approval cards --- */
.approval-row {
  padding: 12px 16px; border-bottom: 1px solid var(--border);
  transition: background .12s;
}
.approval-row:last-child { border-bottom: none; }
.approval-row:hover { background: var(--surface2); }
.approval-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.approval-id { font-family: var(--mono); font-size: 11px; color: var(--dim); }
.approval-badge { font-size: 10px; padding: 1px 7px; border-radius: 10px;
  background: var(--yellow-bg); color: var(--yellow); border: 1px solid var(--yellow-border);
  font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
.approval-text { font-size: 13px; color: var(--text); margin-bottom: 8px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.live-badge { font-size: 10px; padding: 1px 7px; border-radius: 10px;
  font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
.live-approved { background: var(--green-bg); color: var(--green); border: 1px solid var(--green-border); }
.live-pending { background: var(--blue-bg); color: var(--blue); border: 1px solid var(--blue-border); }
.live-no_request { background: var(--orange-bg); color: var(--orange); border: 1px solid var(--orange-border); }
.live-revoked { background: var(--red-bg); color: var(--red); border: 1px solid var(--red-border); }
.live-expired { background: var(--yellow-bg); color: var(--yellow); border: 1px solid var(--yellow-border); }

/* --- Buttons --- */
.btn {
  display: inline-flex; align-items: center; gap: 4px;
  font-family: var(--mono); font-size: 11px; font-weight: 500;
  padding: 4px 10px; border-radius: var(--radius-sm);
  cursor: pointer; border: 1px solid; transition: all .15s;
  background: transparent; text-decoration: none; white-space: nowrap;
}
.btn-approve { color: var(--green); border-color: var(--green-border); }
.btn-approve:hover { background: var(--green-bg); border-color: var(--green); }
.btn-retry { color: var(--yellow); border-color: var(--yellow-border); }
.btn-retry:hover { background: var(--yellow-bg); border-color: var(--yellow); }
.btn-copy { color: var(--text2); border-color: var(--border); }
.btn-copy:hover { background: var(--surface2); border-color: var(--border-hover); color: var(--text); }
.btn-promote { color: var(--purple); border-color: var(--purple-border); }
.btn-promote:hover { background: var(--purple-bg); border-color: var(--purple); }
.btn .copied { display: none; }
.btn.is-copied .label { display: none; }
.btn.is-copied .copied { display: inline; }

/* --- Health checks inline --- */
.health-checks { padding: 4px 16px 12px; }
.hc-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px; }
.hc-level { font-family: var(--mono); font-size: 10px; font-weight: 700;
  text-transform: uppercase; min-width: 36px; }
.hc-warn { color: var(--yellow); }
.hc-fail { color: var(--red); }
.hc-text { color: var(--text2); flex: 1; }
.hc-fix .btn { font-size: 10px; padding: 2px 8px; }

/* --- Collapsible sections --- */
.section-toggle { cursor: pointer; user-select: none; }
.section-toggle .chevron { transition: transform .2s; display: inline-block; font-size: 10px;
  color: var(--dim); margin-left: 4px; }
.section-toggle.collapsed .chevron { transform: rotate(-90deg); }
.section-toggle.collapsed + .card-body { display: none; }

/* --- Overflow --- */
.overflow { padding: 8px 16px; font-size: 12px; color: var(--dim); }

/* --- Footer --- */
.footer { text-align: center; padding: 20px 0 0; font-size: 11px; color: var(--dim);
  font-family: var(--mono); }

/* --- Loading --- */
.loading { color: var(--dim); text-align: center; padding: 60px 0; font-size: 13px; }

/* --- Responsive --- */
@media (max-width: 480px) {
  body { padding: 12px 10px 32px; font-size: 13px; }
  .status-strip { gap: 6px; }
  .stat { padding: 8px 6px; min-width: 60px; }
  .stat-value { font-size: 18px; }
  .row { padding: 8px 12px; gap: 8px; }
  .row-id { min-width: 70px; font-size: 10px; }
  .approval-row { padding: 10px 12px; }
  .card-header { padding: 10px 12px; }
  .hero { padding: 12px; }
}
</style>
</head>
<body>

<div class="header">
  <h1>OpenClaw Ops</h1>
  <span class="meta"><span class="refresh-dot"></span><span id="ts">...</span></span>
</div>

<div id="app" class="loading">Loading live state...</div>

<script>
function esc(s) {
  if (s == null) return '';
  const d = document.createElement('div');
  d.textContent = String(s);
  return d.innerHTML;
}

function shortId(id) { return (id || '').replace(/^(task_|apr_|art_)/, '').substring(0, 10); }

function copyBtn(cmd, label, cls) {
  const escaped = esc(cmd).replace(/'/g, "\\'");
  return `<button class="btn ${cls}" onclick="copyCmd(this, '${escaped}')"><span class="label">${label}</span><span class="copied">copied</span></button>`;
}

function copyCmd(el, text) {
  navigator.clipboard.writeText(text);
  el.classList.add('is-copied');
  setTimeout(() => el.classList.remove('is-copied'), 1200);
}

function toggleSection(el) {
  el.classList.toggle('collapsed');
}

/* --- Status strip --- */
function renderStrip(data) {
  const h = data.health || {};
  const verdictCls = h.verdict === 'PASS' ? 'stat-pass' : h.verdict === 'WARN' ? 'stat-warn' : 'stat-fail';
  const approvals = (data.approvals || []).length;
  const failed = (data.failed || []).length;
  const queued = (data.queued || []).length;
  const blocked = (data.blocked || []).length;
  const liveQueued = (data.quant_live_queued || []).length;
  return `<div class="status-strip">
    <div class="stat ${verdictCls}"><div class="stat-value">${esc(h.verdict || '?')}</div><div class="stat-label">Health</div></div>
    <div class="stat ${approvals > 0 ? 'stat-warn' : ''}"><div class="stat-value">${approvals}</div><div class="stat-label">Approvals</div></div>
    <div class="stat ${liveQueued > 0 ? 'stat-warn' : ''}"><div class="stat-value">${liveQueued}</div><div class="stat-label">Live Queued</div></div>
    <div class="stat ${failed > 0 ? 'stat-fail' : ''}"><div class="stat-value">${failed}</div><div class="stat-label">Failed</div></div>
    <div class="stat"><div class="stat-value">${blocked}</div><div class="stat-label">Blocked</div></div>
    <div class="stat"><div class="stat-value">${queued}</div><div class="stat-label">Queued</div></div>
  </div>`;
}

/* --- Health card --- */
function renderHealth(h) {
  if (!h || !h.checks || h.checks.length === 0) {
    if (h && h.verdict === 'PASS') return '';
    if (h && h.error) return `<div class="card"><div class="card-header"><span class="icon">&#x26A0;</span> Health Error</div><div class="card-body"><div class="card-empty">${esc(h.error)}</div></div></div>`;
    return '';
  }
  let html = `<div class="card"><div class="card-header"><span class="icon">&#x1F3E5;</span> Health Issues <span class="count">${h.checks.length}</span></div><div class="health-checks">`;
  h.checks.forEach(c => {
    const cls = c.level === 'fail' ? 'hc-fail' : 'hc-warn';
    html += `<div class="hc-row"><span class="hc-level ${cls}">${esc(c.level)}</span><span class="hc-text">${esc(c.label)}: ${esc(c.detail)}</span>`;
    if (c.fix) html += `<span class="hc-fix">${copyBtn(c.fix, 'Fix', 'btn-copy')}</span>`;
    html += `</div>`;
  });
  html += `</div></div>`;
  return html;
}

/* --- Next Action hero --- */
function renderNext(actions) {
  if (!actions || actions.length === 0) {
    return `<div class="hero"><div class="hero-label">Next Action</div><div class="hero-text" style="color:var(--dim)">Nothing needs attention right now.</div></div>`;
  }
  const a = actions[0];
  // Extract just the description after the task_id prefix
  const summary = (a.summary || a.category || '').replace(/^(approve|retry|review)\s+task_\w+\s*\u2014\s*/, '');
  const taskId = a.task_id || '';

  let html = `<div class="hero"><div class="hero-label">Next Action</div>`;
  html += `<div class="hero-text">${esc(summary)}</div>`;
  if (a.command) {
    html += `<div class="hero-action">${copyBtn(a.command, a.category === 'approval' ? 'Approve' : 'Run', a.category === 'approval' ? 'btn-approve' : 'btn-retry')}</div>`;
  }

  if (actions.length > 1) {
    html += `<div class="hero-also"><div class="hero-also-label">${actions.length - 1} more action${actions.length > 2 ? 's' : ''}</div>`;
    actions.slice(1, 4).forEach(x => {
      const xs = (x.summary || '').replace(/^(approve|retry|review)\s+task_\w+\s*\u2014\s*/, '');
      html += `<div style="display:flex;align-items:center;gap:8px;padding:3px 0"><span style="font-size:12px;color:var(--text2);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(xs)}</span>`;
      if (x.command) html += copyBtn(x.command, x.category === 'approval' ? 'Approve' : 'Run', 'btn-copy');
      html += `</div>`;
    });
    html += `</div>`;
  }
  html += `</div>`;
  return html;
}

/* --- Approvals --- */
function renderApprovals(items) {
  let html = `<div class="card"><div class="card-header section-toggle" onclick="toggleSection(this)"><span class="icon">&#x1F514;</span> Pending Approvals <span class="chevron">&#x25BC;</span><span class="count">${items.length}</span></div><div class="card-body">`;
  if (items.length === 0) {
    html += `<div class="card-empty">No pending approvals</div>`;
  } else {
    items.slice(0, 10).forEach(item => {
      const tid = item.task_id || '';
      html += `<div class="approval-row">`;
      html += `<div class="approval-meta"><span class="approval-id">${esc(shortId(tid))}</span><span class="approval-badge">Awaiting</span></div>`;
      html += `<div class="approval-text">${esc(item.request || '')}</div>`;
      html += `<div class="row-actions">`;
      html += copyBtn('python3 scripts/run_ralph_v1.py --approve ' + tid, 'Approve', 'btn-approve');
      html += copyBtn(tid, 'Copy ID', 'btn-copy');
      html += `</div></div>`;
    });
    if (items.length > 10) html += `<div class="overflow">+${items.length - 10} more</div>`;
  }
  html += `</div></div>`;
  return html;
}

/* --- LIVE_QUEUED strategies --- */
function renderLiveQueued(items) {
  if (!items || items.length === 0) return '';
  let html = `<div class="card"><div class="card-header section-toggle" onclick="toggleSection(this)"><span class="icon">&#x1F4B0;</span> LIVE_QUEUED Strategies <span class="chevron">&#x25BC;</span><span class="count">${items.length}</span></div><div class="card-body">`;
  items.forEach(item => {
    const sid = item.strategy_id || '';
    const state = item.approval_state || '?';
    const badge = state === 'approved' ? 'Ready' : state === 'pending' ? 'Pending' : state === 'no_request' ? 'Needs Request' : state;
    const cls = state === 'approved' ? 'btn-approve' : state === 'pending' ? 'btn-copy' : 'btn-retry';
    html += `<div class="approval-row">`;
    html += `<div class="approval-meta"><span class="approval-id">${esc(sid)}</span><span class="live-badge live-${state}">${esc(badge)}</span></div>`;
    html += `<div class="approval-text">${esc(item.label || '')}</div>`;
    html += `<div class="row-actions">${copyBtn(item.action || '', badge === 'Ready' ? 'Execute' : 'Action', cls)}</div>`;
    html += `</div>`;
  });
  html += `</div></div>`;
  return html;
}

/* --- Failed --- */
function renderFailed(items) {
  let html = `<div class="card"><div class="card-header section-toggle" onclick="toggleSection(this)"><span class="icon">&#x26A0;</span> Failed <span class="chevron">&#x25BC;</span><span class="count">${items.length}</span></div><div class="card-body">`;
  if (items.length === 0) {
    html += `<div class="card-empty">No failures</div>`;
  } else {
    items.slice(0, 8).forEach(item => {
      const tid = item.task_id || '';
      html += `<div class="row"><div class="row-id">${esc(shortId(tid))}</div><div class="row-body">`;
      html += `<div class="row-text">${esc(item.request || '')}</div>`;
      if (item.error) html += `<div class="row-error">${esc(item.error)}</div>`;
      html += `<div class="row-actions">${copyBtn('python3 scripts/run_ralph_v1.py --retry ' + tid, 'Retry', 'btn-retry')} ${copyBtn(tid, 'Copy ID', 'btn-copy')}</div>`;
      html += `</div></div>`;
    });
    if (items.length > 8) html += `<div class="overflow">+${items.length - 8} more</div>`;
  }
  html += `</div></div>`;
  return html;
}

/* --- Blocked --- */
function renderBlocked(items) {
  let html = `<div class="card"><div class="card-header section-toggle" onclick="toggleSection(this)"><span class="icon">&#x1F6D1;</span> Blocked <span class="chevron">&#x25BC;</span><span class="count">${items.length}</span></div><div class="card-body">`;
  if (items.length === 0) {
    html += `<div class="card-empty">Nothing blocked</div>`;
  } else {
    items.slice(0, 8).forEach(item => {
      const tid = item.task_id || '';
      html += `<div class="row"><div class="row-id">${esc(shortId(tid))}</div><div class="row-body">`;
      html += `<div class="row-text">${esc(item.request || '')}</div>`;
      if (item.error) html += `<div class="row-error">${esc(item.error)}</div>`;
      html += `<div class="row-actions">${copyBtn('python3 scripts/run_ralph_v1.py --retry ' + tid, 'Retry', 'btn-retry')} ${copyBtn(tid, 'Copy ID', 'btn-copy')}</div>`;
      html += `</div></div>`;
    });
    if (items.length > 8) html += `<div class="overflow">+${items.length - 8} more</div>`;
  }
  html += `</div></div>`;
  return html;
}

/* --- Queued --- */
function renderQueued(items) {
  let html = `<div class="card"><div class="card-header section-toggle" onclick="toggleSection(this)"><span class="icon">&#x23F3;</span> Queued <span class="chevron">&#x25BC;</span><span class="count">${items.length}</span></div><div class="card-body">`;
  if (items.length === 0) {
    html += `<div class="card-empty">Queue empty</div>`;
  } else {
    items.slice(0, 8).forEach(item => {
      const tid = item.task_id || '';
      html += `<div class="row"><div class="row-id">${esc(shortId(tid))}</div><div class="row-body">`;
      html += `<div class="row-text">${esc(item.request || '')}</div>`;
      html += `</div></div>`;
    });
    if (items.length > 8) html += `<div class="overflow">+${items.length - 8} more</div>`;
  }
  html += `</div></div>`;
  return html;
}

/* --- Promotable outputs --- */
function renderOutputs(items) {
  let html = `<div class="card"><div class="card-header section-toggle" onclick="toggleSection(this)"><span class="icon">&#x1F4E6;</span> Promotable Outputs <span class="chevron">&#x25BC;</span><span class="count">${items.length}</span></div><div class="card-body">`;
  if (items.length === 0) {
    html += `<div class="card-empty">No outputs ready</div>`;
  } else {
    items.slice(0, 6).forEach(item => {
      const tid = item.task_id || '';
      html += `<div class="row"><div class="row-id">${esc(shortId(tid))}</div><div class="row-body">`;
      html += `<div class="row-text">${esc(item.request || item.preview || '')}</div>`;
      html += `<div class="row-actions">${copyBtn('python3 scripts/promote_output.py --promote ' + tid, 'Promote', 'btn-promote')} ${copyBtn(tid, 'Copy ID', 'btn-copy')}</div>`;
      html += `</div></div>`;
    });
    if (items.length > 6) html += `<div class="overflow">+${items.length - 6} more</div>`;
  }
  html += `</div></div>`;
  return html;
}

/* --- Main render --- */
function render(data) {
  document.getElementById('ts').textContent = (data.generated_at || '').replace('T', ' ').replace('Z', '') + ' UTC';
  let html = '';
  html += renderStrip(data);
  html += renderHealth(data.health || {});
  html += renderNext(data.next_actions || []);
  html += renderApprovals(data.approvals || []);
  html += renderLiveQueued(data.quant_live_queued || []);
  html += renderFailed(data.failed || []);
  html += renderBlocked(data.blocked || []);
  html += renderQueued(data.queued || []);
  html += renderOutputs(data.promotable_outputs || []);
  html += `<div class="footer">auto-refresh 30s</div>`;
  document.getElementById('app').innerHTML = html;
}

async function refresh() {
  try {
    const resp = await fetch('/api/data');
    const data = await resp.json();
    render(data);
  } catch(e) {
    document.getElementById('app').innerHTML = `<div style="color:var(--red);padding:40px;text-align:center">Error: ${esc(e.message)}</div>`;
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
