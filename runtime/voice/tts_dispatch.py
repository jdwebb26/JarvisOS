#!/usr/bin/env python3
"""tts_dispatch.py — TTS engine selection and fallback for Cadence.

Routes speech synthesis requests to:
  piper  (default) — fast, always-on, runs in .venv-voice
  coqui  (optional) — higher-quality, runs in .venv-coqui

Fallback: if the selected engine fails, falls back to piper.
If piper also fails, the call is a no-op (no crash).

Usage
-----
    from runtime.voice.tts_dispatch import speak

    speak("Command received.")
    speak("Processing your request.", engine="coqui")
    speak("Done.", engine=None)   # uses CADENCE_TTS_ENGINE or default
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]


def _engine() -> str:
    return os.environ.get("CADENCE_TTS_ENGINE", "piper").lower().strip()


def speak(text: str, *, engine: Optional[str] = None) -> dict:
    """Speak text using configured TTS engine.

    Args:
        text:    Text to synthesize and play.
        engine:  "piper" | "coqui" | None (use CADENCE_TTS_ENGINE env or default=piper)

    Returns:
        {"ok": bool, "engine_used": str, "error": str}
    """
    if not text or not text.strip():
        return {"ok": True, "engine_used": "noop", "error": ""}

    selected = (engine or _engine()).lower()

    if selected == "coqui":
        result = _speak_coqui(text)
        if result["ok"]:
            return {**result, "engine_used": "coqui"}
        # Fallback to piper
        print(
            f"[tts_dispatch] coqui failed ({result['error']}), falling back to piper",
            file=sys.stderr,
        )
        piper_result = _speak_piper(text)
        return {**piper_result, "engine_used": "piper_fallback"}

    # Default: piper
    result = _speak_piper(text)
    return {**result, "engine_used": "piper"}


# ---------------------------------------------------------------------------
# Piper
# ---------------------------------------------------------------------------

def _speak_piper(text: str) -> dict:
    """Speak via Piper in .venv-voice subprocess."""
    from runtime.voice.voice_config import VENV_VOICE
    py = VENV_VOICE / "bin" / "python"
    if not py.exists():
        return {"ok": False, "error": "venv-voice not found"}

    script = ROOT / "runtime" / "voice" / "tts_piper.py"
    wav = tempfile.mktemp(suffix=".wav", prefix="cadence_piper_")

    try:
        result = subprocess.run(
            [str(py), str(script), "--render", text, "--output", wav],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(ROOT),
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr[:200] or f"exit {result.returncode}"}
        if not Path(wav).exists():
            return {"ok": False, "error": "wav not created"}
        _play_wav(wav)
        return {"ok": True, "error": ""}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "piper timed out"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        try:
            Path(wav).unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Coqui
# ---------------------------------------------------------------------------

def _speak_coqui(text: str) -> dict:
    """Speak via Coqui in .venv-coqui subprocess."""
    from runtime.voice.voice_config import VENV_COQUI, COQUI_VOICE
    py = VENV_COQUI / "bin" / "python"
    if not py.exists():
        return {"ok": False, "error": "venv-coqui not found"}

    script = ROOT / "runtime" / "voice" / "tts_coqui_render.py"
    wav = tempfile.mktemp(suffix=".wav", prefix="cadence_coqui_")

    try:
        result = subprocess.run(
            [str(py), str(script), "--text", text, "--voice", COQUI_VOICE,
             "--output", wav],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(ROOT),
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr[:200] or f"exit {result.returncode}"}
        if not Path(wav).exists():
            return {"ok": False, "error": "wav not created"}
        _play_wav(wav)
        return {"ok": True, "error": ""}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "coqui timed out"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        try:
            Path(wav).unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Audio playback
# ---------------------------------------------------------------------------

def _play_wav(wav_path: str) -> bool:
    """Play a WAV file via paplay.  Returns True if played."""
    import shutil
    if not shutil.which("paplay"):
        return False
    try:
        subprocess.run(
            ["paplay", wav_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        return True
    except Exception:
        return False
