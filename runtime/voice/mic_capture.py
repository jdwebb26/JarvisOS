#!/usr/bin/env python3
"""mic_capture — PulseAudio microphone capture + Whisper transcription.

Records audio via parecord (PulseAudio), transcribes via the local whisper CLI.
Designed for use by cadence_daemon.py and direct CLI invocation for testing.

Requirements (already present on this system):
  parecord — PulseAudio capture (part of pulseaudio-utils)
  whisper  — OpenAI Whisper CLI  (brew install openai-whisper)
  base.pt  — Whisper model       (~/.cache/whisper/base.pt, already downloaded)

Usage:
  python3 runtime/voice/mic_capture.py                 # 5-second capture + transcribe
  python3 runtime/voice/mic_capture.py --duration 8    # 8-second capture
  python3 runtime/voice/mic_capture.py --list-sources  # show PulseAudio sources
  python3 runtime/voice/mic_capture.py --probe-model   # show best available Whisper model
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Whisper silence hallucinations — transcripts to treat as empty
# ---------------------------------------------------------------------------

_SILENCE_PHRASES = frozenset({
    ".", " ", "", "you", "bye.", "bye", "thank you.", "thank you",
    "thanks.", "thanks", "okay.", "okay", "ok.", "ok", "yeah.", "yeah",
    "uh.", "um.", "hmm.", "hm.", "[music]", "[applause]", "[laughter]",
    "[noise]", "[silence]", "(inaudible)", "[blank_audio]",
    "you.", "i.", "so.", "a.", "the.",
})

# Whisper artifact tags to strip from output text
_ARTIFACT_RE = None  # compiled lazily


def _artifact_pattern():
    global _ARTIFACT_RE
    if _ARTIFACT_RE is None:
        import re
        _ARTIFACT_RE = re.compile(
            r'\[(?:Music|Applause|Laughter|Noise|Silence|BLANK_AUDIO|inaudible|crosstalk|'
            r'music|applause|laughter|noise|silence|blank_audio)\]',
            re.IGNORECASE,
        )
    return _ARTIFACT_RE


def _normalize_transcript(raw: str) -> str:
    """Join multi-line Whisper output into one line and strip artifact tags."""
    import re
    # Join lines
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    text = " ".join(lines)
    # Strip artifact tags
    text = _artifact_pattern().sub("", text)
    # Collapse whitespace
    text = " ".join(text.split())
    return text


# ---------------------------------------------------------------------------
# Whisper model probe
# ---------------------------------------------------------------------------

def probe_best_whisper_model() -> str:
    """Return the best locally cached Whisper model name.

    Checks ~/.cache/whisper/ for .pt files.
    Priority: small.en > small > base.en > base
    Ignores models that aren't cached (avoids auto-download during live use).
    Falls back to "base" if nothing is found.
    """
    cache = Path.home() / ".cache" / "whisper"
    candidates = [
        ("small.en", "small.en.pt"),
        ("small",    "small.pt"),
        ("base.en",  "base.en.pt"),
        ("base",     "base.pt"),
    ]
    for model_name, filename in candidates:
        if (cache / filename).exists():
            return model_name
    return "base"


# ---------------------------------------------------------------------------
# System checks
# ---------------------------------------------------------------------------

def parecord_available() -> bool:
    return shutil.which("parecord") is not None


def whisper_available() -> bool:
    return shutil.which("whisper") is not None


def list_pulse_sources() -> list[dict]:
    """Return PulseAudio source list as parsed dicts."""
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources", "short"],
            text=True, timeout=5,
        )
    except Exception:
        return []
    sources = []
    for line in out.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            sources.append({
                "index": parts[0].strip(),
                "name": parts[1].strip(),
                "driver": parts[2].strip() if len(parts) > 2 else "",
                "state": parts[4].strip() if len(parts) > 4 else "",
            })
    return sources


def default_capture_device() -> str:
    """Return best available PulseAudio capture source name.

    Priority order:
    1. RDPSource (WSLg Windows mic passthrough — exact name match)
    2. Any non-monitor source with "source" in name
    3. Any non-monitor source
    4. "default"
    """
    sources = list_pulse_sources()
    for s in sources:
        if s["name"].lower() == "rdpsource":
            return s["name"]
    for s in sources:
        name = s["name"].lower()
        if "source" in name and "monitor" not in name:
            return s["name"]
    for s in sources:
        if "monitor" not in s["name"].lower():
            return s["name"]
    return "default"


# ---------------------------------------------------------------------------
# Audio capture
# ---------------------------------------------------------------------------

def record_chunk(
    duration_sec: float = 5.0,
    *,
    device: Optional[str] = None,
    rate: int = 16000,
    channels: int = 1,
    output_path: Optional[Path] = None,
    tmp_dir: Optional[Path] = None,
) -> Path:
    """Record audio from PulseAudio and save as WAV.

    Uses parecord (outputs WAV directly).  Kills the process after
    duration_sec seconds.

    Returns path to the WAV file.
    """
    if not parecord_available():
        raise RuntimeError("parecord not found; install pulseaudio-utils.")

    resolved_device = device or default_capture_device()

    if output_path is None:
        base_dir = tmp_dir or Path(tempfile.gettempdir())
        output_path = base_dir / f"cadence_chunk_{int(time.time())}.wav"

    cmd = [
        "parecord",
        "-d", resolved_device,
        "--rate", str(rate),
        "--channels", str(channels),
        "--format=s16le",
        "--file-format=wav",
        str(output_path),
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(duration_sec)
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    return output_path


def wav_duration_sec(wav_path: Path) -> float:
    """Return duration of a WAV file in seconds."""
    try:
        with wave.open(str(wav_path), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0


def wav_rms(wav_path: Path) -> float:
    """Return RMS amplitude of a WAV file (0 = silent, higher = louder)."""
    try:
        with wave.open(str(wav_path), "rb") as wf:
            data = wf.readframes(wf.getnframes())
        if not data:
            return 0.0
        n = len(data) // 2
        samples = struct.unpack(f"<{n}h", data[: n * 2])
        if not samples:
            return 0.0
        return (sum(s * s for s in samples) / len(samples)) ** 0.5
    except Exception:
        return 0.0


def wav_is_silent(wav_path: Path, silence_threshold_rms: float = 50.0) -> bool:
    """Return True if the WAV file is below the silence threshold (RMS)."""
    return wav_rms(wav_path) < silence_threshold_rms


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

def transcribe(
    wav_path: Path,
    *,
    model: str = "base",
    language: str = "en",
    timeout_sec: int = 60,
) -> dict:
    """Transcribe a WAV file using the whisper CLI.

    Returns:
      {text, model, language, wav_path, ok, error}
    """
    if not whisper_available():
        return {
            "text": "",
            "model": model,
            "language": language,
            "wav_path": str(wav_path),
            "ok": False,
            "error": "whisper not found in PATH",
        }

    out_dir = wav_path.parent
    txt_path = wav_path.with_suffix(".txt")

    if txt_path.exists():
        txt_path.unlink()

    try:
        result = subprocess.run(
            [
                "whisper",
                str(wav_path),
                "--model", model,
                "--language", language,
                "--fp16", "False",
                "--output_format", "txt",
                "--output_dir", str(out_dir),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return {
            "text": "",
            "model": model,
            "language": language,
            "wav_path": str(wav_path),
            "ok": False,
            "error": f"whisper timed out after {timeout_sec}s",
        }
    except Exception as exc:
        return {
            "text": "",
            "model": model,
            "language": language,
            "wav_path": str(wav_path),
            "ok": False,
            "error": str(exc),
        }

    if result.returncode != 0:
        return {
            "text": "",
            "model": model,
            "language": language,
            "wav_path": str(wav_path),
            "ok": False,
            "error": result.stderr[:400] if result.stderr else f"exit {result.returncode}",
        }

    if txt_path.exists():
        raw = txt_path.read_text(encoding="utf-8").strip()
    else:
        stem_txt = out_dir / (wav_path.stem + ".txt")
        raw = stem_txt.read_text(encoding="utf-8").strip() if stem_txt.exists() else ""

    # Normalize multi-line output and strip artifact tags
    raw = _normalize_transcript(raw)

    # Filter silence hallucinations
    if raw.lower() in _SILENCE_PHRASES:
        raw = ""

    return {
        "text": raw,
        "model": model,
        "language": language,
        "wav_path": str(wav_path),
        "ok": True,
        "error": "",
    }


# ---------------------------------------------------------------------------
# Convenience: record + transcribe
# ---------------------------------------------------------------------------

def record_and_transcribe(
    duration_sec: float = 5.0,
    *,
    device: Optional[str] = None,
    rate: int = 16000,
    model: str = "base",
    language: str = "en",
    tmp_dir: Optional[Path] = None,
    keep_wav: bool = False,
) -> dict:
    """Record a chunk and transcribe it in one call.

    Returns merged dict from record + transcribe plus timing and audio diagnostics.
    """
    t0 = time.time()
    with tempfile.TemporaryDirectory() as _tmpdir:
        base = tmp_dir or Path(_tmpdir)
        wav_path = record_chunk(
            duration_sec=duration_sec,
            device=device,
            rate=rate,
            output_path=base / f"cadence_{int(t0)}.wav",
        )
        wav_bytes = wav_path.stat().st_size if wav_path.exists() else 0
        wav_dur = wav_duration_sec(wav_path)
        rms = wav_rms(wav_path)
        is_silent = rms < 50.0  # advisory only — logged, not used as gate

        # Gate only on structurally empty capture (header-only = 44 bytes, <1s).
        capture_ok = wav_bytes > 44 and wav_dur >= 1.0
        if capture_ok:
            transc = transcribe(wav_path, model=model, language=language)
        else:
            transc = {
                "text": "",
                "model": model,
                "language": language,
                "wav_path": str(wav_path),
                "ok": False,
                "error": f"capture too small: {wav_bytes} bytes, {wav_dur:.2f}s",
            }

        elapsed = time.time() - t0

        if not keep_wav and wav_path.exists():
            try:
                wav_path.unlink()
                txt_path = wav_path.with_suffix(".txt")
                if txt_path.exists():
                    txt_path.unlink()
            except Exception:
                pass

        return {
            **transc,
            "is_silent": is_silent,
            "rms": round(rms, 2),
            "wav_bytes": wav_bytes,
            "wav_dur": round(wav_dur, 2),
            "capture_ok": capture_ok,
            "duration_sec": duration_sec,
            "elapsed_sec": round(elapsed, 2),
            "device": device or default_capture_device(),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Capture audio from mic and transcribe with Whisper.")
    parser.add_argument("--duration", type=float, default=5.0, help="Recording duration in seconds")
    parser.add_argument("--device", default="", help="PulseAudio source name (default: auto-detect RDPSource)")
    parser.add_argument("--model", default="", help="Whisper model (default: probe best available)")
    parser.add_argument("--language", default="en", help="Language code")
    parser.add_argument("--keep-wav", action="store_true", help="Keep WAV file after transcription")
    parser.add_argument("--list-sources", action="store_true", help="List PulseAudio sources and exit")
    parser.add_argument("--probe-model", action="store_true", help="Print best available Whisper model and exit")
    args = parser.parse_args()

    if args.list_sources:
        sources = list_pulse_sources()
        print(json.dumps(sources, indent=2))
        return 0

    if args.probe_model:
        print(probe_best_whisper_model())
        return 0

    if not parecord_available():
        print("ERROR: parecord not found. Install pulseaudio-utils.", file=sys.stderr)
        return 1
    if not whisper_available():
        print("ERROR: whisper not found. Install with: brew install openai-whisper", file=sys.stderr)
        return 1

    model = args.model or probe_best_whisper_model()
    print(f"Recording {args.duration}s from {args.device or default_capture_device()} (model={model}) ...", file=sys.stderr)
    result = record_and_transcribe(
        duration_sec=args.duration,
        device=args.device or None,
        model=model,
        language=args.language,
        keep_wav=args.keep_wav,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
