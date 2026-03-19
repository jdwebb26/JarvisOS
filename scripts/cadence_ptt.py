#!/usr/bin/env python3
"""cadence_ptt — push-to-talk terminal interface for Cadence.

One button. One assistant. One flow.

Usage:
    python3 scripts/cadence_ptt.py                                  # live PTT (Ctrl+Alt+Shift+8)
    python3 scripts/cadence_ptt.py --replay "what failed?"          # replay without mic
    python3 scripts/cadence_ptt.py --status                         # show PTT/input mode status
    python3 scripts/cadence_ptt.py --binding F5                     # use different key
    python3 scripts/cadence_ptt.py --binding ctrl+alt+shift+8       # explicit chord

Controls:
    Hold Ctrl+Alt+Shift+8 (or configured chord/key) to talk.
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
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------

def _show_status() -> int:
    from runtime.voice.ptt import INPUT_MODE, PTT_BINDING, _detect_capture_backend
    from runtime.voice.ptt_input import probe_backends

    backends = probe_backends()
    capture_backend = os.environ.get("CADENCE_CAPTURE", "auto")
    resolved_capture = _detect_capture_backend() if capture_backend == "auto" else capture_backend

    print("Cadence input configuration")
    print(f"  Input mode:      {INPUT_MODE}")
    print(f"  PTT binding:     {PTT_BINDING}")
    print(f"  Active chord:    {backends['active_chord']}")
    if backends['has_modifiers']:
        print(f"  Chord type:      modifier combo (requires global backend)")
    print(f"  Input backend:   {backends['selected_backend']} (configured: {backends['configured_backend']})")
    print(f"  Capture backend: {resolved_capture} (configured: {capture_backend})")
    print(f"  pynput:          {'available' if backends['pynput_available'] else 'not available'}")
    if backends.get('is_wsl2'):
        print(f"  WSL2:            yes")
        print(f"  win_hotkey:      {'available' if backends.get('win_hotkey_available') else 'not available'}")
    print(f"  DISPLAY:         {os.environ.get('DISPLAY', 'not set')}")
    is_global = backends['selected_backend'] in ('pynput', 'win_hotkey')
    if backends['selected_backend'] == 'win_hotkey':
        print(f"  Global capture:  yes (Windows keyboard hook)")
    elif backends['selected_backend'] == 'pynput':
        print(f"  Global capture:  yes (X11)")
    else:
        print(f"  Global capture:  no (terminal-only)")

    if resolved_capture == "win":
        try:
            from runtime.voice.win_capture import probe as win_probe
            wp = win_probe()
            print(f"  Win ffmpeg:      {wp['ffmpeg_path'][:60]}..." if len(wp.get('ffmpeg_path','')) > 60 else f"  Win ffmpeg:      {wp.get('ffmpeg_path','not found')}")
            print(f"  Win mic:         {wp.get('mic_device', 'not found')}")
        except Exception as e:
            print(f"  Win capture:     error ({e})")
    print()

    from runtime.voice.cadence_status import load_status
    status = load_status(root=ROOT)
    if status:
        routing = status.get("last_routing_mode", "—")
        if routing == "personaplex":
            routing = "conversation"
        session_id = status.get("last_personaplex_session_id", "")
        last_t = status.get("last_transcript", "")
        response_preview = status.get("last_response_preview", "")
        print(f"  Last routing:    {routing}")
        if session_id:
            print(f"  Last session:    {session_id}")
        if last_t:
            print(f"  Last transcript: {last_t!r}")
        if response_preview:
            preview = response_preview[:100].replace("\n", " ")
            if len(response_preview) > 100:
                preview += "..."
            print(f"  Last response:   {preview}")
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
    print(f"Mode:     {'conversation' if mode == 'personaplex' else 'command'}")
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

def _live_ptt(*, binding: str = "space", backend: str = "") -> int:
    from runtime.voice.ptt import PTTCapture, process_ptt_turn, interrupt_tts, tts_is_playing
    from runtime.voice.cues import play_cue, cues_available
    from runtime.voice.cadence_status import init_status
    from runtime.voice.ptt_input import create_ptt_backend

    init_status(listener_mode="ptt", root=ROOT)
    input_backend = create_ptt_backend(backend=backend, binding=binding)

    print(f"\033[1mCadence PTT\033[0m — {input_backend.binding_description}")
    if input_backend.is_global:
        backend_detail = "Windows keyboard hook" if input_backend.name == "win_hotkey" else "pynput/X11"
        print(f"\033[2mGlobal capture active ({backend_detail}). Works from any window.\033[0m")
    else:
        print(f"\033[2mTerminal capture. Focus this window to talk.\033[0m")

    capture = PTTCapture()
    cap_label = capture.capture_backend
    if cap_label == "win":
        print(f"\033[2mAudio: Windows mic via ffmpeg (bypasses WSL silence)\033[0m")
    else:
        print(f"\033[2mAudio: PulseAudio ({cap_label})\033[0m")

    if cues_available():
        print(f"\033[2mAudio cues enabled.\033[0m")
    print(f"\033[2mCtrl+C to exit.\033[0m")
    print()

    capturing = False
    stop_event = threading.Event()

    def on_press():
        nonlocal capturing
        if capturing:
            return
        # Interrupt TTS if playing
        if tts_is_playing():
            interrupt_tts()
        # Start capture
        play_cue("wake_accept", block=False)
        try:
            capture.start()
            capturing = True
            _safe_print("\033[33m● Recording...\033[0m", end="")
        except Exception as exc:
            _safe_print(f"\033[31mCapture error: {exc}\033[0m")

    def on_release():
        nonlocal capturing
        if not capturing:
            return
        wav_path = capture.stop()
        capturing = False

        if wav_path is None:
            _safe_print("\033[2m  (too short, ignored)\033[0m")
            return

        _safe_print("\033[36m◉ Processing...\033[0m")
        result = process_ptt_turn(wav_path, execute=False, root=ROOT)
        _display_result_normal(result)

        try:
            wav_path.unlink(missing_ok=True)
        except Exception:
            pass

    input_backend.start(on_press=on_press, on_release=on_release)

    try:
        while not stop_event.is_set():
            try:
                # For terminal backend, the listener runs in its own thread
                # For pynput, we just sleep and let the listener thread handle events
                if input_backend.is_global:
                    stop_event.wait(timeout=0.5)
                else:
                    # Terminal backend handles its own loop; we wait for it to finish
                    stop_event.wait(timeout=0.5)
                    if not input_backend.is_running():
                        break
            except KeyboardInterrupt:
                break
            # Enforce max capture duration
            if capturing and capture.duration > 30.0:
                on_release()
                _safe_print("\033[33m  (max duration reached)\033[0m")
    except KeyboardInterrupt:
        pass
    finally:
        if capturing:
            capture.abort()
        input_backend.stop()

    print("\n\033[2mCadence PTT stopped.\033[0m")
    return 0


def _safe_print(text: str, **kwargs) -> None:
    """Print that works from both main thread and callbacks."""
    try:
        print(text, flush=True, **kwargs)
    except Exception:
        try:
            os.write(sys.stdout.fileno(), (text + "\n").encode())
        except Exception:
            pass


def _display_result_normal(result: dict) -> None:
    """Display a PTT turn result."""
    phase = result.get("phase", "?")

    if phase in ("too_short", "silent", "no_speech", "empty_command"):
        _safe_print(f"\033[2m  ({phase})\033[0m")
        return

    if phase == "route_error":
        _safe_print(f"\033[31m  Error: {result.get('error', '?')}\033[0m")
        return

    command = result.get("command", "")
    mode = result.get("routing_mode", "?")
    response = result.get("response", "")

    _safe_print(f"\033[32m  you:\033[0m {command}")
    _safe_print(f"\033[2m  [{'conversation' if mode == 'personaplex' else 'command'}]\033[0m")

    if response:
        lines = response.split("\n")
        for line in lines[:15]:
            _safe_print(f"\033[36m  Cadence:\033[0m {line}")
        if len(lines) > 15:
            _safe_print(f"\033[2m  ... ({len(lines) - 15} more lines)\033[0m")
    _safe_print("")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cadence push-to-talk — one button, one assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Hold Ctrl+Alt+Shift+8 to talk. Release to submit. Press while speaking to interrupt.",
    )
    parser.add_argument("--replay", default="", help="Replay a canned transcript (no mic)")
    parser.add_argument("--status", action="store_true", help="Show input mode and last routing info")
    parser.add_argument("--binding", default=os.environ.get("CADENCE_PTT_BINDING", "ctrl+alt+shift+8"),
                        help="PTT key/button/chord binding (ctrl+alt+shift+8, space, f5, mouse4)")
    parser.add_argument("--backend", default="",
                        help="Input backend: auto, pynput, terminal (default: auto)")
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
            clean = {k: v for k, v in result.items() if k != "route_result"}
            print(json.dumps(clean, indent=2, default=str))
            return 0
        return _replay(args.replay)

    return _live_ptt(binding=args.binding, backend=args.backend)


if __name__ == "__main__":
    raise SystemExit(main())
