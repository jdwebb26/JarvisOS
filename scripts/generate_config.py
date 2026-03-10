#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.bootstrap import resolve_repo_root


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_MODELS = ["Qwen3.5-9B", "Qwen3.5-35B", "Qwen3.5-122B"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}

    if not path.exists():
        return data

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")

    return data


def write_json_as_yaml(path: Path, payload: dict, force: bool) -> str:
    if path.exists() and path.stat().st_size > 0 and not force:
        return "kept_existing"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return "written"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Jarvis v5 live config files.")
    parser.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        help="Project root path",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Optional .env file path",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing config files",
    )
    args = parser.parse_args()

    root = resolve_repo_root(Path(args.root))
    env_path = Path(args.env_file).expanduser().resolve() if args.env_file else (root / ".env")
    env = parse_env_file(env_path)

    paths = {
        "root": str(root),
        "workspace": str(root / "workspace"),
        "state_dir": str(root / "state"),
        "artifacts_dir": str(root / "state" / "artifacts"),
        "logs_dir": str(root / "state" / "logs"),
    }

    app_payload = {
        "app": {
            "name": "jarvis-v5",
            "version": "0.1.0",
            "environment": env.get("JARVIS_ENVIRONMENT", "dev"),
        },
        "paths": paths,
        "runtime": {
            "chat_first": True,
            "ordinary_chat_creates_tasks": False,
            "explicit_task_creation_enabled": True,
            "validate_first": True,
            "qwen_only": True,
        },
        "features": {
            "heartbeat": env.get("JARVIS_ENABLE_HEARTBEAT", "true").lower() == "true",
            "flowstate": env.get("JARVIS_ENABLE_FLOWSTATE", "true").lower() == "true",
            "dashboard": env.get("JARVIS_ENABLE_DASHBOARD", "true").lower() == "true",
            "approvals": True,
            "review_lanes": True,
        },
        "discord": {
            "enabled": True,
            "guild_id": env.get("DISCORD_GUILD_ID", "REPLACE_ME"),
        },
        "storage": {
            "task_store_backend": "sqlite",
            "events_backend": "sqlite",
            "artifact_index_backend": "json",
        },
    }

    channels_payload = {
        "channels": {
            "jarvis": {
                "discord_id": env.get("DISCORD_CHANNEL_JARVIS", "REPLACE_ME"),
                "purpose": "chat_planning_status_explicit_tasks",
            },
            "tasks": {
                "discord_id": env.get("DISCORD_CHANNEL_TASKS", "REPLACE_ME"),
                "purpose": "durable_task_visibility",
            },
            "outputs": {
                "discord_id": env.get("DISCORD_CHANNEL_OUTPUTS", "REPLACE_ME"),
                "purpose": "approved_final_artifacts",
            },
            "review": {
                "discord_id": env.get("DISCORD_CHANNEL_REVIEW", "REPLACE_ME"),
                "purpose": "concise_approval_decisions",
            },
            "audit": {
                "discord_id": env.get("DISCORD_CHANNEL_AUDIT", "REPLACE_ME"),
                "purpose": "anton_high_stakes_review",
            },
            "code_review": {
                "discord_id": env.get("DISCORD_CHANNEL_CODE_REVIEW", "REPLACE_ME"),
                "purpose": "archimedes_code_review",
            },
            "flowstate": {
                "discord_id": env.get("DISCORD_CHANNEL_FLOWSTATE", "REPLACE_ME"),
                "purpose": "source_ingest_extract_distill_propose",
            },
        }
    }

    models_payload = {
        "models": {
            "router": {
                "family": "qwen3.5",
                "model": env.get("QWEN_ROUTER_MODEL", "Qwen3.5-9B"),
                "base_url": env.get("QWEN_ROUTER_BASE_URL", "http://127.0.0.1:1234/v1"),
                "api_key": env.get("QWEN_ROUTER_API_KEY", "lm-studio"),
            },
            "worker": {
                "family": "qwen3.5",
                "model": env.get("QWEN_WORKER_MODEL", "Qwen3.5-35B"),
                "base_url": env.get("QWEN_WORKER_BASE_URL", "http://127.0.0.1:1234/v1"),
                "api_key": env.get("QWEN_WORKER_API_KEY", "lm-studio"),
            },
            "reviewer": {
                "family": "qwen3.5",
                "model": env.get("QWEN_REVIEWER_MODEL", "Qwen3.5-35B"),
                "base_url": env.get("QWEN_REVIEWER_BASE_URL", "http://127.0.0.1:1234/v1"),
                "api_key": env.get("QWEN_REVIEWER_API_KEY", "lm-studio"),
            },
            "auditor": {
                "family": "qwen3.5",
                "model": env.get("QWEN_AUDITOR_MODEL", "Qwen3.5-122B"),
                "base_url": env.get("QWEN_AUDITOR_BASE_URL", "http://127.0.0.1:1234/v1"),
                "api_key": env.get("QWEN_AUDITOR_API_KEY", "lm-studio"),
            },
        },
        "policy": {
            "qwen_only": True,
            "allowed_models": ALLOWED_MODELS,
        },
    }

    policies_payload = {
        "chat_policy": {
            "chat_first": True,
            "ordinary_chat_creates_tasks": False,
            "explicit_task_triggers": ["task:", "task"],
        },
        "review_policy": {
            "archimedes_required_for": [
                "code",
                "code_review",
                "production_change",
            ],
            "anton_required_for": [
                "risky",
                "deploy",
                "ship",
                "quant",
                "high_stakes",
            ],
        },
        "approval_policy": {
            "require_approval_for": [
                "code_change",
                "flowstate_promotion",
                "deploy",
                "quant",
                "high_stakes_output",
            ]
        },
        "flowstate_policy": {
            "auto_promote": False,
            "allow_memory_write_without_approval": False,
            "allow_task_creation_without_approval": False,
        },
        "model_policy": {
            "qwen_only": True,
            "allowed_families": ["qwen3.5"],
        },
        "storage_policy": {
            "task_store_backend": "sqlite",
            "artifact_index_backend": "json",
            "review_store_backend": "json",
            "approval_store_backend": "json",
        },
    }

    targets = {
        root / "config" / "app.yaml": app_payload,
        root / "config" / "channels.yaml": channels_payload,
        root / "config" / "models.yaml": models_payload,
        root / "config" / "policies.yaml": policies_payload,
    }

    results: dict[str, str] = {}
    for path, payload in targets.items():
        results[str(path.relative_to(root))] = write_json_as_yaml(path, payload, force=args.force)

    report = {
        "ok": True,
        "timestamp_utc": now_iso(),
        "root": str(root),
        "env_file_used": str(env_path),
        "results": results,
    }

    report_path = root / "state" / "logs" / "generate_config_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
