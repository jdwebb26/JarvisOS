#!/usr/bin/env python3
"""voice_config.py — Config layer for Cadence voice engine selection.

Env vars
--------
    CADENCE_TTS_ENGINE        piper (default) | coqui
    CADENCE_PIPER_VOICE       path to .onnx model or voice name (default: auto)
    CADENCE_COQUI_VOICE       Coqui TTS model name (default: tts_models/en/ljspeech/tacotron2-DDC)
    CADENCE_VENV_VOICE        path to .venv-voice (default: auto-detect relative to this file)
    CADENCE_VENV_COQUI        path to .venv-coqui (default: auto-detect relative to this file)
    CADENCE_LISTENER          live (default) | legacy
                              live  = openWakeWord + Silero VAD + faster-whisper subprocess
                              legacy = passive full-Whisper polling (mic_capture.py)
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo root / venv paths
# ---------------------------------------------------------------------------

# This file lives at runtime/voice/voice_config.py  →  ROOT = 2 parents up
_HERE = Path(__file__).resolve()
ROOT = _HERE.parents[2]

def _venv_path(env_key: str, name: str) -> Path:
    override = os.environ.get(env_key, "")
    if override:
        return Path(override).resolve()
    return ROOT / name


VENV_VOICE = _venv_path("CADENCE_VENV_VOICE", ".venv-voice")
VENV_COQUI = _venv_path("CADENCE_VENV_COQUI", ".venv-coqui")

# ---------------------------------------------------------------------------
# Engine selection
# ---------------------------------------------------------------------------

DEFAULT_TTS_ENGINE: str = os.environ.get("CADENCE_TTS_ENGINE", "piper").lower().strip()
LISTENER_MODE: str      = os.environ.get("CADENCE_LISTENER", "live").lower().strip()

# Piper
PIPER_VOICE: str = os.environ.get("CADENCE_PIPER_VOICE", "")
PIPER_SPEAKER: str = os.environ.get("CADENCE_PIPER_SPEAKER", "")

# Coqui
COQUI_VOICE: str = os.environ.get(
    "CADENCE_COQUI_VOICE", "tts_models/en/ljspeech/tacotron2-DDC"
)

# ---------------------------------------------------------------------------
# Listener / STT
# ---------------------------------------------------------------------------

# Wake word confidence threshold for openWakeWord
OWW_THRESHOLD: float = float(os.environ.get("CADENCE_OWW_THRESHOLD", "0.5"))

# Silero VAD threshold (speech probability)
VAD_THRESHOLD: float = float(os.environ.get("CADENCE_VAD_THRESHOLD", "0.5"))

# Max seconds to wait for speech after wake word
COMMAND_WINDOW_SEC: float = float(os.environ.get("CADENCE_COMMAND_WINDOW_SECONDS", "8.0"))

# faster-whisper model to use
FASTER_WHISPER_MODEL: str = os.environ.get("CADENCE_FASTER_WHISPER_MODEL", "small.en")
FASTER_WHISPER_COMPUTE: str = os.environ.get("CADENCE_FASTER_WHISPER_COMPUTE", "int8")

# ---------------------------------------------------------------------------
# Availability helpers (lazy / cheap)
# ---------------------------------------------------------------------------

def venv_voice_available() -> bool:
    """True if .venv-voice exists and has a Python binary."""
    return (VENV_VOICE / "bin" / "python").exists()


def venv_coqui_available() -> bool:
    """True if .venv-coqui exists and has a Python binary."""
    return (VENV_COQUI / "bin" / "python").exists()


def piper_available() -> bool:
    """True if piper is importable inside .venv-voice."""
    return venv_voice_available() and (VENV_VOICE / "lib").exists()


def coqui_available() -> bool:
    """True if TTS is importable inside .venv-coqui."""
    return venv_coqui_available() and (VENV_COQUI / "lib").exists()


def live_listener_available() -> bool:
    """True if live_listener.py subprocess can be launched."""
    return venv_voice_available()
