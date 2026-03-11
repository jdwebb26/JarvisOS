#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

from runtime.gateway.desktop_action import handle_desktop_action
from runtime.voice.spotify_router import maybe_route_voice_to_spotify, parse_spotify_voice_command


ROOT = Path(__file__).resolve().parents[2]

_SITE_LIKE_RE = re.compile(
    r"^(https?://\S+|[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?:/\S*)?)$",
    re.IGNORECASE,
)
_SAFE_DESKTOP_APPS = {"discord", "tradingview", "spotify"}
_SAFE_DESKTOP_PATHS = {"downloads", "desktop", "documents"}


def _looks_like_url_or_site(value: str) -> bool:
    candidate = (value or "").strip()
    return bool(candidate and _SITE_LIKE_RE.fullmatch(candidate))


def classify_voice_route(normalized_command: str) -> dict:
    command = (normalized_command or "").strip()
    lowered = command.lower()

    spotify = parse_spotify_voice_command(command)
    if spotify["matched"]:
        return {
            "matched": True,
            "subsystem": "spotify",
            "intent": spotify["intent"],
            "query": spotify["query"],
            "target": spotify["target"],
            "reason": spotify["reason"],
        }

    if lowered == "show status":
        return {
            "matched": True,
            "subsystem": "system",
            "intent": "show_status",
            "query": "",
            "target": "status",
            "reason": "matched_show_status",
        }

    if lowered == "open dashboard":
        return {
            "matched": True,
            "subsystem": "system",
            "intent": "open_dashboard",
            "query": "",
            "target": "dashboard",
            "reason": "matched_open_dashboard",
        }

    if lowered == "read logs":
        return {
            "matched": True,
            "subsystem": "system",
            "intent": "read_logs",
            "query": "",
            "target": "logs",
            "reason": "matched_read_logs",
        }

    if lowered == "recall memory":
        return {
            "matched": True,
            "subsystem": "memory",
            "intent": "recall_memory",
            "query": "",
            "target": "memory",
            "reason": "matched_recall_memory",
        }

    memory_match = re.fullmatch(r"what do you remember about\s+(.+)", command, re.IGNORECASE)
    if memory_match:
        query = memory_match.group(1).strip()
        if query:
            return {
                "matched": True,
                "subsystem": "memory",
                "intent": "recall_memory",
                "query": query,
                "target": "memory",
                    "reason": "matched_memory_query",
                }

    app_open_match = re.fullmatch(r"open\s+([a-z0-9._-]+)", command, re.IGNORECASE)
    if app_open_match:
        target = app_open_match.group(1).strip().lower()
        if target in _SAFE_DESKTOP_APPS:
            return {
                "matched": True,
                "subsystem": "desktop",
                "intent": "open_app",
                "query": "",
                "target": target,
                "reason": "matched_open_desktop_app",
            }
        if target in _SAFE_DESKTOP_PATHS:
            return {
                "matched": True,
                "subsystem": "desktop",
                "intent": "open_path",
                "query": "",
                "target": target,
                "reason": "matched_open_desktop_path",
            }

    focus_match = re.fullmatch(r"focus\s+([a-z0-9._-]+)", command, re.IGNORECASE)
    if focus_match:
        target = focus_match.group(1).strip().lower()
        if target in _SAFE_DESKTOP_APPS:
            return {
                "matched": True,
                "subsystem": "desktop",
                "intent": "focus_window",
                "query": "",
                "target": target,
                "reason": "matched_focus_desktop_app",
            }

    browser_patterns = (
        ("open website ", "navigate_allowlisted_page", "matched_open_website"),
        ("open ", "navigate_allowlisted_page", "matched_open_site"),
        ("inspect ", "inspect_page", "matched_inspect_site"),
    )
    for prefix, intent, reason in browser_patterns:
        if lowered.startswith(prefix):
            target = command[len(prefix) :].strip()
            if _looks_like_url_or_site(target):
                return {
                    "matched": True,
                    "subsystem": "browser",
                    "intent": intent,
                    "query": "",
                    "target": target,
                    "reason": reason,
                }

    return {
        "matched": False,
        "subsystem": "",
        "intent": "",
        "query": "",
        "target": "",
        "reason": "no_voice_route_match",
    }


def maybe_route_voice_command(
    normalized_command: str,
    *,
    actor: str,
    lane: str,
    task_id: str = "",
    root=None,
    execute: bool = False,
) -> dict:
    resolved_root = Path(root or ROOT).resolve()
    route = classify_voice_route(normalized_command)

    if not route["matched"]:
        return {
            "matched": False,
            "routed": False,
            "execute": bool(execute),
            "route": route,
            "route_reason": route["reason"],
            "gateway_result": None,
        }

    if not execute:
        return {
            "matched": True,
            "routed": False,
            "execute": False,
            "route": route,
            "route_reason": "route_preview_only",
            "gateway_result": None,
        }

    if route["subsystem"] == "spotify":
        spotify_result = maybe_route_voice_to_spotify(
            normalized_command,
            actor=actor,
            lane=lane,
            task_id=task_id,
            root=resolved_root,
            execute=True,
        )
        return {
            "matched": True,
            "routed": bool(spotify_result["routed"]),
            "execute": True,
            "route": route,
            "route_reason": spotify_result["route_reason"],
            "gateway_result": spotify_result["gateway_result"],
        }

    if route["subsystem"] == "desktop":
        gateway_result = handle_desktop_action(
            task_id=task_id,
            actor=actor,
            lane=lane,
            action_type=route["intent"],
            target_app=route["target"] if route["intent"] in {"open_app", "focus_window"} else "",
            target_path=route["target"] if route["intent"] == "open_path" else "",
            execute=True,
            root=resolved_root,
        )
        return {
            "matched": True,
            "routed": True,
            "execute": True,
            "route": route,
            "route_reason": "desktop_gateway_invoked",
            "gateway_result": gateway_result,
        }

    return {
        "matched": True,
        "routed": False,
        "execute": True,
        "route": route,
        "route_reason": f"{route['subsystem']}_preview_only_in_slice",
        "gateway_result": None,
    }
