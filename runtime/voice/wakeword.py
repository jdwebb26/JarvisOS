#!/usr/bin/env python3
from __future__ import annotations


def validate_wake_phrase(transcript: str, required_phrase: str = "Jarvis") -> dict:
    raw = (transcript or "").strip()
    required = (required_phrase or "Jarvis").strip()
    if not raw:
        return {
            "valid": False,
            "wake_phrase_detected": False,
            "normalized_command": "",
            "reason": "empty_transcript",
        }

    lowered = raw.casefold()
    required_lowered = required.casefold()

    if lowered == required_lowered:
        return {
            "valid": False,
            "wake_phrase_detected": True,
            "normalized_command": "",
            "reason": "wake_phrase_without_command",
        }

    required_prefix = f"{required_lowered} "
    if not lowered.startswith(required_prefix):
        return {
            "valid": False,
            "wake_phrase_detected": False,
            "normalized_command": "",
            "reason": "missing_wake_phrase",
        }

    normalized_command = raw[len(required) :].strip()
    if not normalized_command:
        return {
            "valid": False,
            "wake_phrase_detected": True,
            "normalized_command": "",
            "reason": "wake_phrase_without_command",
        }

    return {
        "valid": True,
        "wake_phrase_detected": True,
        "normalized_command": normalized_command,
        "reason": "accepted",
    }
