from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ALLOWED_MODELS = {
    "Qwen3.5-9B",
    "Qwen3.5-35B",
    "Qwen3.5-122B",
}

DISALLOWED_HINTS = [
    "claude",
    "gpt",
    "gemini",
    "llama",
    "mistral",
    "deepseek",
    "qwen2.5",
    "qwen2-",
]


def _read(rel: str) -> str:
    path = ROOT / rel
    assert path.exists(), f"{rel} should exist"
    return path.read_text(encoding="utf-8", errors="replace")


def test_models_example_is_qwen_only():
    text = _read("config/models.example.yaml")
    lower = text.lower()

    for hint in DISALLOWED_HINTS:
        assert hint not in lower, f"Disallowed model-family hint found in example config: {hint}"

    for model in ALLOWED_MODELS:
        assert model in text, f"Allowed model missing from example config: {model}"


def test_models_live_is_qwen_only():
    text = _read("config/models.yaml")
    lower = text.lower()

    for hint in DISALLOWED_HINTS:
        assert hint not in lower, f"Disallowed model-family hint found in live config: {hint}"

    assert "qwen3.5" in lower, "Live model config should explicitly mention qwen3.5 family"

    found = [m for m in ALLOWED_MODELS if m in text]
    assert found, "At least one allowed Qwen 3.5 model should appear in live config"


def test_policies_example_enforces_qwen_only():
    text = _read("config/policies.example.yaml")
    lower = text.lower()

    assert "qwen_only: true" in lower
    assert "allowed_families" in lower
    assert "qwen3.5" in lower


def test_core_record_defaults_stay_provider_neutral():
    from runtime.core.models import CapabilityProfileRecord, ModelRegistryEntryRecord, TaskRecord, now_iso

    created_at = now_iso()
    task = TaskRecord(
        task_id="task_default_neutral",
        created_at=created_at,
        updated_at=created_at,
        source_lane="tests",
        source_channel="tests",
        source_message_id="msg_default_neutral",
        source_user="tester",
        trigger_type="explicit_task_colon",
        raw_request="task: neutral defaults",
        normalized_request="neutral defaults",
    )
    profile = CapabilityProfileRecord(
        capability_profile_id="cap_default_neutral",
        created_at=created_at,
        updated_at=created_at,
        profile_name="neutral_profile",
        provider_id="provider_x",
        model_family="family_x",
    )
    entry = ModelRegistryEntryRecord(
        model_registry_entry_id="model_default_neutral",
        created_at=created_at,
        updated_at=created_at,
        provider_id="provider_x",
        provider_kind="local",
        model_family="family_x",
        model_name="Model-X",
        display_name="Model-X",
    )

    assert task.assigned_model == "unassigned"
    assert profile.preferred_execution_backend == "unassigned"
    assert entry.default_execution_backend == "unassigned"
