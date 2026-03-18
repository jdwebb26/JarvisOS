#!/usr/bin/env python3
"""hermes_live_proof — create a real task and dispatch it through Hermes end-to-end.

Usage:
    python3 scripts/hermes_live_proof.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import TaskRecord, TaskStatus, new_id, now_iso
from runtime.core.task_store import save_task
from runtime.integrations.hermes_adapter import execute_hermes_task


def main() -> int:
    task_id = new_id("task")
    ts = now_iso()

    task = TaskRecord(
        task_id=task_id,
        created_at=ts,
        updated_at=ts,
        source_lane="hermes",
        source_channel="live_proof",
        source_message_id=new_id("msg"),
        source_user="operator",
        trigger_type="manual",
        raw_request="Research: What are the key characteristics of NQ (Nasdaq E-mini) futures that make them suitable for algorithmic trading?",
        normalized_request="What are the key characteristics of NQ (Nasdaq E-mini) futures that make them suitable for algorithmic trading?",
        task_type="research",
        status=TaskStatus.QUEUED.value,
        execution_backend="hermes_adapter",
        backend_metadata={},
    )
    save_task(task, root=ROOT)
    print(f"[1/3] Task created: {task_id}")

    print("[2/3] Dispatching to Hermes (LM Studio Qwen)...")
    result = execute_hermes_task(
        task_id=task_id,
        actor="operator",
        lane="hermes",
        root=ROOT,
        timeout_seconds=120,
    )

    status = result.get("result", {}).get("status", "unknown")
    artifact_id = result.get("candidate_artifact_id")
    task_status = result.get("task_status")

    print(f"[3/3] Result status: {status}")
    print(f"      Task status:   {task_status}")
    print(f"      Artifact ID:   {artifact_id}")

    if status == "completed":
        print("\n--- HERMES LIVE PROOF: SUCCESS ---")
        title = result["result"].get("title", "")
        summary = result["result"].get("summary", "")
        content = result["result"].get("content", "")
        print(f"Title:   {title}")
        print(f"Summary: {summary[:200]}")
        print(f"Content: {content[:500]}...")
        token_usage = result["result"].get("token_usage", {})
        print(f"Tokens:  {json.dumps(token_usage)}")

        # Show where the artifact was stored
        if artifact_id:
            artifact_dir = ROOT / "artifacts"
            print(f"\nArtifact stored under: {artifact_dir}/")

        # Show request/result files
        req_id = result["request"].get("request_id", "")
        res_id = result["result"].get("result_id", "")
        print(f"Request file: state/hermes_requests/{req_id}.json")
        print(f"Result file:  state/hermes_results/{res_id}.json")
        return 0
    else:
        print("\n--- HERMES LIVE PROOF: FAILED ---")
        error = result.get("result", {}).get("error", "unknown error")
        print(f"Error: {error}")
        print(json.dumps(result, indent=2, default=str)[:2000])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
