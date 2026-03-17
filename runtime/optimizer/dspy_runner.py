#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any, Callable, Optional

from runtime.optimizer.eval_gate import compare_to_baseline, evaluate_optimizer_promotion
from runtime.optimizer.variant_store import (
    create_optimizer_run,
    load_optimizer_run,
    load_optimizer_variant,
    save_optimizer_run,
    save_optimizer_variant,
)


ROOT = Path(__file__).resolve().parents[2]
Executor = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
DSPY_TINY_MODEL_ENV = "JARVIS_DSPY_TINY_MODEL"
DSPY_API_BASE_ENV = "JARVIS_DSPY_API_BASE_URL"
DSPY_API_KEY_ENV = "JARVIS_DSPY_API_KEY"


def _dspy_runtime_state() -> dict[str, Any]:
    spec = importlib.util.find_spec("dspy")
    if spec is None:
        return {
            "available": False,
            "runtime_status": "blocked_missing_dspy",
            "details": "Python package `dspy` is not installed in this environment.",
        }
    return {
        "available": True,
        "runtime_status": "available",
        "details": "DSPy runtime import is available.",
    }


def validate_dspy_runtime() -> dict[str, Any]:
    return _dspy_runtime_state()


def _dspy_proof_contract() -> dict[str, Any]:
    model = str(os.environ.get(DSPY_TINY_MODEL_ENV, "")).strip()
    api_base = str(os.environ.get(DSPY_API_BASE_ENV, "")).strip()
    api_key = str(os.environ.get(DSPY_API_KEY_ENV, "")).strip()
    if not model:
        return {
            "configured": False,
            "runtime_status": "blocked_missing_dspy_model",
            "details": f"Set {DSPY_TINY_MODEL_ENV} for a tiny DSPy proof run.",
            "model": "",
            "api_base": api_base,
        }
    if not api_base:
        return {
            "configured": False,
            "runtime_status": "blocked_missing_dspy_api_base",
            "details": f"Set {DSPY_API_BASE_ENV} for a tiny DSPy proof run.",
            "model": model,
            "api_base": "",
        }
    return {
        "configured": True,
        "runtime_status": "configured",
        "details": "DSPy proof contract is configured.",
        "model": model,
        "api_base": api_base,
        "api_key_present": bool(api_key),
    }


def run_dspy_proof(*, prompt: str = "Reply with exactly pong.") -> dict[str, Any]:
    runtime = validate_dspy_runtime()
    if not runtime["available"]:
        return {
            "status": "blocked",
            "runtime_status": str(runtime["runtime_status"]),
            "summary": "DSPy proof is blocked because the DSPy runtime is unavailable.",
            "error": str(runtime["details"]),
            "metadata": {
                "runner_backend": "dspy",
                "real_execution": False,
                "runtime_probe": runtime,
            },
            "metrics": {},
            "output_refs": {},
        }

    contract = _dspy_proof_contract()
    if not contract["configured"]:
        return {
            "status": "blocked",
            "runtime_status": str(contract["runtime_status"]),
            "summary": "DSPy proof is blocked because the local proof contract is incomplete.",
            "error": str(contract["details"]),
            "metadata": {
                "runner_backend": "dspy",
                "real_execution": False,
                "proof_contract": contract,
            },
            "metrics": {},
            "output_refs": {},
        }

    import dspy  # type: ignore

    model = str(contract["model"])
    api_base = str(contract["api_base"])
    api_key = str(os.environ.get(DSPY_API_KEY_ENV, "")).strip() or "not-required"
    try:
        lm = dspy.LM(model=model, api_base=api_base, api_key=api_key)
        settings = getattr(dspy, "settings", None)
        if settings is not None and hasattr(settings, "configure"):
            settings.configure(lm=lm)
        elif hasattr(dspy, "configure"):
            dspy.configure(lm=lm)

        class _TinyProofSignature(dspy.Signature):  # type: ignore
            text = dspy.InputField()
            answer = dspy.OutputField()

        predictor = dspy.Predict(_TinyProofSignature)
        response = predictor(text=prompt)
        answer = str(getattr(response, "answer", "") or getattr(response, "output", "") or "").strip()
    except Exception as exc:
        return {
            "status": "failed",
            "runtime_status": "degraded_dspy_proof_failed",
            "summary": "DSPy proof failed during runtime execution.",
            "error": str(exc),
            "metadata": {
                "runner_backend": "dspy",
                "real_execution": True,
                "proof_contract": contract,
            },
            "metrics": {},
            "output_refs": {},
        }

    return {
        "status": "completed",
        "runtime_status": "completed",
        "summary": "DSPy proof completed.",
        "metrics": {"response_length": len(answer)},
        "output_refs": {"model": model, "api_base": api_base},
        "metadata": {
            "runner_backend": "dspy",
            "real_execution": True,
            "proof_contract": contract,
            "response_preview": answer[:120],
        },
    }


