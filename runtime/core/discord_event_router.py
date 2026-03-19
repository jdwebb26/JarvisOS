#!/usr/bin/env python3
"""discord_event_router — normalize runtime events → owner channel + outbox entries.

Design rules:
  - Local structured state is truth. Discord is presentation.
  - No LLM calls. Status text is deterministic English templates.
  - Cadence channel is VOICE-ONLY. Non-voice events are rejected/rerouted.
  - Every event writes a dispatch_event record.
  - Outbox entries written to state/discord_outbox/ for delivery.
  - Messages are emoji-first, glanceable: ✅ result / ❌ fail / ⚠️ warn / 📌 next step.

Event kinds supported:
    task_created, task_started, task_progress, task_completed, task_failed,
    task_blocked, review_requested, review_completed, approval_requested,
    approval_completed, artifact_promoted, browser_action, browser_result,
    kitt_brief_completed, kitt_brief_failed,
    voice_session_started, voice_session_ended, tts_started, tts_completed,
    call_started, call_ended, agent_online, agent_offline, agent_status,
    delegation_sent, delegation_received, profile_changed, models_status,
    cockpit_status, warning, error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import new_id, now_iso


# ---------------------------------------------------------------------------
# Load channel map
# ---------------------------------------------------------------------------

def _load_channel_map(root: Optional[Path] = None) -> dict[str, Any]:
    base = Path(root or ROOT).resolve()
    path = base / "config" / "agent_channel_map.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# State directories
# ---------------------------------------------------------------------------

def _dispatch_dir(root: Optional[Path] = None) -> Path:
    d = Path(root or ROOT).resolve() / "state" / "dispatch_events"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _outbox_dir(root: Optional[Path] = None) -> Path:
    d = Path(root or ROOT).resolve() / "state" / "discord_outbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Deterministic message formatting
# ---------------------------------------------------------------------------

_AGENT_DISPLAY: dict[str, str] = {
    "jarvis": "Jarvis", "hal": "HAL", "scout": "Scout",
    "anton": "Anton", "archimedes": "Archimedes", "hermes": "Hermes",
    "kitt": "Kitt", "sigma": "Sigma", "atlas": "Atlas", "fish": "Fish",
    "claude": "Claude", "qwen": "Qwen",
    "bowser": "Bowser", "cadence": "Cadence", "muse": "Muse", "ralph": "Ralph",
}

# Patterns to strip from detail text — internal IDs, noise, raw exceptions
_NOISE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\btab [A-F0-9]{16,}\b"),              # PinchTab tab hashes
    re.compile(r"\bsnapshot nodes=\d+"),                # snapshot counts
    re.compile(r"\bcycle r?cycle_[a-f0-9]+"),           # Ralph cycle IDs
    re.compile(r"\(cycle r?cycle_[a-f0-9]+\)"),         # parenthesized cycle IDs
    re.compile(r"\bart_[a-f0-9]{10,}\b"),               # artifact IDs in prose
    re.compile(r"\[artifact:\s*\]"),                    # empty artifact references
    re.compile(r"\[artifact:\s*art_[a-f0-9]+\]"),       # full artifact references in prose
    re.compile(r"HTTPConnectionPool\(.*?\):\s*"),       # urllib connection pool noise
    re.compile(r"Max retries exceeded with url:\s*\S+"), # retry noise
    re.compile(r"\(Caused by \w+Error\(<[^>]*>\s*,\s*"), # nested exception wrappers
    re.compile(r"'\)\)$"),                              # trailing quote-paren from exceptions
    re.compile(r"\(\)"),                                # empty parens left by removals
    # LLM reviewer preamble noise (model name + timing)
    re.compile(r"Archimedes auto-review \([^)]+\):\s*"),  # "Archimedes auto-review (qwen3.5-35b-a3b, 8.29s): "
    re.compile(r"\w+ auto-review \([^)]+\):\s*"),        # any agent auto-review preamble
]

# Emoji prefix per event kind — drives the glanceable visual shape
_EMOJI: dict[str, str] = {
    "task_created": "\U0001f4cb",       # 📋
    "task_started": "\u25b6\ufe0f",     # ▶️
    "task_progress": "\U0001f504",      # 🔄
    "task_completed": "\u2705",         # ✅
    "task_failed": "\u274c",            # ❌
    "task_blocked": "\U0001f6ab",       # 🚫
    "review_requested": "\U0001f440",   # 👀
    "review_completed": "\U0001f4cb",   # 📋
    "approval_requested": "\U0001f510", # 🔐
    "approval_completed": "\U0001f513", # 🔓
    "artifact_promoted": "\U0001f4e6",  # 📦
    "browser_action": "\U0001f310",     # 🌐
    "browser_result": "\U0001f310",     # 🌐
    "kitt_brief_completed": "\U0001f9e0", # 🧠
    "kitt_brief_failed": "\u274c",      # ❌
    "voice_session_started": "\U0001f399\ufe0f", # 🎙️
    "voice_session_ended": "\U0001f399\ufe0f",
    "tts_started": "\U0001f399\ufe0f",
    "tts_completed": "\U0001f399\ufe0f",
    "call_started": "\U0001f399\ufe0f",
    "call_ended": "\U0001f399\ufe0f",
    "agent_online": "\U0001f7e2",       # 🟢
    "agent_offline": "\U0001f534",      # 🔴
    "agent_status": "\U0001f4ac",       # 💬
    "delegation_sent": "\U0001f500",    # 🔀
    "delegation_received": "\U0001f500",
    "warning": "\u26a0\ufe0f",         # ⚠️
    "error": "\U0001f534",             # 🔴
    "profile_changed": "\U0001f504",   # 🔄
    "models_status": "\U0001f4ca",     # 📊
    "cockpit_status": "\U0001f4ca",    # 📊
    # Quant lane events
    "quant_strategy_promoted": "\U0001f4c8",   # 📈
    "quant_strategy_rejected": "\U0001f4c9",   # 📉
    "quant_validation_completed": "\U0001f50d", # 🔍
    "quant_papertrade_candidate": "\U0001f4cb", # 📋
    "quant_papertrade_request": "\U0001f4dd",  # 📝
    "quant_paper_review": "\U0001f4ca",        # 📊
    "quant_execution_intent": "\u23f3",        # ⏳
    "quant_execution_status": "\U0001f4b9",    # 💹
    "quant_execution_rejected": "\U0001f6d1",  # 🛑
    "quant_fill": "\U0001f4b0",               # 💰
    "quant_candidate_submitted": "\U0001f9ea", # 🧪
    "quant_scenario_submitted": "\U0001f3a3", # 🎣
    "quant_alert": "\U0001f6a8",              # 🚨
    "quant_setup": "\U0001f3af",              # 🎯
    "quant_health": "\U0001f3e5",             # 🏥
    "quant_pulse_alert": "\U0001f4a1",       # 💡
    "quant_pulse_cluster": "\U0001f4a1",     # 💡
    "quant_pulse_proposal": "\U0001f4dd",    # 📝 (needs decision)
    "quant_pulse_learning": "\U0001f4a1",    # 💡
    "factory_weekly_summary": "\U0001f4ca",  # 📊
}


def _display(agent_id: str) -> str:
    return _AGENT_DISPLAY.get(agent_id, agent_id.capitalize())


def _short_task_id(task_id: str) -> str:
    """Shorten task_abc123def456 → abc123."""
    if task_id.startswith("task_") and len(task_id) > 11:
        return task_id[5:11]
    return task_id


def _clean_detail(detail: str) -> str:
    """Strip internal noise from detail text, truncate to readable length."""
    if not detail:
        return ""
    text = detail
    for pat in _NOISE_PATTERNS:
        text = pat.sub("", text)
    # Collapse whitespace left by removals
    text = re.sub(r"  +", " ", text).strip()
    # Strip trailing punctuation clutter from removals
    text = re.sub(r"[;,.\s]+$", "", text).strip()
    # Truncate at 200 chars for readability
    if len(text) > 200:
        text = text[:197] + "..."
    return text


def _extract_error_summary(detail: str) -> str:
    """Pull the human-readable error from a possibly long exception string."""
    if not detail:
        return ""
    # Common pattern: "Connection to X timed out" / "SomeError: message"
    # Try to find the innermost meaningful error
    for pat in [
        re.compile(r"Connection to \S+ timed out[^)]*", re.IGNORECASE),
        re.compile(r"(\w+Error):\s*(.{5,80})", re.IGNORECASE),
        re.compile(r"(timed out|connection refused|not found|failed|denied|rejected)\b[^)]{0,80}", re.IGNORECASE),
    ]:
        match = pat.search(detail)
        if match:
            summary = match.group(0).strip().rstrip("',)> ")
            # Balance parens
            while summary.count(")") > summary.count("(") and summary.endswith(")"):
                summary = summary[:-1]
            while summary.count("(") > summary.count(")"):
                idx = summary.rfind("(")
                if idx > 0:
                    summary = summary[:idx].rstrip()
                else:
                    break
            summary = summary.rstrip(" .")
            if len(summary) > 120:
                summary = summary[:117] + "..."
            return summary
    return _clean_detail(detail)


def _render_status_text(kind: str, payload: dict[str, Any]) -> str:
    """Produce an emoji-first, glanceable Discord message for a runtime event.

    Shape:
        <emoji> **Agent** action `task`
        > detail (cleaned, one line)
        📌 next step (only when action needed)

    Optimized for phone readability: short, scannable, no wall-of-text.
    """
    agent = _display(payload.get("agent_id", "unknown"))
    task_id = payload.get("task_id", "")
    short_tid = _short_task_id(task_id) if task_id else ""
    detail = payload.get("detail", "")
    target = payload.get("target", "")
    reviewer = _display(payload.get("reviewer_id", ""))
    artifact = payload.get("artifact_id", "")
    e = _EMOJI.get(kind, "\u2139\ufe0f")  # ℹ️ fallback

    clean = _clean_detail(detail)

    # --- Voice (ultra-compact) ---

    if kind in ("voice_session_started", "voice_session_ended",
                "tts_started", "tts_completed", "call_started", "call_ended"):
        label_map = {
            "voice_session_started": "session started",
            "voice_session_ended": "session ended",
            "tts_started": "TTS started",
            "tts_completed": "TTS done",
            "call_started": "call started",
            "call_ended": "call ended",
        }
        return f"{e} **Cadence** {label_map[kind]}"

    # --- Agent status ---

    if kind == "agent_online":
        return f"{e} **{agent}** online"

    if kind == "agent_offline":
        return f"{e} **{agent}** offline"

    if kind == "agent_status":
        return f"{e} **{agent}** {clean}" if clean else f"{e} **{agent}**"

    # --- Task lifecycle ---

    if kind == "task_created":
        line = f"{e} **{agent}** created `{short_tid}`"
        return f"{line}\n> {clean}" if clean else line

    if kind == "task_started":
        line = f"{e} **{agent}** started `{short_tid}`"
        return f"{line}\n> {clean}" if clean else line

    if kind == "task_progress":
        line = f"{e} **{agent}** `{short_tid}` in progress"
        return f"{line}\n> {clean}" if clean else line

    if kind == "task_completed":
        line = f"{e} **{agent}** completed `{short_tid}`"
        return f"{line}\n> {clean}" if clean else line

    if kind == "task_failed":
        err = _extract_error_summary(detail)
        is_transient = "[TRANSIENT]" in detail or "transient" in detail.lower()[:30]
        if is_transient:
            line = f"\u26a0\ufe0f **{agent}** `{short_tid}` transient failure"  # ⚠️
            if err:
                line += f"\n> {err}"
            line += f"\n\U0001f504 Retryable \u2014 `--retry {task_id}`"  # 🔄
        else:
            line = f"{e} **{agent}** failed `{short_tid}`"
            if err:
                line += f"\n> {err}"
            line += f"\n\U0001f4cc Check logs or retry"  # 📌
        return line

    if kind == "task_blocked":
        line = f"{e} **{agent}** `{short_tid}` blocked"
        if clean:
            line += f"\n> {clean}"
        line += f"\n\U0001f4cc Unblock or reassign"  # 📌
        return line

    # --- Review / Approval ---
    #
    # Requests → #review (operator action inbox)
    # Completions → #worklog (audit trail)

    if kind == "review_requested":
        title = payload.get("title") or clean or short_tid
        who = reviewer or "Archimedes"
        source_lane = payload.get("source_lane", "")
        task_type = payload.get("task_type", "")
        risk = payload.get("risk_level", "")
        review_id = payload.get("review_id", "")
        art_ids = payload.get("artifact_ids", [])
        backend = payload.get("execution_backend", "")

        lines = [f"{e} **Review needed** \u2014 {title}"]
        meta = f"**ID**: `{task_id}`"
        if review_id:
            meta += f" / `{review_id}`"
        meta += f"  |  **Type**: {task_type}" if task_type else ""
        meta += f"  |  **Lane**: {source_lane}" if source_lane else ""
        lines.append(meta)
        lines.append(f"**Reviewer**: {who}  |  **Built by**: {agent}" + (f" via {backend}" if backend else ""))
        if clean and clean != title:
            lines.append(f"> {clean}")
        if risk and risk != "normal":
            lines.append(f"\u26a0\ufe0f Risk: **{risk}**")
        if art_ids:
            lines.append(f"\U0001f4e6 Artifact: `{art_ids[0]}`")
        # Review stage: no approval_id yet. Operator can react with emoji
        # or approve via CLI after review passes to approval stage.
        lines.append(f"\u2705 React \u2705 to approve  |  CLI: `python3 scripts/run_ralph_v1.py --approve {task_id}`")
        return "\n".join(lines)

    if kind == "review_completed":
        title = payload.get("title", "")
        who = reviewer or agent
        source_lane = payload.get("source_lane", "")
        task_type = payload.get("task_type", "")
        review_id = payload.get("review_id", "")
        verdict_match = re.match(r"verdict:\s*(\w+)[.\s]*(.*)", detail, re.IGNORECASE)
        if verdict_match:
            verdict = verdict_match.group(1).upper()
            reason = _clean_detail(verdict_match.group(2))
            v_emoji = "\u2705" if verdict == "APPROVED" else "\u274c"
            headline = title or short_tid
            line = f"{v_emoji} **Review {verdict}** \u2014 {headline}"
            meta = f"`{task_id}`  |  **By**: {who}"
            if source_lane:
                meta += f"  |  **Lane**: {source_lane}"
            line += f"\n{meta}"
            return f"{line}\n> {reason}" if reason else line
        headline = title or short_tid
        line = f"{e} **Review complete** \u2014 {headline}\n`{task_id}`  |  **By**: {who}"
        return f"{line}\n> {clean}" if clean else line

    if kind == "approval_requested":
        title = payload.get("title") or clean or short_tid
        # Clean up developer-jargon prefixes in title
        for _prefix in ("Quant paper_trade: ", "Quant live_trade: ", "Quant pulse_downstream: "):
            if title.startswith(_prefix):
                title = title[len(_prefix):]
                break
        approval_id = payload.get("approval_id", "")
        source_lane = payload.get("source_lane", "")
        task_type = payload.get("task_type", "")
        risk = payload.get("risk_level", "")
        art_ids = payload.get("artifact_ids", [])
        who = reviewer or "operator"

        lines = [f"{e} **Approval needed** \u2014 {title}"]
        # Build ID line — omit empty task_id (quant approvals have none)
        id_parts: list[str] = []
        if task_id:
            id_parts.append(f"`{task_id}`")
        if approval_id:
            id_parts.append(f"`{approval_id}`")
        meta = f"**ID**: {' / '.join(id_parts)}" if id_parts else ""
        if task_type:
            meta += f"  |  **Type**: {task_type}" if meta else f"**Type**: {task_type}"
        if source_lane:
            meta += f"  |  **Lane**: {source_lane}" if meta else f"**Lane**: {source_lane}"
        if meta:
            lines.append(meta)
        lines.append(f"**Approver**: {who}  |  **Source**: {agent}")
        if clean and clean != title:
            lines.append(f"> {clean}")
        if risk and risk not in ("normal", ""):
            lines.append(f"\u26a0\ufe0f Risk: **{risk}**")
        if art_ids:
            lines.append(f"\U0001f4e6 Artifact: `{art_ids[0]}`")
        cmd_id = approval_id or task_id
        lines.append(f"\u2705 `approve {cmd_id}`  \u274c `reject {cmd_id} [reason]`")
        return "\n".join(lines)

    if kind == "approval_completed":
        title = payload.get("title", "")
        source_lane = payload.get("source_lane", "")
        task_type = payload.get("task_type", "")
        approval_id = payload.get("approval_id", "")
        who = reviewer or agent or "operator"
        decision_match = re.match(r"decision:\s*(\w+)[.\s]*(.*)", detail, re.IGNORECASE)
        if decision_match:
            decision = decision_match.group(1).upper()
            reason = _clean_detail(decision_match.group(2))
            d_emoji = "\u2705" if decision == "APPROVED" else "\u274c"
            headline = title or (f"`{task_id}`" if task_id else f"`{approval_id}`" if approval_id else "unknown")
            line = f"{d_emoji} **{decision}** \u2014 {headline}"
            id_parts: list[str] = []
            if task_id:
                id_parts.append(f"`{task_id}`")
            if approval_id:
                id_parts.append(f"`{approval_id}`")
            meta = " / ".join(id_parts) if id_parts else ""
            meta += f"  |  **By**: {who}" if meta else f"**By**: {who}"
            if source_lane:
                meta += f"  |  **Lane**: {source_lane}"
            line += f"\n{meta}"
            return f"{line}\n> {reason}" if reason else line
        headline = title or (f"`{task_id}`" if task_id else "approval")
        line = f"{e} **Approval complete** \u2014 {headline}\n**By**: {who}"
        return f"{line}\n> {clean}" if clean else line

    # --- Artifacts ---

    if kind == "artifact_promoted":
        short_art = artifact[4:10] if artifact.startswith("art_") and len(artifact) > 10 else artifact
        line = f"{e} **{agent}** promoted `{short_art}`"
        return f"{line}\n> {clean}" if clean else line

    # --- Browser ---

    if kind == "browser_action":
        return f"{e} **{agent}** browsing `{target}`"

    if kind == "browser_result":
        line = f"{e} **{agent}** browsed `{target}`"
        return f"{line}\n> {clean}" if clean else line

    # --- Kitt brief ---

    if kind == "kitt_brief_completed":
        source = payload.get("source", "")
        cycle_id = payload.get("cycle_id", "")
        op_status = payload.get("operator_status", "")
        priority_fam = payload.get("priority_family", "")
        # Factory-sourced briefs get richer headline
        if source == "strategy_factory" and cycle_id:
            line = f"{e} **Kitt** \u2014 factory brief `{cycle_id}`"
            if op_status:
                line += f" ({op_status})"
            if priority_fam:
                line += f"\n\U0001f3af Priority family: **{priority_fam}**"
        else:
            line = f"{e} **Kitt** \u2014 NQ brief ready"
        return f"{line}\n> {clean}" if clean else line

    if kind == "kitt_brief_failed":
        err = _extract_error_summary(detail)
        model = payload.get("model_used", "")
        line = f"{e} **Kitt** brief failed"
        if model:
            line += f" ({model})"
        return f"{line}\n> {err}" if err else line

    # --- Delegation ---

    if kind == "delegation_sent":
        return f"{e} **{agent}** delegated `{short_tid}` \u2192 {target}"

    if kind == "delegation_received":
        return f"{e} **{agent}** received `{short_tid}` \u2190 {target}"

    # --- Warning / Error ---

    # --- Profile / Models status ---

    if kind == "profile_changed":
        return f"{e} Profile switched to **{clean}**" if clean else f"{e} Profile changed"

    if kind == "models_status":
        # detail carries the pre-formatted status block
        return f"{e} **Model status**\n{detail}" if detail else f"{e} **Model status**"

    if kind == "cockpit_status":
        # detail carries the pre-formatted cockpit block
        return detail if detail else f"{e} **Mission Control**"

    if kind == "factory_weekly_summary":
        # detail carries the pre-rendered factory adapter message (multi-line)
        return detail if detail else f"{e} **Strategy Factory** weekly summary"

    if kind == "warning":
        err = _extract_error_summary(detail) if len(detail) > 120 else clean
        line = f"{e} **{agent}**"
        return f"{line}\n> {err}" if err else line

    if kind == "error":
        err = _extract_error_summary(detail) if len(detail) > 120 else clean
        line = f"{e} **{agent}**"
        if err:
            line += f"\n> {err}"
        line += f"\n\U0001f4cc Investigate immediately"  # 📌
        return line

    # --- Quant lane events ---

    if kind.startswith("quant_"):
        strategy = payload.get("strategy_id", "")
        pkt_type = payload.get("packet_type", "")
        strat_tag = f" `{strategy}`" if strategy else ""
        priority = payload.get("priority", "")

        # Strip redundant "[strategy_id] Strategy strategy_id ..." prefix from detail.
        # The quant bridge prepends "[strategy_id]" and the lane code often follows with
        # "Strategy strategy_id verb:" — both are noise when the headline already has strat_tag.
        _qclean = clean
        if strategy:
            # Strip leading "[strategy_id] " bracket prefix
            _bracket = f"[{strategy}] "
            if _qclean.startswith(_bracket):
                _qclean = _qclean[len(_bracket):]
            # Strip "Strategy strategy_id verb:" prose prefix
            if _qclean.startswith(f"Strategy {strategy} "):
                _qclean = _qclean[len(f"Strategy {strategy} "):]
            # Strip "Execution refused for strategy_id:" prose prefix
            if _qclean.startswith(f"Execution refused for {strategy}: "):
                _qclean = _qclean[len(f"Execution refused for {strategy}: "):]

        if kind == "quant_strategy_promoted":
            line = f"{e} **Strategy promoted**{strat_tag}"
            if _qclean:
                line += f"\n> {_qclean}"
            if priority == "high":
                line += f"\n\U0001f4cc Sigma validated \u2014 next: paper-trade approval"
            return line
        if kind == "quant_strategy_rejected":
            line = f"{e} **Strategy rejected**{strat_tag}"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_papertrade_candidate":
            line = f"{e} **Paper-trade candidate**{strat_tag}"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_papertrade_request":
            thesis = payload.get("thesis", "")
            symbol = payload.get("symbol", "NQ")
            risk_limits = payload.get("risk_limits") or {}
            sizing = payload.get("sizing") or {}
            max_dd = payload.get("max_drawdown")
            approval_ref = payload.get("approval_ref", "")
            notes = payload.get("notes", "")

            lines = [f"\U0001f4dd **Paper-trade approval needed** \u2014 {strategy or 'strategy'} ({symbol})"]
            lines.append(f"**Source**: Kitt (quant lead)  |  **Lane**: quant  |  **Priority**: {payload.get('priority', 'medium')}")
            if thesis:
                lines.append(f"**Thesis**: {_clean_detail(thesis)}")
            elif clean:
                lines.append(f"> {clean}")
            # Capital / risk context
            risk_parts: list[str] = []
            if max_dd is not None:
                risk_parts.append(f"MaxDD {max_dd:.1f}%")
            if risk_limits.get("max_position"):
                risk_parts.append(f"MaxPos {risk_limits['max_position']}")
            if risk_limits.get("max_loss_per_trade"):
                risk_parts.append(f"MaxLoss/trade ${risk_limits['max_loss_per_trade']}")
            if sizing.get("contracts"):
                risk_parts.append(f"{sizing['contracts']} contracts")
            if risk_parts:
                lines.append(f"\U0001f4b0 **Risk**: {' | '.join(risk_parts)}")
            lines.append(f"\u26a0\ufe0f Paper-trade uses live capital \u2014 requires explicit operator approval")
            if notes:
                lines.append(f"\U0001f4ac {notes}")
            if approval_ref:
                lines.append(f"\u2705 `approve {approval_ref}`  \u274c `reject {approval_ref} [reason]`")
            else:
                lines.append(f"\U0001f4cc Approve/reject via emoji reaction on this message")
            return "\n".join(lines)
        if kind == "quant_execution_intent":
            line = f"\u23f3 **Trade intent**{strat_tag}"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_execution_status":
            line = f"{e} **Trade filled**{strat_tag}"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_fill":
            line = f"\U0001f4b0 **Fill**{strat_tag}"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_execution_rejected":
            line = f"{e} **Trade rejected**{strat_tag}"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_paper_review":
            line = f"{e} **Paper-trade review**{strat_tag}"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_alert":
            line = f"{e} **Kitt** ALERT{strat_tag}"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_pulse_alert":
            line = f"\U0001f4a1 **Pulse alert**"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_pulse_cluster":
            line = f"\U0001f4a1 **Pulse cluster**"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_pulse_learning":
            line = f"\U0001f4a1 **Pulse learning**"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_candidate_submitted":
            line = f"\U0001f9ea **New candidate**{strat_tag}"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_scenario_submitted":
            line = f"\U0001f3a3 **Scenario**"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_validation_completed":
            line = f"\U0001f50d **Validation complete**{strat_tag}"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_setup":
            line = f"\U0001f3af **Setup**{strat_tag}"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_health":
            line = f"\U0001f3e5 **{agent}** health"
            return f"{line}\n> {_qclean}" if _qclean else line
        if kind == "quant_pulse_proposal":
            thesis = payload.get("thesis", "")
            symbol = payload.get("symbol", "NQ")
            action_req = payload.get("action_requested", "")
            confidence = payload.get("confidence")
            escalation = payload.get("escalation_level", "none")
            approval_ref = payload.get("approval_ref", "")
            notes = payload.get("notes", "")

            # Use strategy_id if present, else short thesis, else generic
            _pulse_headline = strategy or (thesis[:50] + "..." if len(thesis) > 53 else thesis) or "pulse proposal"
            lines = [f"\U0001f4dd **Pulse proposal needs approval** \u2014 {_pulse_headline} ({symbol})"]
            lines.append(f"**Source**: Pulse (discretionary alerts)  |  **Lane**: quant")
            if thesis:
                lines.append(f"**Thesis**: {_clean_detail(thesis)}")
            elif clean:
                lines.append(f"> {clean}")
            if action_req:
                lines.append(f"**Action**: {action_req}")
            meta_parts: list[str] = []
            if confidence is not None:
                meta_parts.append(f"Confidence {confidence:.0%}")
            if escalation and escalation != "none":
                meta_parts.append(f"Escalation: {escalation}")
            if meta_parts:
                lines.append(f"\U0001f4ca {' | '.join(meta_parts)}")
            if notes:
                lines.append(f"\U0001f4ac {notes}")
            if approval_ref:
                lines.append(f"\u2705 `approve {approval_ref}`  \u274c `reject {approval_ref} [reason]`")
            else:
                lines.append(f"\U0001f4cc Approve/reject via emoji reaction on this message")
            return "\n".join(lines)
        # Generic quant event — fallback
        label = kind.replace("quant_", "").replace("_", " ")
        line = f"{e} **{agent}** {label}{strat_tag}"
        return f"{line}\n> {_qclean}" if _qclean else line

    # --- Fallback ---
    line = f"\u2139\ufe0f **{agent}** {kind}"
    return f"{line}\n> {clean}" if clean else line


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------

# Events that need operator action → route to #review (archimedes channel)
_REVIEW_REQUEST_KINDS = {
    "approval_requested", "review_requested",
    "quant_papertrade_request", "quant_pulse_proposal",
}
# Events that are completion receipts → route to #worklog, NOT #review
_REVIEW_COMPLETION_KINDS = {"approval_completed", "review_completed"}


def _resolve_owner_channel_id(
    kind: str,
    agent_id: str,
    channel_map: dict[str, Any],
) -> Optional[str]:
    """Return the Discord channel ID that should receive this event."""
    agents = channel_map.get("agents", {})
    voice_only_kinds = set(channel_map.get("voice_only_event_kinds", []))

    # Voice events always go to cadence
    if kind in voice_only_kinds:
        return agents.get("cadence", {}).get("channel_id")

    # Operator-action-needed events → #review (archimedes channel)
    if kind in _REVIEW_REQUEST_KINDS:
        review_ch = agents.get("archimedes", {}).get("channel_id")
        if review_ch:
            return review_ch

    # Completion receipts → #worklog (not #review)
    if kind in _REVIEW_COMPLETION_KINDS:
        logical = channel_map.get("logical_channels", {})
        wl_ch = logical.get("worklog", {}).get("channel_id")
        if wl_ch:
            return wl_ch

    # For known agents, use their channel
    entry = agents.get(agent_id, {})
    ch_id = entry.get("channel_id")

    # If the resolved channel is cadence but event is NOT voice → reject
    cadence_ch = agents.get("cadence", {}).get("channel_id")
    if ch_id and ch_id == cadence_ch and kind not in voice_only_kinds:
        return None  # blocked

    return ch_id


def _should_mirror_worklog(kind: str, channel_map: dict[str, Any]) -> bool:
    return kind in set(channel_map.get("worklog_mirror_event_kinds", []))


def _should_forward_jarvis(kind: str, channel_map: dict[str, Any]) -> bool:
    return kind in set(channel_map.get("jarvis_forward_event_kinds", []))


# ---------------------------------------------------------------------------
# Outbox entry
# ---------------------------------------------------------------------------

def _write_outbox_entry(
    channel_id: str,
    text: str,
    event_id: str,
    kind: str,
    label: str,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    entry_id = new_id("outbox")
    entry: dict[str, Any] = {
        "entry_id": entry_id,
        "created_at": now_iso(),
        "channel_id": channel_id,
        "text": text,
        "source_event_id": event_id,
        "event_kind": kind,
        "label": label,
        "status": "pending",
    }
    path = _outbox_dir(root) / f"{entry_id}.json"
    path.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    return entry


# ---------------------------------------------------------------------------
# Main public interface
# ---------------------------------------------------------------------------

def emit_event(
    kind: str,
    agent_id: str,
    *,
    task_id: str = "",
    detail: str = "",
    target: str = "",
    reviewer_id: str = "",
    artifact_id: str = "",
    extra: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Create a dispatch_event record and write outbox entries for Discord routing.

    Returns a summary dict with:
        event_id, owner_channel_id, worklog_mirrored, jarvis_forwarded,
        cadence_blocked, text, outbox_entries
    """
    resolved_root = Path(root or ROOT).resolve()
    channel_map = _load_channel_map(resolved_root)

    event_id = new_id("devt")
    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "task_id": task_id,
        "detail": detail,
        "target": target,
        "reviewer_id": reviewer_id,
        "artifact_id": artifact_id,
        **(extra or {}),
    }

    # Resolve owner channel
    owner_ch = _resolve_owner_channel_id(kind, agent_id, channel_map)
    cadence_blocked = False
    agents = channel_map.get("agents", {})
    voice_only_kinds = set(channel_map.get("voice_only_event_kinds", []))

    # Detect cadence block: agent is cadence but event is non-voice
    cadence_entry = agents.get("cadence", {})
    cadence_ch = cadence_entry.get("channel_id")
    if kind not in voice_only_kinds and agent_id == "cadence":
        cadence_blocked = True
        owner_ch = None  # blocked

    # Render text
    text = _render_status_text(kind, payload)

    # Worklog + Jarvis decisions
    mirror_worklog = _should_mirror_worklog(kind, channel_map)
    forward_jarvis = _should_forward_jarvis(kind, channel_map)
    worklog_ch = channel_map.get("logical_channels", {}).get("worklog", {}).get("channel_id")
    jarvis_ch = channel_map.get("logical_channels", {}).get("jarvis", {}).get("channel_id")

    # Build dispatch event record
    dispatch_record: dict[str, Any] = {
        "event_id": event_id,
        "created_at": now_iso(),
        "kind": kind,
        "agent_id": agent_id,
        "task_id": task_id,
        "owner_channel_id": owner_ch,
        "worklog_mirrored": mirror_worklog and bool(worklog_ch),
        "jarvis_forwarded": forward_jarvis and bool(jarvis_ch) and (owner_ch != jarvis_ch),
        "cadence_blocked": cadence_blocked,
        "text": text,
        "payload": payload,
    }
    dp = _dispatch_dir(resolved_root) / f"{event_id}.json"
    dp.write_text(json.dumps(dispatch_record, indent=2) + "\n", encoding="utf-8")

    # Write outbox entries
    outbox_entries: list[dict[str, Any]] = []

    # For review REQUEST events, send directly via bot token to #review channel
    # (the REVIEW_WEBHOOK_URL may be bound to a different channel)
    if kind in _REVIEW_REQUEST_KINDS and owner_ch:
        try:
            _scripts = resolved_root / "scripts"
            if str(_scripts) not in sys.path:
                sys.path.insert(0, str(_scripts))
            from dispatch_utils import send_bot_message
            send_bot_message(owner_ch, text)
        except Exception:
            pass

    if owner_ch and not cadence_blocked:
        outbox_entries.append(_write_outbox_entry(
            owner_ch, text, event_id, kind, "owner", resolved_root,
        ))

    if mirror_worklog and worklog_ch and worklog_ch != owner_ch:
        outbox_entries.append(_write_outbox_entry(
            worklog_ch, text, event_id, kind, "worklog", resolved_root,
        ))

    # Jarvis forward (skip if owner IS jarvis already to avoid duplicate)
    if forward_jarvis and jarvis_ch and jarvis_ch != owner_ch:
        outbox_entries.append(_write_outbox_entry(
            jarvis_ch, text, event_id, kind, "jarvis_fwd", resolved_root,
        ))

    return {
        "event_id": event_id,
        "kind": kind,
        "owner_channel_id": owner_ch,
        "worklog_mirrored": dispatch_record["worklog_mirrored"],
        "jarvis_forwarded": dispatch_record["jarvis_forwarded"],
        "cadence_blocked": cadence_blocked,
        "text": text,
        "outbox_entries": outbox_entries,
    }


