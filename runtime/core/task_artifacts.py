#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.task_events import make_event
from runtime.core.task_runtime import append_task_event, load_task, save_task
from runtime.dashboard.rebuild_helpers import rebuild_all_outputs


def attach_artifact_to_task(
    *,
    task_id: str,
    artifact_id: str,
    artifact_type: str,
    title: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
) -> dict:
    root_path = Path(root or ROOT).resolve()

    task = load_task(root_path, task_id)
    if task is None:
        raise ValueError(f"Task not found: {task_id}")

    related = list(task.related_artifact_ids or [])
    already_linked = artifact_id in related

    if not already_linked:
        related.append(artifact_id)
        task.related_artifact_ids = related
        save_task(root_path, task)

    event = append_task_event(
        root_path,
        make_event(
            task_id=task_id,
            event_type="artifact_linked",
            actor=actor,
            lane=lane,
            summary=f"Artifact linked: {artifact_id}",
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            artifact_title=title,
            already_linked=already_linked,
        ),
    )

    rebuild_all_outputs(root_path)

    return {
        "task_id": task_id,
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "title": title,
        "already_linked": already_linked,
        "related_artifact_ids": list(task.related_artifact_ids or []),
        "event_id": event.event_id,
    }
