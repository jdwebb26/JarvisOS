#!/usr/bin/env python3
"""promote_output — operator tool to promote task results into published outputs.

Bridges the gap between completed task execution and the output store.
Uses existing artifact_store.promote_artifact and output_store.publish_artifact.

Usage:
    python3 scripts/promote_output.py --list                    # promotable tasks
    python3 scripts/promote_output.py --promote task_xxx        # promote + publish
    python3 scripts/promote_output.py --inspect art_xxx         # show artifact chain
    python3 scripts/promote_output.py --inspect-output out_xxx  # show output record
    python3 scripts/promote_output.py --json                    # machine-readable
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_tasks(root: Path) -> list[dict[str, Any]]:
    d = root / "state" / "tasks"
    rows = []
    if not d.exists():
        return rows
    for p in d.glob("task_*.json"):
        try:
            rows.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return rows


def _load_result(result_id: str, root: Path) -> Optional[dict[str, Any]]:
    for prefix in ["bkres_", ""]:
        p = root / "state" / "backend_execution_results" / f"{prefix}{result_id}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    # Also try hal_results
    p = root / "state" / "hal_results" / f"{result_id}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _extract_result_id(final_outcome: str) -> Optional[str]:
    m = re.search(r"Result id: (bkres_\w+)", final_outcome)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# List promotable tasks
# ---------------------------------------------------------------------------

def list_promotable(root: Path) -> list[dict[str, Any]]:
    """Find completed tasks that have results but no promoted artifact."""
    tasks = _load_tasks(root)
    promotable = []

    for t in tasks:
        if t.get("status") != "completed":
            continue
        if t.get("promoted_artifact_id"):
            continue  # already has a promoted artifact

        outcome = t.get("final_outcome", "")
        result_id = _extract_result_id(outcome)
        if not result_id:
            continue

        result = _load_result(result_id, root)
        if not result:
            continue

        content = result.get("outcome_summary", "")
        if not content or len(content) < 20:
            continue  # too short to be meaningful

        promotable.append({
            "task_id": t.get("task_id", ""),
            "request": (t.get("normalized_request") or "")[:60],
            "task_type": t.get("task_type", ""),
            "result_id": result_id,
            "content_length": len(content),
            "model": result.get("model_name", ""),
            "has_review": bool(t.get("related_review_ids")),
            "source_channel": t.get("source_channel", ""),
        })

    promotable.sort(key=lambda x: x["task_id"])
    return promotable


# ---------------------------------------------------------------------------
# Promote a task's result
# ---------------------------------------------------------------------------

def promote_task_result(
    task_id: str,
    *,
    actor: str = "operator",
    root: Path,
) -> dict[str, Any]:
    """Create a candidate artifact from a task's result, promote it, and publish it.

    Steps:
      1. Load the task and its backend execution result
      2. Create a CANDIDATE artifact via write_text_artifact
      3. Promote the artifact via promote_artifact
      4. Publish the artifact via output_store.publish_artifact
      5. Emit Discord event

    Returns summary dict with artifact_id, output_id, paths.
    """
    from runtime.core.artifact_store import (
        load_artifact,
        promote_artifact,
        write_text_artifact,
    )
    from runtime.core.output_store import publish_artifact as publish_output
    from runtime.core.discord_event_router import emit_event

    # 1. Load task
    task_path = root / "state" / "tasks" / f"{task_id}.json"
    if not task_path.exists():
        return {"ok": False, "error": f"Task not found: {task_id}"}

    task = json.loads(task_path.read_text(encoding="utf-8"))

    if task.get("status") != "completed":
        return {"ok": False, "error": f"Task {task_id} is '{task.get('status')}', not completed"}

    if task.get("promoted_artifact_id"):
        return {"ok": False, "error": f"Task {task_id} already has promoted artifact: {task['promoted_artifact_id']}"}

    outcome = task.get("final_outcome", "")
    result_id = _extract_result_id(outcome)
    if not result_id:
        return {"ok": False, "error": f"No result ID found in final_outcome for {task_id}"}

    result = _load_result(result_id, root)
    if not result:
        return {"ok": False, "error": f"Backend result {result_id} not found"}

    content = result.get("outcome_summary", "")
    if not content:
        return {"ok": False, "error": f"Backend result {result_id} has no content"}

    # 2. Create candidate artifact
    request = task.get("normalized_request", "")[:80]
    task_type = task.get("task_type", "general")
    model = result.get("model_name", "unknown")

    artifact_result = write_text_artifact(
        task_id=task_id,
        artifact_type=task_type,
        title=f"{request}",
        summary=f"Result from {model} ({result_id})",
        content=content,
        actor=actor,
        lane="promotion",
        root=root,
        producer_kind="backend",
        lifecycle_state="candidate",
        execution_backend=task.get("execution_backend", ""),
        backend_run_id=result_id,
        provenance_ref=f"promote_output:{task_id}:{result_id}",
    )

    artifact_id = artifact_result.get("artifact_id")
    if not artifact_id:
        return {"ok": False, "error": f"Failed to create artifact: {artifact_result}"}

    # 3. Promote
    try:
        promoted = promote_artifact(
            artifact_id=artifact_id,
            actor=actor,
            lane="promotion",
            root=root,
            provenance_ref=f"operator_promote:{task_id}",
        )
    except (ValueError, Exception) as exc:
        return {"ok": False, "error": f"Promotion failed: {exc}", "artifact_id": artifact_id}

    # 4. Publish
    try:
        pub_result = publish_output(
            task_id=task_id,
            artifact_id=artifact_id,
            actor=actor,
            lane="promotion",
            root=root,
        )
    except (ValueError, Exception) as exc:
        return {
            "ok": False, "error": f"Publish failed: {exc}",
            "artifact_id": artifact_id,
            "promoted": True,
        }

    # 5. Discord event
    try:
        emit_event(
            "artifact_promoted", actor,
            task_id=task_id,
            artifact_id=artifact_id,
            detail=f"Output promoted: {request[:60]}",
            root=root,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "task_id": task_id,
        "artifact_id": artifact_id,
        "output_id": pub_result.get("output_id"),
        "markdown_path": pub_result.get("markdown_path"),
        "json_path": pub_result.get("json_path"),
        "title": request,
        "model": model,
        "result_id": result_id,
        "content_length": len(content),
    }


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------

def inspect_artifact(artifact_id: str, root: Path) -> dict[str, Any]:
    """Show full provenance chain for an artifact."""
    p = root / "state" / "artifacts" / f"{artifact_id}.json"
    if not p.exists():
        return {"ok": False, "error": f"Artifact not found: {artifact_id}"}

    artifact = json.loads(p.read_text(encoding="utf-8"))

    # Find task
    task_id = artifact.get("task_id", "")
    task_path = root / "state" / "tasks" / f"{task_id}.json"
    task = json.loads(task_path.read_text()) if task_path.exists() else {}

    # Find reviews for this task
    reviews = []
    reviews_dir = root / "state" / "reviews"
    if reviews_dir.exists():
        for rp in reviews_dir.glob("rev_*.json"):
            try:
                r = json.loads(rp.read_text())
                if r.get("task_id") == task_id:
                    reviews.append({
                        "review_id": r.get("review_id"),
                        "status": r.get("status"),
                        "reviewer": r.get("requested_reviewer", ""),
                    })
            except Exception:
                continue

    # Find approvals
    approvals = []
    approvals_dir = root / "state" / "approvals"
    if approvals_dir.exists():
        for ap in approvals_dir.glob("apr_*.json"):
            try:
                a = json.loads(ap.read_text())
                if a.get("task_id") == task_id:
                    approvals.append({
                        "approval_id": a.get("approval_id"),
                        "status": a.get("status"),
                    })
            except Exception:
                continue

    # Find published output
    outputs = []
    out_dir = root / "workspace" / "out"
    if out_dir.exists():
        for op in out_dir.glob("out_*.json"):
            try:
                o = json.loads(op.read_text())
                if o.get("artifact_id") == artifact_id:
                    outputs.append({
                        "output_id": o.get("output_id"),
                        "status": o.get("status"),
                        "markdown_path": o.get("markdown_path"),
                    })
            except Exception:
                continue

    return {
        "ok": True,
        "artifact_id": artifact_id,
        "task_id": task_id,
        "lifecycle_state": artifact.get("lifecycle_state"),
        "artifact_type": artifact.get("artifact_type"),
        "title": artifact.get("title", ""),
        "created_at": artifact.get("created_at", ""),
        "promoted_at": artifact.get("promoted_at"),
        "promoted_by": artifact.get("promoted_by"),
        "provenance_ref": artifact.get("provenance_ref"),
        "content_length": len(artifact.get("content", "")),
        "task_status": task.get("status"),
        "task_request": (task.get("normalized_request") or "")[:80],
        "reviews": reviews,
        "approvals": approvals,
        "outputs": outputs,
    }


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def render_list(items: list[dict[str, Any]]) -> str:
    if not items:
        return "No promotable tasks found."
    lines = [f"PROMOTABLE TASKS ({len(items)})", ""]
    for item in items:
        reviewed = " [reviewed]" if item["has_review"] else ""
        lines.append(f"  {item['task_id'][:16]}  {item['task_type']:10}  {item['content_length']:4}ch{reviewed}")
        lines.append(f"    {item['request']}")
    lines.append("")
    lines.append("Promote:")
    lines.append(f"  python3 scripts/promote_output.py --promote {items[0]['task_id']}")
    return "\n".join(lines)


def render_promote_result(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"ERROR: {result.get('error')}"
    lines = [
        f"PROMOTED: {result['artifact_id']}",
        f"  task:     {result['task_id']}",
        f"  output:   {result['output_id']}",
        f"  title:    {result['title']}",
        f"  model:    {result['model']}",
        f"  content:  {result['content_length']} chars",
        f"  markdown: {result['markdown_path']}",
        "",
        "Inspect:",
        f"  python3 scripts/promote_output.py --inspect {result['artifact_id']}",
    ]
    return "\n".join(lines)


def render_inspect(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return f"ERROR: {data.get('error')}"
    lines = [
        f"ARTIFACT: {data['artifact_id']}",
        f"  state:     {data['lifecycle_state']}",
        f"  type:      {data['artifact_type']}",
        f"  title:     {data['title'][:60]}",
        f"  task:      {data['task_id']}  ({data['task_status']})",
        f"  request:   {data['task_request']}",
        f"  created:   {data['created_at'][:19]}",
        f"  promoted:  {data['promoted_at'][:19] if data.get('promoted_at') else 'no'}",
        f"  by:        {data.get('promoted_by', '-')}",
        f"  ref:       {data.get('provenance_ref', '-')}",
        f"  content:   {data['content_length']} chars",
    ]
    if data["reviews"]:
        lines.append(f"  reviews:   {', '.join(r['review_id'] + '=' + r['status'] for r in data['reviews'])}")
    if data["approvals"]:
        lines.append(f"  approvals: {', '.join(a['approval_id'] + '=' + a['status'] for a in data['approvals'])}")
    if data["outputs"]:
        for o in data["outputs"]:
            lines.append(f"  output:    {o['output_id']}  status={o['status']}")
            if o.get("markdown_path"):
                lines.append(f"             {o['markdown_path']}")
    else:
        lines.append("  output:    (not published)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Promote task results into published outputs")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--list", action="store_true", dest="list_promotable",
                        help="Show tasks eligible for promotion")
    parser.add_argument("--promote", metavar="TASK_ID",
                        help="Promote a completed task's result")
    parser.add_argument("--inspect", metavar="ARTIFACT_ID",
                        help="Show artifact provenance chain")
    parser.add_argument("--json", action="store_true", dest="json_out")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    if args.list_promotable:
        items = list_promotable(root)
        if args.json_out:
            print(json.dumps(items, indent=2))
        else:
            print(render_list(items))
        return 0

    if args.promote:
        result = promote_task_result(args.promote, root=root)
        if args.json_out:
            print(json.dumps(result, indent=2))
        else:
            print(render_promote_result(result))
        return 0 if result.get("ok") else 1

    if args.inspect:
        data = inspect_artifact(args.inspect, root=root)
        if args.json_out:
            print(json.dumps(data, indent=2))
        else:
            print(render_inspect(data))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
