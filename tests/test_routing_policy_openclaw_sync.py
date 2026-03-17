#!/usr/bin/env python3
"""Tests proving routing policy ↔ openclaw.json sync alignment.

Focused proof that the gateway model selection seam (openclaw.json)
matches the authoritative Python routing policy for all agents,
with special attention to Kitt (nvidia/kimi).
"""
from __future__ import annotations

import json
import sys
import tempfile
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sync_routing_policy_to_openclaw import (
    MODEL_NAME_TO_REF,
    compute_sync_plan,
    apply_changes,
    resolve_model_ref,
    resolve_fallback_refs,
)

POLICY_PATH = ROOT / "config" / "runtime_routing_policy.json"
OPENCLAW_JSON = Path.home() / ".openclaw" / "openclaw.json"


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


# --- Unit tests for mapping functions ---

def test_resolve_model_ref_qwen():
    assert resolve_model_ref("Qwen3.5-9B") == "lmstudio/qwen/qwen3.5-9b"
    assert resolve_model_ref("Qwen3.5-35B") == "lmstudio/qwen3.5-35b-a3b"
    assert resolve_model_ref("Qwen3.5-122B") == "lmstudio/qwen3.5-122b-a10b"


def test_resolve_model_ref_kimi():
    ref = resolve_model_ref("moonshotai/kimi-k2.5", "nvidia")
    assert ref == "nvidia/moonshotai/kimi-k2.5"


def test_resolve_fallback_refs():
    refs = resolve_fallback_refs(["Qwen3.5-35B", "Qwen3.5-122B"])
    assert refs == ["lmstudio/qwen3.5-35b-a3b", "lmstudio/qwen3.5-122b-a10b"]


def test_resolve_unknown_model_returns_none():
    assert resolve_model_ref("UnknownModel-99B") is None


# --- Integration: live config alignment ---

@pytest.mark.skipif(not POLICY_PATH.exists(), reason="policy not found")
@pytest.mark.skipif(not OPENCLAW_JSON.exists(), reason="openclaw.json not found")
def test_live_configs_in_sync():
    """After sync, there should be zero divergences."""
    policy = _load(POLICY_PATH)
    openclaw = _load(OPENCLAW_JSON)
    changes = compute_sync_plan(policy, openclaw)
    assert changes == [], f"Divergences found: {json.dumps(changes, indent=2)}"


@pytest.mark.skipif(not OPENCLAW_JSON.exists(), reason="openclaw.json not found")
def test_kitt_gateway_model_is_nvidia_kimi():
    """Kitt's gateway model must be nvidia/moonshotai/kimi-k2.5."""
    openclaw = _load(OPENCLAW_JSON)
    kitt = next(
        (a for a in (openclaw.get("agents") or {}).get("list") or [] if a.get("id") == "kitt"),
        None,
    )
    assert kitt is not None, "Kitt not found in openclaw.json agents.list"
    primary = (kitt.get("model") or {}).get("primary", "")
    assert primary == "nvidia/moonshotai/kimi-k2.5", f"Kitt primary={primary}, expected nvidia/moonshotai/kimi-k2.5"
    fallbacks = (kitt.get("model") or {}).get("fallbacks") or []
    assert "lmstudio/qwen3.5-35b-a3b" in fallbacks, f"Kitt fallbacks={fallbacks} missing qwen3.5-35b"


@pytest.mark.skipif(not OPENCLAW_JSON.exists(), reason="openclaw.json not found")
def test_kitt_nvidia_provider_registered():
    """The nvidia provider must exist in openclaw.json models.providers."""
    openclaw = _load(OPENCLAW_JSON)
    providers = (openclaw.get("models") or {}).get("providers") or {}
    nvidia = providers.get("nvidia")
    assert nvidia is not None, "nvidia provider not registered in openclaw.json"
    assert nvidia.get("baseUrl") == "https://integrate.api.nvidia.com/v1"
    model_ids = [m.get("id") for m in (nvidia.get("models") or [])]
    assert "moonshotai/kimi-k2.5" in model_ids, f"kimi-k2.5 not in nvidia models: {model_ids}"


# --- Synthetic: apply on diverged config ---

def test_apply_fixes_kitt_divergence():
    """Given a pre-sync Kitt config, apply_changes corrects it."""
    policy = {
        "agent_policies": {
            "kitt": {
                "preferred_provider": "nvidia",
                "preferred_model": "moonshotai/kimi-k2.5",
                "allowed_fallbacks": ["Qwen3.5-35B"],
            }
        }
    }
    openclaw = {
        "agents": {
            "list": [
                {
                    "id": "kitt",
                    "model": {
                        "primary": "lmstudio/qwen3.5-35b-a3b",
                        "fallbacks": ["lmstudio/qwen3.5-122b-a10b"],
                    },
                }
            ]
        }
    }
    changes = compute_sync_plan(policy, openclaw)
    assert len(changes) == 2  # primary + fallbacks

    applied = apply_changes(openclaw, changes)
    assert applied == 2

    kitt = openclaw["agents"]["list"][0]
    assert kitt["model"]["primary"] == "nvidia/moonshotai/kimi-k2.5"
    assert kitt["model"]["fallbacks"] == ["lmstudio/qwen3.5-35b-a3b"]

    # Verify idempotent
    changes2 = compute_sync_plan(policy, openclaw)
    assert changes2 == []


@pytest.mark.skipif(not POLICY_PATH.exists(), reason="policy not found")
def test_all_policy_agents_have_valid_model_refs():
    """Every agent in the routing policy must map to a known openclaw model ref."""
    policy = _load(POLICY_PATH)
    for agent_id, ap in policy.get("agent_policies", {}).items():
        preferred = ap.get("preferred_model", "")
        provider = ap.get("preferred_provider", "")
        ref = resolve_model_ref(preferred, provider)
        assert ref is not None, (
            f"Agent {agent_id}: preferred_model={preferred} has no mapping in MODEL_NAME_TO_REF"
        )
        for fb in ap.get("allowed_fallbacks", []):
            fb_ref = resolve_model_ref(fb)
            assert fb_ref is not None, (
                f"Agent {agent_id}: fallback={fb} has no mapping in MODEL_NAME_TO_REF"
            )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
