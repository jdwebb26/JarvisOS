#!/usr/bin/env python3
"""cadence_daemon — two-phase voice loop: passive standby → wake → command capture → route.

Phase behaviour
---------------
1. Passive standby
   Records short chunks sequentially.  Stays completely silent unless a wake
   phrase is detected.  If speech is heard but not understood
   (speech_unrecognized) logs a single rate-limited diagnostic line.

2. Wake detected
   Play ``wake_accept`` earcon immediately.
   If the passive chunk also contains a real command (≥ 3 non-garbage words
   after the wake phrase), route that command directly (inline path).
   Otherwise open a command-capture window.

3. Command window  (when wake-only or short-remainder chunk)
   Optionally play ``command_open`` earcon (env-gated, default off).
   Record one longer chunk.
   If empty / nothing usable heard: log command_timeout, return to standby.
   If the operator repeated the wake phrase first, strip it.

4. Routing
   Call ``route_cadence_utterance()``.
   On success → play ``route_ok`` earcon.
   On failure → play ``error`` earcon.

Log phases (stderr / journal):
    standby_start          once at daemon start
    wake_detected          every time wake phrase heard
    command_window_open    when command window is opened
    command_captured       command text in hand, routing about to start
    routed_ok              routing returned successfully
    routed_error           routing returned error / blocked
    command_timeout        command window expired with no usable speech
    speech_unrecognized    audio heard but Whisper returned nothing (rate-limited)

IMPORTANT — WSL/RDPSource capture safety note
---------------------------------------------
RDPSource (WSLg Windows mic passthrough) is NOT safe for concurrent parecord
capture.  Multiple simultaneous parecord processes against the same PulseAudio
source cause audio corruption that makes Whisper return empty transcripts even
when speech is clearly present (high RMS).

The live daemon therefore uses SINGLE sequential capture only:
  - One parecord process at a time
  - Next recording starts only after the previous one has fully stopped
  - The --overlap / CADENCE_OVERLAP_SEC parameter is accepted for API
    compatibility but is IGNORED in the live loop (reserved for future use
    with a proper VAD/ring-buffer approach)

Env config
----------
    CADENCE_PASSIVE_CHUNK_SEC=4       passive chunk duration (s)
    CADENCE_COMMAND_WINDOW_SECONDS=8  command window duration (s)
    CADENCE_LOOP_SLEEP_SEC=0.0        extra sleep between cycles (default 0)
    CADENCE_WHISPER_MODEL=            model name; empty = probe best available
    CADENCE_AUDIO_CUES=1              master cue toggle
    CADENCE_WAKE_ACCEPT_CUE=1
    CADENCE_COMMAND_OPEN_CUE=0        default off
    CADENCE_ROUTE_OK_CUE=1
    CADENCE_ERROR_CUE=1

Usage
-----
    # Passive standby loop (preview — no side-effects)
    python3 runtime/voice/cadence_daemon.py

    # Execute mode — actually delegates tasks/browser actions
    python3 runtime/voice/cadence_daemon.py --execute

    # Single turn — record once, transcribe, route, exit
    python3 runtime/voice/cadence_daemon.py --once

    # Test with a canned transcript (no mic needed)
    python3 runtime/voice/cadence_daemon.py --transcript "Jarvis browse example.com"

    # Two-transcript test: wake only, then command
    python3 runtime/voice/cadence_daemon.py \\
        --transcript "Jarvis" --command-transcript "browse finance.yahoo.com"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal as _signal
import sys
import time
import threading
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.cadence_ingress import route_cadence_utterance
from runtime.voice.cues import play_cue
from runtime.voice.wakeword import validate_wake_phrase


# ---------------------------------------------------------------------------
# Constants / env defaults
# ---------------------------------------------------------------------------

WAKE_PHRASES = ("Jarvis", "Hey Cadence", "Cadence")

DEFAULT_PASSIVE_CHUNK_SEC  = float(os.environ.get("CADENCE_PASSIVE_CHUNK_SEC",      "4.0"))
DEFAULT_COMMAND_WINDOW_SEC = float(os.environ.get("CADENCE_COMMAND_WINDOW_SECONDS", "8.0"))
DEFAULT_LOOP_SLEEP_SEC     = float(os.environ.get("CADENCE_LOOP_SLEEP_SEC",         "0.0"))

# Minimum words in post-wake remainder to treat as inline command.
_MIN_INLINE_WORDS = 3

# Wake deduplication window (seconds).  Suppresses the same wake event
# being detected twice in rapid succession.
_WAKE_DEDUP_SEC = 3.0

# speech_unrecognized events are rate-limited to at most one per this many seconds.
_UNRECOGNIZED_RATE_LIMIT_SEC = 15.0


# ---------------------------------------------------------------------------
# Graceful shutdown event — set by SIGTERM handler
# ---------------------------------------------------------------------------

_STOP = threading.Event()


def _sigterm_handler(signum: int, frame) -> None:  # noqa: ANN001
    _STOP.set()


_signal.signal(_signal.SIGTERM, _sigterm_handler)


# ---------------------------------------------------------------------------
# Text cleaning helpers
# ---------------------------------------------------------------------------

_WHISPER_ARTIFACT_RE = re.compile(
    r'\[(?:Music|Applause|Laughter|Noise|Silence|BLANK_AUDIO|inaudible|crosstalk)'
    r'\]',
    re.IGNORECASE,
)

_GARBAGE_WORDS = frozenset({
    "okay", "ok", "yeah", "uh", "um", "hmm", "hm", "bye", "thanks",
    "thank", "you", "i", "so", "the", "a", "and", "or", "is", "it",
})


def _clean_command(text: str) -> str:
    """Normalize multi-line Whisper output into a clean single-line string.

    - Joins lines
    - Strips Whisper artifact tags ([Music], etc.)
    - Strips punctuation noise (commas, periods, etc.)
    - Collapses whitespace
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    cleaned = _WHISPER_ARTIFACT_RE.sub("", joined)
    cleaned = re.sub(r"[,;:.!?]+", " ", cleaned)
    return " ".join(cleaned.split())


