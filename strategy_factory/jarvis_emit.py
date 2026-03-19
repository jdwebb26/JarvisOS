"""Thin bridge to the Jarvis runtime factory packet adapter.

Called by weekly_runner Phase 7 to emit the operator_packet through
the Jarvis Discord event router after a weekly cycle completes.

This module exists so the strategy_factory package does not directly
import from the jarvis-v5 runtime tree.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_JARVIS_ROOT = Path.home() / ".openclaw" / "workspace" / "jarvis-v5"


def emit_factory_summary(packet_path: Path) -> dict[str, Any]:
    """Emit a single factory weekly summary through the Jarvis runtime.

    Parameters
    ----------
    packet_path : path to the operator_packet.json just written

    Returns
    -------
    dict with keys: payload, discord_message, worklog_entry, kitt_handoff,
                    event_result, kitt_brief_path, artifact_path
    """
    if str(_JARVIS_ROOT) not in sys.path:
        sys.path.insert(0, str(_JARVIS_ROOT))

    from runtime.integrations.factory_packet_adapter import emit_factory_weekly

    return emit_factory_weekly(path=packet_path)
