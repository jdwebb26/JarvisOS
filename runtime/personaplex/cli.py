#!/usr/bin/env python3
"""PersonaPlex terminal chat — proof-mode interactive session.

Usage:
    python3 runtime/personaplex/cli.py                    # new session
    python3 runtime/personaplex/cli.py --resume            # resume latest session
    python3 runtime/personaplex/cli.py --resume ppx_abc123 # resume specific session
    python3 runtime/personaplex/cli.py --one "what needs approval?"  # single-shot query
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _print_response(result: dict) -> None:
    """Pretty-print the assistant response."""
    response = result.get("response", "")
    intent = result.get("intent", {})
    usage = result.get("llm_usage", {})

    print()
    print(f"\033[36mPersonaPlex\033[0m: {response}")

    # Show metadata in dim text
    parts: list[str] = []
    if intent.get("intent"):
        parts.append(f"intent={intent['intent']}")
    if intent.get("command_type"):
        parts.append(f"cmd={intent['command_type']}")
    if usage.get("total_tokens"):
        parts.append(f"tokens={usage['total_tokens']}")
    if result.get("action_proposed"):
        parts.append("ACTION PROPOSED — confirm or cancel")
    if result.get("action_executed"):
        parts.append("ACTION EXECUTED")
    if parts:
        print(f"\033[2m  [{', '.join(parts)}]\033[0m")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="PersonaPlex terminal chat")
    parser.add_argument("--resume", nargs="?", const="__latest__", default=None,
                        help="Resume a session (latest if no ID given)")
    parser.add_argument("--one", type=str, default="",
                        help="Single-shot query (no interactive loop)")
    parser.add_argument("--root", type=str, default=str(ROOT),
                        help="Project root path")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    from runtime.personaplex.engine import chat
    from runtime.personaplex.session import create_session, latest_session, load_session

    # Resolve session
    conversation_id = None
    if args.resume:
        if args.resume == "__latest__":
            s = latest_session(root=root)
            if s:
                conversation_id = s.conversation_id
                print(f"\033[2mResuming session {conversation_id} ({s.turn_count} turns)\033[0m")
            else:
                print("\033[2mNo previous session found, starting new.\033[0m")
        else:
            conversation_id = args.resume
            s = load_session(conversation_id, root=root)
            if s:
                print(f"\033[2mResuming session {conversation_id} ({s.turn_count} turns)\033[0m")
            else:
                print(f"\033[33mSession {conversation_id} not found, starting new.\033[0m")
                conversation_id = None

    # Single-shot mode
    if args.one:
        result = chat(args.one, conversation_id=conversation_id, root=root)
        _print_response(result)
        return 0

    # Interactive loop
    if not conversation_id:
        s = create_session(root=root)
        conversation_id = s.conversation_id

    print("\033[1mPersonaPlex\033[0m — OpenClaw conversational copilot")
    print(f"\033[2mSession: {conversation_id} | Type 'help' for commands, 'quit' to exit\033[0m")
    print()

    while True:
        try:
            user_input = input("\033[32myou\033[0m: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\033[2mSession saved. Goodbye.\033[0m")
            break

        if not user_input:
            continue

        result = chat(user_input, conversation_id=conversation_id, root=root)
        _print_response(result)

        session = result.get("session")
        if session and getattr(session, "mode", "") == "ended":
            print("\033[2mSession ended.\033[0m")
            break
        if session:
            conversation_id = session.conversation_id

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