def _is_garbage_text(text: str) -> bool:
    """True if text looks like hallucinated noise rather than a real command."""
    if not text:
        return True
    stripped = text.strip(".,!?;: ").lower()
    if stripped in _GARBAGE_WORDS:
        return True
    words = [w for w in stripped.split() if w]
    if len(words) < 2:
        return True
    alpha = sum(c.isalpha() for c in text)
    if len(text) > 0 and alpha / len(text) < 0.45:
        return True
    return False


# ---------------------------------------------------------------------------
# Wake phrase check
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Strip Whisper punctuation insertions and collapse whitespace."""
    return " ".join(re.sub(r"[,;:.!?]+", " ", text).split())


def check_wake_phrase(transcript: str) -> dict:
    """Check transcript against all recognised wake phrases.

    Returns same shape as validate_wake_phrase() plus ``wake_phrase_used``.
    """
    for phrase in WAKE_PHRASES:
        result = validate_wake_phrase(transcript, required_phrase=phrase)
        if result["valid"]:
            return {**result, "wake_phrase_used": phrase}
        if result["wake_phrase_detected"]:
            return {**result, "wake_phrase_used": phrase}
    return {
        "valid": False,
        "wake_phrase_detected": False,
        "normalized_command": "",
        "reason": "no_wake_phrase",
        "wake_phrase_used": "",
    }


# ---------------------------------------------------------------------------
# Single-chunk transcription helper  (used by --once / --transcript paths)
# ---------------------------------------------------------------------------

def _transcribe_chunk(
    *,
    transcript: Optional[str],
    duration_sec: float,
    device: Optional[str],
    whisper_model: str,
    label: str,
    verbose: bool,
) -> dict:
    """Return a pre-canned transcript dict or record + transcribe from mic."""
    if transcript is not None:
        return {
            "text": transcript,
            "ok": True,
            "is_silent": False,
            "rms": 0.0,
            "capture_ok": True,
            "wav_bytes": 0,
            "wav_dur": 0.0,
            "elapsed_sec": 0.0,
            "device": "manual",
            "source": "manual",
        }

    from runtime.voice.mic_capture import record_and_transcribe
    if verbose:
        print(
            f"[cadence] recording {duration_sec}s ({label}) from {device or 'default'} …",
            file=sys.stderr,
        )
    result = record_and_transcribe(duration_sec=duration_sec, device=device, model=whisper_model)
    result["source"] = "mic"
    if verbose:
        print(
            f"[cadence] capture: device={result.get('device','?')} "
            f"bytes={result.get('wav_bytes','?')} dur={result.get('wav_dur','?')}s "
            f"rms={result.get('rms','?')} silent={result.get('is_silent','?')} "
            f"capture_ok={result.get('capture_ok','?')}",
            file=sys.stderr,
        )
    return result


# ---------------------------------------------------------------------------
# run_turn — single-turn entry point  (used by --once / --transcript)
# ---------------------------------------------------------------------------

def run_turn(
    *,
    passive_transcript: Optional[str] = None,
    command_transcript: Optional[str] = None,
    passive_duration_sec: float = DEFAULT_PASSIVE_CHUNK_SEC,
    command_window_sec: float = DEFAULT_COMMAND_WINDOW_SEC,
    device: Optional[str] = None,
    whisper_model: str = "",
    execute: bool = False,
    voice_session_id: str = "",
    actor: str = "cadence",
    lane: str = "voice",
    root: Optional[Path] = None,
    verbose: bool = True,
) -> dict:
    """One full voice turn: passive listen → [wake → command window] → route.

    Returns a dict with ``phase`` describing the final outcome:
      ``no_speech``            passive chunk was empty / silent
      ``speech_unrecognized``  audio present but Whisper found nothing
      ``no_wake``              speech heard but no wake phrase
      ``capture_too_small``    WAV was too short / corrupt
      ``command_timeout``      wake detected but command window produced nothing
      ``routed``               routing ran (check ``route_ok`` for success)
    """
    from runtime.voice.mic_capture import probe_best_whisper_model
    resolved_root = Path(root or ROOT).resolve()
    model = whisper_model or probe_best_whisper_model()

    # ── Phase 1: passive standby chunk ──────────────────────────────────────
    passive = _transcribe_chunk(
        transcript=passive_transcript,
        duration_sec=passive_duration_sec,
        device=device,
        whisper_model=model,
        label="passive",
        verbose=verbose,
    )

    if not passive.get("capture_ok", True) and passive.get("source") == "mic":
        if verbose:
            print(f"[cadence] capture_too_small — {passive.get('error','?')}", file=sys.stderr)
        return {"phase": "capture_too_small", "passive": passive}

    raw_text = _clean_command(passive.get("text", "")).strip()

    if not raw_text:
        is_silent = passive.get("is_silent", True)
        if not is_silent and passive.get("source") == "mic":
            print(
                f"[cadence] speech_unrecognized  "
                f"bytes={passive.get('wav_bytes','?')} rms={passive.get('rms','?')}",
                file=sys.stderr,
            )
            return {"phase": "speech_unrecognized", "passive": passive}
        return {"phase": "no_speech", "passive": passive}

    # ── Phase 2: wake phrase check ───────────────────────────────────────────
    normalized = _normalize(raw_text)
    wake = check_wake_phrase(normalized)

    if not wake["wake_phrase_detected"]:
        return {"phase": "no_wake", "passive": passive, "wake": wake}

    print(
        f"[cadence] wake_detected  phrase={wake['wake_phrase_used']!r}"
        f"  text={raw_text!r}",
        file=sys.stderr,
    )
    play_cue("wake_accept")

    remainder = _clean_command(wake["normalized_command"]).strip()

    if (wake["valid"]
            and len(remainder.split()) >= _MIN_INLINE_WORDS
            and not _is_garbage_text(remainder)):
        command = remainder
        print(f"[cadence] command_captured (inline): {command!r}", file=sys.stderr)
    else:
        # ── Phase 3: command window ──────────────────────────────────────────
        play_cue("command_open")
        print("[cadence] command_window_open", file=sys.stderr)

        cmd_chunk = _transcribe_chunk(
            transcript=command_transcript,
            duration_sec=command_window_sec,
            device=device,
            whisper_model=model,
            label="command",
            verbose=verbose,
        )
        raw_cmd = _clean_command(cmd_chunk.get("text", "")).strip()

        if not raw_cmd or _is_garbage_text(raw_cmd):
            print("[cadence] command_timeout", file=sys.stderr)
            return {"phase": "command_timeout", "passive": passive, "wake": wake,
                    "cmd_chunk": cmd_chunk}

        cmd_norm = _normalize(raw_cmd)
        cmd_wake = check_wake_phrase(cmd_norm)
        if cmd_wake["valid"] and cmd_wake["normalized_command"].strip():
            command = _clean_command(cmd_wake["normalized_command"])
        else:
            command = raw_cmd

        print(f"[cadence] command_captured: {command!r}", file=sys.stderr)

    # ── Phase 4: routing ─────────────────────────────────────────────────────
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
        print(f"[cadence] routed_error  exc={exc}", file=sys.stderr)
        play_cue("error")
        return {"phase": "routed", "route_ok": False, "error": str(exc),
                "passive": passive, "wake": wake}

    intent = route_result.get("intent_result", {}).get("intent", "?")
    routed = route_result.get("routed", False)
    route_ok = routed or not execute
    if route_ok:
        play_cue("route_ok")
        print(f"[cadence] routed_ok  intent={intent}  routed={routed}", file=sys.stderr)
    else:
        play_cue("error")
        print(f"[cadence] routed_error  intent={intent}  routed={routed}", file=sys.stderr)

    return {
        "phase": "routed",
        "route_ok": route_ok,
        "command": command,
        "passive": passive,
        "wake": wake,
        "route_result": route_result,
    }


# ---------------------------------------------------------------------------
# Continuous loop  (production path — single sequential capture)
# ---------------------------------------------------------------------------

def run_loop(
    *,
    passive_duration_sec: float = DEFAULT_PASSIVE_CHUNK_SEC,
    command_window_sec: float = DEFAULT_COMMAND_WINDOW_SEC,
    overlap_sec: float = 0.0,   # accepted for API compat; IGNORED — see module docstring
    device: Optional[str] = None,
    whisper_model: str = "",
    execute: bool = False,
    actor: str = "cadence",
    lane: str = "voice",
    root: Optional[Path] = None,
    verbose: bool = True,
    sleep_between: float = DEFAULT_LOOP_SLEEP_SEC,
) -> None:
    """Continuous two-phase voice loop.

    Uses SINGLE sequential capture — one parecord at a time.
    The overlap_sec parameter is accepted for CLI compatibility but is not
    used; see module docstring for why concurrent parecord is unsafe on
    WSL/RDPSource.

    Exits cleanly on KeyboardInterrupt or SIGTERM.
    """
    from runtime.core.models import new_id
    from runtime.voice.mic_capture import probe_best_whisper_model, record_and_transcribe

    resolved_root = Path(root or ROOT).resolve()
    model = whisper_model or probe_best_whisper_model()
    voice_session_id = new_id("vsession")

    if overlap_sec > 0:
        print(
            f"[cadence] note: --overlap={overlap_sec} ignored "
            f"(concurrent parecord unsafe on RDPSource; using single-capture)",
            file=sys.stderr,
        )

    print(f"[cadence] standby_start  execute={execute}  model={model}", file=sys.stderr)
    print(f"[cadence] wake_phrases={WAKE_PHRASES}", file=sys.stderr)
    print(
        f"[cadence] passive={passive_duration_sec}s  command_window={command_window_sec}s",
        file=sys.stderr,
    )
    print("[cadence] press Ctrl+C to stop", file=sys.stderr)

    _last_wake_at = 0.0
    _last_unrecognized_at = 0.0

    try:
        while not _STOP.is_set():
            # ── Single passive capture ────────────────────────────────────────
            try:
                chunk = record_and_transcribe(
                    duration_sec=passive_duration_sec,
                    device=device,
                    model=model,
                )
            except Exception as exc:
                print(f"[cadence] capture_error: {exc}", file=sys.stderr)
                time.sleep(1.0)
                continue

            if _STOP.is_set():
                break

            wav_bytes  = chunk.get("wav_bytes", 0)
            rms        = chunk.get("rms", 0.0)
            is_silent  = chunk.get("is_silent", True)
            capture_ok = chunk.get("capture_ok", True)
            raw_text   = _clean_command(chunk.get("text", "")).strip()

            # ── Phase dispatch ───────────────────────────────────────────────
            if not capture_ok:
                pass  # structurally empty WAV — skip silently

            elif not raw_text:
                if not is_silent:
                    now = time.time()
                    if now - _last_unrecognized_at >= _UNRECOGNIZED_RATE_LIMIT_SEC:
                        _last_unrecognized_at = now
                        print(
                            f"[cadence] speech_unrecognized  "
                            f"bytes={wav_bytes} rms={rms:.1f}",
                            file=sys.stderr,
                        )
                # silent → no log at all (keeps journal clean)

            else:
                normalized = _normalize(raw_text)
                wake = check_wake_phrase(normalized)

                if not wake["wake_phrase_detected"]:
                    pass  # speech but no wake word — silent discard

                else:
                    now = time.time()
                    if now - _last_wake_at < _WAKE_DEDUP_SEC:
                        pass  # duplicate detection — discard silently
                    else:
                        _last_wake_at = now

                        print(
                            f"[cadence] wake_detected  phrase={wake['wake_phrase_used']!r}"
                            f"  text={raw_text!r}",
                            file=sys.stderr,
                        )
                        play_cue("wake_accept")

                        remainder = _clean_command(wake["normalized_command"]).strip()
                        command: Optional[str]

                        if (wake["valid"]
                                and len(remainder.split()) >= _MIN_INLINE_WORDS
                                and not _is_garbage_text(remainder)):
                            command = remainder
                            print(f"[cadence] command_captured (inline): {command!r}",
                                  file=sys.stderr)
                        else:
                            play_cue("command_open")
                            print("[cadence] command_window_open", file=sys.stderr)

                            try:
                                cmd_chunk = record_and_transcribe(
                                    duration_sec=command_window_sec,
                                    device=device,
                                    model=model,
                                )
                            except Exception as exc:
                                print(f"[cadence] command_capture_error: {exc}", file=sys.stderr)
                                command = None
                            else:
                                raw_cmd = _clean_command(cmd_chunk.get("text", "")).strip()
                                if not raw_cmd or _is_garbage_text(raw_cmd):
                                    print("[cadence] command_timeout", file=sys.stderr)
                                    command = None
                                else:
                                    cmd_norm = _normalize(raw_cmd)
                                    cmd_wake = check_wake_phrase(cmd_norm)
                                    if cmd_wake["valid"] and cmd_wake["normalized_command"].strip():
                                        command = _clean_command(cmd_wake["normalized_command"])
                                    else:
                                        command = raw_cmd
                                    print(f"[cadence] command_captured: {command!r}",
                                          file=sys.stderr)

                        if command:
                            try:
                                route_result = route_cadence_utterance(
                                    command,
                                    voice_session_id=voice_session_id,
                                    actor=actor,
                                    lane=lane,
                                    execute=execute,
                                    root=resolved_root,
                                )
                                intent = route_result.get("intent_result", {}).get("intent", "?")
                                routed = route_result.get("routed", False)
                                route_ok = routed or not execute
                                if route_ok:
                                    play_cue("route_ok")
                                    print(f"[cadence] routed_ok  intent={intent}", file=sys.stderr)
                                else:
                                    play_cue("error")
                                    print(f"[cadence] routed_error  intent={intent}",
                                          file=sys.stderr)
                            except Exception as exc:
                                play_cue("error")
                                print(f"[cadence] routed_error  exc={exc}", file=sys.stderr)

            if sleep_between > 0 and not _STOP.is_set():
                time.sleep(sleep_between)

    except KeyboardInterrupt:
        pass

    print("\n[cadence] stopped.", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    from runtime.voice.mic_capture import probe_best_whisper_model

    parser = argparse.ArgumentParser(
        description="Cadence two-phase voice daemon — passive listen → wake → command → route."
    )
    parser.add_argument("--execute", action="store_true",
                        help="Execute routing (create tasks, run browser, etc.).")
    parser.add_argument("--once", action="store_true",
                        help="Run one passive turn and exit.")
    parser.add_argument("--transcript", default="",
                        help="Skip mic: use this literal string as passive chunk transcript.")
    parser.add_argument("--command-transcript", default="",
                        help="Skip mic for command window: use this literal string.")
    parser.add_argument("--duration", type=float, default=DEFAULT_PASSIVE_CHUNK_SEC,
                        help="Passive chunk duration (s).")
    parser.add_argument("--command-window", type=float, default=DEFAULT_COMMAND_WINDOW_SEC,
                        help="Command window duration (s).")
    parser.add_argument("--overlap", type=float, default=0.0,
                        help="Accepted for API compat; ignored in live loop (see module docs).")
    parser.add_argument("--device", default="",
                        help="PulseAudio source name (default: auto-detect).")
    parser.add_argument("--model", default="",
                        help="Whisper model (default: probe best available).")
    parser.add_argument("--actor", default="cadence")
    parser.add_argument("--lane", default="voice")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--json", action="store_true", dest="json_out",
                        help="Output result as JSON (--once / --transcript mode).")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress progress output to stderr.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    verbose = not args.quiet
    model = args.model or probe_best_whisper_model()

    if args.transcript or args.once:
        passive_t = args.transcript or None
        command_t = args.command_transcript or None
        result = run_turn(
            passive_transcript=passive_t,
            command_transcript=command_t,
            passive_duration_sec=args.duration,
            command_window_sec=args.command_window,
            device=args.device or None,
            whisper_model=model,
            execute=args.execute,
            actor=args.actor,
            lane=args.lane,
            root=root,
            verbose=verbose,
        )
        if args.json_out:
            print(json.dumps(result, indent=2, default=str))
        else:
            phase = result.get("phase")
            if phase == "routed":
                rr = result.get("route_result") or {}
                print(f"phase:   {phase}")
                print(f"command: {result.get('command','')}")
                print(f"intent:  {rr.get('intent_result',{}).get('intent','?')}")
                print(f"routed:  {rr.get('routed', False)}")
                print(f"reason:  {rr.get('route_reason','')}")
            else:
                print(f"phase: {phase}")
        return 0

    run_loop(
        passive_duration_sec=args.duration,
        command_window_sec=args.command_window,
        overlap_sec=args.overlap,
        device=args.device or None,
        whisper_model=model,
        execute=args.execute,
        actor=args.actor,
        lane=args.lane,
        root=root,
        verbose=verbose,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
