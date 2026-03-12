from pathlib import Path

from scripts.preflight_lib import validate_runtime_routing_policy_config


def _write_runtime_policy(root: Path, text: str) -> Path:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "runtime_routing_policy.json"
    path.write_text(text, encoding="utf-8")
    return path


def test_preflight_runtime_routing_policy_passes_with_good_policy(tmp_path: Path):
    _write_runtime_policy(
        tmp_path,
        """{
  "schema_version": "v5.2_runtime_routing_v1",
  "defaults": {
    "preferred_provider": "qwen",
    "preferred_host_role": "primary",
    "allowed_host_roles": ["primary"],
    "forbidden_host_roles": ["burst"],
    "burst_allowed": false
  },
  "agent_policies": {
    "jarvis": {
      "preferred_model": "Qwen3.5-9B",
      "allowed_host_roles": ["primary"]
    }
  }
}
""",
    )

    findings = validate_runtime_routing_policy_config(tmp_path)

    assert findings
    assert all(row.status == "pass" for row in findings)
    assert any(row.message == "Runtime routing policy config is valid." for row in findings)


def test_preflight_runtime_routing_policy_fails_on_malformed_json(tmp_path: Path):
    _write_runtime_policy(tmp_path, "{ invalid json")

    findings = validate_runtime_routing_policy_config(tmp_path)

    failed = [row for row in findings if row.status == "fail"]
    assert len(failed) == 1
    assert failed[0].message == "Runtime routing policy config is invalid."
    assert "Invalid runtime routing policy JSON" in failed[0].details


def test_preflight_runtime_routing_policy_fails_on_bad_shape(tmp_path: Path):
    _write_runtime_policy(
        tmp_path,
        """{
  "defaults": {
    "preferred_provider": "qwen",
    "bogus_key": "nope"
  }
}
""",
    )

    findings = validate_runtime_routing_policy_config(tmp_path)

    failed = [row for row in findings if row.status == "fail"]
    assert len(failed) == 1
    assert "unknown keys" in failed[0].details


def test_preflight_runtime_routing_policy_fails_on_unknown_host_role(tmp_path: Path):
    _write_runtime_policy(
        tmp_path,
        """{
  "defaults": {
    "allowed_host_roles": ["primary", "not_a_real_role"]
  }
}
""",
    )

    findings = validate_runtime_routing_policy_config(tmp_path)

    failed = [row for row in findings if row.status == "fail"]
    assert len(failed) == 1
    assert "unknown host roles" in failed[0].details


def test_preflight_runtime_routing_policy_missing_file_uses_defaults(tmp_path: Path):
    findings = validate_runtime_routing_policy_config(tmp_path)

    assert len(findings) == 1
    assert findings[0].status == "pass"
    assert findings[0].message == "Optional runtime routing policy file is absent; built-in routing defaults remain active."


def test_preflight_runtime_routing_policy_fails_when_preferred_model_is_impossible(tmp_path: Path):
    _write_runtime_policy(
        tmp_path,
        """{
  "defaults": {
    "preferred_provider": "qwen",
    "preferred_host_role": "primary",
    "allowed_host_roles": ["primary"],
    "preferred_model": "Missing-Primary-Qwen"
  }
}
""",
    )

    findings = validate_runtime_routing_policy_config(tmp_path)

    failed = [row for row in findings if row.status == "fail"]
    assert len(failed) == 1
    assert "preferred model with no legal candidate" in failed[0].message
    assert "Missing-Primary-Qwen" in failed[0].details


def test_preflight_runtime_routing_policy_fails_when_local_only_has_no_local_candidate(tmp_path: Path):
    _write_runtime_policy(
        tmp_path,
        """{
  "defaults": {
    "preferred_provider": "local",
    "preferred_host_role": "local",
    "allowed_host_roles": ["primary"],
    "local_only": true
  }
}
""",
    )

    findings = validate_runtime_routing_policy_config(tmp_path)

    failed = [row for row in findings if row.status == "fail"]
    assert len(failed) >= 1
    assert any("no legal candidate pool" in row.message for row in failed)


def test_preflight_runtime_routing_policy_fails_when_fallbacks_only_exist_on_forbidden_host_role(tmp_path: Path):
    _write_runtime_policy(
        tmp_path,
        """{
  "defaults": {
    "preferred_provider": "qwen",
    "preferred_host_role": "primary",
    "allowed_host_roles": ["primary"],
    "forbidden_host_roles": ["burst"],
    "allowed_fallbacks": ["Burst-Qwen-35B"]
  },
  "workload_policies": {
    "general": {
      "preferred_model": "Missing-Primary-Qwen",
      "allowed_fallbacks": ["Burst-Qwen-35B"]
    }
  }
}
""",
    )

    findings = validate_runtime_routing_policy_config(tmp_path)

    failed = [row for row in findings if row.status == "fail"]
    assert len(failed) >= 1
    assert any("fallbacks that are not legal candidates" in row.message or "no legal candidate pool" in row.message for row in failed)
