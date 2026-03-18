#!/usr/bin/env python3
"""tts_coqui_render.py — Coqui TTS render script for Cadence.

IMPORTANT: This script runs INSIDE .venv-coqui (Python 3.11).
It is NOT imported by the main runtime; it is invoked as a subprocess.

Usage
-----
    .venv-coqui/bin/python runtime/voice/tts_coqui_render.py "Text to speak"
    .venv-coqui/bin/python runtime/voice/tts_coqui_render.py \\
        --text "Hello operator" \\
        --voice tts_models/en/ljspeech/tacotron2-DDC \\
        --output /tmp/reply.wav

    # Health probe
    .venv-coqui/bin/python runtime/voice/tts_coqui_render.py --probe

Exit codes
----------
    0  success
    1  error
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_VOICE = os.environ.get(
    "CADENCE_COQUI_VOICE", "tts_models/en/ljspeech/tacotron2-DDC"
)


def _do_render(text: str, voice: str, output: str) -> int:
    """Synthesize text with Coqui TTS.  Writes WAV to output path."""
    try:
        from TTS.api import TTS
        tts = TTS(model_name=voice, progress_bar=False, gpu=False)
        tts.tts_to_file(text=text, file_path=output)
        return 0
    except Exception as exc:
        print(f"[tts_coqui] render error: {exc}", file=sys.stderr)
        return 1


def _do_probe() -> dict:
    """Check Coqui TTS availability from within .venv-coqui."""
    try:
        from TTS.api import TTS
        import TTS as _tts_pkg
        version = getattr(_tts_pkg, "__version__", "unknown")
        return {"status": "ok", "coqui_version": version, "voice": DEFAULT_VOICE}
    except ImportError as exc:
        return {"status": "error", "reason": f"TTS not importable: {exc}"}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Coqui TTS renderer — runs inside .venv-coqui"
    )
    parser.add_argument("text_pos", nargs="?", default="",
                        metavar="TEXT",
                        help="Text to synthesize (positional)")
    parser.add_argument("--text", default="",
                        help="Text to synthesize (flag alternative)")
    parser.add_argument("--voice", default=DEFAULT_VOICE,
                        help=f"Coqui model name (default: {DEFAULT_VOICE})")
    parser.add_argument("--output", default="",
                        help="Output WAV path (default: play inline and delete)")
    parser.add_argument("--probe", action="store_true",
                        help="Run health probe and exit")
    args = parser.parse_args()

    if args.probe:
        result = _do_probe()
        print(json.dumps(result))
        return 0 if result.get("status") == "ok" else 1

    text = args.text or args.text_pos
    if not text:
        print("ERROR: no text provided", file=sys.stderr)
        return 1

    output = args.output
    cleanup = False
    if not output:
        output = tempfile.mktemp(suffix=".wav", prefix="coqui_")
        cleanup = True

    rc = _do_render(text, args.voice, output)

    if rc == 0 and cleanup:
        if shutil.which("paplay"):
            subprocess.run(["paplay", output], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        Path(output).unlink(missing_ok=True)

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
