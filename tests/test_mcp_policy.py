from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.mcp_policy import (
    build_mcp_policy_summary,
    enforce_mcp_runtime_request,
    validate_mcp_server_config,
    validate_mcp_tool_request,
)


def test_localhost_token_auth_with_tools_and_scopes_passes() -> None:
    result = validate_mcp_server_config(
        server_name="safe_server",
        transport="stdio",
        auth_mode="token",
        declared_tools=["search", "fetch"],
        declared_scopes=["read:docs"],
        localhost_only=True,
    )
    assert result["allowed"] is True
    assert result["findings"] == []


def test_missing_auth_is_flagged() -> None:
    result = validate_mcp_server_config(
        server_name="missing_auth",
        transport="stdio",
        auth_mode="",
        declared_tools=["search"],
        declared_scopes=["read:docs"],
        localhost_only=True,
    )
    assert result["allowed"] is False
    assert "missing_auth" in result["findings"]


def test_non_localhost_posture_is_flagged() -> None:
    result = validate_mcp_server_config(
        server_name="remote_server",
        transport="http",
        auth_mode="token",
        declared_tools=["search"],
        declared_scopes=["read:docs"],
        localhost_only=False,
    )
    assert result["allowed"] is False
    assert "non_localhost_network_posture" in result["findings"]


def test_missing_declared_tools_and_scopes_are_flagged() -> None:
    result = validate_mcp_server_config(
        server_name="underspecified",
        transport="stdio",
        auth_mode="token",
        declared_tools=[],
        declared_scopes=[],
        localhost_only=True,
    )
    assert result["allowed"] is False
    assert "missing_declared_tools" in result["findings"]
    assert "missing_declared_scopes" in result["findings"]


def test_unauthenticated_tool_request_is_flagged() -> None:
    result = validate_mcp_tool_request(
        server_name="safe_server",
        tool_name="search_docs",
        requested_scope="read:docs",
        auth_present=False,
    )
    assert result["allowed"] is False
    assert "unauthenticated_tool_request" in result["findings"]


def test_empty_requested_scope_is_flagged() -> None:
    result = validate_mcp_tool_request(
        server_name="safe_server",
        tool_name="search_docs",
        requested_scope="",
        auth_present=True,
    )
    assert result["allowed"] is False
    assert "missing_requested_scope" in result["findings"]


def test_suspicious_tool_request_is_flagged() -> None:
    result = validate_mcp_tool_request(
        server_name="unsafe_server",
        tool_name="secret_exfiltrate_dump",
        requested_scope="read:secret",
        auth_present=True,
    )
    assert result["allowed"] is False
    assert "dangerous_tool_name" in result["findings"]


def test_runtime_request_is_fail_closed_when_auth_scope_or_declarations_are_missing() -> None:
    result = enforce_mcp_runtime_request(
        server_name="voice_runtime",
        transport="voice_gateway",
        auth_mode="",
        tool_name="open_authenticated_tool",
        requested_scope="",
        auth_present=False,
        declared_tools=[],
        declared_scopes=[],
        localhost_only=True,
    )
    assert result["allowed"] is False
    assert "missing_auth" in result["findings"]
    assert "unauthenticated_tool_request" in result["findings"]
    assert result["reason"] == "mcp_runtime_request_blocked"


def test_summary_builds_cleanly() -> None:
    result = build_mcp_policy_summary(root=ROOT)
    assert result["mcp_policy_present"] is True
    assert "tool_request_auth" in result["supported_checks"]
    assert result["safe_defaults"]["localhost_only"] is True


if __name__ == "__main__":
    test_localhost_token_auth_with_tools_and_scopes_passes()
    test_missing_auth_is_flagged()
    test_non_localhost_posture_is_flagged()
    test_missing_declared_tools_and_scopes_are_flagged()
    test_unauthenticated_tool_request_is_flagged()
    test_empty_requested_scope_is_flagged()
    test_suspicious_tool_request_is_flagged()
    test_runtime_request_is_fail_closed_when_auth_scope_or_declarations_are_missing()
    test_summary_builds_cleanly()
