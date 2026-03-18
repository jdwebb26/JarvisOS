#!/usr/bin/env python3
"""Runtime provider profiles — explicit provider/model switching for OpenClaw agents.

Profiles define named sets of agent_policy overrides applied on top of the base
routing policy. Only one profile is active at a time, persisted in
state/active_profile.json.

Available profiles:
    local_only   — All agents on LM Studio / Qwen (default, safe)
    hybrid       — Orchestration/research on Kimi 2.5, coders stay local
    cloud_fast   — Jarvis + research agents on Kimi 2.5 for speed
    cloud_smart  — All reasoning-heavy agents on Kimi 2.5
    degraded     — Minimal local fallbacks for LM Studio outage
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import now_iso

# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------

_STATE_DIR = ROOT / "state"
_ACTIVE_PROFILE_PATH = _STATE_DIR / "active_profile.json"


def _ensure_state_dir() -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Profile definitions
# ---------------------------------------------------------------------------

# Each profile maps agent_id → partial agent_policy override.
# These are merged on top of the base agent_policies in runtime_routing_policy.json.
# Keys not present in a profile's override are inherited from the base policy.

PROFILES: dict[str, dict[str, Any]] = {
    "local_only": {
        "description": "All agents on LM Studio / Qwen. No cloud calls. Safe default.",
        "agent_overrides": {},  # No overrides — base policy is already local-only
    },
    "hybrid": {
        "description": "Orchestration and research on Kimi 2.5, coders stay on local Qwen.",
        "agent_overrides": {
            "jarvis": {
                "preferred_provider": "nvidia",
                "preferred_model": "moonshotai/kimi-k2.5",
                "allowed_families": ["kimi", "qwen3.5"],
                "allowed_fallbacks": ["Qwen3.5-35B", "Qwen3.5-9B"],
            },
            "scout": {
                "preferred_provider": "nvidia",
                "preferred_model": "moonshotai/kimi-k2.5",
                "allowed_families": ["kimi", "qwen3.5"],
                "allowed_fallbacks": ["Qwen3.5-35B"],
            },
            "hermes": {
                "preferred_provider": "nvidia",
                "preferred_model": "moonshotai/kimi-k2.5",
                "allowed_families": ["kimi", "qwen3.5"],
                "allowed_fallbacks": ["Qwen3.5-35B"],
            },
            # hal, archimedes stay on local Qwen coders
        },
    },
    "cloud_fast": {
        "description": "Jarvis + research agents on Kimi 2.5 for speed. Coders local.",
        "agent_overrides": {
            "jarvis": {
                "preferred_provider": "nvidia",
                "preferred_model": "moonshotai/kimi-k2.5",
                "allowed_families": ["kimi", "qwen3.5"],
                "allowed_fallbacks": ["Qwen3.5-35B"],
            },
            "scout": {
                "preferred_provider": "nvidia",
                "preferred_model": "moonshotai/kimi-k2.5",
                "allowed_families": ["kimi", "qwen3.5"],
                "allowed_fallbacks": ["Qwen3.5-35B"],
            },
            "ralph": {
                "preferred_provider": "nvidia",
                "preferred_model": "moonshotai/kimi-k2.5",
                "allowed_families": ["kimi", "qwen3.5"],
                "allowed_fallbacks": ["Qwen3.5-35B"],
            },
        },
    },
    "cloud_smart": {
        "description": "All reasoning-heavy agents on Kimi 2.5. Full cloud for orchestration.",
        "agent_overrides": {
            "jarvis": {
                "preferred_provider": "nvidia",
                "preferred_model": "moonshotai/kimi-k2.5",
                "allowed_families": ["kimi", "qwen3.5"],
                "allowed_fallbacks": ["Qwen3.5-35B"],
            },
            "anton": {
                "preferred_provider": "nvidia",
                "preferred_model": "moonshotai/kimi-k2.5",
                "allowed_families": ["kimi", "qwen3.5"],
                "allowed_fallbacks": ["Qwen3.5-122B"],
            },
            "hermes": {
                "preferred_provider": "nvidia",
                "preferred_model": "moonshotai/kimi-k2.5",
                "allowed_families": ["kimi", "qwen3.5"],
                "allowed_fallbacks": ["Qwen3.5-35B"],
            },
            "scout": {
                "preferred_provider": "nvidia",
                "preferred_model": "moonshotai/kimi-k2.5",
                "allowed_families": ["kimi", "qwen3.5"],
                "allowed_fallbacks": ["Qwen3.5-35B"],
            },
        },
    },
    "degraded": {
        "description": "Minimal local fallbacks. For when LM Studio is overloaded or down.",
        "agent_overrides": {
            "jarvis": {
                "preferred_model": "Qwen3.5-9B",
                "allowed_fallbacks": [],
            },
            "hal": {
                "preferred_model": "Qwen3.5-9B",
                "allowed_fallbacks": [],
            },
            "archimedes": {
                "preferred_model": "Qwen3.5-9B",
                "allowed_fallbacks": [],
            },
            "anton": {
                "preferred_model": "Qwen3.5-35B",
                "allowed_fallbacks": ["Qwen3.5-9B"],
            },
            "scout": {
                "preferred_model": "Qwen3.5-9B",
                "allowed_fallbacks": [],
            },
            "ralph": {
                "preferred_model": "Qwen3.5-9B",
                "allowed_fallbacks": [],
            },
        },
    },
}

PROFILE_NAMES = sorted(PROFILES.keys())
DEFAULT_PROFILE = "local_only"


# ---------------------------------------------------------------------------
# Active profile state
# ---------------------------------------------------------------------------

def get_active_profile(root: Optional[Path] = None) -> dict[str, Any]:
    """Return the active profile state. Creates default if missing."""
    base = Path(root or ROOT).resolve()
    path = base / "state" / "active_profile.json"
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            name = state.get("profile", DEFAULT_PROFILE)
            if name in PROFILES:
                return state
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "profile": DEFAULT_PROFILE,
        "set_at": now_iso(),
        "set_by": "default",
    }


def set_active_profile(
    profile_name: str,
    *,
    set_by: str = "operator",
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Switch the active runtime profile. Returns the new state."""
    if profile_name not in PROFILES:
        raise ValueError(
            f"Unknown profile '{profile_name}'. Available: {', '.join(PROFILE_NAMES)}"
        )
    base = Path(root or ROOT).resolve()
    state_dir = base / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "active_profile.json"

    state = {
        "profile": profile_name,
        "set_at": now_iso(),
        "set_by": set_by,
        "description": PROFILES[profile_name]["description"],
    }
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return state


