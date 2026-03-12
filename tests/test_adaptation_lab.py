import os
from pathlib import Path
from unittest.mock import patch

from runtime.adaptation_lab.dataset_store import register_adaptation_dataset
from runtime.adaptation_lab.job_store import create_adaptation_job, list_adaptation_jobs, load_adaptation_job
from runtime.adaptation_lab.promotion_policy import evaluate_adaptation_promotion
from runtime.adaptation_lab.runner import (
    UNSLOTH_TINY_MODEL_ENV,
    run_unsloth_job,
    validate_base_model_ref,
    validate_dataset_contract,
    validate_training_contract,
    validate_unsloth_runtime,
)
from runtime.adaptation_lab.summary import summarize_adaptation_lab
from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from scripts.preflight_lib import build_doctor_report


def test_register_adaptation_dataset(tmp_path: Path):
    dataset_path = tmp_path / "datasets" / "sample.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text('{"text": "hello"}\n', encoding="utf-8")
    record = register_adaptation_dataset(
        label="Sample Dataset",
        absolute_path=str(dataset_path.resolve()),
        dataset_kind="instruction_jsonl",
        actor="tester",
        lane="adaptation_lab",
        purpose="bounded_unsloth_test",
        root=tmp_path,
    )
    jobs = list_adaptation_jobs(root=tmp_path)
    assert record["dataset_id"]
    assert record["dataset_kind"] == "instruction_jsonl"
    assert jobs == []


def test_unsloth_job_blocks_when_runtime_requirements_missing(tmp_path: Path):
    dataset_path = tmp_path / "datasets" / "sample.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text('{"text": "hello"}\n', encoding="utf-8")
    dataset = register_adaptation_dataset(
        label="Sample Dataset",
        absolute_path=str(dataset_path.resolve()),
        dataset_kind="instruction_jsonl",
        actor="tester",
        lane="adaptation_lab",
        root=tmp_path,
    )
    job = create_adaptation_job(
        actor="tester",
        lane="adaptation_lab",
        dataset_id=dataset["dataset_id"],
        base_model="qwen/qwen3.5-9b",
        objective="test blocked runtime",
        train_dataset_path=str(dataset_path.resolve()),
        max_steps=4,
        batch_size=1,
        learning_rate=1e-4,
        target_modules=["q_proj", "v_proj"],
        sequence_length=512,
        metadata={"baseline_metrics": {"score": 0.5}, "candidate_metrics": {"score": 0.6}},
        root=tmp_path,
    )
    with patch("runtime.adaptation_lab.runner._unsloth_runtime_state", return_value={"available": False, "runtime_status": "blocked_missing_unsloth", "details": "missing"}):
        result = run_unsloth_job(job["job_id"], root=tmp_path)
    status = build_status(tmp_path)
    assert result["status"] == "blocked"
    assert result["runtime_status"] == "blocked_missing_unsloth"
    assert status["adaptation_lab_summary"]["blocked_job_count"] == 1
    assert job["training_backend"] == "unsloth"
    assert job["train_dataset_path"] == str(dataset_path.resolve())
    runtime_probe = validate_unsloth_runtime()
    assert "runtime_status" in runtime_probe


