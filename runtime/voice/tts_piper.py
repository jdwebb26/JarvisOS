#!/usr/bin/env python3
"""tts_piper.py — Piper TTS integration for Cadence.

Renders text to speech using Piper, running inside .venv-voice.

This module is importable from the main Python 3.14 runtime — it invokes
Piper through the .venv-voice Python subprocess, so no Piper packages need
to be installed in the main env.

Usage (from main runtime)
--------------------------
    from runtime.voice.tts_piper import speak, probe_piper

    speak("Command received.")           # plays audio via paplay
    speak("Hello", output_wav="/tmp/x.wav")  # saves to file only
    probe_piper()                        # → {"status": "ok", ...}

Direct CLI (run from .venv-voice for rendering)
------------------------------------------------
    .venv-voice/bin/python runtime/voice/tts_piper.py "Text to speak"
    .venv-voice/bin/python runtime/voice/tts_piper.py --probe
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Voice / model selection
# ---------------------------------------------------------------------------

# Piper voices directory (models are downloaded here by piper on first use)
_PIPER_VOICES_DIR = Path.home() / ".local" / "share" / "piper" / "voices"
_PIPER_VOICE_ENV  = os.environ.get("CADENCE_PIPER_VOICE", "")

# Default voice: en_US-lessac-medium is a good general-purpose voice
_DEFAULT_VOICE = "en_US-lessac-medium"


def _piper_voice() -> str:
    """Return the configured or default Piper voice name/path."""
    return _PIPER_VOICE_ENV or _DEFAULT_VOICE


# ---------------------------------------------------------------------------
# Locate .venv-voice python
# ---------------------------------------------------------------------------

def _venv_python() -> Optional[str]:
    """Return path to .venv-voice/bin/python, or None if not found."""
    from runtime.voice.voice_config import VENV_VOICE
    p = VENV_VOICE / "bin" / "python"
    return str(p) if p.exists() else None


# ---------------------------------------------------------------------------
# Internal render helper (runs inside .venv-voice)
# ---------------------------------------------------------------------------

def _render_in_subprocess(text: str, output_wav: Optional[str] = None) -> dict:
    """Invoke tts_piper.py in .venv-voice to render audio.

    Returns {"ok": bool, "wav": path|None, "error": str}
    """
    py = _venv_python()
    if py is None:
        return {"ok": False, "wav": None, "error": "venv-voice not found"}

    script = str(Path(__file__).resolve())
    with_wav = output_wav or tempfile.mktemp(suffix=".wav", prefix="cadence_piper_")

    try:
        result = subprocess.run(
            [py, script, "--render", text, "--output", with_wav],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(ROOT),
        )
        if result.returncode != 0:
            return {
                "ok": False,
                "wav": None,
                "error": result.stderr[:300] or f"exit {result.returncode}",
            }
        if not Path(with_wav).exists():
            return {"ok": False, "wav": None, "error": "output wav not created"}
        return {"ok": True, "wav": with_wav, "error": ""}
    except subprocess.TimeoutExpired:
        return {"ok": False, "wav": None, "error": "piper render timed out"}
    except Exception as exc:
        return {"ok": False, "wav": None, "error": str(exc)}


# ---------------------------------------------------------------------------
# Public API (called from main runtime)
# ---------------------------------------------------------------------------

def speak(text: str, *, output_wav: Optional[str] = None) -> dict:
    """Synthesise text and play it via paplay (or save to output_wav).

    Returns {"ok": bool, "wav": path|None, "error": str, "played": bool}
    """
    if not text or not text.strip():
        return {"ok": True, "wav": None, "error": "", "played": False}

    render = _render_in_subprocess(text, output_wav=output_wav)
    if not render["ok"]:
        return {**render, "played": False}

    wav = render["wav"]
    played = False

    if output_wav is None and wav:
        # Play and then delete temp file
        played = _play_wav(wav)
        try:
            Path(wav).unlink(missing_ok=True)
        except Exception:
            pass

    return {"ok": True, "wav": output_wav, "error": "", "played": played}


def _play_wav(wav_path: str) -> bool:
    """Play a WAV file via paplay.  Returns True if started."""
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


def probe_piper() -> dict:
    """Check Piper availability.  Returns status dict."""
    py = _venv_python()
    if py is None:
        return {"status": "error", "reason": "venv-voice not found"}
    try:
        result = subprocess.run(
            [py, str(Path(__file__).resolve()), "--probe"],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=str(ROOT),
        )
        if result.returncode != 0:
            return {"status": "error", "reason": result.stderr[:200]}
        try:
            return json.loads(result.stdout)
        except Exception:
            return {"status": "ok", "raw": result.stdout[:200]}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


# ---------------------------------------------------------------------------
# Render entry point — runs INSIDE .venv-voice
# ---------------------------------------------------------------------------

def _resolve_voice_path(voice: str) -> tuple[str, str]:
    """Return (model_onnx_path, config_json_path) for a voice name or path.

    Downloads the voice if not already cached.
    """
    # If voice looks like a path to an .onnx file, use it directly
    model_path = Path(voice)
    if model_path.suffix == ".onnx" and model_path.exists():
        config_path = Path(str(model_path) + ".json")
        return str(model_path), str(config_path) if config_path.exists() else ""

    # Otherwise treat it as a named voice — check cache first, then download
    voices_dir = _PIPER_VOICES_DIR
    voices_dir.mkdir(parents=True, exist_ok=True)

    onnx  = voices_dir / f"{voice}.onnx"
    json_ = voices_dir / f"{voice}.onnx.json"

    if not onnx.exists():
        from piper.download_voices import download_voice
        download_voice(voice, voices_dir)

    return str(onnx), str(json_) if json_.exists() else ""


def _do_render(text: str, output: str, voice: str) -> int:
    """Actually synthesize text using piper.  Called inside .venv-voice subprocess."""
    try:
        from piper import PiperVoice
        import wave as _wave

        model_path, config_path = _resolve_voice_path(voice)
        if not Path(model_path).exists():
            print(f"[tts_piper] model not found: {model_path}", file=sys.stderr)
            return 1

        pvoice = PiperVoice.load(
            model_path,
            config_path=config_path if config_path else None,
        )

        with _wave.open(output, "wb") as wf:
            pvoice.synthesize_wav(text, wf)

        return 0
    except Exception as exc:
        print(f"[tts_piper render] error: {exc}", file=sys.stderr)
        return 1


def _do_probe() -> dict:
    """Check piper availability from within .venv-voice."""
    try:
        import piper
        version = getattr(piper, "__version__", "unknown")
        return {"status": "ok", "piper_version": version, "voice": _piper_voice()}
    except ImportError as exc:
        return {"status": "error", "reason": f"piper not importable: {exc}"}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Piper TTS renderer (runs in .venv-voice)")
    parser.add_argument("text", nargs="?", default="", help="Text to synthesize")
    parser.add_argument("--render", default="", help="Text to render (alt to positional)")
    parser.add_argument("--output", default="", help="Output WAV path")
    parser.add_argument("--voice", default="", help="Piper voice name")
    parser.add_argument("--probe", action="store_true", help="Health check and exit")
    args = parser.parse_args()

    if args.probe:
        result = _do_probe()
        print(json.dumps(result))
        return 0 if result.get("status") == "ok" else 1

    text = args.render or args.text
    if not text:
        print("ERROR: no text provided", file=sys.stderr)
        return 1

    voice = args.voice or _piper_voice()
    output = args.output
    if not output:
        output = tempfile.mktemp(suffix=".wav", prefix="piper_")

    rc = _do_render(text, output, voice)
    if rc == 0 and not args.output:
        # If called with no output, play it inline (used for quick tests)
        if shutil.which("paplay"):
            subprocess.run(["paplay", output], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        Path(output).unlink(missing_ok=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
