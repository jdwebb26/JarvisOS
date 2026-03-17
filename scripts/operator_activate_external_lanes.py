#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.integrations.autoresearch_adapter import probe_autoresearch_upstream_runtime
from runtime.integrations.hermes_adapter import probe_hermes_runtime
from runtime.integrations.lane_activation import (
    record_lane_activation_attempt,
    record_lane_activation_result,
    summarize_lane_activation,
)
from runtime.integrations.research_backends import get_research_backend
from runtime.integrations.shadowbroker_adapter import fetch_shadowbroker_snapshot, validate_shadowbroker_runtime
from runtime.core.status import build_extension_lane_status_summary
from runtime.adaptation_lab.summary import summarize_adaptation_lab
from runtime.browser.reporting import build_browser_action_summary
from runtime.core.a2a_policy import build_a2a_policy_summary
from runtime.integrations.autoresearch_adapter import build_autoresearch_summary
from runtime.integrations.hermes_adapter import build_hermes_summary
from runtime.integrations.research_backends import build_research_backend_summary
from runtime.integrations.shadowbroker_adapter import summarize_shadowbroker_backend
from runtime.optimizer.eval_gate import summarize_optimizer_lane
from runtime.world_ops.summary import build_world_ops_summary


def _shadowbroker(root: Path) -> dict:
    runtime = validate_shadowbroker_runtime()
    endpoint = str(runtime.get("base_url") or "")
    attempt = record_lane_activation_attempt(lane="shadowbroker", command_or_endpoint=endpoint, root=root)
    if not runtime.get("configured"):
        return record_lane_activation_result(
            activation_run_id=attempt["activation_run_id"],
            lane="shadowbroker",
            status="blocked",
            runtime_status=str(runtime.get("status") or "blocked_shadowbroker_not_configured"),
            configured=False,
            healthy=False,
            command_or_endpoint=endpoint,
            details=str(runtime.get("reason") or ""),
            operator_action_required="Set ShadowBroker env/config and rerun activation.",
            root=root,
        )
    result = fetch_shadowbroker_snapshot(feed_id="shadowbroker_activation", actor="operator_activation", lane="operator_activation", root=root)
    snapshot = dict(result.get("snapshot") or {})
    evidence_ref = dict(snapshot.get("evidence_bundle_ref") or {})
    if result.get("ok"):
        return record_lane_activation_result(
            activation_run_id=attempt["activation_run_id"],
            lane="shadowbroker",
            status="completed",
            runtime_status=str(result.get("backend_status") or "healthy"),
            configured=True,
            healthy=True,
            command_or_endpoint=endpoint,
            evidence_refs={
                "snapshot_id": snapshot.get("snapshot_id"),
                "evidence_bundle_ref": evidence_ref,
            },
            details=str(result.get("fetch_latency_ms") or ""),
            operator_action_required="",
            root=root,
        )
    return record_lane_activation_result(
        activation_run_id=attempt["activation_run_id"],
        lane="shadowbroker",
        status="degraded",
        runtime_status=str(result.get("backend_status") or "degraded_shadowbroker_unreachable"),
        configured=True,
        healthy=False,
        command_or_endpoint=endpoint,
        error=str(result.get("degraded_reason") or ""),
        details=str((result.get("health") or {}).get("degraded_reason") or ""),
        operator_action_required="Inspect the external ShadowBroker service and snapshot payload.",
        root=root,
    )


def _searxng(root: Path) -> dict:
    backend = get_research_backend("searxng", root=root)
    health = backend.healthcheck()
    endpoint = str(health.get("configured_url") or "")
    attempt = record_lane_activation_attempt(lane="searxng", command_or_endpoint=endpoint, root=root)
    configured = bool(endpoint)
    healthy = bool(health.get("healthy"))
    if not configured:
        return record_lane_activation_result(
            activation_run_id=attempt["activation_run_id"],
            lane="searxng",
            status="blocked",
            runtime_status="blocked_searxng_not_configured",
            configured=False,
            healthy=False,
            command_or_endpoint="",
            details=str(health.get("details") or ""),
            operator_action_required="Set JARVIS_SEARXNG_URL and rerun activation.",
            root=root,
        )
    return record_lane_activation_result(
        activation_run_id=attempt["activation_run_id"],
        lane="searxng",
        status="completed" if healthy else "degraded",
        runtime_status=str(health.get("status") or ("healthy" if healthy else "unreachable")),
        configured=True,
        healthy=healthy,
        command_or_endpoint=endpoint,
        details=str(health.get("details") or ""),
        operator_action_required="" if healthy else "Inspect the configured SearXNG endpoint and health path.",
        root=root,
    )


