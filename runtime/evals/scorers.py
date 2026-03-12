#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


def build_scorer_catalog() -> list[dict[str, str]]:
    return [
        {
            "scorer": "routing_correctness",
            "status": "stubbed",
            "description": "Checks whether a replay trace stayed aligned with the expected lane/backend policy.",
        },
        {
            "scorer": "no_silent_downgrade",
            "status": "stubbed",
            "description": "Checks whether a replay trace appears to downgrade backend capability without an explicit reason.",
        },
        {
            "scorer": "evidence_completeness",
            "status": "stubbed",
            "description": "Checks whether the trace carries basic evidence/provenance payloads needed for operator review.",
        },
        {
            "scorer": "reroute_behavior",
            "status": "stubbed",
            "description": "Checks whether future reroute metadata is explicit rather than silent.",
        },
    ]


def score_routing_correctness(trace: dict[str, Any]) -> dict[str, Any]:
    payload = dict(trace.get("request_payload") or {})
    passed = bool(trace.get("lane")) and bool(trace.get("execution_backend"))
    return {
        "scorer": "routing_correctness",
        "score": 1.0 if passed else 0.0,
        "passed": passed,
        "status": "stubbed",
        "notes": [
            "Scaffolding-only heuristic. Replace with real routing replay assertions in routing-core tickets."
        ],
        "observed_lane": trace.get("lane"),
        "observed_backend": trace.get("execution_backend"),
        "has_request_payload": bool(payload),
    }


def score_no_silent_downgrade(trace: dict[str, Any]) -> dict[str, Any]:
    response_payload = dict(trace.get("response_payload") or {})
    source_refs = dict(trace.get("source_refs") or {})
    reroute_explicit = bool(source_refs.get("reroute_reason") or response_payload.get("reroute_reason"))
    return {
        "scorer": "no_silent_downgrade",
        "score": 1.0 if (not reroute_explicit or source_refs.get("reroute_reason")) else 0.5,
        "passed": True,
        "status": "stubbed",
        "notes": [
            "Scaffolding-only check. Future routing-core work should compare expected-vs-observed backend quality class."
        ],
        "reroute_explicit": reroute_explicit,
    }


def score_evidence_completeness(trace: dict[str, Any]) -> dict[str, Any]:
    source_refs = dict(trace.get("source_refs") or {})
    evidence_like = bool(trace.get("candidate_artifact_id") or source_refs or trace.get("response_payload"))
    return {
        "scorer": "evidence_completeness",
        "score": 1.0 if evidence_like else 0.0,
        "passed": evidence_like,
        "status": "stubbed",
        "notes": [
            "Scaffolding-only heuristic. Real evidence completeness should become task-type aware later."
        ],
    }


def score_reroute_behavior(trace: dict[str, Any]) -> dict[str, Any]:
    source_refs = dict(trace.get("source_refs") or {})
    reroute_seen = bool(source_refs.get("reroute_reason") or source_refs.get("reroute_from_backend"))
    return {
        "scorer": "reroute_behavior",
        "score": 0.0 if reroute_seen else 1.0,
        "passed": True,
        "status": "stubbed",
        "notes": [
            "Scaffolding-only placeholder. No routing-core reroute execution logic is introduced in this pass."
        ],
        "reroute_seen": reroute_seen,
    }


def run_scaffolding_scorers(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        score_routing_correctness(trace),
        score_no_silent_downgrade(trace),
        score_evidence_completeness(trace),
        score_reroute_behavior(trace),
    ]
