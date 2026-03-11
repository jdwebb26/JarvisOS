#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import new_id, now_iso


ROOT = Path(__file__).resolve().parents[2]


def browser_snapshots_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "browser_snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def browser_traces_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "browser_traces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _snapshot_path(snapshot_id: str, *, root: Optional[Path] = None) -> Path:
    return browser_snapshots_dir(root=root) / f"{snapshot_id}.json"


def _trace_path(trace_id: str, *, root: Optional[Path] = None) -> Path:
    return browser_traces_dir(root=root) / f"{trace_id}.json"


def save_browser_snapshot(
    *,
    task_id: str,
    actor: str,
    lane: str,
    snapshot_kind: str,
    payload: dict[str, Any],
    request_id: Optional[str] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    record = {
        "snapshot_id": new_id("bsnap"),
        "task_id": task_id,
        "request_id": request_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "actor": actor,
        "lane": lane,
        "snapshot_kind": snapshot_kind,
        "payload": dict(payload or {}),
    }
    _snapshot_path(record["snapshot_id"], root=root).write_text(
        json.dumps(record, indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def save_browser_trace(
    *,
    task_id: str,
    actor: str,
    lane: str,
    trace_kind: str,
    steps: list[dict[str, Any]],
    request_id: Optional[str] = None,
    snapshot_refs: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    record = {
        "trace_id": new_id("btrace"),
        "task_id": task_id,
        "request_id": request_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "actor": actor,
        "lane": lane,
        "trace_kind": trace_kind,
        "steps": list(steps or []),
        "snapshot_refs": dict(snapshot_refs or {}),
    }
    _trace_path(record["trace_id"], root=root).write_text(
        json.dumps(record, indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_browser_snapshot(snapshot_id: str, *, root: Optional[Path] = None) -> dict[str, Any]:
    return json.loads(_snapshot_path(snapshot_id, root=root).read_text(encoding="utf-8"))


def load_browser_trace(trace_id: str, *, root: Optional[Path] = None) -> dict[str, Any]:
    return json.loads(_trace_path(trace_id, root=root).read_text(encoding="utf-8"))