def get_profile_definition(profile_name: str) -> dict[str, Any]:
    """Return the full profile definition. Raises ValueError if unknown."""
    if profile_name not in PROFILES:
        raise ValueError(
            f"Unknown profile '{profile_name}'. Available: {', '.join(PROFILE_NAMES)}"
        )
    return dict(PROFILES[profile_name])


def apply_profile_overrides(
    agent_policies: dict[str, Any],
    profile_name: str,
) -> dict[str, Any]:
    """Return agent_policies with the named profile's overrides merged on top."""
    if profile_name not in PROFILES:
        return dict(agent_policies)

    profile = PROFILES[profile_name]
    overrides = profile.get("agent_overrides", {})
    if not overrides:
        return dict(agent_policies)

    merged = {}
    for agent_id, base_policy in agent_policies.items():
        if agent_id in overrides:
            # Merge: profile override wins over base
            merged_policy = dict(base_policy)
            for key, value in overrides[agent_id].items():
                if isinstance(value, list):
                    merged_policy[key] = list(value)
                else:
                    merged_policy[key] = value
            merged[agent_id] = merged_policy
        else:
            merged[agent_id] = dict(base_policy)
    return merged


def _read_last_model_snapshot(
    agent_id: str,
    openclaw_root: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Read the most recent model-snapshot from an agent's session files."""
    oc_root = Path(openclaw_root or Path.home() / ".openclaw")
    sessions_dir = oc_root / "agents" / agent_id / "sessions"
    if not sessions_dir.exists():
        return None

    # Find most recent .jsonl session file
    jsonl_files = sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for session_file in jsonl_files[:3]:  # Check up to 3 most recent
        try:
            # Read from end for efficiency
            lines = session_file.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines[-50:]):  # Check last 50 entries
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "model-snapshot" or entry.get("customType") == "model-snapshot":
                        data = entry.get("data", entry)
                        return {
                            "provider": data.get("provider", ""),
                            "model": data.get("modelId", data.get("model", "")),
                            "timestamp": data.get("timestamp", ""),
                            "session_file": session_file.name,
                        }
                except (json.JSONDecodeError, KeyError):
                    continue
        except OSError:
            continue
    return None


