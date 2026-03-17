#!/usr/bin/env python3
"""cadence_cli — bounded CLI entry point for Cadence voice ingress.

Simulates a voice utterance arriving at the Cadence pipeline.  Useful for
local proofs, integration smoke tests, and manual debugging without needing
a live mic/TTS chain.

Usage:
    python3 runtime/voice/cadence_cli.py "Jarvis, browse finance.yahoo.com"
    python3 runtime/voice/cadence_cli.py --execute "snapshot https://example.com"
    python3 runtime/voice/cadence_cli.py --preview "implement the artifact cleanup"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.cadence_ingress import route_cadence_utterance


def main() -> int:
    parser = argparse.ArgumentParser(description="Cadence voice ingress CLI — simulate a voice utterance.")
    parser.add_argument("utterance", nargs="?", default="", help="The voice utterance text")
    parser.add_argument("--execute", action="store_true", help="Execute (delegate) the utterance; default is preview only")
    parser.add_argument("--preview", action="store_true", help="Preview only (no delegation) — this is the default")
    parser.add_argument("--actor", default="cadence", help="Actor name")
    parser.add_argument("--lane", default="voice", help="Lane name")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--session", default="", help="Voice session ID (generated if not given)")
    args = parser.parse_args()

    utterance = args.utterance.strip()
    if not utterance:
        print("ERROR: utterance is required.", file=sys.stderr)
        return 1

    execute = args.execute and not args.preview
    root = Path(args.root).resolve()

    try:
        result = route_cadence_utterance(
            utterance,
            voice_session_id=args.session,
            actor=args.actor,
            lane=args.lane,
            execute=execute,
            root=root,
        )
    except Exception as exc:
        result = {
            "error": str(exc),
            "utterance": utterance,
        }

    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("routed") or not execute else 0


if __name__ == "__main__":
    raise SystemExit(main())
