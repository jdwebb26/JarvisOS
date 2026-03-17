"""Tests for the advisory drift and backend-adapter-coverage preflight checks."""
from pathlib import Path
from unittest.mock import patch
import json

from scripts.preflight_lib import (
    check_routing_policy_openclaw_drift,
    check_backend_adapter_coverage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_policy(root: Path, payload: dict) -> Path:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "runtime_routing_policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_openclaw(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _minimal_openclaw(agents: list[dict]) -> dict:
    return {"agents": {"list": agents}}


def _minimal_policy(agent_policies: dict | None = None) -> dict:
    return {
        "schema_version": "v5.2_runtime_routing_v1",
        "defaults": {"preferred_provider": "qwen"},
        "agent_policies": agent_policies or {},
    }


# ---------------------------------------------------------------------------
# check_routing_policy_openclaw_drift
# ---------------------------------------------------------------------------

class TestRoutingPolicyOpenclawDrift:
    def test_skip_when_policy_absent(self, tmp_path: Path):
        findings = check_routing_policy_openclaw_drift(tmp_path)
        assert len(findings) == 1
        assert findings[0].status == "pass"
        assert "skipped" in findings[0].message

    def test_skip_when_openclaw_absent(self, tmp_path: Path):
        _write_policy(tmp_path, _minimal_policy())
        with patch("scripts.preflight_lib.Path.home", return_value=tmp_path / "fake_home"):
            findings = check_routing_policy_openclaw_drift(tmp_path)
        assert len(findings) == 1
        assert findings[0].status == "pass"
        assert "skipped" in findings[0].message

    def test_in_sync_produces_pass(self, tmp_path: Path):
        policy = _minimal_policy({
            "jarvis": {
                "preferred_model": "Qwen3.5-9B",
                "preferred_provider": "qwen",
                "allowed_fallbacks": ["Qwen3.5-35B"],
            },
        })
        openclaw = _minimal_openclaw([{
            "id": "jarvis",
            "model": {
                "primary": "lmstudio/qwen/qwen3.5-9b",
                "fallbacks": ["lmstudio/qwen3.5-35b-a3b"],
            },
        }])
        _write_policy(tmp_path, policy)
        openclaw_path = tmp_path / ".openclaw" / "openclaw.json"
        _write_openclaw(openclaw_path, openclaw)

        with patch("scripts.preflight_lib.Path.home", return_value=tmp_path):
            findings = check_routing_policy_openclaw_drift(tmp_path)

        assert len(findings) == 1
        assert findings[0].status == "pass"
        assert "in sync" in findings[0].message

    def test_drift_detected_produces_warn(self, tmp_path: Path):
        policy = _minimal_policy({
            "jarvis": {
                "preferred_model": "Qwen3.5-35B",
                "preferred_provider": "qwen",
            },
        })
        openclaw = _minimal_openclaw([{
            "id": "jarvis",
            "model": {
                "primary": "lmstudio/qwen/qwen3.5-9b",
                "fallbacks": [],
            },
        }])
        _write_policy(tmp_path, policy)
        openclaw_path = tmp_path / ".openclaw" / "openclaw.json"
        _write_openclaw(openclaw_path, openclaw)

        with patch("scripts.preflight_lib.Path.home", return_value=tmp_path):
            findings = check_routing_policy_openclaw_drift(tmp_path)

        warns = [f for f in findings if f.status == "warn"]
        assert len(warns) >= 1
        assert "jarvis" in warns[0].message
        assert "drift" in warns[0].message.lower()

    def test_multiple_agents_drift(self, tmp_path: Path):
        policy = _minimal_policy({
            "jarvis": {"preferred_model": "Qwen3.5-35B", "preferred_provider": "qwen"},
            "hal": {"preferred_model": "Qwen3.5-122B", "preferred_provider": "qwen"},
        })
        openclaw = _minimal_openclaw([
            {"id": "jarvis", "model": {"primary": "lmstudio/qwen/qwen3.5-9b", "fallbacks": []}},
            {"id": "hal", "model": {"primary": "lmstudio/qwen/qwen3.5-9b", "fallbacks": []}},
        ])
        _write_policy(tmp_path, policy)
        openclaw_path = tmp_path / ".openclaw" / "openclaw.json"
        _write_openclaw(openclaw_path, openclaw)

        with patch("scripts.preflight_lib.Path.home", return_value=tmp_path):
            findings = check_routing_policy_openclaw_drift(tmp_path)

        warns = [f for f in findings if f.status == "warn"]
        assert len(warns) >= 2


# ---------------------------------------------------------------------------
# check_backend_adapter_coverage
# ---------------------------------------------------------------------------

class TestBackendAdapterCoverage:
    def test_skip_when_policy_absent(self, tmp_path: Path):
        findings = check_backend_adapter_coverage(tmp_path)
        assert len(findings) == 1
        assert findings[0].status == "pass"
        assert "skipped" in findings[0].message

    def test_gateway_only_agents_pass(self, tmp_path: Path):
        policy = _minimal_policy({
            "jarvis": {"preferred_provider": "qwen", "preferred_model": "Qwen3.5-9B"},
            "hal": {"preferred_provider": "qwen", "preferred_model": "Qwen3.5-35B"},
        })
        _write_policy(tmp_path, policy)

        findings = check_backend_adapter_coverage(tmp_path)
        assert all(f.status == "pass" for f in findings)

    def test_nvidia_agent_with_wired_adapter_passes(self, tmp_path: Path):
        policy = _minimal_policy({
            "kitt": {"preferred_provider": "nvidia", "preferred_model": "moonshotai/kimi-k2.5"},
        })
        _write_policy(tmp_path, policy)

        findings = check_backend_adapter_coverage(tmp_path)
        assert all(f.status == "pass" for f in findings)
        assert any("All routed" in f.message for f in findings)

    def test_nvidia_agent_without_adapter_warns(self, tmp_path: Path):
        policy = _minimal_policy({
            "kitt": {"preferred_provider": "nvidia", "preferred_model": "moonshotai/kimi-k2.5"},
        })
        _write_policy(tmp_path, policy)

        mock_registry = {"wired": [], "known_unwired": ["nvidia_executor"], "gateway_handled": ["qwen_executor"]}
        with patch("runtime.executor.backend_dispatch.list_registered_backends", return_value=mock_registry):
            findings = check_backend_adapter_coverage(tmp_path)

        warns = [f for f in findings if f.status == "warn"]
        assert len(warns) == 1
        assert "nvidia_executor" in warns[0].message
        assert "kitt" in warns[0].message

    def test_unknown_provider_warns(self, tmp_path: Path):
        policy = _minimal_policy({
            "agent_x": {"preferred_provider": "mystery_provider", "preferred_model": "some-model"},
        })
        _write_policy(tmp_path, policy)

        findings = check_backend_adapter_coverage(tmp_path)
        warns = [f for f in findings if f.status == "warn"]
        assert len(warns) == 1
        assert "mystery_provider" in warns[0].message
        assert "no known Python-track backend mapping" in warns[0].message
