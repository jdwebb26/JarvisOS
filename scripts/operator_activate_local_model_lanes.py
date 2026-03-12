#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.adaptation_lab.runner import UNSLOTH_TINY_MODEL_ENV, run_unsloth_proof
from runtime.integrations.lane_activation import (
    record_lane_activation_attempt,
    record_lane_activation_result,
    summarize_lane_activation,
)
from runtime.optimizer.dspy_runner import DSPY_API_BASE_ENV, DSPY_TINY_MODEL_ENV, run_dspy_proof
from runtime.core.status import build_extension_lane_status_summary, build_local_model_lane_proof_summary
from runtime.adaptation_lab.summary import summarize_adaptation_lab
from runtime.browser.reporting import build_browser_action_summary
from runtime.core.a2a_policy import build_a2a_policy_summary
from runtime.integrations.autoresearch_adapter import build_autoresearch_summary
from runtime.integrations.hermes_adapter import build_hermes_summary
from runtime.integrations.research_backends import build_research_backend_summary
from runtime.integrations.shadowbroker_adapter import summarize_shadowbroker_backend
from runtime.optimizer.eval_gate import summarize_optimizer_lane
from runtime.world_ops.summary import build_world_ops_summary


def _unsloth(root: Path) -> dict:
    command = "run_unsloth_proof"
    attempt = record_lane_activation_attempt(lane="adaptation_lab_unsloth", command_or_endpoint=command, root=root)
    result = run_unsloth_proof(root=root)
    status = str(result.get("status") or "failed")
    runtime_status = str(result.get("runtime_status") or "unknown")
    healthy = status == "completed" and runtime_status == "completed"
    metadata = dict(result.get("metadata") or {})
    output_refs = dict(result.get("output_refs") or {})
    return record_lane_activation_result(
        activation_run_id=attempt["activation_run_id"],
        lane="adaptation_lab_unsloth",
        status=status,
        runtime_status=runtime_status,
        configured=runtime_status != "blocked_missing_unsloth_tiny_model",
        healthy=healthy,
        command_or_endpoint=command,
        evidence_refs={
            "proof_dataset_id": metadata.get("proof_dataset_id"),
            "proof_job_id": metadata.get("proof_job_id"),
            "result_id": result.get("result_id"),
            "output_dir": output_refs.get("output_dir"),
            "run_config_path": output_refs.get("run_config_path"),
            "trainer_metrics_path": output_refs.get("trainer_metrics_path"),
        },
        error=str(result.get("error") or ""),
        details=str(result.get("summary") or ""),
        operator_action_required=(
            ""
            if healthy
            else f"Install/configure Unsloth and set {UNSLOTH_TINY_MODEL_ENV} for a real local proof."
        ),
        root=root,
    )


def _dspy(root: Path) -> dict:
    command = "run_dspy_proof"
    attempt = record_lane_activation_attempt(lane="optimizer_dspy", command_or_endpoint=command, root=root)
    result = run_dspy_proof()
    status = str(result.get("status") or "failed")
    runtime_status = str(result.get("runtime_status") or "unknown")
    healthy = status == "completed" and runtime_status == "completed"
    output_refs = dict(result.get("output_refs") or {})
    return record_lane_activation_result(
        activation_run_id=attempt["activation_run_id"],
        lane="optimizer_dspy",
        status=status,
        runtime_status=runtime_status,
        configured=runtime_status not in {"blocked_missing_dspy_model", "blocked_missing_dspy_api_base", "blocked_missing_dspy"},
        healthy=healthy,
        command_or_endpoint=command,
        evidence_refs={
            "model": output_refs.get("model"),
            "api_base": output_refs.get("api_base"),
        },
        error=str(result.get("error") or ""),
        details=str(result.get("summary") or ""),
        operator_action_required=(
            ""
            if healthy
            else f"Install/configure DSPy and set {DSPY_TINY_MODEL_ENV} plus {DSPY_API_BASE_ENV} for a real local proof."
        ),
        root=root,
    )


def _extension_summary(root: Path) -> dict:
    local_model_lane_proof_summary = build_local_model_lane_proof_summary(root=root)
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
        local_model_lane_proof_summary=local_model_lane_proof_summary,
    )


def activate_local_model_lanes(*, root: Path) -> dict:
    results = [_unsloth(root), _dspy(root)]
    summary = summarize_lane_activation(root=root, extension_lane_status_summary=_extension_summary(root))
    proof_summary = build_local_model_lane_proof_summary(root=root)
    return {
        "ok": True,
        "results": results,
        "local_model_lane_proof_summary": proof_summary,
        "lane_activation_summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run and record local-model proof activation for Unsloth and DSPy lanes.")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    result = activate_local_model_lanes(root=Path(args.root).resolve())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
