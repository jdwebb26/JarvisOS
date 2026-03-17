#!/usr/bin/env python3
"""cadence_daemon — continuous voice capture → Whisper → Cadence routing loop.

Listens via the local microphone (PulseAudio), transcribes each chunk with
Whisper, checks for a wake phrase, then routes the command through the
Cadence ingress pipeline.

This is the live voice daemon for the OpenClaw Cadence agent.

Usage:
    # Preview mode — classify intent, no side-effects
    python3 runtime/voice/cadence_daemon.py

    # Execute mode — actually route (create tasks, run browser, etc.)
    python3 runtime/voice/cadence_daemon.py --execute

    # Single turn — record once, transcribe, route, exit
    python3 runtime/voice/cadence_daemon.py --once

    # Test with a canned transcript (no mic needed)
    python3 runtime/voice/cadence_daemon.py --transcript "Jarvis browse example.com"

    # Custom duration per chunk
    python3 runtime/voice/cadence_daemon.py --duration 8 --execute

Wake phrases (any prefix triggers routing):
    "Jarvis ..."   — default, matches existing wakeword.py behaviour
    "Hey Cadence ..." / "Cadence ..."  — also accepted
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.cadence_ingress import route_cadence_utterance
from runtime.voice.wakeword import validate_wake_phrase


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WAKE_PHRASES = ("Jarvis", "Hey Cadence", "Cadence")
DEFAULT_CHUNK_SEC = 5.0
DEFAULT_WHISPER_MODEL = "base"
DEFAULT_LOOP_SLEEP_SEC = 0.3


# ---------------------------------------------------------------------------
# Wake phrase check — accepts any of the WAKE_PHRASES
# ---------------------------------------------------------------------------

def check_wake_phrase(transcript: str) -> dict:
    """Check if transcript starts with any recognised wake phrase.

    Returns same shape as validate_wake_phrase():
      {valid, wake_phrase_detected, normalized_command, reason, wake_phrase_used}
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
# Single turn
# ---------------------------------------------------------------------------

def run_one_turn(
    *,
    transcript: Optional[str] = None,
    duration_sec: float = DEFAULT_CHUNK_SEC,
    device: Optional[str] = None,
    whisper_model: str = DEFAULT_WHISPER_MODEL,
    execute: bool = False,
    voice_session_id: str = "",
    actor: str = "cadence",
    lane: str = "voice",
    root: Optional[Path] = None,
    verbose: bool = True,
) -> dict:
    """Run one capture→transcribe→route turn.

    If transcript is given, skip the mic capture step (useful for --transcript
    CLI flag or testing without a microphone).

    Returns a structured result dict.
    """
    resolved_root = Path(root or ROOT).resolve()

    # ── Step 1: get transcript ──────────────────────────────────────────────
    if transcript is not None:
        transcription = {
            "text": transcript,
            "ok": True,
            "is_silent": False,
            "elapsed_sec": 0.0,
            "source": "manual",
        }
    else:
        from runtime.voice.mic_capture import record_and_transcribe
        if verbose:
            print(f"[cadence] recording {duration_sec}s ...", file=sys.stderr)
        transcription = record_and_transcribe(
            duration_sec=duration_sec,
            device=device,
            model=whisper_model,
        )
        transcription["source"] = "mic"

    raw_text = transcription.get("text", "").strip()

    if not raw_text or transcription.get("is_silent"):
        if verbose:
            print("[cadence] silence / empty transcript — skipping", file=sys.stderr)
        return {
            "status": "silent",
            "transcript": raw_text,
            "transcription": transcription,
            "wake": None,
            "route_result": None,
        }

    if verbose:
        print(f"[cadence] transcript: {raw_text!r}", file=sys.stderr)

    # ── Step 2: wake phrase check ───────────────────────────────────────────
    wake = check_wake_phrase(raw_text)
    if not wake["valid"]:
        if verbose:
            print(f"[cadence] no wake phrase ({wake['reason']}) — skipping", file=sys.stderr)
        return {
            "status": "no_wake",
            "transcript": raw_text,
            "transcription": transcription,
            "wake": wake,
            "route_result": None,
        }

    command = wake["normalized_command"]
    if verbose:
        print(f"[cadence] wake accepted — command: {command!r}", file=sys.stderr)

    # ── Step 3: route through Cadence ingress ──────────────────────────────
    route_result = route_cadence_utterance(
        command,
        voice_session_id=voice_session_id,
        actor=actor,
        lane=lane,
        execute=execute,
        root=resolved_root,
    )

    if verbose:
        intent = route_result["intent_result"]["intent"]
        reason = route_result.get("route_reason", "")
        routed = route_result.get("routed", False)
        print(f"[cadence] intent={intent}  routed={routed}  reason={reason}", file=sys.stderr)

    return {
        "status": "routed",
        "transcript": raw_text,
        "command": command,
        "transcription": transcription,
        "wake": wake,
        "route_result": route_result,
    }


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------