def test_unsloth_job_mocked_success_path_and_promotion_stays_blocked(tmp_path: Path):
    dataset_path = tmp_path / "datasets" / "sample.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text('{"text": "hello"}\n', encoding="utf-8")
    dataset = register_adaptation_dataset(
        label="Sample Dataset",
        absolute_path=str(dataset_path.resolve()),
        dataset_kind="instruction_jsonl",
        actor="tester",
        lane="adaptation_lab",
        root=tmp_path,
    )
    job = create_adaptation_job(
        actor="tester",
        lane="adaptation_lab",
        dataset_id=dataset["dataset_id"],
        base_model="qwen/qwen3.5-9b",
        objective="mocked adaptation run",
        train_dataset_path=str(dataset_path.resolve()),
        eval_dataset_path="",
        max_steps=4,
        batch_size=1,
        learning_rate=1e-4,
        target_modules=["q_proj", "v_proj"],
        sequence_length=512,
        output_dir=str((tmp_path / "adapter_out").resolve()),
        metadata={"baseline_metrics": {"score": 0.5}, "candidate_metrics": {"score": 0.8}, "primary_metric": "score"},
        root=tmp_path,
    )
    with patch("runtime.adaptation_lab.runner._unsloth_runtime_state", return_value={"available": True, "runtime_status": "available", "details": "ok"}):
        result = run_unsloth_job(
            job["job_id"],
            root=tmp_path,
            executor=lambda _job, _dataset: {
                "status": "completed",
                "runtime_status": "completed",
                "summary": "mocked training completed",
                "metrics": {
                    "baseline_metrics": {"score": 0.5},
                    "candidate_metrics": {"score": 0.8},
                    "comparison": {"primary_metric": "score", "candidate_value": 0.8, "baseline_value": 0.5, "delta": 0.3, "improved": True},
                    "train_metrics": {"train_loss": 0.1},
                    "eval_metrics": {"eval_score": 0.8},
                },
                "output_refs": {
                    "output_dir": str((tmp_path / "adapter_out").resolve()),
                    "run_config_path": str((tmp_path / "adapter_out" / "run_config.json").resolve()),
                    "trainer_metrics_path": str((tmp_path / "adapter_out" / "trainer_metrics.json").resolve()),
                },
                "metadata": {
                    "runner_backend": "unsloth",
                    "training_backend": "unsloth",
                    "train_dataset_path": str(dataset_path.resolve()),
                    "eval_dataset_path": "",
                    "max_steps": 4,
                    "batch_size": 1,
                    "learning_rate": 1e-4,
                    "target_modules": ["q_proj", "v_proj"],
                    "sequence_length": 512,
                },
            },
        )
    stored_job = load_adaptation_job(job["job_id"], root=tmp_path)
    promotion = evaluate_adaptation_promotion(stored_job or {}, result)
    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    doctor_report = build_doctor_report(root=tmp_path)
    assert result["status"] == "completed"
    assert result["metadata"]["runner_backend"] == "unsloth"
    assert result["metadata"]["training_backend"] == "unsloth"
    assert result["metadata"]["dataset_row_count"] == 1
    assert result["metadata"]["base_model_validation"]["allowed"] is True
    assert result["metadata"]["real_execution"] is False
    assert stored_job["latest_result_id"] == result["result_id"]
    assert stored_job["promotion_decision"]["promotion_allowed"] is False
    assert "promotion_disabled" in stored_job["promotion_decision"]["reasons"]
    assert promotion["promotion_allowed"] is False
    assert status["adaptation_lab_summary"]["job_count"] == 1
    assert status["adaptation_lab_summary"]["latest_result"]["result_id"] == result["result_id"]
    assert snapshot["adaptation_lab_summary"]["latest_job"]["job_id"] == job["job_id"]
    assert export_payload["adaptation_lab_summary"]["job_status_counts"]["completed"] == 1
    assert doctor_report["adaptation_lab_summary"]["job_count"] == 1


def test_unsloth_job_real_execution_seam_records_failure_when_runner_cannot_start(tmp_path: Path):
    dataset_path = tmp_path / "datasets" / "sample.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text('{"text": "hello"}\n', encoding="utf-8")
    dataset = register_adaptation_dataset(
        label="Sample Dataset",
        absolute_path=str(dataset_path.resolve()),
        dataset_kind="instruction_jsonl",
        actor="tester",
        lane="adaptation_lab",
        root=tmp_path,
    )
    job = create_adaptation_job(
        actor="tester",
        lane="adaptation_lab",
        dataset_id=dataset["dataset_id"],
        base_model="qwen/qwen3.5-9b",
        objective="real seam failure",
        train_dataset_path=str(dataset_path.resolve()),
        root=tmp_path,
    )
    with patch("runtime.adaptation_lab.runner._unsloth_runtime_state", return_value={"available": True, "runtime_status": "available", "details": "ok"}):
        result = run_unsloth_job(
            job["job_id"],
            root=tmp_path,
            executor=lambda _job, _dataset: (_ for _ in ()).throw(RuntimeError("trainer boot failed")),
        )

    assert result["status"] == "failed"
    assert result["runtime_status"] == "degraded_unsloth_run_failed"
    assert "trainer boot failed" in result["error"]


