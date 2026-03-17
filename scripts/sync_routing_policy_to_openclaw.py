#!/usr/bin/env python3
"""Sync runtime_routing_policy.json → openclaw.json agent model configs.

Reads the authoritative routing policy and updates openclaw.json so that
gateway-side model selection matches the Python task-track routing decisions.

Usage:
    python3 scripts/sync_routing_policy_to_openclaw.py           # apply
    python3 scripts/sync_routing_policy_to_openclaw.py --check   # dry-run report
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[1]
OPENCLAW_ROOT = Path.home() / ".openclaw"
POLICY_PATH = ROOT / "config" / "runtime_routing_policy.json"
OPENCLAW_JSON = OPENCLAW_ROOT / "openclaw.json"

# Maps policy preferred_model → openclaw model ref (provider/model_id).
# This is the canonical mapping between the two naming conventions.
MODEL_NAME_TO_REF: dict[str, str] = {
    "Qwen3.5-9B": "lmstudio/qwen/qwen3.5-9b",
    "Qwen3.5-35B": "lmstudio/qwen3.5-35b-a3b",
    "Qwen3.5-122B": "lmstudio/qwen3.5-122b-a10b",
    # Direct model IDs (already in provider/model format)
    "moonshotai/kimi-k2.5": "nvidia/moonshotai/kimi-k2.5",
}

# Reverse: openclaw ref → policy model name (for reporting)
REF_TO_MODEL_NAME = {v: k for k, v in MODEL_NAME_TO_REF.items()}


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


def resolve_model_ref(preferred_model: str, preferred_provider: Optional[str] = None) -> Optional[str]:
    """Map a policy model name to an openclaw model ref."""
    if preferred_model in MODEL_NAME_TO_REF:
        return MODEL_NAME_TO_REF[preferred_model]
    # If the model already looks like a provider/model ref, use provider from policy
    if "/" in preferred_model and preferred_provider:
        return f"{preferred_provider}/{preferred_model}"
    return None


def resolve_fallback_refs(allowed_fallbacks: list[str]) -> list[str]:
    """Map policy fallback names to openclaw model refs."""
    refs = []
    for fb in allowed_fallbacks:
        ref = resolve_model_ref(fb)
        if ref:
            refs.append(ref)
    return refs


def compute_sync_plan(
    policy: dict[str, Any],
    openclaw: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compare policy agent_policies against openclaw agent configs.

    Returns a list of changes needed, each with:
      agent_id, field, current, desired, reason
    """
    agent_policies = policy.get("agent_policies", {})
    agents_list = (openclaw.get("agents") or {}).get("list") or []
    agents_by_id = {str(a.get("id") or ""): a for a in agents_list}

    changes: list[dict[str, Any]] = []

    for agent_id, ap in agent_policies.items():
        agent_cfg = agents_by_id.get(agent_id)
        if not agent_cfg:
            continue  # agent not in openclaw.json — skip

        preferred_model = ap.get("preferred_model", "")
        preferred_provider = ap.get("preferred_provider", "")
        allowed_fallbacks = list(ap.get("allowed_fallbacks") or [])

        # Resolve desired primary
        desired_primary = resolve_model_ref(preferred_model, preferred_provider)
        if not desired_primary:
            continue  # can't map — skip

        # Resolve desired fallbacks
        desired_fallbacks = resolve_fallback_refs(allowed_fallbacks)

        # Current values
        model_cfg = agent_cfg.get("model") or {}
        current_primary = model_cfg.get("primary", "")
        current_fallbacks = list(model_cfg.get("fallbacks") or [])

        if current_primary != desired_primary:
            changes.append({
                "agent_id": agent_id,
                "field": "model.primary",
                "current": current_primary,
                "desired": desired_primary,
                "reason": f"policy preferred_model={preferred_model}, preferred_provider={preferred_provider}",
            })

        if desired_fallbacks and current_fallbacks != desired_fallbacks:
            changes.append({
                "agent_id": agent_id,
                "field": "model.fallbacks",
                "current": current_fallbacks,
                "desired": desired_fallbacks,
                "reason": f"policy allowed_fallbacks={allowed_fallbacks}",
            })

    return changes


def apply_changes(
    openclaw: dict[str, Any],
    changes: list[dict[str, Any]],
) -> int:
    """Apply computed changes to openclaw payload in-place. Returns count applied."""
    agents_list = (openclaw.get("agents") or {}).get("list") or []
    agents_by_id = {str(a.get("id") or ""): a for a in agents_list}
    applied = 0

    for change in changes:
        agent_cfg = agents_by_id.get(change["agent_id"])
        if not agent_cfg:
            continue

        model_cfg = agent_cfg.setdefault("model", {})

        if change["field"] == "model.primary":
            model_cfg["primary"] = change["desired"]
            applied += 1
        elif change["field"] == "model.fallbacks":
            model_cfg["fallbacks"] = change["desired"]
            applied += 1

    return applied


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync runtime routing policy to openclaw.json agent model configs."
    )
    parser.add_argument("--check", action="store_true", help="Dry-run: show changes without applying.")
    parser.add_argument(
        "--policy",
        default=str(POLICY_PATH),
        help="Path to runtime_routing_policy.json",
    )
    parser.add_argument(
        "--openclaw-json",
        default=str(OPENCLAW_JSON),
        help="Path to openclaw.json",
    )
    args = parser.parse_args()

    policy_path = Path(args.policy).resolve()
    openclaw_path = Path(args.openclaw_json).resolve()

    if not policy_path.exists():
        print(json.dumps({"ok": False, "error": f"Policy not found: {policy_path}"}))
        return 1
    if not openclaw_path.exists():
        print(json.dumps({"ok": False, "error": f"openclaw.json not found: {openclaw_path}"}))
        return 1

    policy = _load_json(policy_path)
    openclaw = _load_json(openclaw_path)

    changes = compute_sync_plan(policy, openclaw)

    if args.check:
        print(json.dumps({
            "ok": True,
            "mode": "check",
            "changes_needed": len(changes),
            "changes": changes,
        }, indent=2))
        return 0

    if not changes:
        print(json.dumps({
            "ok": True,
            "mode": "apply",
            "changes_applied": 0,
            "message": "Already in sync — no changes needed.",
        }, indent=2))
        return 0

    backup_path = _backup(openclaw_path)
    applied = apply_changes(openclaw, changes)
    _write_json(openclaw_path, openclaw)

    print(json.dumps({
        "ok": True,
        "mode": "apply",
        "changes_applied": applied,
        "backup": str(backup_path),
        "changes": changes,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