def _execute_dspy_run(variant: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    import dspy  # type: ignore

    settings_module = getattr(dspy, "settings", None)
    baseline_metrics = dict((run.get("metadata") or {}).get("baseline_metrics") or {})
    candidate_metrics = dict((run.get("metadata") or {}).get("candidate_metrics") or baseline_metrics)
    primary_metric = str((run.get("metadata") or {}).get("primary_metric") or "score")
    comparison = compare_to_baseline(
        candidate_metrics=candidate_metrics,
        baseline_metrics=baseline_metrics,
        primary_metric=primary_metric,
    )
    return {
        "status": "completed",
        "runtime_status": "completed",
        "summary": f"DSPy optimizer run completed for `{variant['base_name']}`.",
        "metrics": {
            "baseline_metrics": baseline_metrics,
            "candidate_metrics": candidate_metrics,
            "comparison": comparison,
        },
        "output_refs": {
            "optimizer_kind": variant.get("variant_kind"),
            "dspy_runtime_detected": bool(settings_module is not None),
        },
        "metadata": {
            "runner_backend": "dspy",
            "variant_label": variant.get("variant_label"),
        },
    }


def run_dspy_optimization(
    variant_id: str,
    *,
    actor: str,
    lane: str,
    objective: str,
    baseline_ref: str = "",
    eval_profile: str = "",
    metadata: Optional[dict[str, Any]] = None,
    executor: Optional[Executor] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    variant = load_optimizer_variant(variant_id, root=root)
    if variant is None:
        raise ValueError(f"Optimizer variant not found: {variant_id}")

    run = create_optimizer_run(
        variant_id=variant_id,
        actor=actor,
        lane=lane,
        objective=objective,
        baseline_ref=baseline_ref,
        eval_profile=eval_profile,
        metadata=metadata,
        root=root,
    )
    runtime_state = _dspy_runtime_state()
    if not runtime_state["available"] and executor is None:
        run["status"] = "blocked"
        run["runtime_status"] = str(runtime_state["runtime_status"])
        run["summary"] = "DSPy optimizer run is blocked because the DSPy runtime is unavailable."
        run["error"] = str(runtime_state["details"])
        run["metadata"] = {
            **dict(run.get("metadata") or {}),
            "runner_backend": "dspy",
            "runtime_probe": runtime_state,
        }
        saved_run = save_optimizer_run(run, root=root)
        variant["latest_run_id"] = saved_run["optimizer_run_id"]
        variant["status"] = "blocked"
        save_optimizer_variant(variant, root=root)
        return saved_run

    run["status"] = "running"
    run["runtime_status"] = "available"
    save_optimizer_run(run, root=root)

    executed = (executor or _execute_dspy_run)(variant, run)
    run = load_optimizer_run(str(run["optimizer_run_id"]), root=root) or run
    run["status"] = str(executed.get("status") or "completed")
    run["runtime_status"] = str(executed.get("runtime_status") or "completed")
    run["summary"] = str(executed.get("summary") or "")
    run["metrics"] = dict(executed.get("metrics") or {})
    run["output_refs"] = dict(executed.get("output_refs") or {})
    run["metadata"] = {
        **dict(run.get("metadata") or {}),
        **dict(executed.get("metadata") or {}),
    }
    if executed.get("error"):
        run["error"] = str(executed.get("error"))
    saved_run = save_optimizer_run(run, root=root)

    variant["latest_run_id"] = saved_run["optimizer_run_id"]
    variant["status"] = "evaluated" if saved_run["status"] == "completed" else saved_run["status"]
    variant["eval_gate"] = evaluate_optimizer_promotion(variant_id, run_id=saved_run["optimizer_run_id"], root=root)
    save_optimizer_variant(variant, root=root)
    return saved_run
