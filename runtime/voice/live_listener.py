#!/usr/bin/env python3
"""live_listener.py — openWakeWord + Silero VAD + faster-whisper listener.

IMPORTANT: This script is designed to run INSIDE .venv-voice (Python 3.12).
It is spawned as a subprocess by cadence_daemon.py, which reads its stdout.

Pipeline
--------
1. Stream raw PCM audio from parecord (16kHz mono s16le)
2. Feed 80ms frames (1280 samples) to openWakeWord for wake detection
3. On wake phrase detected:
   a. Emit  {"event": "wake_detected", "phrase": "<name>"}  to stdout
   b. Switch to VAD+capture mode
4. Silero VAD gates speech (512-sample / 32ms chunks)
   - Speech start detected → begin accumulating audio
   - Silence after speech ends (end_silence_sec) → stop accumulating
   - Hard timeout (command_window_sec) → emit {"event": "timeout"}
5. Assembled audio → faster-whisper → emit {"event": "transcript", "text": "..."}

Output (one JSON per line to stdout)
-------------------------------------
  {"event": "ready"}                   — listener is up and receiving audio
  {"event": "wake_detected", "phrase": "hey_jarvis", "score": 0.92}
  {"event": "transcript", "text": "browse to finance dot yahoo dot com"}
  {"event": "timeout"}                 — command window expired with no speech
  {"event": "error", "message": "..."}

Stdin: not used (set to /dev/null)

Usage (normally launched by cadence_daemon.py, not directly)
-------------------------------------------------------------
    .venv-voice/bin/python runtime/voice/live_listener.py \\
        --device RDPSource \\
        --model small.en \\
        --threshold 0.5

    # Health probe — prints component status JSON and exits
    .venv-voice/bin/python runtime/voice/live_listener.py --probe

Env
---
    CADENCE_OWW_THRESHOLD     wake word score threshold (default 0.5)
    CADENCE_VAD_THRESHOLD     Silero VAD speech probability (default 0.5)
    CADENCE_COMMAND_WINDOW_SECONDS  max seconds waiting for command (default 8)
    CADENCE_FASTER_WHISPER_MODEL    STT model (default small.en)
    CADENCE_FASTER_WHISPER_COMPUTE  compute_type (default int8)
    PULSE_SERVER              PulseAudio socket (e.g. unix:/mnt/wslg/PulseServer)
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants / env
# ---------------------------------------------------------------------------

SAMPLE_RATE       = 16000
BYTES_PER_SAMPLE  = 2          # s16le
OWW_FRAME_SAMPLES = 1280       # 80ms @ 16kHz
VAD_FRAME_SAMPLES = 512        # 32ms @ 16kHz (silero requirement)

OWW_THRESHOLD          = float(os.environ.get("CADENCE_OWW_THRESHOLD", "0.5"))
VAD_THRESHOLD          = float(os.environ.get("CADENCE_VAD_THRESHOLD", "0.5"))
COMMAND_WINDOW_SEC     = float(os.environ.get("CADENCE_COMMAND_WINDOW_SECONDS", "8.0"))
FASTER_WHISPER_MODEL   = os.environ.get("CADENCE_FASTER_WHISPER_MODEL", "small.en")
FASTER_WHISPER_COMPUTE = os.environ.get("CADENCE_FASTER_WHISPER_COMPUTE", "int8")

# Silence duration (seconds) to mark end-of-speech in command window
END_SILENCE_SEC = 1.0

# OWW wake word model IDs to try (in priority order)
OWW_MODEL_IDS = ["hey_jarvis", "alexa"]

# How long to keep the OWW score high before resetting (dedup window)
_WAKE_DEDUP_SEC = 3.0

_STOP = False


def _sigterm(_sig, _frame):
    global _STOP
    _STOP = True


signal.signal(signal.SIGTERM, _sigterm)
signal.signal(signal.SIGINT, _sigterm)


# ---------------------------------------------------------------------------
# Emit helpers
# ---------------------------------------------------------------------------

def _emit(obj: dict) -> None:
    """Write a single JSON line to stdout, flush immediately."""
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _err(msg: str) -> None:
    print(f"[live_listener] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# PulseAudio source detection
# ---------------------------------------------------------------------------

def _best_device() -> str:
    """Return best available PulseAudio capture device name."""
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources", "short"], text=True, timeout=5
        )
    except Exception:
        return "default"
    for line in out.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].lower() == "rdpsource":
            return parts[1]
    for line in out.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and "monitor" not in parts[1].lower():
            return parts[1]
    return "default"


# ---------------------------------------------------------------------------
# Audio streaming from parecord
# ---------------------------------------------------------------------------

class AudioStream:
    """Wraps a parecord subprocess streaming raw PCM to a pipe."""

    def __init__(self, device: str, rate: int = SAMPLE_RATE):
        self._device = device
        self._rate = rate
        self._proc: Optional[subprocess.Popen] = None

    def start(self) -> None:
        cmd = [
            "parecord",
            "-d", self._device,
            f"--rate={self._rate}",
            "--channels=1",
            "--format=s16le",
            "--raw",
            "-",            # write raw PCM to stdout
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def read_samples(self, n_samples: int) -> Optional[bytes]:
        """Read exactly n_samples samples (blocking).  Returns None on EOF/error."""
        if self._proc is None:
            return None
        n_bytes = n_samples * BYTES_PER_SAMPLE
        buf = b""
        while len(buf) < n_bytes:
            chunk = self._proc.stdout.read(n_bytes - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.send_signal(signal.SIGINT)
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None


# ---------------------------------------------------------------------------
# OpenWakeWord wrapper
# ---------------------------------------------------------------------------

def _load_oww():
    """Load openWakeWord model.  Returns (model, active_model_id) or (None, None)."""
    try:
        import openwakeword
        from openwakeword.model import Model as OWWModel
        import warnings

        # Resolve pretrained model paths (model_id → full .onnx path)
        all_paths = openwakeword.get_pretrained_model_paths()

        def _find_path(keyword: str) -> str:
            for p in all_paths:
                if keyword.lower() in p.lower():
                    return p
            return ""

        # Try preferred models in priority order
        for model_id in OWW_MODEL_IDS:
            path = _find_path(model_id)
            if not path:
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model = OWWModel(wakeword_model_paths=[path])
                loaded_id = list(model.models.keys())[0]
                _err(f"openWakeWord loaded: {loaded_id}")
                return model, loaded_id
            except Exception as exc:
                _err(f"OWW model {model_id} failed: {exc}")
                continue

        # Fall back to first available model
        if all_paths:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model = OWWModel(wakeword_model_paths=[all_paths[0]])
                loaded_id = list(model.models.keys())[0]
                _err(f"openWakeWord loaded (fallback): {loaded_id}")
                return model, loaded_id
            except Exception as exc:
                _err(f"OWW fallback load failed: {exc}")

        _err("openWakeWord: no models available")
        return None, None

    except ImportError as exc:
        _err(f"openwakeword not importable: {exc}")
        return None, None


# ---------------------------------------------------------------------------
# Silero VAD wrapper
# ---------------------------------------------------------------------------

def _load_vad():
    """Load Silero VAD model.  Returns model or None."""
    try:
        import torch
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=True,
        )
        _err("Silero VAD loaded (torch.hub onnx)")
        return model
    except Exception as hub_exc:
        _err(f"silero torch.hub failed ({hub_exc}), trying pip package…")

    try:
        from silero_vad import load_silero_vad
        model = load_silero_vad(onnx=True)
        _err("Silero VAD loaded (pip package onnx)")
        return model
    except Exception as exc2:
        _err(f"Silero VAD load failed: {exc2}")
        return None


# ---------------------------------------------------------------------------
# faster-whisper wrapper
# ---------------------------------------------------------------------------

def _load_whisper(model_name: str, compute_type: str):
    """Load faster-whisper model.  Returns model or None."""
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(model_name, device="cpu", compute_type=compute_type)
        _err(f"faster-whisper loaded: {model_name}")
        return model
    except Exception as exc:
        _err(f"faster-whisper load failed: {exc}")
        return None


def _transcribe(whisper_model, audio_bytes: bytes) -> str:
    """Transcribe raw s16le PCM bytes.  Returns cleaned text."""
    import io
    import numpy as np
    from faster_whisper import WhisperModel

    # Convert s16le bytes to float32 numpy
    samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    try:
        segments, _ = whisper_model.transcribe(
            samples,
            language="en",
            beam_size=3,
            vad_filter=False,       # we do our own VAD
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()

        # Strip common hallucinations
        _GARBAGE = {"", ".", "you", "bye", "thank you", "thanks", "okay",
                    "ok", "yeah", "uh", "um", "hmm"}
        if text.lower() in _GARBAGE:
            return ""
        return text

    except Exception as exc:
        _err(f"transcribe error: {exc}")
        return ""


# ---------------------------------------------------------------------------
# VAD speech gating
# ---------------------------------------------------------------------------

def _vad_score(vad_model, samples_s16le: bytes) -> float:
    """Return Silero VAD speech probability for a 512-sample frame."""
    import numpy as np
    try:
        import torch
        samples = np.frombuffer(samples_s16le, dtype=np.int16).astype(np.float32) / 32768.0
        t = torch.from_numpy(samples).unsqueeze(0)
        score = vad_model(t, SAMPLE_RATE).item()
        return score
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------

def run_listener(
    device: str,
    whisper_model_name: str,
    oww_threshold: float,
    vad_threshold: float,
    command_window_sec: float,
    compute_type: str,
) -> None:
    """Main listener loop.  Runs until SIGTERM/SIGINT."""
    global _STOP

    oww_model, oww_model_id = _load_oww()
    vad_model = _load_vad()
    whisper = _load_whisper(whisper_model_name, compute_type)

    if not whisper:
        _emit({"event": "error", "message": "faster-whisper failed to load"})
        return

    _emit({
        "event": "ready",
        "device": device,
        "oww_model": oww_model_id or "unavailable",
        "vad": "loaded" if vad_model else "unavailable",
        "whisper": whisper_model_name,
    })

    _last_wake_at = 0.0
    _STREAM_RETRY_SEC = 15.0    # wait before retrying after stream failure
    _stream_error_reported = False   # track whether we already told daemon about the failure

    def _make_stream() -> AudioStream:
        s = AudioStream(device=device)
        s.start()
        _err(f"streaming from {device}")
        return s

    stream = _make_stream()

    try:
        while not _STOP:
            # ── Passive mode: feed frames to openWakeWord ──────────────────
            raw = stream.read_samples(OWW_FRAME_SAMPLES)
            if raw is None:
                stream.stop()
                # Emit error only once per failure episode to avoid log spam
                if not _stream_error_reported:
                    _emit({"event": "error",
                           "message": "audio stream ended — retrying (RDPSource may be unavailable)"})
                    _stream_error_reported = True
                # Wait before retrying (mic may be reconnecting)
                import time as _time
                _time.sleep(_STREAM_RETRY_SEC)
                if not _STOP:
                    stream = _make_stream()
                continue

            if _STOP:
                break

            # Got real audio — clear error state
            _stream_error_reported = False

            wake_detected = False
            wake_phrase = ""
            wake_score = 0.0

            if oww_model is not None:
                try:
                    import numpy as np
                    samples_f = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                    oww_model.predict(samples_f)
                    scores = oww_model.prediction_buffer
                    # Check all model scores
                    for mid, buf in scores.items():
                        score = buf[-1] if buf else 0.0
                        if score >= oww_threshold:
                            now = time.time()
                            if now - _last_wake_at >= _WAKE_DEDUP_SEC:
                                wake_detected = True
                                wake_phrase = mid
                                wake_score = float(score)
                                _last_wake_at = now
                            break
                except Exception as exc:
                    _err(f"oww predict error: {exc}")

            if not wake_detected:
                continue

            # ── Wake detected ──────────────────────────────────────────────
            _emit({"event": "wake_detected", "phrase": wake_phrase, "score": wake_score})

            # ── Command window: VAD gating ─────────────────────────────────
            speech_frames: list[bytes] = []
            in_speech = False
            silence_frames = 0
            total_frames = 0
            max_frames = int(command_window_sec * SAMPLE_RATE / VAD_FRAME_SAMPLES)
            silence_frames_threshold = int(END_SILENCE_SEC * SAMPLE_RATE / VAD_FRAME_SAMPLES)

            capture_deadline = time.time() + command_window_sec

            while not _STOP and time.time() < capture_deadline:
                frame = stream.read_samples(VAD_FRAME_SAMPLES)
                if frame is None:
                    break

                total_frames += 1

                if vad_model is not None:
                    speech_prob = _vad_score(vad_model, frame)
                    is_speech = speech_prob >= vad_threshold
                else:
                    # Fallback: RMS-based detection
                    n = len(frame) // 2
                    samples = struct.unpack(f"<{n}h", frame[:n * 2])
                    rms = (sum(s * s for s in samples) / max(n, 1)) ** 0.5
                    is_speech = rms > 50.0

                if is_speech:
                    in_speech = True
                    silence_frames = 0
                    speech_frames.append(frame)
                elif in_speech:
                    silence_frames += 1
                    speech_frames.append(frame)   # include trailing silence
                    if silence_frames >= silence_frames_threshold:
                        break  # end-of-speech detected
                # else: silence before speech starts — keep waiting

            if not speech_frames or not in_speech:
                _emit({"event": "timeout"})
                continue

            # ── Transcribe captured speech ─────────────────────────────────
            audio_bytes = b"".join(speech_frames)
            _err(f"transcribing {len(audio_bytes) / (SAMPLE_RATE * BYTES_PER_SAMPLE):.1f}s of speech…")
            text = _transcribe(whisper, audio_bytes)

            if text:
                _emit({"event": "transcript", "text": text})
            else:
                _emit({"event": "timeout"})

    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()
        _err("listener stopped")


# ---------------------------------------------------------------------------
# Health probe
# ---------------------------------------------------------------------------

def run_probe() -> dict:
    """Quick health check for all listener components.  Returns status dict."""
    import shutil

    results: dict = {}

    # parecord
    results["parecord"] = "ok" if shutil.which("parecord") else "missing"

    # openWakeWord
    try:
        import openwakeword
        version = getattr(openwakeword, "__version__", "installed")
        results["openwakeword"] = f"ok ({version})"
    except Exception as exc:
        results["openwakeword"] = f"error: {exc}"

    # torch (needed for Silero VAD)
    try:
        import torch
        results["torch"] = f"ok ({torch.__version__})"
    except Exception as exc:
        results["torch"] = f"error: {exc}"

    # silero-vad
    try:
        from silero_vad import load_silero_vad
        results["silero_vad"] = "ok (pip)"
    except Exception:
        try:
            import torch
            torch.hub.load("snakers4/silero-vad", "silero_vad", force_reload=False, onnx=True)
            results["silero_vad"] = "ok (torch.hub)"
        except Exception as exc:
            results["silero_vad"] = f"error: {exc}"

    # faster-whisper
    try:
        from faster_whisper import WhisperModel
        results["faster_whisper"] = "ok"
    except Exception as exc:
        results["faster_whisper"] = f"error: {exc}"

    # OWW models
    try:
        import openwakeword, warnings
        from openwakeword.model import Model as OWWModel
        all_paths = openwakeword.get_pretrained_model_paths()
        loaded = False
        for mid in OWW_MODEL_IDS:
            path = next((p for p in all_paths if mid.lower() in p.lower()), "")
            if not path:
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    m = OWWModel(wakeword_model_paths=[path])
                results["oww_model"] = f"ok ({list(m.models.keys())[0]})"
                loaded = True
                break
            except Exception:
                pass
        if not loaded:
            avail = [p.split("/")[-1] for p in all_paths]
            results["oww_model"] = f"warn: preferred models not loaded; available={avail}"
    except Exception as exc:
        results["oww_model"] = f"error: {exc}"

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live listener: openWakeWord + Silero VAD + faster-whisper"
    )
    parser.add_argument("--device", default="",
                        help="PulseAudio source (default: auto-detect RDPSource)")
    parser.add_argument("--model", default=FASTER_WHISPER_MODEL,
                        help=f"faster-whisper model (default: {FASTER_WHISPER_MODEL})")
    parser.add_argument("--compute", default=FASTER_WHISPER_COMPUTE,
                        help=f"compute_type (default: {FASTER_WHISPER_COMPUTE})")
    parser.add_argument("--threshold", type=float, default=OWW_THRESHOLD,
                        help=f"wake word score threshold (default: {OWW_THRESHOLD})")
    parser.add_argument("--vad-threshold", type=float, default=VAD_THRESHOLD,
                        help=f"VAD speech threshold (default: {VAD_THRESHOLD})")
    parser.add_argument("--command-window", type=float, default=COMMAND_WINDOW_SEC,
                        help=f"command window seconds (default: {COMMAND_WINDOW_SEC})")
    parser.add_argument("--probe", action="store_true",
                        help="Run health probe and exit")
    args = parser.parse_args()

    if args.probe:
        status = run_probe()
        print(json.dumps(status, indent=2))
        return 0

    device = args.device or _best_device()

    run_listener(
        device=device,
        whisper_model_name=args.model,
        oww_threshold=args.threshold,
        vad_threshold=args.vad_threshold,
        command_window_sec=args.command_window,
        compute_type=args.compute,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
