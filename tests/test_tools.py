from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_required_scripts_exist():
    required = [
        "scripts/install.sh",
        "scripts/bootstrap.py",
        "scripts/generate_config.py",
        "scripts/validate.py",
        "scripts/doctor.py",
        "scripts/smoke_test.py",
    ]

    for rel in required:
        path = ROOT / rel
        assert path.exists(), f"Missing required script: {rel}"
        assert path.stat().st_size > 0, f"Script is empty: {rel}"


def test_qwen_runtime_core_slice_exists():
    required = [
        "runtime/core/qwen_agent_smoke.py",
        "runtime/core/qwen_task_adapter.py",
        "runtime/core/qwen_live_bridge.py",
        "runtime/core/qwen_live_worker.py",
        "runtime/core/qwen_live_recommender.py",
        "runtime/core/qwen_patch_planner.py",
        "runtime/core/qwen_patch_executor.py",
        "runtime/core/qwen_write_gate_check.py",
        "runtime/core/qwen_write_executor.py",
        "runtime/core/qwen_candidate_writer.py",
        "runtime/core/qwen_candidate_applier.py",
    ]

    for rel in required:
        path = ROOT / rel
        assert path.exists(), f"Missing runtime/core file: {rel}"
        assert path.stat().st_size > 0, f"Runtime/core file is empty: {rel}"


def test_approval_state_files_exist():
    required = [
        "runtime/core/qwen_approval_state.json",
        "runtime/core/qwen_write_gate.json",
        "runtime/core/qwen_live_state.json",
    ]

    for rel in required:
        path = ROOT / rel
        assert path.exists(), f"Missing state file: {rel}"


def test_flowstate_docs_keep_promotion_gated():
    path = ROOT / "docs" / "flowstate.md"
    assert path.exists(), "docs/flowstate.md should exist"
    text = path.read_text(encoding="utf-8")

    assert "Promotion requires explicit approval" in text
    assert "no silent promotion" in text


def test_readme_keeps_chat_first_rule():
    path = ROOT / "README.md"
    assert path.exists(), "README.md should exist"
    text = path.read_text(encoding="utf-8")

    assert "Ordinary chat in `#jarvis` must not silently enqueue work." in text
    assert "Explicit task creation remains supported." in text