def route_event(
    kind: str,
    agent_id: str,
    payload: dict[str, Any],
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Lower-level: just compute routing decision without writing state.

    Returns dict with owner_channel_id, worklog_mirror, jarvis_forward,
    cadence_blocked, rendered_text.
    """
    resolved_root = Path(root or ROOT).resolve()
    channel_map = _load_channel_map(resolved_root)
    voice_only_kinds = set(channel_map.get("voice_only_event_kinds", []))
    agents = channel_map.get("agents", {})
    cadence_ch = agents.get("cadence", {}).get("channel_id")

    cadence_blocked = agent_id == "cadence" and kind not in voice_only_kinds
    owner_ch = None if cadence_blocked else _resolve_owner_channel_id(kind, agent_id, channel_map)
    text = _render_status_text(kind, payload)

    worklog_ch = channel_map.get("logical_channels", {}).get("worklog", {}).get("channel_id")
    jarvis_ch = channel_map.get("logical_channels", {}).get("jarvis", {}).get("channel_id")

    return {
        "owner_channel_id": owner_ch,
        "worklog_mirror": _should_mirror_worklog(kind, channel_map) and bool(worklog_ch),
        "jarvis_forward": _should_forward_jarvis(kind, channel_map) and bool(jarvis_ch),
        "cadence_blocked": cadence_blocked,
        "text": text,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Discord event router CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_emit = sub.add_parser("emit", help="Emit an event and write outbox")
    p_emit.add_argument("kind")
    p_emit.add_argument("agent_id")
    p_emit.add_argument("--task-id", default="")
    p_emit.add_argument("--detail", default="")
    p_emit.add_argument("--target", default="")

    p_route = sub.add_parser("route", help="Show routing decision (no writes)")
    p_route.add_argument("kind")
    p_route.add_argument("agent_id")
    p_route.add_argument("--detail", default="")

    args = parser.parse_args()
    if args.cmd == "emit":
        result = emit_event(
            args.kind, args.agent_id,
            task_id=args.task_id, detail=args.detail, target=args.target,
        )
        print(json.dumps(result, indent=2, default=str))
    elif args.cmd == "route":
        result = route_event(args.kind, args.agent_id, {"detail": args.detail})
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
