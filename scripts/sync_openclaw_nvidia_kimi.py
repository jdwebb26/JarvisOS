#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROVIDER_ID = "nvidia"
PROVIDER_BASE_URL = "https://integrate.api.nvidia.com/v1"
PROVIDER_API = "openai-completions"
PROVIDER_API_KEY_ENV = "NVIDIA_API_KEY"
MODEL_SLUG = "kimi-k2.5"
MODEL_DISPLAY_NAME = "Kimi 2.5"
MODEL_BACKEND_ID = "moonshotai/kimi-k2.5"
MODEL_REF = f"{PROVIDER_ID}/{MODEL_BACKEND_ID}"


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _backup(path: Path) -> Path:
    backup = path.with_name(f"{path.name}.bak.{_now_stamp()}")
    shutil.copy2(path, backup)
    return backup


def _normalize_models(existing: list[dict[str, Any]], desired: dict[str, Any]) -> list[dict[str, Any]]:
    next_models: list[dict[str, Any]] = []
    matched = False
    desired_id = str(desired.get("id") or "").strip().lower()
    for model in existing:
        model_id = str((model or {}).get("id") or "").strip().lower()
        if model_id == desired_id:
            next_models.append({**model, **desired})
            matched = True
        else:
            next_models.append(model)
    if not matched:
        next_models.insert(0, desired)
    return next_models


def _desired_provider_model() -> dict[str, Any]:
    return {
        "id": MODEL_BACKEND_ID,
        "name": MODEL_DISPLAY_NAME,
        "reasoning": False,
        "input": ["text"],
        "cost": {
            "input": 0,
            "output": 0,
            "cacheRead": 0,
            "cacheWrite": 0,
        },
        "contextWindow": 200000,
        "maxTokens": 8192,
        "api": PROVIDER_API,
    }


def _ensure_provider_block(payload: dict[str, Any]) -> bool:
    changed = False
    providers = payload.setdefault("providers", {})
    provider = dict(providers.get(PROVIDER_ID) or {})
    if provider.get("baseUrl") != PROVIDER_BASE_URL:
        provider["baseUrl"] = PROVIDER_BASE_URL
        changed = True
    if provider.get("api") != PROVIDER_API:
        provider["api"] = PROVIDER_API
        changed = True
    if provider.get("apiKey") != PROVIDER_API_KEY_ENV:
        provider["apiKey"] = PROVIDER_API_KEY_ENV
        changed = True
    existing_models = list(provider.get("models") or [])
    next_models = _normalize_models(existing_models, _desired_provider_model())
    if next_models != existing_models:
        provider["models"] = next_models
        changed = True
    providers[PROVIDER_ID] = provider
    return changed


def _ensure_openclaw_config(payload: dict[str, Any]) -> bool:
    changed = False
    models = payload.setdefault("models", {})
    providers = models.setdefault("providers", {})
    provider = dict(providers.get(PROVIDER_ID) or {})
    if provider.get("baseUrl") != PROVIDER_BASE_URL:
        provider["baseUrl"] = PROVIDER_BASE_URL
        changed = True
    if provider.get("api") != PROVIDER_API:
        provider["api"] = PROVIDER_API
        changed = True
    if provider.get("apiKey") != PROVIDER_API_KEY_ENV:
        provider["apiKey"] = PROVIDER_API_KEY_ENV
        changed = True
    existing_models = list(provider.get("models") or [])
    next_models = _normalize_models(existing_models, _desired_provider_model())
    if next_models != existing_models:
        provider["models"] = next_models
        changed = True
    providers[PROVIDER_ID] = provider

    agents = payload.setdefault("agents", {})
    defaults = agents.setdefault("defaults", {})
    model_aliases = defaults.setdefault("models", {})
    existing_alias = dict(model_aliases.get(MODEL_REF) or {})
    if existing_alias.get("alias") != MODEL_SLUG:
        model_aliases[MODEL_REF] = {"alias": MODEL_SLUG}
        changed = True
    return changed


def _build_report(*, openclaw_root: Path) -> dict[str, Any]:
    openclaw_config = _load_json(openclaw_root / "openclaw.json")
    jarvis_models = _load_json(openclaw_root / "agents" / "jarvis" / "agent" / "models.json")
    auth_store = _load_json(openclaw_root / "agents" / "jarvis" / "agent" / "auth-profiles.json")

    openclaw_provider = (((openclaw_config.get("models") or {}).get("providers") or {}).get(PROVIDER_ID) or {})
    jarvis_provider = ((jarvis_models.get("providers") or {}).get(PROVIDER_ID) or {})
    jarvis_model_ids = [str(entry.get("id") or "") for entry in list(jarvis_provider.get("models") or [])]
    configured_primary = ""
    for agent in list(((openclaw_config.get("agents") or {}).get("list") or [])):
        if str(agent.get("id") or "") == "jarvis":
            configured_primary = str(((agent.get("model") or {}).get("primary")) or "")
            break

    return {
        "provider_id": PROVIDER_ID,
        "model_slug": MODEL_SLUG,
        "model_ref": MODEL_REF,
        "backend_model_id": MODEL_BACKEND_ID,
        "display_name": MODEL_DISPLAY_NAME,
        "openclaw_provider_present": bool(openclaw_provider),
        "jarvis_provider_present": bool(jarvis_provider),
        "jarvis_model_selectable": MODEL_BACKEND_ID in jarvis_model_ids,
        "jarvis_configured_primary": configured_primary,
        "jarvis_remains_fail_closed": configured_primary == "lmstudio/qwen/qwen3.5-9b",
        "nvidia_env_present": bool(os.environ.get(PROVIDER_API_KEY_ENV, "").strip()),
        "nvidia_auth_profiles_present": [
            profile_id
            for profile_id, entry in dict(auth_store.get("profiles") or {}).items()
            if str((entry or {}).get("provider") or "") == PROVIDER_ID
        ],
        "expected_missing_key_error": f'No API key found for provider "{PROVIDER_ID}".',
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync NVIDIA Kimi 2.5 into live OpenClaw picker files.")
    parser.add_argument(
        "--openclaw-root",
        default=str(Path.home() / ".openclaw"),
        help="OpenClaw home directory",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only inspect current state and print a JSON report.",
    )
    args = parser.parse_args()

    openclaw_root = Path(args.openclaw_root).expanduser().resolve()
    openclaw_config_path = openclaw_root / "openclaw.json"
    jarvis_models_path = openclaw_root / "agents" / "jarvis" / "agent" / "models.json"
    auth_profiles_path = openclaw_root / "agents" / "jarvis" / "agent" / "auth-profiles.json"
    required = [openclaw_config_path, jarvis_models_path, auth_profiles_path]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"Missing required OpenClaw file(s): {', '.join(missing)}")

    if not args.check:
        openclaw_config = _load_json(openclaw_config_path)
        jarvis_models = _load_json(jarvis_models_path)

        openclaw_changed = _ensure_openclaw_config(openclaw_config)
        jarvis_changed = _ensure_provider_block(jarvis_models)

        backups: list[str] = []
        if openclaw_changed:
            backups.append(str(_backup(openclaw_config_path)))
            _write_json(openclaw_config_path, openclaw_config)
        if jarvis_changed:
            backups.append(str(_backup(jarvis_models_path)))
            _write_json(jarvis_models_path, jarvis_models)

        print(json.dumps({"ok": True, "mode": "apply", "backups": backups, "report": _build_report(openclaw_root=openclaw_root)}, indent=2))
        return 0

    print(json.dumps({"ok": True, "mode": "check", "report": _build_report(openclaw_root=openclaw_root)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
