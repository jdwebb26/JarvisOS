#!/usr/bin/env python3
"""cues.py — Earcon playback for Cadence voice assistant.

Plays short WAV cue files via paplay.  Fails softly if audio is unavailable.

Cues:
  wake_accept   — heard the wake phrase, ready for command
  command_open  — command window is now open (optional, subtle)
  route_ok      — routing succeeded
  error         — routing failed / blocked

Env toggles (all default 1/enabled, command_open default 0):
  CADENCE_AUDIO_CUES=0          master disable
  CADENCE_WAKE_ACCEPT_CUE=1
  CADENCE_COMMAND_OPEN_CUE=0    default off (can be noisy)
  CADENCE_ROUTE_OK_CUE=1
  CADENCE_ERROR_CUE=1
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CUES_DIR = ROOT / "assets" / "audio" / "cues"

_CUE_FILES: dict[str, str] = {
    "wake_accept":  "wake_accept.wav",
    "command_open": "command_open.wav",
    "route_ok":     "route_ok.wav",
    "error":        "error.wav",
}

_CUE_DEFAULTS: dict[str, str] = {
    "CADENCE_WAKE_ACCEPT_CUE":  "1",
    "CADENCE_COMMAND_OPEN_CUE": "0",   # off by default
    "CADENCE_ROUTE_OK_CUE":     "1",
    "CADENCE_ERROR_CUE":        "1",
}


def _cue_enabled(cue_name: str) -> bool:
    if os.environ.get("CADENCE_AUDIO_CUES", "1") == "0":
        return False
    key = f"CADENCE_{cue_name.upper()}_CUE"
    return os.environ.get(key, _CUE_DEFAULTS.get(key, "1")) != "0"


def play_cue(cue_name: str, *, block: bool = False) -> bool:
    """Play a named earcon.  Returns True if playback was started.

    Non-blocking by default so the daemon loop continues immediately.
    Pass block=True to wait for playback to finish (e.g. in tests).
    """
    if not _cue_enabled(cue_name):
        return False
    if not shutil.which("paplay"):
        return False
    filename = _CUE_FILES.get(cue_name)
    if not filename:
        return False
    wav_path = CUES_DIR / filename
    if not wav_path.exists():
        return False
    try:
        silence = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if block:
            subprocess.run(["paplay", str(wav_path)], **silence)
        else:
            subprocess.Popen(["paplay", str(wav_path)], **silence)
        return True
    except Exception:
        return False


def cues_available() -> bool:
    """True if paplay is present and at least one cue file exists."""
    if not shutil.which("paplay"):
        return False
    return any((CUES_DIR / f).exists() for f in _CUE_FILES.values())
