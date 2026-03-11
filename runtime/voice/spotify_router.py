#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

from runtime.gateway.spotify_command import handle_spotify_command


ROOT = Path(__file__).resolve().parents[2]


def parse_spotify_voice_command(normalized_command: str) -> dict:
    command = (normalized_command or "").strip()
    lowered = command.lower()

    if not command:
        return {
            "matched": False,
            "intent": "",
            "query": "",
            "target": "spotify",
            "reason": "empty_command",
        }

    if lowered == "play spotify":
        return {
            "matched": True,
            "intent": "play",
            "query": "",
            "target": "spotify",
            "reason": "matched_play_spotify",
        }

    if lowered.startswith("play ") and lowered.endswith(" on spotify"):
        query = command[5 : len(command) - len(" on spotify")].strip()
        if query:
            return {
                "matched": True,
                "intent": "play",
                "query": query,
                "target": "spotify",
                "reason": "matched_play_query_on_spotify",
            }

    if lowered == "pause spotify":
        return {
            "matched": True,
            "intent": "pause",
            "query": "",
            "target": "spotify",
            "reason": "matched_pause_spotify",
        }

    if lowered in {"next song on spotify", "next track on spotify", "skip on spotify"}:
        return {
            "matched": True,
            "intent": "next_track",
            "query": "",
            "target": "spotify",
            "reason": "matched_next_track_spotify",
        }

    if lowered in {"previous song on spotify", "previous track on spotify", "back on spotify"}:
        return {
            "matched": True,
            "intent": "previous_track",
            "query": "",
            "target": "spotify",
            "reason": "matched_previous_track_spotify",
        }

    if lowered == "open spotify":
        return {
            "matched": True,
            "intent": "open_spotify",
            "query": "",
            "target": "spotify",
            "reason": "matched_open_spotify",
        }

    volume_match = re.fullmatch(r"set spotify volume to\s+(.+)", lowered)
    if volume_match:
        query = command[len("set spotify volume to ") :].strip()
        if query:
            return {
                "matched": True,
                "intent": "set_volume",
                "query": query,
                "target": "spotify",
                "reason": "matched_set_volume_spotify",
            }

    return {
        "matched": False,
        "intent": "",
        "query": "",
        "target": "",
        "reason": "no_spotify_match",
    }


def maybe_route_voice_to_spotify(
    normalized_command: str,
    *,
    actor: str,
    lane: str,
    task_id: str = "",
    root=None,
    execute: bool = False,
) -> dict:
    resolved_root = Path(root or ROOT).resolve()
    spotify_command = parse_spotify_voice_command(normalized_command)
    if not spotify_command["matched"]:
        return {
            "matched": False,
            "routed": False,
            "execute": bool(execute),
            "spotify_command": spotify_command,
            "route_reason": spotify_command["reason"],
            "gateway_result": None,
        }

    if not execute:
        return {
            "matched": True,
            "routed": False,
            "execute": False,
            "spotify_command": spotify_command,
            "route_reason": "spotify_route_preview_only",
            "gateway_result": None,
        }

    gateway_result = handle_spotify_command(
        spotify_command["intent"],
        query=spotify_command["query"],
        actor=actor,
        lane=lane,
        task_id=task_id,
        root=resolved_root,
    )
    return {
        "matched": True,
        "routed": True,
        "execute": True,
        "spotify_command": spotify_command,
        "route_reason": "spotify_gateway_invoked",
        "gateway_result": gateway_result,
    }