def _hermes(root: Path) -> dict:
    probe = probe_hermes_runtime(root=root)
    command = " ".join(probe.get("command") or [])
    attempt = record_lane_activation_attempt(lane="hermes_bridge", command_or_endpoint=command, root=root)
    status = "completed" if probe.get("healthy") else ("blocked" if not probe.get("configured") else "degraded")
    return record_lane_activation_result(
        activation_run_id=attempt["activation_run_id"],
        lane="hermes_bridge",
        status=status,
        runtime_status=str(probe.get("runtime_status") or ("healthy" if probe.get("healthy") else "blocked_hermes_not_configured")),
        configured=bool(probe.get("configured")),
        healthy=bool(probe.get("healthy")),
        command_or_endpoint=command,
        evidence_refs={
            "request_path": probe.get("request_path"),
            "result_path": probe.get("result_path"),
        },
        error="" if probe.get("healthy") else str(probe.get("details") or ""),
        details=str(probe.get("details") or ""),
        operator_action_required="" if probe.get("healthy") else "Configure a Hermes bridge command that supports Jarvis healthcheck mode.",
        root=root,
    )


def _autoresearch(root: Path) -> dict:
    probe = probe_autoresearch_upstream_runtime(root=root)
    command = " ".join(probe.get("command") or [])
    attempt = record_lane_activation_attempt(lane="autoresearch_upstream_bridge", command_or_endpoint=command, root=root)
    status = "completed" if probe.get("healthy") else ("blocked" if not probe.get("configured") else "degraded")
    return record_lane_activation_result(
        activation_run_id=attempt["activation_run_id"],
        lane="autoresearch_upstream_bridge",
        status=status,
        runtime_status=str(probe.get("runtime_status") or ("healthy" if probe.get("healthy") else "blocked_upstream_not_configured")),
        configured=bool(probe.get("configured")),
        healthy=bool(probe.get("healthy")),
        command_or_endpoint=command,
        evidence_refs={
            "request_path": probe.get("request_path"),
            "result_path": probe.get("result_path"),
        },
        error="" if probe.get("healthy") else str(probe.get("details") or ""),
        details=str(probe.get("details") or ""),
        operator_action_required="" if probe.get("healthy") else "Configure a working autoresearch upstream command and rerun activation.",
        root=root,
    )


def _extension_summary(root: Path) -> dict:
    return build_extension_lane_status_summary(
        shadowbroker_summary=summarize_shadowbroker_backend(root=root),
        world_ops_summary=build_world_ops_summary(root=root),
        autoresearch_summary=build_autoresearch_summary(root=root),
        adaptation_lab_summary=summarize_adaptation_lab(root=root),
        optimizer_summary=summarize_optimizer_lane(root=root),
        hermes_summary=build_hermes_summary(root=root),
        research_backend_summary=build_research_backend_summary(root=root),
        browser_action_summary=build_browser_action_summary(root=root),
        a2a_policy_summary=build_a2a_policy_summary(root=root),
    )


def activate_external_lanes(*, root: Path) -> dict:
    results = [
        _shadowbroker(root),
        _searxng(root),
        _hermes(root),
        _autoresearch(root),
    ]
    summary = summarize_lane_activation(root=root, extension_lane_status_summary=_extension_summary(root))
    return {"ok": True, "results": results, "lane_activation_summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe and record external lane activation state.")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    result = activate_external_lanes(root=Path(args.root).resolve())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
