from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.plugin_policy import (
    build_plugin_policy_summary,
    enforce_plugin_runtime_request,
    validate_plugin_activation_request,
    validate_plugin_descriptor,
)


def test_descriptor_with_capabilities_scopes_approval_reversible_and_portability_passes() -> None:
    result = validate_plugin_descriptor(
        plugin_id="portable_skill_pack",
        plugin_kind="plugin",
        declared_capabilities=["search_docs", "review_candidate"],
        declared_scopes=["read:docs", "read:artifacts"],
        approval_required=True,
        reversible=True,
        portability_mode="portable",
    )
    assert result["allowed"] is True
    assert result["findings"] == []


def test_missing_declared_capabilities_is_flagged() -> None:
    result = validate_plugin_descriptor(
        plugin_id="bad_plugin",
        plugin_kind="plugin",
        declared_capabilities=[],
        declared_scopes=["read:docs"],
        portability_mode="repo_local",
    )
    assert result["allowed"] is False
    assert "missing_declared_capabilities" in result["findings"]


def test_missing_declared_scopes_is_flagged() -> None:
    result = validate_plugin_descriptor(
        plugin_id="bad_plugin",
        plugin_kind="plugin",
        declared_capabilities=["search_docs"],
        declared_scopes=[],
        portability_mode="repo_local",
    )
    assert result["allowed"] is False
    assert "missing_declared_scopes" in result["findings"]


def test_approval_required_false_is_flagged() -> None:
    result = validate_plugin_descriptor(
        plugin_id="unsafe_plugin",
        plugin_kind="plugin",
        declared_capabilities=["search_docs"],
        declared_scopes=["read:docs"],
        approval_required=False,
        portability_mode="portable",
    )
    assert result["allowed"] is False
    assert "approval_not_required" in result["findings"]


def test_reversible_false_is_flagged() -> None:
    result = validate_plugin_descriptor(
        plugin_id="unsafe_plugin",
        plugin_kind="plugin",
        declared_capabilities=["search_docs"],
        declared_scopes=["read:docs"],
        reversible=False,
        portability_mode="portable",
    )
    assert result["allowed"] is False
    assert "irreversible_plugin_posture" in result["findings"]


def test_missing_or_unknown_portability_mode_is_flagged() -> None:
    missing = validate_plugin_descriptor(
        plugin_id="missing_mode",
        plugin_kind="plugin",
        declared_capabilities=["search_docs"],
        declared_scopes=["read:docs"],
        portability_mode="",
    )
    unknown = validate_plugin_descriptor(
        plugin_id="unknown_mode",
        plugin_kind="plugin",
        declared_capabilities=["search_docs"],
        declared_scopes=["read:docs"],
        portability_mode="internet_global",
    )
    assert "missing_portability_mode" in missing["findings"]
    assert "unknown_portability_mode" in unknown["findings"]


def test_activation_without_operator_approval_is_flagged() -> None:
    result = validate_plugin_activation_request(
        plugin_id="plugin_one",
        requested_capability="search_docs",
        requested_scope="read:docs",
        operator_approved=False,
    )
    assert result["allowed"] is False
    assert "missing_operator_approval" in result["findings"]


def test_activation_with_empty_scope_is_flagged() -> None:
    result = validate_plugin_activation_request(
        plugin_id="plugin_one",
        requested_capability="search_docs",
        requested_scope="",
        operator_approved=True,
    )
    assert result["allowed"] is False
    assert "missing_requested_scope" in result["findings"]


def test_suspicious_capability_name_is_flagged() -> None:
    result = validate_plugin_activation_request(
        plugin_id="plugin_one",
        requested_capability="secret_dump_exfiltrate",
        requested_scope="read:secret",
        operator_approved=True,
    )
    assert result["allowed"] is False
    assert "suspicious_capability_name" in result["findings"]


def test_runtime_request_is_fail_closed_without_approval_scope_and_descriptor() -> None:
    result = enforce_plugin_runtime_request(
        plugin_id="voice_runtime_plugin",
        plugin_kind="plugin",
        requested_capability="plugin install secret bundle",
        requested_scope="",
        operator_approved=False,
        reversible=True,
        portability_mode="runtime_local",
        declared_capabilities=[],
        declared_scopes=[],
        approval_required=True,
    )
    assert result["allowed"] is False
    assert "missing_declared_capabilities" in result["findings"]
    assert "missing_operator_approval" in result["findings"]
    assert result["reason"] == "plugin_runtime_request_blocked"


def test_summary_builds_cleanly() -> None:
    result = build_plugin_policy_summary(root=ROOT)
    assert result["plugin_policy_present"] is True
    assert "descriptor_portability_mode" in result["supported_checks"]
    assert result["safe_defaults"]["approval_required"] is True


if __name__ == "__main__":
    test_descriptor_with_capabilities_scopes_approval_reversible_and_portability_passes()
    test_missing_declared_capabilities_is_flagged()
    test_missing_declared_scopes_is_flagged()
    test_approval_required_false_is_flagged()
    test_reversible_false_is_flagged()
    test_missing_or_unknown_portability_mode_is_flagged()
    test_activation_without_operator_approval_is_flagged()
    test_activation_with_empty_scope_is_flagged()
    test_suspicious_capability_name_is_flagged()
    test_runtime_request_is_fail_closed_without_approval_scope_and_descriptor()
    test_summary_builds_cleanly()
