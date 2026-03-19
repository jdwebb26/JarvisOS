#!/usr/bin/env python3
"""ptt — push-to-talk controller for Cadence.

Manages the PTT lifecycle:
  press → beep → capture → release → transcribe → route → TTS response

The controller is input-agnostic: callers signal press/release events and the
controller handles capture, transcription, routing, and TTS.  This lets the
same logic serve terminal hotkey, mouse button, or future hardware bindings.

TTS interruption: if TTS is playing and a new press arrives, the TTS process
is killed and capture begins immediately.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.cues import play_cue
from runtime.voice.cadence_status import record_route, record_wake


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MIN_CAPTURE_SEC = 0.4           # ignore captures shorter than this
MAX_CAPTURE_SEC = 30.0          # hard cap on capture duration
SILENCE_RMS_THRESHOLD = 50.0    # below this RMS, treat as silent

# Input mode: "ptt" (push-to-talk) or "wake" (wake-word, existing behavior)
INPUT_MODE = os.environ.get("CADENCE_INPUT_MODE", "ptt")

# PTT binding hint (informational — actual binding is in the CLI/UI layer)
PTT_BINDING = os.environ.get("CADENCE_PTT_BINDING", "space")


# ---------------------------------------------------------------------------
# TTS tracking for interruption
# ---------------------------------------------------------------------------

_tts_lock = threading.Lock()
_tts_proc: Optional[subprocess.Popen] = None


def _set_tts_proc(proc: Optional[subprocess.Popen]) -> None:
    global _tts_proc
    with _tts_lock:
        _tts_proc = proc


def interrupt_tts() -> bool:
    """Kill any in-progress TTS playback. Returns True if something was killed."""
    global _tts_proc
    with _tts_lock:
        if _tts_proc is not None and _tts_proc.poll() is None:
            try:
                _tts_proc.send_signal(signal.SIGTERM)
                _tts_proc.wait(timeout=1)
            except Exception:
                try:
                    _tts_proc.kill()
                except Exception:
                    pass
            _tts_proc = None
            return True
        _tts_proc = None
    return False


def tts_is_playing() -> bool:
    with _tts_lock:
        return _tts_proc is not None and _tts_proc.poll() is None


# ---------------------------------------------------------------------------
# Capture: start/stop parecord on demand
# ---------------------------------------------------------------------------

class PTTCapture:
    """Manages a parecord process that starts on press and stops on release."""

    def __init__(self, *, device: str = "", rate: int = 16000):
        self._device = device
        self._rate = rate
        self._proc: Optional[subprocess.Popen] = None
        self._wav_path: Optional[Path] = None
        self._start_time: float = 0.0

    @property
    def is_capturing(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def duration(self) -> float:
        if self._start_time == 0:
            return 0.0
        return time.monotonic() - self._start_time

    def start(self, *, output_dir: Optional[Path] = None) -> Path:
        """Start recording. Returns the WAV file path that will be written to."""
        if self.is_capturing:
            self.stop()

        from runtime.voice.mic_capture import default_capture_device, parecord_available
        if not parecord_available():
            raise RuntimeError("parecord not found; install pulseaudio-utils.")

        device = self._device or default_capture_device()
        base = output_dir or Path(tempfile.gettempdir())
        self._wav_path = base / f"cadence_ptt_{int(time.time() * 1000)}.wav"

        cmd = [
            "parecord",
            "-d", device,
            "--rate", str(self._rate),
            "--channels", "1",
            "--format=s16le",
            "--file-format=wav",
            str(self._wav_path),
        ]

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._start_time = time.monotonic()
        return self._wav_path

    def stop(self) -> Optional[Path]:
        """Stop recording. Returns the WAV path or None if nothing was captured."""
        if self._proc is None:
            return None

        try:
            self._proc.send_signal(signal.SIGINT)
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        except Exception:
            pass

        self._proc = None
        duration = self.duration
        self._start_time = 0.0

        if self._wav_path and self._wav_path.exists():
            # Check minimum duration
            if duration < MIN_CAPTURE_SEC:
                try:
                    self._wav_path.unlink()
                except Exception:
                    pass
                return None
            return self._wav_path
        return None

    def abort(self) -> None:
        """Abort recording, discard any captured audio."""
        if self._proc is not None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=1)
            except Exception:
                pass
            self._proc = None
        self._start_time = 0.0
        if self._wav_path and self._wav_path.exists():
            try:
                self._wav_path.unlink()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Full PTT turn: transcribe → route → TTS
# ---------------------------------------------------------------------------

def process_ptt_turn(
    wav_path: Path,
    *,
    execute: bool = False,
    voice_session_id: str = "",
    actor: str = "cadence",
    lane: str = "voice",
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Process a completed PTT capture through the full Cadence pipeline.

    Steps:
    1. Check WAV quality (duration, RMS)
    2. Transcribe via Whisper
    3. Optionally strip wake phrase (PTT mode doesn't require it)
    4. Route through cadence_ingress (which delegates to PersonaPlex or command path)
    5. Speak the response via TTS

    Returns a dict describing the outcome.
    """
    from runtime.voice.mic_capture import (
        transcribe, wav_duration_sec, wav_rms, wav_is_silent,
        probe_best_whisper_model,
    )
    from runtime.voice.cadence_ingress import route_cadence_utterance
    from runtime.voice.cadence_daemon import _clean_command, _is_garbage_text, check_wake_phrase

    resolved_root = Path(root or ROOT).resolve()

    # 1. Check WAV quality
    duration = wav_duration_sec(wav_path)
    if duration < MIN_CAPTURE_SEC:
        return {"phase": "too_short", "duration": duration}

    rms = wav_rms(wav_path)
    if wav_is_silent(wav_path, SILENCE_RMS_THRESHOLD):
        return {"phase": "silent", "duration": duration, "rms": rms}

    # 2. Transcribe
    model = probe_best_whisper_model()
    result = transcribe(wav_path, model=model)
    raw_text = _clean_command(result.get("text", "")).strip()

    if not raw_text or _is_garbage_text(raw_text):
        return {"phase": "no_speech", "raw_text": raw_text, "duration": duration}

    # 3. Strip wake phrase if present (PTT doesn't require it, but operator might say it)
    wake_check = check_wake_phrase(raw_text)
    if wake_check.get("valid"):
        command = wake_check.get("normalized_command", raw_text)
        record_wake(phrase=wake_check.get("wake_phrase_used", ""))
    else:
        command = raw_text

    if not command.strip():
        return {"phase": "empty_command", "raw_text": raw_text, "duration": duration}

    # 4. Route through Cadence pipeline
    try:
        route_result = route_cadence_utterance(
            command,
            voice_session_id=voice_session_id,
            actor=actor,
            lane=lane,
            execute=execute,
            root=resolved_root,
        )
    except Exception as exc:
        record_route(transcript=command, intent="error", ok=False, error=str(exc),
                     routing_mode="error")
        return {"phase": "route_error", "command": command, "error": str(exc)}

    intent = route_result.get("intent_result", {}).get("intent", "?")
    routed = route_result.get("routed", False)
    delegation = route_result.get("delegation_result") or {}
    route_reason = route_result.get("route_reason", "")
    is_ppx = route_reason == "personaplex_conversation"
    ppx_session_id = delegation.get("conversation_id", "") if is_ppx else ""
    ppx_response = delegation.get("response", "") if is_ppx else ""

    record_route(
        transcript=command, intent=intent, ok=True,
        routing_mode="personaplex" if is_ppx else "command",
        personaplex_session_id=ppx_session_id,
        response_preview=ppx_response,
    )

    # 5. TTS response
    response_text = ""
    if is_ppx and ppx_response:
        response_text = ppx_response
    elif delegation.get("response"):
        response_text = delegation["response"]

    tts_played = False
    if response_text:
        tts_played = _speak_with_interrupt(response_text)

    return {
        "phase": "routed",
        "command": command,
        "raw_text": raw_text,
        "intent": intent,
        "routing_mode": "personaplex" if is_ppx else "command",
        "routed": routed,
        "personaplex_session_id": ppx_session_id,
        "response": response_text,
        "tts_played": tts_played,
        "duration": duration,
        "route_result": route_result,
    }


