#!/usr/bin/env python3
"""Tests for runtime/core/runtime_profiles.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.runtime_profiles import (
    PROFILES,
    PROFILE_NAMES,
    DEFAULT_PROFILE,
    apply_profile_overrides,
    get_active_profile,
    get_profile_definition,
    set_active_profile,
    show_realized_routing,
)


def test_profile_names_complete():
    assert "local_only" in PROFILE_NAMES
    assert "hybrid" in PROFILE_NAMES
    assert "cloud_fast" in PROFILE_NAMES
    assert "cloud_smart" in PROFILE_NAMES
    assert "degraded" in PROFILE_NAMES


def test_default_profile_is_local_only():
    assert DEFAULT_PROFILE == "local_only"


def test_all_profiles_have_description():
    for name, profile in PROFILES.items():
        assert "description" in profile, f"Profile {name} missing description"
        assert len(profile["description"]) > 10


def test_all_profiles_have_agent_overrides():
    for name, profile in PROFILES.items():
        assert "agent_overrides" in profile, f"Profile {name} missing agent_overrides"
        assert isinstance(profile["agent_overrides"], dict)


def test_local_only_has_no_overrides():
    assert PROFILES["local_only"]["agent_overrides"] == {}


def test_hybrid_overrides_jarvis_to_kimi():
    overrides = PROFILES["hybrid"]["agent_overrides"]
    assert "jarvis" in overrides
    assert overrides["jarvis"]["preferred_provider"] == "nvidia"
    assert overrides["jarvis"]["preferred_model"] == "moonshotai/kimi-k2.5"


def test_apply_profile_overrides_local_only():
    base = {
        "jarvis": {"preferred_provider": "qwen", "preferred_model": "Qwen3.5-35B"},
    }
    result = apply_profile_overrides(base, "local_only")
    assert result["jarvis"]["preferred_provider"] == "qwen"


def test_apply_profile_overrides_hybrid():
    base = {
        "jarvis": {"preferred_provider": "qwen", "preferred_model": "Qwen3.5-35B", "allowed_families": ["qwen3.5"]},
        "hal": {"preferred_provider": "qwen", "preferred_model": "Qwen3-Coder-30B"},
    }
    result = apply_profile_overrides(base, "hybrid")
    # Jarvis switches to nvidia/kimi
    assert result["jarvis"]["preferred_provider"] == "nvidia"
    assert result["jarvis"]["preferred_model"] == "moonshotai/kimi-k2.5"
    # HAL stays on local qwen
    assert result["hal"]["preferred_provider"] == "qwen"
    assert result["hal"]["preferred_model"] == "Qwen3-Coder-30B"


def test_apply_profile_overrides_preserves_unoverridden_keys():
    base = {
        "jarvis": {
            "preferred_provider": "qwen",
            "preferred_model": "Qwen3.5-35B",
            "burst_allowed": False,
            "preferred_host_role": "primary",
        },
    }
    result = apply_profile_overrides(base, "hybrid")
    # Original keys not in override are preserved
    assert result["jarvis"]["burst_allowed"] is False
    assert result["jarvis"]["preferred_host_role"] == "primary"
    # Overridden keys are updated
    assert result["jarvis"]["preferred_provider"] == "nvidia"


def test_get_set_active_profile(tmp_path):
    state = set_active_profile("hybrid", root=tmp_path)
    assert state["profile"] == "hybrid"
    assert state["set_by"] == "operator"

    retrieved = get_active_profile(root=tmp_path)
    assert retrieved["profile"] == "hybrid"


def test_set_invalid_profile_raises(tmp_path):
    with pytest.raises(ValueError, match="Unknown profile"):
        set_active_profile("nonexistent_profile", root=tmp_path)


def test_get_profile_definition():
    defn = get_profile_definition("cloud_smart")
    assert "description" in defn
    assert "agent_overrides" in defn
    assert "jarvis" in defn["agent_overrides"]


def test_show_realized_routing():
    result = show_realized_routing()
    assert "active_profile" in result
    assert "agents" in result
    assert "jarvis" in result["agents"]
    jarvis = result["agents"]["jarvis"]
    assert "provider" in jarvis
    assert "model" in jarvis


def test_cloud_fast_overrides_jarvis():
    overrides = PROFILES["cloud_fast"]["agent_overrides"]
    assert "jarvis" in overrides
    assert overrides["jarvis"]["preferred_provider"] == "nvidia"


def test_cloud_smart_overrides_anton():
    overrides = PROFILES["cloud_smart"]["agent_overrides"]
    assert "anton" in overrides
    assert overrides["anton"]["preferred_provider"] == "nvidia"


def test_degraded_reduces_to_small_models():
    overrides = PROFILES["degraded"]["agent_overrides"]
    assert overrides["jarvis"]["preferred_model"] == "Qwen3.5-9B"
    assert overrides["hal"]["preferred_model"] == "Qwen3.5-9B"