def show_realized_routing(
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Show the effective provider/model for each agent under the active profile."""
    base = Path(root or ROOT).resolve()
    state = get_active_profile(root=base)
    profile_name = state.get("profile", DEFAULT_PROFILE)

    # Load base policy
    policy_path = base / "config" / "runtime_routing_policy.json"
    if policy_path.exists():
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    else:
        policy = {}

    base_agent_policies = policy.get("agent_policies", {})
    effective = apply_profile_overrides(base_agent_policies, profile_name)

    # Determine openclaw root for session reads
    openclaw_root = base.parent.parent if base.name == "jarvis-v5" else None

    agents_summary = {}
    for agent_id, ap in sorted(effective.items()):
        agent_info: dict[str, Any] = {
            "provider": ap.get("preferred_provider", "qwen"),
            "model": ap.get("preferred_model", "?"),
            "fallbacks": ap.get("allowed_fallbacks", []),
            "families": ap.get("allowed_families", []),
        }
        # Try to read last realized model from session evidence
        snapshot = _read_last_model_snapshot(agent_id, openclaw_root)
        if snapshot:
            agent_info["last_realized"] = {
                "provider": snapshot["provider"],
                "model": snapshot["model"],
            }
            if snapshot.get("timestamp"):
                agent_info["last_realized"]["timestamp"] = snapshot["timestamp"]
        agents_summary[agent_id] = agent_info

    return {
        "active_profile": profile_name,
        "description": PROFILES.get(profile_name, {}).get("description", ""),
        "set_at": state.get("set_at", ""),
        "set_by": state.get("set_by", ""),
        "agents": agents_summary,
    }


# ---------------------------------------------------------------------------
# Model name matching (policy names vs gateway refs)
# ---------------------------------------------------------------------------

# Maps policy model names to patterns found in gateway model refs
_MODEL_MATCH_PATTERNS: dict[str, list[str]] = {
    "Qwen3.5-9B": ["qwen3.5-9b", "qwen/qwen3.5-9b"],
    "Qwen3.5-35B": ["qwen3.5-35b", "qwen3.5-35b-a3b"],
    "Qwen3.5-122B": ["qwen3.5-122b", "qwen3.5-122b-a10b"],
    "Qwen3-Coder-Next": ["qwen3-coder-next"],
    "Qwen3-Coder-30B": ["qwen3-coder-30b"],
    "moonshotai/kimi-k2.5": ["moonshotai/kimi-k2.5", "kimi-k2.5"],
}

# Maps policy provider names to gateway provider names
_PROVIDER_MATCH: dict[str, list[str]] = {
    "qwen": ["lmstudio", "qwen"],
    "nvidia": ["nvidia"],
    "local": ["local"],
}


def _match_provider_model(
    policy_provider: str,
    policy_model: str,
    realized_provider: str,
    realized_model: str,
) -> str:
    """Compare policy provider/model against realized values, return 'ok' or 'stale'."""
    # Provider match
    prov_ok = False
    for pattern in _PROVIDER_MATCH.get(policy_provider, [policy_provider]):
        if pattern.lower() in realized_provider.lower():
            prov_ok = True
            break

    # Model match
    model_ok = False
    for pattern in _MODEL_MATCH_PATTERNS.get(policy_model, [policy_model.lower()]):
        if pattern.lower() in realized_model.lower():
            model_ok = True
            break

    if prov_ok and model_ok:
        return "ok"
    return "stale"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="OpenClaw runtime profile manager")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="List available profiles")
    sub.add_parser("show", help="Show active profile and realized routing")

    p_set = sub.add_parser("set", help="Switch active profile")
    p_set.add_argument("profile", choices=PROFILE_NAMES)

    args = parser.parse_args()

    if args.cmd == "list":
        for name in PROFILE_NAMES:
            active = " (active)" if name == get_active_profile().get("profile") else ""
            desc = PROFILES[name]["description"]
            print(f"  {name:<14} {desc}{active}")
        return 0

    if args.cmd == "show":
        result = show_realized_routing()
        # Pretty table output
        print(f"Profile: {result['active_profile']}  ({result['description']})")
        print(f"Set at:  {result['set_at']}  by: {result['set_by']}")
        print()
        print(f"  {'Agent':<12} {'Provider':<10} {'Model':<28} {'Last Realized'}")
        print(f"  {'─'*12} {'─'*10} {'─'*28} {'─'*30}")
        for agent_id, info in result["agents"].items():
            realized = info.get("last_realized", {})
            if realized:
                r_prov = realized.get("provider", "")
                r_model = realized.get("model", "")
                match = _match_provider_model(info["provider"], info["model"], r_prov, r_model)
                last = f"{r_prov}/{r_model} [{match}]"
            else:
                last = "(no turn yet)"
            print(f"  {agent_id:<12} {info['provider']:<10} {info['model']:<28} {last}")
        if "--json" in sys.argv:
            print()
            print(json.dumps(result, indent=2))
        return 0

    if args.cmd == "set":
        state = set_active_profile(args.profile)
        print(json.dumps(state, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
