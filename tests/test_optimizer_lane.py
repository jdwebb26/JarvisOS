#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path

from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.optimizer.dspy_runner import run_dspy_optimization
from runtime.optimizer.eval_gate import evaluate_optimizer_promotion
from runtime.optimizer.variant_store import (
    load_optimizer_run,
    load_optimizer_variant,
    register_optimizer_variant,
)


def test_optimizer_variant_registration_and_visibility(tmp_path: Path) -> None:
    variant = register_optimizer_variant(
        actor="tester",
        lane="optimizer",
        variant_kind="prompt_program",
        base_name="jarvis_prompt",
        variant_label="v2",
        proposal={"prompt": "be more concise"},
        root=tmp_path,
    )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    exported = build_state_export(tmp_path)

    assert variant["metadata"]["promotion_disabled"] is True
    assert status["optimizer_summary"]["variant_summary"]["variant_count"] == 1
    assert snapshot["optimizer_summary"]["variant_summary"]["latest_variant"]["variant_label"] == "v2"
    assert exported["optimizer_summary"]["variant_summary"]["latest_variant"]["base_name"] == "jarvis_prompt"


def test_optimizer_blocks_when_dspy_missing(tmp_path: Path) -> None:
    variant = register_optimizer_variant(
        actor="tester",
        lane="optimizer",
        variant_kind="skill_program",
        base_name="skill_alpha",
        variant_label="candidate_a",
        proposal={"program": "improve chain"},
        root=tmp_path,
    )

    run = run_dspy_optimization(
        variant["variant_id"],
        actor="tester",
        lane="optimizer",
        objective="improve score",
        root=tmp_path,
        executor=None,
    )

    stored_run = load_optimizer_run(run["optimizer_run_id"], root=tmp_path)
    stored_variant = load_optimizer_variant(variant["variant_id"], root=tmp_path)

    assert stored_run is not None
    assert stored_run["status"] == "blocked"
    assert stored_run["runtime_status"] == "blocked_missing_dspy"
    assert stored_variant is not None
    assert stored_variant["status"] == "blocked"


def test_optimizer_mocked_runner_stays_eval_and_operator_gated(tmp_path: Path) -> None:
    variant = register_optimizer_variant(
        actor="tester",
        lane="optimizer",
        variant_kind="prompt_program",
        base_name="jarvis_prompt",
        variant_label="candidate_b",
        proposal={"prompt": "optimize"},
        root=tmp_path,
    )

    run = run_dspy_optimization(
        variant["variant_id"],
        actor="tester",
        lane="optimizer",
        objective="improve score",
        root=tmp_path,
        metadata={
            "baseline_metrics": {"score": 0.55},
            "candidate_metrics": {"score": 0.72},
            "primary_metric": "score",
        },
        executor=lambda _variant, _run: {
            "status": "completed",
            "runtime_status": "completed",
            "summary": "DSPy optimization completed.",
            "metrics": {
                "baseline_metrics": {"score": 0.55},
                "candidate_metrics": {"score": 0.72},
                "comparison": {"primary_metric": "score", "delta_value": 0.17, "improved": True},
            },
            "output_refs": {"artifact": "optimizer://candidate_b"},
            "metadata": {"runner_backend": "dspy"},
        },
    )

    gate = evaluate_optimizer_promotion(variant["variant_id"], run_id=run["optimizer_run_id"], root=tmp_path)
    status = build_status(tmp_path)

    assert run["status"] == "completed"
    assert run["runtime_status"] == "completed"
    assert gate["promotion_allowed"] is False
    assert gate["operator_approval_required"] is True
    assert gate["eval_required"] is True
    assert status["optimizer_summary"]["optimizer_runtime_status_counts"]["completed"] == 1
    assert status["optimizer_summary"]["promotion_disabled"] is True


def _run_tmp(test_fn, name: str) -> None:
    path = Path(name)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    try:
        test_fn(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    _run_tmp(test_optimizer_variant_registration_and_visibility, "tmp_test_optimizer_variant")
    _run_tmp(test_optimizer_blocks_when_dspy_missing, "tmp_test_optimizer_blocked")
    _run_tmp(test_optimizer_mocked_runner_stays_eval_and_operator_gated, "tmp_test_optimizer_success")
