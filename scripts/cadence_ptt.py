#!/usr/bin/env python3
"""cadence_ptt — push-to-talk terminal interface for Cadence.

One button. One assistant. One flow.

Usage:
    python3 scripts/cadence_ptt.py                        # live PTT (hold SPACE)
    python3 scripts/cadence_ptt.py --replay "what failed?" # replay without mic
    python3 scripts/cadence_ptt.py --status                # show PTT/input mode status
    python3 scripts/cadence_ptt.py --binding F5            # use different key

Controls:
    Hold SPACE (or configured key) to talk.
    Release to submit.
    Press while Cadence is speaking to interrupt.
    Ctrl+C to exit.

The operator never needs to say a wake word in PTT mode, though "Cadence" or
"Jarvis" prefixes are accepted and stripped automatically.
"""
from __future__ import annotations

import argparse
import json
import os
import select
import sys
import termios
import tty
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Terminal raw-mode key detection
# ---------------------------------------------------------------------------

class RawTerminal:
    """Context manager for raw terminal input (no echo, character-at-a-time)."""

    def __init__(self):
        self._fd = sys.stdin.fileno()
        self._old_settings = None

    def __enter__(self):
        self._old_settings = termios.tcgetattr(self._fd)
        tty.setraw(self._fd)
        return self

    def __exit__(self, *args):
        if self._old_settings is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)

    def key_pressed(self, timeout: float = 0.1) -> str:
        """Return the key pressed, or empty string if none within timeout."""
        rlist, _, _ = select.select([sys.stdin], [], [], timeout)
        if rlist:
            ch = sys.stdin.read(1)
            return ch
        return ""


# Key mapping for named keys
_KEY_MAP = {
    "space": " ",
    "enter": "\r",
    "tab": "\t",
}


def _resolve_key(binding: str) -> str:
    """Resolve a key binding name to the actual character."""
    lower = binding.lower().strip()
    if lower in _KEY_MAP:
        return _KEY_MAP[lower]
    if len(lower) == 1:
        return lower
    return " "  # default to space


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------

def _show_status() -> int:
    from runtime.voice.ptt import INPUT_MODE, PTT_BINDING

    print("Cadence input configuration")
    print(f"  Input mode:   {INPUT_MODE}")
    print(f"  PTT binding:  {PTT_BINDING}")
    print()

    from runtime.voice.cadence_status import load_status
    status = load_status(root=ROOT)
    if status:
        routing = status.get("last_routing_mode", "—")
        ppx_id = status.get("last_personaplex_session_id", "")
        last_t = status.get("last_transcript", "")
        print(f"  Last routing:  {routing}")
        if ppx_id:
            print(f"  Last PPX session: {ppx_id}")
        if last_t:
            print(f"  Last transcript:  {last_t!r}")
    else:
        print("  No status file yet (daemon hasn't run).")
    return 0


# ---------------------------------------------------------------------------
# Replay mode
# ---------------------------------------------------------------------------

def _replay(transcript: str) -> int:
    from runtime.voice.ptt import replay_ptt_turn
    from runtime.voice.cadence_status import init_status
    init_status(root=ROOT)

    result = replay_ptt_turn(transcript, root=ROOT)
    phase = result.get("phase", "?")
    mode = result.get("routing_mode", "?")
    intent = result.get("intent", "?")
    ppx_id = result.get("personaplex_session_id", "")
    response = result.get("response", "")
    action = result.get("action_proposed")

    print(f"Phase:    {phase}")
    print(f"Command:  {result.get('command', '')!r}")
    print(f"Intent:   {intent}")
    print(f"Mode:     {'PersonaPlex' if mode == 'personaplex' else 'command'}")
    if ppx_id:
        print(f"Session:  {ppx_id}")
    if action:
        print(f"Action:   {action.get('description', '?')} (PROPOSED — needs confirmation)")
    if response:
        print()
        print("--- Cadence ---")
        print(response)
        print("---")
    return 0


# ---------------------------------------------------------------------------
# Live PTT loop
# ---------------------------------------------------------------------------

