#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import (
    AuthorityClass,
    BackendRuntime,
    NodeProfile,
    NodeRole,
    NodeStatus,
    new_id,
    now_iso,
)


DEFAULT_NODE_PROFILES = [
    {
        "node_name": "NIMO",
        "node_role": NodeRole.PRIMARY.value,
        "status": NodeStatus.HEALTHY.value,
        "authority_class": AuthorityClass.SUGGEST_ONLY.value,
        "available_backends": [
            BackendRuntime.QWEN_PLANNER.value,
            BackendRuntime.QWEN_EXECUTOR.value,
            BackendRuntime.OPERATOR.value,
        ],
        "accelerator_refs": ["local_scaffolding_accelerator"],
        "labels": ["live_primary", "scaffolding_seed"],
        "metadata": {
            "scaffolding_only": True,
            "backend_summary": ["qwen_planner", "qwen_executor", "operator"],
            "model_family_summary": ["qwen"],
            "notes": ["Primary durable node scaffold for 5.2 prep visibility."],
        },
    },
    {
        "node_name": "Koolkidclub",
        "node_role": NodeRole.BURST.value,
        "status": NodeStatus.STOPPED.value,
        "authority_class": AuthorityClass.SUGGEST_ONLY.value,
        "available_backends": [],
        "accelerator_refs": [],
        "labels": ["optional_burst", "scaffolding_seed"],
        "metadata": {
            "scaffolding_only": True,
            "optional": True,
            "backend_summary": [],
            "model_family_summary": [],
            "notes": ["Optional burst worker scaffold. Not part of the critical path."],
        },
    },
]


def nodes_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "nodes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def worker_heartbeats_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "worker_heartbeats"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _node_path(node_name: str, *, root: Optional[Path] = None) -> Path:
    safe_name = str(node_name or "unknown").strip().lower().replace(" ", "_")
    return nodes_dir(root=root) / f"{safe_name}.json"


def save_node(record: NodeProfile, *, root: Optional[Path] = None) -> NodeProfile:
    record.updated_at = now_iso()
    _node_path(record.node_name, root=root).write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return record


def get_node(node_name: str, *, root: Optional[Path] = None) -> Optional[NodeProfile]:
    path = _node_path(node_name, root=root)
    if not path.exists():
        return None
    try:
        return NodeProfile.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def list_nodes(*, root: Optional[Path] = None) -> list[NodeProfile]:
    rows: list[NodeProfile] = []
    for path in sorted(nodes_dir(root=root).glob("*.json")):
        try:
            rows.append(NodeProfile.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: (row.node_role != NodeRole.PRIMARY.value, row.node_name.lower()))
    return rows


def register_node(
    *,
    node_name: str,
    actor: str = "system",
    lane: str = "bootstrap",
    node_role: str = NodeRole.PRIMARY.value,
    status: str = NodeStatus.HEALTHY.value,
    authority_class: str = AuthorityClass.SUGGEST_ONLY.value,
    available_backends: Optional[list[str]] = None,
    accelerator_refs: Optional[list[str]] = None,
    labels: Optional[list[str]] = None,
    metadata: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> NodeProfile:
    existing = get_node(node_name, root=root)
    if existing is not None:
        return existing
    timestamp = now_iso()
    return save_node(
        NodeProfile(
            node_profile_id=new_id("node"),
            created_at=timestamp,
            updated_at=timestamp,
            actor=actor,
            lane=lane,
            node_name=node_name,
            node_role=node_role,
            status=status,
            authority_class=authority_class,
            available_backends=list(available_backends or []),
            accelerator_refs=list(accelerator_refs or []),
            labels=list(labels or []),
            metadata=dict(metadata or {}),
        ),
        root=root,
    )


def update_node_status(
    node_name: str,
    *,
    status: str,
    actor: str = "system",
    lane: str = "heartbeat",
    metadata: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> NodeProfile:
    node = get_node(node_name, root=root)
    if node is None:
        node = register_node(node_name=node_name, actor=actor, lane=lane, status=status, root=root)
    node.status = status
    node.actor = actor
    node.lane = lane
    if metadata:
        node.metadata = {**dict(node.metadata or {}), **dict(metadata)}
    return save_node(node, root=root)


def get_node_capabilities(node_name: str, *, root: Optional[Path] = None) -> dict[str, Any]:
    node = get_node(node_name, root=root)
    if node is None:
        return {
            "node_name": node_name,
            "available_backends": [],
            "accelerator_refs": [],
            "labels": [],
            "metadata": {},
        }
    return {
        "node_name": node.node_name,
        "node_role": node.node_role,
        "authority_class": node.authority_class,
        "available_backends": list(node.available_backends or []),
        "accelerator_refs": list(node.accelerator_refs or []),
        "labels": list(node.labels or []),
        "metadata": dict(node.metadata or {}),
    }


def ensure_default_nodes(*, root: Optional[Path] = None) -> list[NodeProfile]:
    root_path = Path(root or ROOT).resolve()
    worker_heartbeats_dir(root=root_path)
    created_or_existing: list[NodeProfile] = []
    for row in DEFAULT_NODE_PROFILES:
        created_or_existing.append(
            register_node(
                node_name=row["node_name"],
                actor="system",
                lane="bootstrap",
                node_role=row["node_role"],
                status=row["status"],
                authority_class=row["authority_class"],
                available_backends=row["available_backends"],
                accelerator_refs=row["accelerator_refs"],
                labels=row["labels"],
                metadata=row["metadata"],
                root=root_path,
            )
        )
    return created_or_existing