def run_loop(
    *,
    duration_sec: float = DEFAULT_CHUNK_SEC,
    device: Optional[str] = None,
    whisper_model: str = DEFAULT_WHISPER_MODEL,
    execute: bool = False,
    actor: str = "cadence",
    lane: str = "voice",
    root: Optional[Path] = None,
    verbose: bool = True,
    sleep_between: float = DEFAULT_LOOP_SLEEP_SEC,
) -> None:
    """Continuous voice capture loop.  Runs until KeyboardInterrupt."""
    from runtime.core.models import new_id
    voice_session_id = new_id("vsession")
    resolved_root = Path(root or ROOT).resolve()

    print(f"[cadence] voice daemon starting (execute={execute}, model={whisper_model})", file=sys.stderr)
    print(f"[cadence] wake phrases: {WAKE_PHRASES}", file=sys.stderr)
    print(f"[cadence] press Ctrl+C to stop", file=sys.stderr)

    try:
        while True:
            try:
                result = run_one_turn(
                    duration_sec=duration_sec,
                    device=device,
                    whisper_model=whisper_model,
                    execute=execute,
                    voice_session_id=voice_session_id,
                    actor=actor,
                    lane=lane,
                    root=resolved_root,
                    verbose=verbose,
                )
                if result["status"] == "routed" and verbose:
                    print(json.dumps(result["route_result"], indent=2, default=str), file=sys.stderr)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"[cadence] turn error: {exc}", file=sys.stderr)

            if sleep_between > 0:
                time.sleep(sleep_between)
    except KeyboardInterrupt:
        print("\n[cadence] stopped.", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cadence voice daemon — mic capture → Whisper → Cadence routing."
    )
    parser.add_argument("--execute", action="store_true", help="Execute routing (create tasks, run browser, etc.). Default: preview only.")
    parser.add_argument("--once", action="store_true", help="Run one turn and exit.")
    parser.add_argument("--transcript", default="", help="Skip mic capture and use this literal transcript string.")
    parser.add_argument("--duration", type=float, default=DEFAULT_CHUNK_SEC, help="Recording duration per chunk (seconds).")
    parser.add_argument("--device", default="", help="PulseAudio source name (default: auto-detect).")
    parser.add_argument("--model", default=DEFAULT_WHISPER_MODEL, help="Whisper model (base/small/medium/large).")
    parser.add_argument("--actor", default="cadence", help="Actor name.")
    parser.add_argument("--lane", default="voice", help="Lane name.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path.")
    parser.add_argument("--json", action="store_true", dest="json_out", help="Output result as JSON (for --once or --transcript).")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output to stderr.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    verbose = not args.quiet

    if args.transcript or args.once:
        transcript = args.transcript or None
        result = run_one_turn(
            transcript=transcript,
            duration_sec=args.duration,
            device=args.device or None,
            whisper_model=args.model,
            execute=args.execute,
            actor=args.actor,
            lane=args.lane,
            root=root,
            verbose=verbose,
        )
        if args.json_out:
            print(json.dumps(result, indent=2, default=str))
        else:
            status = result.get("status")
            if status == "routed":
                rr = result.get("route_result") or {}
                print(f"intent:  {rr.get('intent_result', {}).get('intent', '?')}")
                print(f"routed:  {rr.get('routed', False)}")
                print(f"reason:  {rr.get('route_reason', '')}")
                dr = rr.get("delegation_result") or {}
                if dr:
                    print(f"result:  {json.dumps(dr, default=str)[:200]}")
            else:
                print(f"status: {status}")
        return 0

    # Loop mode
    run_loop(
        duration_sec=args.duration,
        device=args.device or None,
        whisper_model=args.model,
        execute=args.execute,
        actor=args.actor,
        lane=args.lane,
        root=root,
        verbose=verbose,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