def test_unsloth_job_blocks_on_invalid_dataset_contract(tmp_path: Path):
    dataset_path = tmp_path / "datasets" / "broken.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text("", encoding="utf-8")
    dataset = register_adaptation_dataset(
        label="Broken Dataset",
        absolute_path=str(dataset_path.resolve()),
        dataset_kind="instruction_jsonl",
        actor="tester",
        lane="adaptation_lab",
        root=tmp_path,
    )
    job = create_adaptation_job(
        actor="tester",
        lane="adaptation_lab",
        dataset_id=dataset["dataset_id"],
        base_model="qwen/qwen3.5-9b",
        objective="invalid dataset contract",
        train_dataset_path=str(dataset_path.resolve()),
        root=tmp_path,
    )
    dataset_validation = validate_dataset_contract(job, dataset)
    training_validation = validate_training_contract(job)
    result = run_unsloth_job(job["job_id"], root=tmp_path)

    assert training_validation["allowed"] is True
    assert dataset_validation["allowed"] is False
    assert result["status"] == "blocked"
    assert result["runtime_status"] == "blocked_invalid_dataset_contract"
    assert "empty" in result["error"]


def test_unsloth_job_blocks_on_invalid_base_model_ref(tmp_path: Path):
    dataset_path = tmp_path / "datasets" / "sample.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text('{"text": "hello"}\n', encoding="utf-8")
    dataset = register_adaptation_dataset(
        label="Sample Dataset",
        absolute_path=str(dataset_path.resolve()),
        dataset_kind="instruction_jsonl",
        actor="tester",
        lane="adaptation_lab",
        root=tmp_path,
    )
    job = create_adaptation_job(
        actor="tester",
        lane="adaptation_lab",
        dataset_id=dataset["dataset_id"],
        base_model="definitely-not-a-valid-model-ref",
        objective="invalid model ref",
        train_dataset_path=str(dataset_path.resolve()),
        root=tmp_path,
    )
    model_validation = validate_base_model_ref(job)
    result = run_unsloth_job(job["job_id"], root=tmp_path)

    assert model_validation["allowed"] is False
    assert result["status"] == "blocked"
    assert result["runtime_status"] == "blocked_invalid_base_model_ref"


def test_unsloth_tiny_real_execution_when_environment_available(tmp_path: Path):
    runtime_probe = validate_unsloth_runtime()
    tiny_model = str(os.environ.get(UNSLOTH_TINY_MODEL_ENV, "")).strip()
    if not runtime_probe.get("available") or not tiny_model:
        return

    dataset_path = tmp_path / "datasets" / "tiny.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text('{"text": "hello world"}\n', encoding="utf-8")
    dataset = register_adaptation_dataset(
        label="Tiny Dataset",
        absolute_path=str(dataset_path.resolve()),
        dataset_kind="instruction_jsonl",
        actor="tester",
        lane="adaptation_lab",
        root=tmp_path,
    )
    output_dir = (tmp_path / "real_unsloth_out").resolve()
    job = create_adaptation_job(
        actor="tester",
        lane="adaptation_lab",
        dataset_id=dataset["dataset_id"],
        base_model="placeholder/base-model",
        objective="tiny real unsloth run",
        train_dataset_path=str(dataset_path.resolve()),
        max_steps=1,
        batch_size=1,
        learning_rate=1e-4,
        sequence_length=128,
        output_dir=str(output_dir),
        metadata={"runtime_base_model_override": tiny_model},
        root=tmp_path,
    )

    result = run_unsloth_job(job["job_id"], root=tmp_path)

    assert result["status"] == "completed"
    assert result["runtime_status"] == "completed"
    assert output_dir.exists()
    assert (output_dir / "run_config.json").exists()
    assert (output_dir / "trainer_metrics.json").exists()
    assert result["metadata"]["real_execution"] is True
    assert result["metadata"]["base_model_validation"]["base_model_ref"] == tiny_model
