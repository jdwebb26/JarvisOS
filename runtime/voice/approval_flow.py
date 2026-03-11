#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional

from runtime.core.spoken_approval import (
    create_spoken_approval_challenge,
    verify_spoken_approval_code,
)
from runtime.voice.approval_prompt import (
    acknowledge_spoken_approval_result,
    create_voice_confirmation_prompt,
)


ROOT = Path(__file__).resolve().parents[2]

_INLINE_CODE_PATTERNS = (
    re.compile(r"^(?P<body>.+?)\s+approval code:\s*(?P<code>.+)$", re.IGNORECASE),
    re.compile(r"^(?P<body>.+?)\s+code:\s*(?P<code>.+)$", re.IGNORECASE),
)


def extract_inline_approval_code(normalized_command: str) -> dict:
    command = " ".join((normalized_command or "").strip().split())
    for pattern in _INLINE_CODE_PATTERNS:
        match = pattern.match(command)
        if not match:
            continue
        body = match.group("body").strip()
        code = match.group("code").strip()
        if body and code:
            return {
                "inline_code_present": True,
                "spoken_code": code,
                "normalized_command_without_code": body,
                "reason": "inline_code_detected",
            }
    return {
        "inline_code_present": False,
        "spoken_code": "",
        "normalized_command_without_code": command,
        "reason": "no_inline_code",
    }


def build_action_id_for_voice_request(voice_command: dict, route_preview: dict | None = None) -> str:
    normalized_command = (voice_command or {}).get("normalized_command", "")
    route_bits = route_preview.get("route", {}) if route_preview else {}
    material = "|".join(
        [
            str((voice_command or {}).get("voice_session_id", "")),
            str((voice_command or {}).get("task_id", "")),
            str(normalized_command),
            str(route_bits.get("subsystem", "")),
            str(route_bits.get("intent", "")),
            str(route_bits.get("target", "")),
            str(route_bits.get("query", "")),
        ]
    )
    return f"voiceact_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"


def maybe_verify_inline_spoken_code(
    *,
    normalized_command: str,
    challenge_id: str,
    actor: str,
    lane: str,
    root=None,
) -> dict:
    extracted = extract_inline_approval_code(normalized_command)
    if not extracted["inline_code_present"]:
        return {
            "inline_code_present": False,
            "verification": None,
            "normalized_command_without_code": extracted["normalized_command_without_code"],
            "reason": extracted["reason"],
        }
    verification = verify_spoken_approval_code(
        extracted["spoken_code"],
        challenge_id=challenge_id,
        actor=actor,
        lane=lane,
        root=root,
    )
    return {
        "inline_code_present": True,
        "verification": verification,
        "normalized_command_without_code": extracted["normalized_command_without_code"],
        "reason": "inline_code_verified",
    }


def handle_voice_confirmation_requirement(
    *,
    voice_command: dict,
    route_preview: dict | None,
    actor: str,
    lane: str,
    root=None,
) -> dict:
    resolved_root = Path(root or ROOT).resolve()
    action_id = build_action_id_for_voice_request(voice_command, route_preview=route_preview)
    challenge = create_spoken_approval_challenge(
        action_id=action_id,
        actor=actor,
        lane=lane,
        risk_tier=str((voice_command or {}).get("risk_tier", "high")),
        root=resolved_root,
    )
    verification_attempt = maybe_verify_inline_spoken_code(
        normalized_command=str((voice_command or {}).get("normalized_command", "")),
        challenge_id=challenge["challenge_id"],
        actor=actor,
        lane=lane,
        root=resolved_root,
    )

    verification = verification_attempt["verification"]
    if verification and verification["status"] == "approved":
        ack = acknowledge_spoken_approval_result(
            "approved",
            actor=actor,
            lane=lane,
            root=resolved_root,
        )
        return {
            "approval_required": True,
            "challenge": challenge,
            "inline_code_present": True,
            "verification": verification,
            "prompt": None,
            "ack": ack,
            "action_id": action_id,
            "normalized_command_without_code": verification_attempt["normalized_command_without_code"],
            "reason": "spoken_approval_verified_inline",
        }

    if verification and verification["status"] != "approved":
        ack = acknowledge_spoken_approval_result(
            verification["status"],
            actor=actor,
            lane=lane,
            root=resolved_root,
        )
        return {
            "approval_required": True,
            "challenge": challenge,
            "inline_code_present": True,
            "verification": verification,
            "prompt": None,
            "ack": ack,
            "action_id": action_id,
            "normalized_command_without_code": verification_attempt["normalized_command_without_code"],
            "reason": "spoken_approval_inline_rejected",
        }

    prompt = create_voice_confirmation_prompt(
        challenge_id=challenge["challenge_id"],
        action_id=action_id,
        actor=actor,
        lane=lane,
        root=resolved_root,
    )
    return {
        "approval_required": True,
        "challenge": challenge,
        "inline_code_present": False,
        "verification": None,
        "prompt": prompt,
        "ack": None,
        "action_id": action_id,
        "normalized_command_without_code": verification_attempt["normalized_command_without_code"],
        "reason": "spoken_approval_prompt_required",
    }