def _speak_with_interrupt(text: str) -> bool:
    """Speak text via TTS, trackable for interruption. Returns True if played."""
    try:
        from runtime.voice.feedback import speak_response
        # Run in a thread so we can track the process for interruption
        result = speak_response(text, actor="cadence", lane="voice")
        return result.get("status") == "played"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Convenience: full PTT turn from canned transcript (for replay/testing)
# ---------------------------------------------------------------------------

def replay_ptt_turn(
    transcript: str,
    *,
    execute: bool = False,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Simulate a PTT turn with a canned transcript (no mic needed).

    This bypasses audio capture and transcription, injecting the transcript
    directly into the routing pipeline. Useful for testing and operator proofs.
    """
    from runtime.voice.cadence_ingress import route_cadence_utterance
    from runtime.voice.cadence_daemon import _clean_command, check_wake_phrase
    from runtime.voice.cadence_status import record_wake

    resolved_root = Path(root or ROOT).resolve()
    text = _clean_command(transcript).strip()
    if not text:
        return {"phase": "empty", "transcript": transcript}

    # Strip wake phrase if present
    wake_check = check_wake_phrase(text)
    if wake_check.get("valid"):
        command = wake_check.get("normalized_command", text)
        record_wake(phrase=wake_check.get("wake_phrase_used", ""))
    else:
        command = text

    if not command.strip():
        return {"phase": "empty_command", "transcript": transcript}

    try:
        route_result = route_cadence_utterance(
            command,
            actor="cadence",
            lane="voice",
            execute=execute,
            root=resolved_root,
        )
    except Exception as exc:
        return {"phase": "route_error", "command": command, "error": str(exc)}

    delegation = route_result.get("delegation_result") or {}
    route_reason = route_result.get("route_reason", "")
    is_ppx = route_reason == "personaplex_conversation"
    intent = route_result.get("intent_result", {}).get("intent", "?")

    record_route(
        transcript=command, intent=intent, ok=True,
        routing_mode="personaplex" if is_ppx else "command",
        personaplex_session_id=delegation.get("conversation_id", "") if is_ppx else "",
        response_preview=delegation.get("response", "") if is_ppx else "",
    )

    return {
        "phase": "routed",
        "command": command,
        "intent": intent,
        "routing_mode": "personaplex" if is_ppx else "command",
        "personaplex_session_id": delegation.get("conversation_id", "") if is_ppx else "",
        "response": delegation.get("response", "") if is_ppx else "",
        "action_proposed": delegation.get("action_proposed") if is_ppx else None,
        "route_result": route_result,
    }
