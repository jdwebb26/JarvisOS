#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.pipeline import process_voice_transcript
from runtime.voice.policy import evaluate_voice_command_policy
from runtime.voice.speaker_guard import SpeakerGuard


def handle_voice_command(
    raw_transcript,
    *,
    voice_session_id,
    actor,
    lane,
    task_id="",
    speaker_confidence=0.0,
    route=False,
    root=None,
) -> dict:
    del route
    resolved_root = Path(root or ROOT).resolve()
    pipeline_result = process_voice_transcript(
        raw_transcript,
        voice_session_id=voice_session_id,
        actor=actor,
        lane=lane,
        task_id=task_id,
        speaker_confidence=speaker_confidence,
        root=resolved_root,
    )

    if pipeline_result["status"] != "accepted":
        return {
            "kind": "rejected",
            "status": pipeline_result["status"],
            "voice_command": pipeline_result["voice_command"],
            "wakeword": pipeline_result["wakeword"],
            "feedback": pipeline_result["feedback"],
            "routed": False,
        }

    policy = evaluate_voice_command_policy(
        pipeline_result["voice_command"]["normalized_command"],
        speaker_confidence=speaker_confidence,
        input_source="voice",
        root=resolved_root,
    )
    speaker_guard = SpeakerGuard()
    speaker_score = speaker_guard.score_speaker({"speaker_confidence": speaker_confidence})
    speaker_gate = {
        "known_operator": speaker_guard.is_known_operator(speaker_score),
        "confidence_meets_threshold": speaker_guard.confidence_meets_threshold(
            speaker_score, policy["risk_tier"]
        ),
    }

    kind = "accepted"
    if policy["requires_confirmation"]:
        kind = "confirmation_required"

    return {
        "kind": kind,
        "status": pipeline_result["status"],
        "voice_command": pipeline_result["voice_command"],
        "wakeword": pipeline_result["wakeword"],
        "risk": pipeline_result["risk"],
        "policy": policy,
        "speaker_guard": {
            "score": speaker_score,
            "gate": speaker_gate,
        },
        "feedback": pipeline_result["feedback"],
        "routed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Thin voice command gateway wrapper.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--raw-transcript", required=True, help="Voice transcript")
    parser.add_argument("--voice-session-id", required=True, help="Voice session id")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="voice", help="Lane name")
    parser.add_argument("--task-id", default="", help="Task id")
    parser.add_argument("--speaker-confidence", type=float, default=0.0, help="Speaker confidence")
    parser.add_argument("--route", action="store_true", help="Reserved routing flag")
    args = parser.parse_args()

    result = handle_voice_command(
        args.raw_transcript,
        voice_session_id=args.voice_session_id,
        actor=args.actor,
        lane=args.lane,
        task_id=args.task_id,
        speaker_confidence=args.speaker_confidence,
        route=args.route,
        root=Path(args.root).resolve(),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
