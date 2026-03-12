#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Optional

from runtime.adaptation_lab.dataset_store import load_adaptation_dataset
from runtime.adaptation_lab.job_store import load_adaptation_job, record_adaptation_result, update_adaptation_job
from runtime.adaptation_lab.evaluator import compare_to_baseline
from runtime.adaptation_lab.promotion_policy import evaluate_adaptation_promotion


UNSLOTH_TINY_MODEL_ENV = "JARVIS_UNSLOTH_TINY_MODEL"


class AdaptationRuntimeError(RuntimeError):
    def __init__(self, runtime_status: str, message: str, *, category: str = "", metadata: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.runtime_status = runtime_status
        self.category = category
        self.metadata = dict(metadata or {})


def _unsloth_runtime_state() -> dict[str, Any]:
    spec = importlib.util.find_spec("unsloth")
    if spec is None:
        return {
            "available": False,
            "runtime_status": "blocked_missing_unsloth",
            "details": "Python package `unsloth` is not installed in this environment.",
        }
    missing_dependencies: list[str] = []
    for package_name in ("datasets", "transformers", "trl"):
        if importlib.util.find_spec(package_name) is None:
            missing_dependencies.append(package_name)
    if missing_dependencies:
        return {
            "available": False,
            "runtime_status": "blocked_missing_unsloth_dependencies",
            "details": f"Missing required Unsloth runtime dependencies: {', '.join(missing_dependencies)}.",
            "missing_dependencies": missing_dependencies,
        }
    return {
        "available": True,
        "runtime_status": "available",
        "details": "unsloth runtime import is available.",
    }


def validate_unsloth_runtime() -> dict[str, Any]:
    return _unsloth_runtime_state()


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _effective_base_model_ref(job: dict[str, Any]) -> tuple[str, str]:
    metadata = dict(job.get("metadata") or {})
    override = str(metadata.get("runtime_base_model_override") or os.environ.get(UNSLOTH_TINY_MODEL_ENV, "")).strip()
    if override:
        return override, "metadata_or_env_override"
    return str(job.get("base_model") or "").strip(), "job_base_model"


def validate_base_model_ref(job: dict[str, Any]) -> dict[str, Any]:
    base_model_ref, source = _effective_base_model_ref(job)
    if not base_model_ref:
        return {
            "allowed": False,
            "runtime_status": "blocked_invalid_base_model_ref",
            "details": "Base model reference is empty.",
            "base_model_ref": base_model_ref,
            "source": source,
        }
    looks_like_hf_ref = "/" in base_model_ref
    looks_like_local_path = Path(base_model_ref).expanduser().exists()
    if not looks_like_hf_ref and not looks_like_local_path:
        return {
            "allowed": False,
            "runtime_status": "blocked_invalid_base_model_ref",
            "details": f"Base model reference `{base_model_ref}` is not a valid HuggingFace-style ref or local path.",
            "base_model_ref": base_model_ref,
            "source": source,
        }
    return {
        "allowed": True,
        "runtime_status": "valid",
        "details": "Base model reference is structurally valid.",
        "base_model_ref": base_model_ref,
        "source": source,
    }


def validate_dataset_contract(job: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
    train_dataset_path, eval_dataset_path = _resolve_dataset_paths(job, dataset)
    if not train_dataset_path.exists():
        return {
            "allowed": False,
            "runtime_status": "blocked_invalid_dataset_contract",
            "details": f"Train dataset path does not exist: {train_dataset_path}",
            "train_dataset_path": str(train_dataset_path),
            "eval_dataset_path": str(eval_dataset_path) if eval_dataset_path else "",
            "dataset_row_count": 0,
        }
    try:
        train_rows = _load_jsonl_rows(train_dataset_path)
    except Exception as exc:
        return {
            "allowed": False,
            "runtime_status": "blocked_invalid_dataset_contract",
            "details": f"Train dataset could not be parsed as JSONL: {exc}",
            "train_dataset_path": str(train_dataset_path),
            "eval_dataset_path": str(eval_dataset_path) if eval_dataset_path else "",
            "dataset_row_count": 0,
        }
    if not train_rows:
        return {
            "allowed": False,
            "runtime_status": "blocked_invalid_dataset_contract",
            "details": "Train dataset is empty after JSONL normalization.",
            "train_dataset_path": str(train_dataset_path),
            "eval_dataset_path": str(eval_dataset_path) if eval_dataset_path else "",
            "dataset_row_count": 0,
        }
    eval_row_count = 0
    if eval_dataset_path is not None:
        if not eval_dataset_path.exists():
            return {
                "allowed": False,
                "runtime_status": "blocked_invalid_dataset_contract",
                "details": f"Eval dataset path does not exist: {eval_dataset_path}",
                "train_dataset_path": str(train_dataset_path),
                "eval_dataset_path": str(eval_dataset_path),
                "dataset_row_count": len(train_rows),
            }
        try:
            eval_rows = _load_jsonl_rows(eval_dataset_path)
        except Exception as exc:
            return {
                "allowed": False,
                "runtime_status": "blocked_invalid_dataset_contract",
                "details": f"Eval dataset could not be parsed as JSONL: {exc}",
                "train_dataset_path": str(train_dataset_path),
                "eval_dataset_path": str(eval_dataset_path),
                "dataset_row_count": len(train_rows),
            }
        eval_row_count = len(eval_rows)
    return {
        "allowed": True,
        "runtime_status": "valid",
        "details": "Dataset contract is valid.",
        "train_dataset_path": str(train_dataset_path),
        "eval_dataset_path": str(eval_dataset_path) if eval_dataset_path else "",
        "dataset_row_count": len(train_rows),
        "eval_dataset_row_count": eval_row_count,
    }


def validate_training_contract(job: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    if str(job.get("training_backend") or "unsloth") != "unsloth":
        issues.append("training_backend must be `unsloth`")
    if int(job.get("max_steps") or 0) < 1:
        issues.append("max_steps must be >= 1")
    if int(job.get("batch_size") or 0) < 1:
        issues.append("batch_size must be >= 1")
    if float(job.get("learning_rate") or 0.0) <= 0:
        issues.append("learning_rate must be > 0")
    if issues:
        return {
            "allowed": False,
            "runtime_status": "blocked_invalid_dataset_contract",
            "details": "; ".join(issues),
        }
    return {
        "allowed": True,
        "runtime_status": "valid",
        "details": "Training contract is valid.",
    }


def _row_to_text(row: dict[str, Any]) -> str:
    if isinstance(row.get("text"), str) and row["text"].strip():
        return str(row["text"]).strip()
    parts: list[str] = []
    for key in ("instruction", "input", "output", "response", "completion"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{key}: {value.strip()}")
    if parts:
        return "\n".join(parts)
    return json.dumps(row, sort_keys=True)


def _resolve_dataset_paths(job: dict[str, Any], dataset: dict[str, Any]) -> tuple[Path, Optional[Path]]:
    train_path = Path(str(job.get("train_dataset_path") or dataset["absolute_path"])).resolve()
    eval_value = str(job.get("eval_dataset_path") or "").strip()
    eval_path = Path(eval_value).resolve() if eval_value else None
    return train_path, eval_path


def _resolve_output_dir(job: dict[str, Any], dataset: dict[str, Any]) -> Path:
    output_dir = str(job.get("output_dir") or "").strip()
    if not output_dir:
        output_dir = str((Path(dataset["absolute_path"]).resolve().parent / f"{job['job_id']}_output").resolve())
    path = Path(output_dir).resolve()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AdaptationRuntimeError("degraded_output_write_failed", f"Could not create output directory `{path}`: {exc}", category="output_write_failed") from exc
    return path


def _job_run_config(job: dict[str, Any], dataset: dict[str, Any], *, train_dataset_path: Path, eval_dataset_path: Optional[Path], output_dir: Path) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "dataset_id": dataset["dataset_id"],
        "base_model": job["base_model"],
        "adapter_kind": job.get("adapter_kind"),
        "training_backend": job.get("training_backend", "unsloth"),
        "train_dataset_path": str(train_dataset_path),
        "eval_dataset_path": str(eval_dataset_path) if eval_dataset_path else "",
        "output_dir": str(output_dir),
        "max_steps": int(job.get("max_steps") or 8),
        "batch_size": int(job.get("batch_size") or 1),
        "learning_rate": float(job.get("learning_rate") or 2e-4),
        "target_modules": list(job.get("target_modules") or []),
        "sequence_length": job.get("sequence_length"),
        "objective": job.get("objective", ""),
    }


def _execute_unsloth_job(job: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
    from datasets import Dataset  # type: ignore
    from transformers import TrainingArguments  # type: ignore
    from trl import SFTTrainer  # type: ignore
    from unsloth import FastLanguageModel  # type: ignore

    dataset_validation = validate_dataset_contract(job, dataset)
    if not dataset_validation["allowed"]:
        raise AdaptationRuntimeError(
            str(dataset_validation["runtime_status"]),
            str(dataset_validation["details"]),
            category="dataset_contract",
            metadata=dataset_validation,
        )
    train_dataset_path, eval_dataset_path = _resolve_dataset_paths(job, dataset)
    base_model_validation = validate_base_model_ref(job)
    if not base_model_validation["allowed"]:
        raise AdaptationRuntimeError(
            str(base_model_validation["runtime_status"]),
            str(base_model_validation["details"]),
            category="base_model_ref",
            metadata=base_model_validation,
        )

    output_dir = _resolve_output_dir(job, dataset)
    run_config = _job_run_config(
        job,
        dataset,
        train_dataset_path=train_dataset_path,
        eval_dataset_path=eval_dataset_path,
        output_dir=output_dir,
    )
    try:
        (output_dir / "run_config.json").write_text(json.dumps(run_config, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise AdaptationRuntimeError("degraded_output_write_failed", f"Could not write run config: {exc}", category="output_write_failed") from exc

    train_rows = [{"text": _row_to_text(row)} for row in _load_jsonl_rows(train_dataset_path)]
    eval_rows = [{"text": _row_to_text(row)} for row in _load_jsonl_rows(eval_dataset_path)] if eval_dataset_path else []

    max_seq_length = int(job.get("sequence_length") or 1024)
    try:
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=str(base_model_validation["base_model_ref"]),
            max_seq_length=max_seq_length,
            load_in_4bit=True,
        )
    except Exception as exc:
        raise AdaptationRuntimeError("degraded_model_load_failed", f"Unsloth model load failed: {exc}", category="model_load_failed", metadata=base_model_validation) from exc
    target_modules = list(job.get("target_modules") or []) or [
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    ]
    model = FastLanguageModel.get_peft_model(
        model,
        r=8,
        target_modules=target_modules,
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
    )

    train_dataset = Dataset.from_list(train_rows)
    eval_dataset = Dataset.from_list(eval_rows) if eval_rows else None
    try:
        trainer = SFTTrainer(
            model=model,
            tokenizer=tokenizer,
            train_dataset=train_dataset,
            eval_dataset=eval_dataset,
            dataset_text_field="text",
            args=TrainingArguments(
                output_dir=str(output_dir),
                max_steps=int(job.get("max_steps") or 8),
                per_device_train_batch_size=int(job.get("batch_size") or 1),
                learning_rate=float(job.get("learning_rate") or 2e-4),
                logging_steps=1,
                save_strategy="no",
                report_to=[],
            ),
        )
    except Exception as exc:
        raise AdaptationRuntimeError("degraded_trainer_init_failed", f"Unsloth trainer init failed: {exc}", category="trainer_init_failed") from exc
    try:
        train_result = trainer.train()
        eval_metrics = trainer.evaluate() if eval_dataset is not None else {}
        trainer.save_model(str(output_dir))
        tokenizer.save_pretrained(str(output_dir))
    except Exception as exc:
        raise AdaptationRuntimeError("degraded_unsloth_run_failed", f"Unsloth run failed: {exc}", category="unsloth_run_failed") from exc

    train_metrics = dict(getattr(train_result, "metrics", {}) or {})
    baseline_metrics = dict((job.get("metadata") or {}).get("baseline_metrics") or {})
    candidate_metrics = {
        key: float(value)
        for key, value in {**train_metrics, **dict(eval_metrics or {})}.items()
        if isinstance(value, (int, float))
    }
    primary_metric = str((job.get("metadata") or {}).get("primary_metric") or "eval_loss")
    comparison = compare_to_baseline(
        candidate_metrics=candidate_metrics,
        baseline_metrics=baseline_metrics,
        primary_metric=primary_metric,
    )
    trainer_metrics_path = output_dir / "trainer_metrics.json"
    try:
        trainer_metrics_path.write_text(
            json.dumps({"train_metrics": train_metrics, "eval_metrics": dict(eval_metrics or {})}, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise AdaptationRuntimeError("degraded_output_write_failed", f"Could not write trainer metrics: {exc}", category="output_write_failed") from exc
    return {
        "status": "completed",
        "runtime_status": "completed",
        "summary": f"Unsloth adaptation job completed for `{job['base_model']}`.",
        "metrics": {
            "baseline_metrics": baseline_metrics,
            "candidate_metrics": candidate_metrics,
            "comparison": comparison,
            "train_metrics": train_metrics,
            "eval_metrics": dict(eval_metrics or {}),
        },
        "output_refs": {
            "output_dir": str(output_dir),
            "adapter_kind": job.get("adapter_kind"),
            "run_config_path": str(output_dir / "run_config.json"),
            "trainer_metrics_path": str(trainer_metrics_path),
        },
        "metadata": {
            "runner_backend": "unsloth",
            "training_backend": job.get("training_backend", "unsloth"),
            "dataset_path": dataset["absolute_path"],
            "dataset_row_count": int(dataset_validation["dataset_row_count"]),
            "train_dataset_path": str(train_dataset_path),
            "eval_dataset_path": str(eval_dataset_path) if eval_dataset_path else "",
            "max_steps": int(job.get("max_steps") or 8),
            "batch_size": int(job.get("batch_size") or 1),
            "learning_rate": float(job.get("learning_rate") or 2e-4),
            "target_modules": target_modules,
            "sequence_length": max_seq_length,
            "base_model_validation": base_model_validation,
            "real_execution": True,
        },
    }


def run_unsloth_job(job_id: str, *, root: Optional[Path] = None, executor: Any = None) -> dict[str, Any]:
    job = load_adaptation_job(job_id, root=root)
    if job is None:
        raise ValueError(f"Adaptation job not found: {job_id}")
    dataset = load_adaptation_dataset(str(job.get("dataset_id") or ""), root=root)
    if dataset is None:
        return record_adaptation_result(
            job_id=job_id,
            actor=str(job.get("actor") or "adaptation_lab"),
            lane=str(job.get("lane") or "adaptation_lab"),
            status="blocked",
            runtime_status="blocked_missing_dataset",
            summary="Adaptation job is blocked because the dataset record is missing.",
            error="dataset not found",
            root=root,
        )

    training_validation = validate_training_contract(job)
    if not training_validation["allowed"]:
        return record_adaptation_result(
            job_id=job_id,
            actor=str(job.get("actor") or "adaptation_lab"),
            lane=str(job.get("lane") or "adaptation_lab"),
            status="blocked",
            runtime_status=str(training_validation["runtime_status"]),
            summary="Adaptation job is blocked because the training contract is invalid.",
            error=str(training_validation["details"]),
            metadata={"runner_backend": "unsloth", "training_validation": training_validation},
            root=root,
        )

    dataset_validation = validate_dataset_contract(job, dataset)
    if not dataset_validation["allowed"]:
        return record_adaptation_result(
            job_id=job_id,
            actor=str(job.get("actor") or "adaptation_lab"),
            lane=str(job.get("lane") or "adaptation_lab"),
            status="blocked",
            runtime_status=str(dataset_validation["runtime_status"]),
            summary="Adaptation job is blocked because the dataset contract is invalid.",
            error=str(dataset_validation["details"]),
            metadata={"runner_backend": "unsloth", "dataset_validation": dataset_validation},
            root=root,
        )

    base_model_validation = validate_base_model_ref(job)
    if not base_model_validation["allowed"]:
        return record_adaptation_result(
            job_id=job_id,
            actor=str(job.get("actor") or "adaptation_lab"),
            lane=str(job.get("lane") or "adaptation_lab"),
            status="blocked",
            runtime_status=str(base_model_validation["runtime_status"]),
            summary="Adaptation job is blocked because the base model reference is invalid.",
            error=str(base_model_validation["details"]),
            metadata={"runner_backend": "unsloth", "base_model_validation": base_model_validation},
            root=root,
        )

    runtime_state = _unsloth_runtime_state()
    if not runtime_state["available"]:
        return record_adaptation_result(
            job_id=job_id,
            actor=str(job.get("actor") or "adaptation_lab"),
            lane=str(job.get("lane") or "adaptation_lab"),
            status="blocked",
            runtime_status=str(runtime_state["runtime_status"]),
            summary="Adaptation job is blocked because the Unsloth runtime is unavailable.",
            error=str(runtime_state["details"]),
            metadata={
                "runner_backend": "unsloth",
                "runtime_probe": runtime_state,
                "dataset_row_count": int(dataset_validation.get("dataset_row_count", 0)),
                "base_model_validation": base_model_validation,
            },
            root=root,
        )

    update_adaptation_job(job_id, {"status": "running", "runtime_requirement_status": "available"}, root=root)
    try:
        executed = (executor or _execute_unsloth_job)(job, dataset)
    except Exception as exc:
        runtime_status = "degraded_unsloth_run_failed"
        metadata = {
            "runner_backend": "unsloth",
            "training_backend": str(job.get("training_backend") or "unsloth"),
            "dataset_row_count": int(dataset_validation.get("dataset_row_count", 0)),
            "base_model_validation": base_model_validation,
            "real_execution": executor is None,
        }
        if isinstance(exc, AdaptationRuntimeError):
            runtime_status = exc.runtime_status
            metadata.update(dict(exc.metadata))
        result = record_adaptation_result(
            job_id=job_id,
            actor=str(job.get("actor") or "adaptation_lab"),
            lane=str(job.get("lane") or "adaptation_lab"),
            status="failed",
            runtime_status=runtime_status,
            summary="Adaptation job failed during bounded Unsloth execution.",
            error=str(exc),
            metadata=metadata,
            root=root,
        )
        promotion = evaluate_adaptation_promotion(job, result)
        update_adaptation_job(job_id, {"promotion_decision": promotion}, root=root)
        return result
    executed.setdefault("metadata", {})
    executed["metadata"].setdefault("base_model_validation", base_model_validation)
    executed["metadata"].setdefault("dataset_row_count", int(dataset_validation.get("dataset_row_count", 0)))
    executed["metadata"].setdefault("real_execution", executor is None)
    executed["output_refs"].setdefault("output_dir", str(job.get("output_dir") or ""))
    result = record_adaptation_result(
        job_id=job_id,
        actor=str(job.get("actor") or "adaptation_lab"),
        lane=str(job.get("lane") or "adaptation_lab"),
        status=str(executed["status"]),
        runtime_status=str(executed["runtime_status"]),
        summary=str(executed["summary"]),
        metrics=dict(executed.get("metrics") or {}),
        output_refs=dict(executed.get("output_refs") or {}),
        error=str(executed.get("error") or ""),
        metadata=dict(executed.get("metadata") or {}),
        root=root,
    )
    promotion = evaluate_adaptation_promotion(job, result)
    update_adaptation_job(job_id, {"promotion_decision": promotion}, root=root)
    return result
