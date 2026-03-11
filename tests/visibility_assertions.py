from __future__ import annotations


def assert_policy_visibility(surface: dict) -> None:
    assert surface["security_validation_summary"]["validation_layer_present"] is True
    assert surface["prompt_caching_policy_summary"]["prompt_caching_policy_present"] is True
    assert surface["mcp_policy_summary"]["mcp_policy_present"] is True
    assert surface["plugin_policy_summary"]["plugin_policy_present"] is True
    assert surface["a2a_policy_summary"]["a2a_policy_present"] is True


def assert_policy_surface_summary(surface: dict) -> None:
    summary = surface["policy_surface_summary"]
    assert summary["security_validation_present"] is True
    assert summary["prompt_caching_policy_present"] is True
    assert summary["mcp_policy_present"] is True
    assert summary["plugin_policy_present"] is True
    assert summary["a2a_policy_present"] is True
    assert summary["notification_capability_present"] is True
    assert summary["voice_route_capability_present"] is True
    assert summary["voice_route_safety_present"] is True
    assert isinstance(summary["notes"], list)
    assert len(summary["notes"]) >= 3


def assert_voice_route_capability_visibility(surface: dict) -> None:
    summary = surface["voice_route_capability_summary"]
    assert summary["voice_route_capability_present"] is True
    assert summary["preview_only_default"] is True
    assert summary["explicit_route_execute"] is True
    assert "browser" in summary["supported_subsystems"]
    assert "spotify" in summary["supported_subsystems"]
    assert "desktop" in summary["supported_subsystems"]
    assert "discord" in summary["supported_subsystems"]
    assert "tradingview" in summary["supported_subsystems"]


def assert_voice_route_safety_visibility(surface: dict) -> None:
    summary = surface["voice_route_safety_summary"]
    assert summary["route_safety_present"] is True
    assert summary["preview_includes_route_safety"] is True
    assert summary["execute_blocks_unsafe_routes"] is True


def assert_notification_visibility(surface: dict) -> None:
    summary = surface["notification_summary"]
    assert summary["notification_capability_present"] is True
    assert summary["stubbed_only"] is True
    assert summary["voice_route_supported"] is True