def _live_ptt(*, binding: str = "space") -> int:
    from runtime.voice.ptt import PTTCapture, process_ptt_turn, interrupt_tts, tts_is_playing
    from runtime.voice.cues import play_cue, cues_available
    from runtime.voice.cadence_status import init_status

    init_status(listener_mode="ptt", root=ROOT)
    ptt_key = _resolve_key(binding)
    key_name = binding.upper() if len(binding) > 1 else repr(binding)

    print(f"\033[1mCadence PTT\033[0m — hold {key_name} to talk, Ctrl+C to exit")
    if cues_available():
        print(f"\033[2mAudio cues enabled. TTS via Piper.\033[0m")
    else:
        print(f"\033[2mAudio cues not available (paplay missing or no cue files).\033[0m")
    print()

    capture = PTTCapture()
    capturing = False

    try:
        with RawTerminal() as term:
            while True:
                ch = term.key_pressed(timeout=0.05)

                # Ctrl+C
                if ch == "\x03":
                    if capturing:
                        capture.abort()
                    break

                # PTT key pressed
                if ch == ptt_key:
                    if not capturing:
                        # Interrupt TTS if playing
                        if tts_is_playing():
                            interrupt_tts()

                        # Start capture
                        play_cue("wake_accept", block=False)
                        try:
                            capture.start()
                            capturing = True
                            _raw_write("\r\033[33m● Recording...\033[0m")
                        except Exception as exc:
                            _raw_write(f"\r\033[31mCapture error: {exc}\033[0m\n")
                    else:
                        # Key is still held — no action needed
                        pass

                # No key pressed (released or idle)
                elif capturing and ch == "":
                    # Check if key was released by waiting a bit longer
                    # In raw mode, we detect release by absence of the key
                    ch2 = term.key_pressed(timeout=0.15)
                    if ch2 == ptt_key:
                        # Still held
                        continue

                    # Key released — stop capture
                    wav_path = capture.stop()
                    capturing = False

                    if wav_path is None:
                        _raw_write("\r\033[2m  (too short, ignored)\033[0m\n")
                        continue

                    _raw_write("\r\033[36m◉ Processing...\033[0m   \n")

                    # Process the captured audio
                    result = process_ptt_turn(wav_path, execute=False, root=ROOT)
                    _display_result(result)

                    # Clean up WAV
                    try:
                        wav_path.unlink(missing_ok=True)
                    except Exception:
                        pass

                # Enforce max capture duration
                if capturing and capture.duration > 30.0:
                    wav_path = capture.stop()
                    capturing = False
                    _raw_write("\r\033[33m  (max duration reached)\033[0m\n")
                    if wav_path:
                        result = process_ptt_turn(wav_path, execute=False, root=ROOT)
                        _display_result(result)
                        try:
                            wav_path.unlink(missing_ok=True)
                        except Exception:
                            pass

    except KeyboardInterrupt:
        if capturing:
            capture.abort()

    _raw_write("\n\033[2mCadence PTT stopped.\033[0m\n")
    return 0


def _raw_write(text: str) -> None:
    """Write to stdout in raw terminal mode (needs \\r for line start)."""
    os.write(sys.stdout.fileno(), text.encode())


def _display_result(result: dict) -> None:
    """Display a PTT turn result in raw terminal mode."""
    phase = result.get("phase", "?")

    if phase in ("too_short", "silent", "no_speech", "empty_command"):
        _raw_write(f"\r\033[2m  ({phase})\033[0m\n")
        return

    if phase == "route_error":
        _raw_write(f"\r\033[31m  Error: {result.get('error', '?')}\033[0m\n")
        return

    command = result.get("command", "")
    mode = result.get("routing_mode", "?")
    response = result.get("response", "")

    mode_label = "PersonaPlex" if mode == "personaplex" else "command"
    _raw_write(f"\r\033[32m  you:\033[0m {command}\n")
    _raw_write(f"\r\033[2m  [{mode_label}]\033[0m\n")

    if response:
        # Compact response for terminal
        lines = response.split("\n")
        for line in lines[:15]:
            _raw_write(f"\r\033[36m  Cadence:\033[0m {line}\n")
        if len(lines) > 15:
            _raw_write(f"\r\033[2m  ... ({len(lines) - 15} more lines)\033[0m\n")
    _raw_write("\r\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cadence push-to-talk — one button, one assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Hold SPACE to talk. Release to submit. Press while speaking to interrupt.",
    )
    parser.add_argument("--replay", default="", help="Replay a canned transcript (no mic)")
    parser.add_argument("--status", action="store_true", help="Show input mode and last routing info")
    parser.add_argument("--binding", default=os.environ.get("CADENCE_PTT_BINDING", "space"),
                        help="PTT key binding (default: space)")
    parser.add_argument("--json", action="store_true", help="Output replay result as JSON")
    args = parser.parse_args()

    if args.status:
        return _show_status()

    if args.replay:
        if args.json:
            from runtime.voice.ptt import replay_ptt_turn
            from runtime.voice.cadence_status import init_status
            init_status(root=ROOT)
            result = replay_ptt_turn(args.replay, root=ROOT)
            # Strip non-serializable route_result for clean JSON
            clean = {k: v for k, v in result.items() if k != "route_result"}
            print(json.dumps(clean, indent=2, default=str))
            return 0
        return _replay(args.replay)

    return _live_ptt(binding=args.binding)


if __name__ == "__main__":
    raise SystemExit(main())
