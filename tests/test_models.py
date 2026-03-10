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
