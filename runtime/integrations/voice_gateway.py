#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from runtime.gateway.voice_command import handle_voice_command


ROOT = Path(__file__).resolve().parents[2]


def run_voice_gateway_cycle(
    raw_transcript,
    *,
    voice_session_id,
    actor="operator",
    lane="voice",
    task_id="",
    speaker_confidence=0.0,
    route=False,
    root=None,
) -> dict:
    resolved_root = Path(root or ROOT).resolve()
    gateway_result = handle_voice_command(
        raw_transcript,
        voice_session_id=voice_session_id,
        actor=actor,
        lane=lane,
        task_id=task_id,
        speaker_confidence=speaker_confidence,
        route=route,
        root=resolved_root,
    )
    return {
        "integration": "voice_gateway",
        "status": "stubbed",
        "reason": "live_voice_io_not_connected",
        "gateway_result": gateway_result,
    }
