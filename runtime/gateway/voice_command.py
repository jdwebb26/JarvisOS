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
from runtime.voice.approval_flow import extract_inline_approval_code, handle_voice_confirmation_requirement
from runtime.voice.policy import evaluate_voice_command_policy
from runtime.voice.router import maybe_route_voice_command
from runtime.voice.speaker_guard import SpeakerGuard
from runtime.core.security_validation import validate_runtime_policy_request
from runtime.core.voice_sessions import update_voice_session_from_command


def handle_voice_command(
    raw_transcript,
    *,
    voice_session_id,
    actor,
    lane,
    task_id="",
    speaker_confidence=0.0,
    route=False,
    route_execute=False,
    root=None,
) -> dict:
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
        update_voice_session_from_command(
            voice_session_id=voice_session_id,
            actor=actor,
            lane=lane,
            command_id=pipeline_result["voice_command"]["command_id"],
            raw_transcript=pipeline_result["voice_command"]["raw_transcript"],
            normalized_command=pipeline_result["voice_command"]["normalized_command"],
            task_id=task_id,
            command_status="rejected",
            risk_tier=pipeline_result["voice_command"]["risk_tier"],
            confirmation_required=False,
            confirmation_state="not_required",
            verification_status="none",
            root=resolved_root,
        )
        return {
            "kind": "rejected",
            "status": pipeline_result["status"],
            "voice_command": pipeline_result["voice_command"],
            "wakeword": pipeline_result["wakeword"],
            "feedback": pipeline_result["feedback"],
            "routed": False,
            "route_preview": None,
        }

    actionable_command = extract_inline_approval_code(
        pipeline_result["voice_command"]["normalized_command"]
    )["normalized_command_without_code"]

    policy = evaluate_voice_command_policy(
        actionable_command,
        speaker_confidence=speaker_confidence,
        input_source="voice",
        root=resolved_root,
    )
    runtime_policy_validation = validate_runtime_policy_request(
        actionable_command,
        action_type=policy["action_type"],
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

    if not runtime_policy_validation["safe"]:
        update_voice_session_from_command(
            voice_session_id=voice_session_id,
            actor=actor,
            lane=lane,
            command_id=pipeline_result["voice_command"]["command_id"],
            raw_transcript=pipeline_result["voice_command"]["raw_transcript"],
            normalized_command=actionable_command,
            task_id=task_id,
            command_status="rejected",
            risk_tier=policy["risk_tier"],
            confirmation_required=False,
            confirmation_state="not_required",
            verification_status="blocked_by_runtime_policy",
            root=resolved_root,
        )
        return {
            "kind": "rejected",
            "status": pipeline_result["status"],
            "voice_command": pipeline_result["voice_command"],
            "wakeword": pipeline_result["wakeword"],
            "risk": pipeline_result["risk"],
            "policy": {
                **policy,
                "allowed": False,
                "reason": runtime_policy_validation["reason"],
                "findings": runtime_policy_validation["findings"],
            },
            "runtime_policy_validation": runtime_policy_validation,
            "speaker_guard": {
                "score": speaker_score,
                "gate": speaker_gate,
            },
            "feedback": pipeline_result["feedback"],
            "routed": False,
            "route_preview": None,
            "route_result": None,
            "approval_flow": None,
        }

    kind = "accepted"
    if policy["requires_confirmation"]:
        kind = "confirmation_required"

    route_preview = None
    route_result = None
    if route:
        route_preview = maybe_route_voice_command(
            actionable_command,
            actor=actor,
            lane=lane,
            task_id=task_id,
            root=resolved_root,
            execute=False,
        )

    approval_flow = None
    if policy["requires_confirmation"]:
        approval_flow = handle_voice_confirmation_requirement(
            voice_command=pipeline_result["voice_command"],
            route_preview=route_preview,
            actor=actor,
            lane=lane,
            root=resolved_root,
        )
        if approval_flow["verification"] and approval_flow["verification"]["status"] == "approved":
            kind = "approved"
        elif approval_flow["verification"] and approval_flow["verification"]["status"] != "approved":
            kind = "approval_rejected"
        else:
            kind = "confirmation_required"

    if route and route_execute and kind in {"accepted", "approved"}:
        route_result = maybe_route_voice_command(
            actionable_command,
            actor=actor,
            lane=lane,
            task_id=task_id,
            root=resolved_root,
            execute=True,
        )

    confirmation_state = "not_required"
    confirmation_required = False
    latest_challenge_id = None
    latest_action_id = None
    latest_verification_status = "none"
    if policy["requires_confirmation"]:
        confirmation_required = True
        confirmation_state = "pending_confirmation"
        if approval_flow is not None:
            latest_challenge_id = (approval_flow.get("challenge") or {}).get("challenge_id")
            latest_action_id = approval_flow.get("action_id")
            verification = approval_flow.get("verification")
            if verification is not None:
                latest_verification_status = verification.get("status", "none")
                if verification.get("status") == "approved":
                    confirmation_state = "confirmed"
                elif verification.get("status") != "pending":
                    confirmation_state = "rejected"
            elif approval_flow.get("prompt") is not None:
                latest_verification_status = "pending"

    update_voice_session_from_command(
        voice_session_id=voice_session_id,
        actor=actor,
        lane=lane,
        command_id=pipeline_result["voice_command"]["command_id"],
        raw_transcript=pipeline_result["voice_command"]["raw_transcript"],
        normalized_command=actionable_command,
        task_id=task_id,
        command_status=kind,
        risk_tier=policy["risk_tier"],
        confirmation_required=confirmation_required,
        confirmation_state=confirmation_state,
        challenge_id=latest_challenge_id,
        action_id=latest_action_id,
        verification_status=latest_verification_status,
        root=resolved_root,
    )

    return {
        "kind": kind,
        "status": pipeline_result["status"],
        "voice_command": pipeline_result["voice_command"],
        "wakeword": pipeline_result["wakeword"],
        "risk": pipeline_result["risk"],
        "policy": policy,
        "runtime_policy_validation": runtime_policy_validation,
        "speaker_guard": {
            "score": speaker_score,
            "gate": speaker_gate,
        },
        "feedback": pipeline_result["feedback"],
        "routed": bool(route_result and route_result.get("routed")),
        "route_preview": route_preview,
        "route_result": route_result,
        "approval_flow": approval_flow,
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
    parser.add_argument("--route-execute", action="store_true", help="Dispatch matched routes through bounded gateways")
    args = parser.parse_args()

    result = handle_voice_command(
        args.raw_transcript,
        voice_session_id=args.voice_session_id,
        actor=args.actor,
        lane=args.lane,
        task_id=args.task_id,
        speaker_confidence=args.speaker_confidence,
        route=args.route,
        route_execute=args.route_execute,
        root=Path(args.root).resolve(),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
