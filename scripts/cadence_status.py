#!/usr/bin/env python3
"""cadence_status — operator CLI for Cadence voice daemon status, proof, and replay.

Usage:
    # Show current daemon status
    python3 scripts/cadence_status.py

    # Show status as JSON
    python3 scripts/cadence_status.py --json

    # Replay a canned transcript through the full wake→route pipeline (no mic needed)
    python3 scripts/cadence_status.py --replay "Jarvis browse finance.yahoo.com"

    # Replay wake-only + separate command
    python3 scripts/cadence_status.py --replay "Jarvis" --command "browse finance.yahoo.com"

    # Run health probe
    python3 scripts/cadence_status.py --health

    # Show recent voice command records
    python3 scripts/cadence_status.py --recent
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _show_status(*, as_json: bool = False) -> int:
    from runtime.voice.cadence_status import load_status

    status = load_status(root=ROOT)
    if not status:
        if as_json:
            print(json.dumps({"error": "no status file", "path": str(ROOT / "state" / "cadence_status.json")}))
        else:
            print("Cadence status: no status file found.")
            print(f"  Expected at: {ROOT / 'state' / 'cadence_status.json'}")
            print("  The daemon may not have run yet, or status tracking was just added.")
        return 1

    if as_json:
        print(json.dumps(status, indent=2))
        return 0

    state = status.get("state", "?")
    updated = status.get("updated_at", "?")
    listener = status.get("listener_mode", "?")
    device = status.get("audio_device", "?")
    mic = status.get("mic_available", "?")
    mic_err = status.get("mic_error", "")
    uptime = status.get("uptime_seconds", 0)

    print(f"Cadence daemon status")
    print(f"  State:          {state}")
    print(f"  Updated:        {updated}")
    print(f"  Listener:       {listener}")
    print(f"  Audio device:   {device}")
    print(f"  Mic available:  {mic}{f'  ({mic_err})' if mic_err else ''}")
    print(f"  Uptime:         {uptime}s")
    print()

    wakes = status.get("wake_count", 0)
    routes = status.get("route_count", 0)
    errors = status.get("error_count", 0)
    timeouts = status.get("timeout_count", 0)
    print(f"  Counters:  wakes={wakes}  routes={routes}  errors={errors}  timeouts={timeouts}")

    last_wake = status.get("last_wake_at", "")
    last_phrase = status.get("last_wake_phrase", "")
    last_transcript = status.get("last_transcript", "")
    last_intent = status.get("last_intent", "")
    last_ok = status.get("last_route_ok")
    last_err = status.get("last_route_error", "")
    last_route_at = status.get("last_route_at", "")

    if last_wake:
        print()
        print(f"  Last wake:       {last_wake}  phrase={last_phrase!r}")
    if last_transcript:
        print(f"  Last transcript: {last_transcript!r}")
        print(f"  Last intent:     {last_intent}")
        print(f"  Last route ok:   {last_ok}")
        if last_err:
            print(f"  Last error:      {last_err}")
        if last_route_at:
            print(f"  Last route at:   {last_route_at}")

    # Conversation routing info
    routing_mode = status.get("last_routing_mode", "")
    ppx_session = status.get("last_personaplex_session_id", "")
    ppx_response = status.get("last_response_preview", "")
    if routing_mode:
        print()
        print(f"  Routing mode:    {routing_mode}")
        if ppx_session:
            print(f"  Conversation session: {ppx_session}")
        if ppx_response:
            preview = ppx_response[:120].replace("\n", " ")
            if len(ppx_response) > 120:
                preview += "..."
            print(f"  Response preview: {preview}")
    return 0


def _replay(*, transcript: str, command: str = "", execute: bool = False, verbose: bool = False) -> int:
    from runtime.voice.cadence_daemon import run_turn

    passive_t = transcript
    command_t = command or None

    result = run_turn(
        passive_transcript=passive_t,
        command_transcript=command_t,
        execute=execute,
        root=ROOT,
        verbose=True,
    )

    phase = result.get("phase", "?")
    route_result = result.get("route_result") or {}
    intent_result = route_result.get("intent_result") or {}
    delegation = route_result.get("delegation_result") or {}
    route_reason = route_result.get("route_reason", "")
    is_ppx = route_reason == "personaplex_conversation"

    print()
    # Compact summary first
    if phase == "routed":
        ok = result.get("route_ok", False)
        cmd = result.get("command", "")
        intent = intent_result.get("intent", "?")
        mode = "conversation" if is_ppx else "command"
        print(f"Phase:     {phase}")
        print(f"OK:        {ok}")
        print(f"Command:   {cmd!r}")
        print(f"Intent:    {intent}")
        print(f"Mode:      {mode}")

        if is_ppx:
            ppx_session = delegation.get("conversation_id", "")
            ppx_intent = delegation.get("personaplex_intent", "")
            ppx_response = delegation.get("response", "")
            action = delegation.get("action_proposed")
            usage = delegation.get("llm_usage") or {}

            if ppx_session:
                print(f"Session:   {ppx_session}")
            if ppx_intent:
                print(f"PPX Intent: {ppx_intent}")
            if usage.get("total_tokens"):
                print(f"Tokens:    {usage['total_tokens']}")
            if action:
                print(f"Action:    {action.get('description', '?')} (PROPOSED — needs confirmation)")
            if ppx_response:
                print()
                print("--- Cadence Response ---")
                print(ppx_response)
                print("---")
        else:
            # Command routing — show delegation result
            if delegation:
                print(f"Delegation: {json.dumps(delegation, indent=2, default=str)[:500]}")
    else:
        print(f"Phase: {phase}")

    if verbose:
        print()
        print("--- Full Result JSON ---")
        print(json.dumps(result, indent=2, default=str))
    return 0


def _health() -> int:
    from runtime.voice.health_probe import run_all_probes
    result = run_all_probes()
    print(json.dumps(result, indent=2))
    return 0 if result.get("overall") == "ok" else 1


def _recent() -> int:
    voice_dir = ROOT / "state" / "voice_commands"
    if not voice_dir.exists():
        print("No voice command records found.")
        return 0
    files = sorted(voice_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[:5]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            ts = data.get("created_at", "?")
            cmd = data.get("normalized_command", data.get("raw_command", "?"))
            intent = data.get("intent", "?")
            print(f"  {ts}  intent={intent}  cmd={cmd!r}")
        except Exception:
            print(f"  {f.name}: unreadable")
    if len(files) > 5:
        print(f"  ... +{len(files) - 5} more")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Cadence voice daemon — operator status and replay")
    parser.add_argument("--json", action="store_true", help="Output status as JSON")
    parser.add_argument("--replay", default="", help="Replay a transcript through the wake→route pipeline")
    parser.add_argument("--command", default="", help="Command window transcript (used with --replay)")
    parser.add_argument("--execute", action="store_true", help="Execute mode for --replay (default: preview)")
    parser.add_argument("--health", action="store_true", help="Run voice stack health probe")
    parser.add_argument("--recent", action="store_true", help="Show recent voice command records")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show full JSON in --replay output")
    args = parser.parse_args()

    if args.health:
        return _health()
    if args.recent:
        return _recent()
    if args.replay:
        return _replay(transcript=args.replay, command=args.command, execute=args.execute, verbose=args.verbose)
    return _show_status(as_json=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
