#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from runtime.voice.feedback import play_voice_cue, speak_response


ROOT = Path(__file__).resolve().parents[2]


def create_voice_confirmation_prompt(
    *,
    challenge_id: str,
    action_id: str,
    actor: str = "system",
    lane: str = "voice",
    root=None,
) -> dict:
    resolved_root = Path(root or ROOT).resolve()
    cue = play_voice_cue("confirmation_required", actor=actor, lane=lane, root=resolved_root)
    response = speak_response(
        "That action requires approval. Say your approval code.",
        actor=actor,
        lane=lane,
        root=resolved_root,
    )
    return {
        "challenge_id": challenge_id,
        "action_id": action_id,
        "status": "prompted",
        "mode": "voice_stub_prompt",
        "reason": "spoken_approval_required",
        "cue": cue,
        "response": response,
    }


def acknowledge_spoken_approval_result(
    verification_result: str,
    *,
    actor: str = "system",
    lane: str = "voice",
    root=None,
) -> dict:
    resolved_root = Path(root or ROOT).resolve()
    messages = {
        "approved": ("command_accepted", "Approval accepted."),
        "invalid_code": ("command_rejected", "Approval code rejected."),
        "expired": ("command_rejected", "Approval expired."),
        "reused": ("command_rejected", "Approval code already used."),
        "no_active_code": ("command_rejected", "No approval code is set."),
    }
    event_type, message = messages.get(
        verification_result,
        ("command_rejected", "Approval could not be verified."),
    )
    cue = play_voice_cue(event_type, actor=actor, lane=lane, root=resolved_root)
    response = speak_response(message, actor=actor, lane=lane, root=resolved_root)
    return {
        "status": verification_result,
        "mode": "voice_stub_ack",
        "reason": f"spoken_approval_{verification_result}",
        "cue": cue,
        "response": response,
    }
