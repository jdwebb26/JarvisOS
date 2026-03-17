#!/usr/bin/env python3
"""backend_dispatch — centralized execution-backend dispatch for the task executor.

Maps execution_backend identifiers to their adapter functions.
Fail-closed: unrecognized or unconfigured backends return an error result
and never silently fall through.

This module is the single seam where routing decisions connect to actual
backend execution adapters on the Python task track.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import new_id, now_iso


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------

# Each entry maps an execution_backend identifier to a lazy-imported
# callable with the signature:
#   (task_id, actor, lane, messages, *, routing_decision_id, root) -> dict
#
# Adapters are imported lazily so that missing optional dependencies
# (e.g., requests) do not prevent the dispatch module from loading.

def _nvidia_adapter(
    *,
    task_id: str,
    actor: str,
    lane: str,
    messages: list[dict[str, str]],
    routing_decision_id: Optional[str] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Dispatch to the NVIDIA executor adapter."""
    from runtime.integrations.nvidia_executor import execute_nvidia_chat

    return execute_nvidia_chat(
        task_id=task_id,
        actor=actor,
        lane=lane,
        messages=messages,
        routing_decision_id=routing_decision_id,
        root=root,
    )


# ---------------------------------------------------------------------------
# Backend registry — add new adapters here.
# ---------------------------------------------------------------------------

BACKEND_ADAPTERS: dict[str, Callable[..., dict[str, Any]]] = {
    "nvidia_executor": _nvidia_adapter,
}

# Backends that are known but not yet wired to an adapter.
# Dispatching to these returns a structured "not_wired" result.
KNOWN_BUT_UNWIRED: set[str] = {
    "hermes_adapter",
    "autoresearch_adapter",
    "memory_spine",
    "browser_backend",
    "voice_gateway",
    "evaluation_spine",
    "ralph_adapter",
}


# ---------------------------------------------------------------------------
# Public dispatch API
# ---------------------------------------------------------------------------

def has_backend_adapter(execution_backend: str) -> bool:
    """Return True if the backend has a wired adapter in this dispatch map."""
    return execution_backend in BACKEND_ADAPTERS


def is_known_backend(execution_backend: str) -> bool:
    """Return True if the backend is recognized (wired or unwired)."""
    return execution_backend in BACKEND_ADAPTERS or execution_backend in KNOWN_BUT_UNWIRED


def dispatch_to_backend(
    *,
    task_id: str,
    actor: str,
    lane: str,
    execution_backend: str,
    messages: list[dict[str, str]],
    routing_decision_id: Optional[str] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Dispatch a task's messages to the appropriate backend adapter.

    Returns a structured result dict with at minimum:
      - status: "completed" | "error" | "config_error" | "not_wired" | "unknown_backend"
      - content: str (response text if any)
      - error: str (error message if any)
      - execution_backend: str (echo of the dispatched backend)
      - dispatched: bool (True if an adapter was actually called)

    Fail-closed: unknown or unrecognized backends return an error result.
    """
    root_path = Path(root or ROOT).resolve()

    # --- Wired adapter: dispatch ---
    adapter = BACKEND_ADAPTERS.get(execution_backend)
    if adapter is not None:
        try:
            result = adapter(
                task_id=task_id,
                actor=actor,
                lane=lane,
                messages=messages,
                routing_decision_id=routing_decision_id,
                root=root_path,
            )
            result["execution_backend"] = execution_backend
            result["dispatched"] = True
            return result
        except Exception as exc:
            return {
                "status": "error",
                "content": "",
                "usage": {},
                "error": f"Backend adapter raised: {type(exc).__name__}: {exc}",
                "execution_backend": execution_backend,
                "dispatched": True,
                "request_id": None,
                "result_id": None,
            }

    # --- Known but not yet wired ---
    if execution_backend in KNOWN_BUT_UNWIRED:
        return {
            "status": "not_wired",
            "content": "",
            "usage": {},
            "error": f"Backend '{execution_backend}' is recognized but has no Python adapter wired yet.",
            "execution_backend": execution_backend,
            "dispatched": False,
            "request_id": None,
            "result_id": None,
        }

    # --- Qwen executors: handled by the embedded gateway, not Python dispatch ---
    if execution_backend in {"qwen_executor", "qwen_planner"}:
        return {
            "status": "gateway_handled",
            "content": "",
            "usage": {},
            "error": "",
            "execution_backend": execution_backend,
            "dispatched": False,
            "message": f"Backend '{execution_backend}' is handled by the embedded gateway, not Python-track dispatch.",
            "request_id": None,
            "result_id": None,
        }

    # --- Unknown: fail-closed ---
    return {
        "status": "unknown_backend",
        "content": "",
        "usage": {},
        "error": f"Unrecognized execution_backend '{execution_backend}'. Refusing to dispatch.",
        "execution_backend": execution_backend,
        "dispatched": False,
        "request_id": None,
        "result_id": None,
    }


def list_registered_backends() -> dict[str, Any]:
    """Return a summary of all known backends and their wiring status."""
    return {
        "wired": sorted(BACKEND_ADAPTERS.keys()),
        "known_unwired": sorted(KNOWN_BUT_UNWIRED),
        "gateway_handled": ["qwen_executor", "qwen_planner"],
    }
