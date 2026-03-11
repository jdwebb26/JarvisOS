from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.a2a_policy import (
    build_a2a_policy_summary,
    enforce_a2a_runtime_request,
    validate_a2a_request,
    validate_daemon_descriptor,
)


def test_safe_daemon_descriptor_passes() -> None:
    result = validate_daemon_descriptor(
        daemon_name="hermes",
        transport="stdio",
        auth_mode="token",
        declared_actions=["research_task", "checkpoint"],
        declared_scopes=["read:artifacts", "write:candidates"],
        localhost_only=True,
        reversible_sessions=True,
    )
    assert result["allowed"] is True
    assert result["findings"] == []


def test_missing_auth_is_flagged() -> None:
    result = validate_daemon_descriptor(
        daemon_name="hermes",
        transport="stdio",
        auth_mode="",
        declared_actions=["research_task"],
        declared_scopes=["read:artifacts"],
    )
    assert result["allowed"] is False
    assert "missing_auth" in result["findings"]


def test_non_localhost_posture_is_flagged() -> None:
    result = validate_daemon_descriptor(
        daemon_name="hermes",
        transport="http",
        auth_mode="token",
        declared_actions=["research_task"],
        declared_scopes=["read:artifacts"],
        localhost_only=False,
    )
    assert result["allowed"] is False
    assert "non_localhost_network_posture" in result["findings"]


def test_missing_declared_actions_and_scopes_are_flagged() -> None:
    result = validate_daemon_descriptor(
        daemon_name="hermes",
        transport="stdio",
        auth_mode="token",
        declared_actions=[],
        declared_scopes=[],
    )
    assert result["allowed"] is False
    assert "missing_declared_actions" in result["findings"]
    assert "missing_declared_scopes" in result["findings"]


def test_irreversible_daemon_session_posture_is_flagged() -> None:
    result = validate_daemon_descriptor(
        daemon_name="hermes",
        transport="stdio",
        auth_mode="token",
        declared_actions=["research_task"],
        declared_scopes=["read:artifacts"],
        reversible_sessions=False,
    )
    assert result["allowed"] is False
    assert "irreversible_daemon_session_posture" in result["findings"]


def test_unauthenticated_a2a_request_is_flagged() -> None:
    result = validate_a2a_request(
        source_daemon="jarvis",
        target_daemon="hermes",
        action_name="research_task",
        requested_scope="write:candidates",
        auth_present=False,
        session_bound=True,
    )
    assert result["allowed"] is False
    assert "unauthenticated_a2a_request" in result["findings"]


def test_empty_requested_scope_is_flagged() -> None:
    result = validate_a2a_request(
        source_daemon="jarvis",
        target_daemon="hermes",
        action_name="research_task",
        requested_scope="",
        auth_present=True,
        session_bound=True,
    )
    assert result["allowed"] is False
    assert "missing_requested_scope" in result["findings"]


def test_suspicious_action_name_is_flagged() -> None:
    result = validate_a2a_request(
        source_daemon="jarvis",
        target_daemon="hermes",
        action_name="secret_exfiltrate_dump",
        requested_scope="read:secret",
        auth_present=True,
        session_bound=True,
    )
    assert result["allowed"] is False
    assert "dangerous_action_name" in result["findings"]


def test_runtime_request_is_fail_closed_without_auth_scope_or_binding() -> None:
    result = enforce_a2a_runtime_request(
        daemon_name="voice_runtime",
        transport="voice_gateway",
        auth_mode="",
        source_daemon="jarvis",
        target_daemon="unspecified",
        action_name="daemon secret dump",
        requested_scope="",
        auth_present=False,
        session_bound=False,
        declared_actions=[],
        declared_scopes=[],
        localhost_only=True,
        reversible_sessions=True,
    )
    assert result["allowed"] is False
    assert "missing_auth" in result["findings"]
    assert "unauthenticated_a2a_request" in result["findings"]
    assert "unbound_session_posture" in result["findings"]
    assert result["reason"] == "a2a_runtime_request_blocked"


def test_summary_builds_cleanly() -> None:
    result = build_a2a_policy_summary(root=ROOT)
    assert result["a2a_policy_present"] is True
    assert "a2a_request_auth" in result["supported_checks"]
    assert result["safe_defaults"]["localhost_only"] is True


if __name__ == "__main__":
    test_safe_daemon_descriptor_passes()
    test_missing_auth_is_flagged()
    test_non_localhost_posture_is_flagged()
    test_missing_declared_actions_and_scopes_are_flagged()
    test_irreversible_daemon_session_posture_is_flagged()
    test_unauthenticated_a2a_request_is_flagged()
    test_empty_requested_scope_is_flagged()
    test_suspicious_action_name_is_flagged()
    test_runtime_request_is_fail_closed_without_auth_scope_or_binding()
    test_summary_builds_cleanly()
