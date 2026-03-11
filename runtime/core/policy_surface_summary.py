#!/usr/bin/env python3
from __future__ import annotations


def build_policy_surface_summary(
    *,
    security_validation_summary: dict,
    prompt_caching_policy_summary: dict,
    mcp_policy_summary: dict,
    plugin_policy_summary: dict,
    a2a_policy_summary: dict,
    notification_summary: dict,
    voice_route_capability_summary: dict,
    voice_route_safety_summary: dict,
) -> dict:
    return {
        "security_validation_present": bool(security_validation_summary.get("validation_layer_present")),
        "prompt_caching_policy_present": bool(prompt_caching_policy_summary.get("prompt_caching_policy_present")),
        "mcp_policy_present": bool(mcp_policy_summary.get("mcp_policy_present")),
        "plugin_policy_present": bool(plugin_policy_summary.get("plugin_policy_present")),
        "a2a_policy_present": bool(a2a_policy_summary.get("a2a_policy_present")),
        "notification_capability_present": bool(notification_summary.get("notification_capability_present")),
        "voice_route_capability_present": bool(voice_route_capability_summary.get("voice_route_capability_present")),
        "voice_route_safety_present": bool(voice_route_safety_summary.get("route_safety_present")),
        "notes": [
            "Security validation covers tool output, degradation fallback, and route safety checks.",
            "Prompt caching keeps reusable scaffold material separate from volatile run-time operator context.",
            "MCP, plugin, and A2A surfaces stay bounded by declared scopes, capabilities, and authenticated access posture.",
            "Notification delivery remains stubbed and bounded while voice routing stays preview-first unless explicit execution is requested.",
            "Known unsafe matched routes stay blocked before gateway dispatch.",
        ],
    }
