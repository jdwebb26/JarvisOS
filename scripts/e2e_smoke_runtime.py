#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_json(cmd: list[str]) -> dict:
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{completed.stdout}\n\nSTDERR:\n{completed.stderr}"
        )

    stdout = completed.stdout.strip()
    if not stdout:
        return {}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Command did not return JSON: {' '.join(cmd)}\n"
            f"STDOUT:\n{completed.stdout}\n\nSTDERR:\n{completed.stderr}"
        ) from exc


def read_task(root: Path, task_id: str) -> dict:
    path = root / "state" / "tasks" / f"{task_id}.json"
    if not path.exists():
        raise RuntimeError(f"Task file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a small end-to-end runtime smoke test.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    py = sys.executable

    token = uuid.uuid4().hex[:8]
    message_id = f"smoke-{token}"
    task_text = f"task: smoke test runtime pipeline {token}"

    intake_result = run_json(
        [
            py,
            str(root / "runtime" / "gateway" / "discord_intake.py"),
            "--root", str(root),
            "--text", task_text,
            "--user", "smoke",
            "--lane", "jarvis",
            "--channel", "jarvis",
            "--message-id", message_id,
        ]
    )

    intake_payload = intake_result.get("result", intake_result)
    task_id = intake_payload.get("task_id")
    if not task_id:
        raise RuntimeError(f"Could not find task_id in intake result: {json.dumps(intake_result, indent=2)}")

    execute_runs: list[dict] = []
    complete_runs: list[dict] = []

    for _ in range(8):
        task = read_task(root, task_id)
        status = task.get("status", "")

        if status in {"completed", "shipped"}:
            break

        if status == "running":
            complete_result = run_json(
                [
                    py,
                    str(root / "runtime" / "executor" / "complete_once.py"),
                    "--root", str(root),
                    "--task-id", task_id,
                    "--actor", "executor",
                    "--lane", "executor",
                    "--final-outcome", "Smoke task closed automatically by e2e smoke runtime.",
                ]
            )
            complete_runs.append(complete_result)
        else:
            execute_result = run_json(
                [
                    py,
                    str(root / "runtime" / "executor" / "execute_once.py"),
                    "--root", str(root),
                    "--actor", "executor",
                    "--lane", "executor",
                ]
            )
            execute_runs.append(execute_result)

        time.sleep(0.1)

    final_task = read_task(root, task_id)

    rebuild_result = run_json(
        [
            py,
            str(root / "runtime" / "dashboard" / "rebuild_all.py"),
            "--root", str(root),
        ]
    )

    status_result = run_json(
        [
            py,
            str(root / "runtime" / "core" / "status.py"),
            "--root", str(root),
        ]
    )

    ok = final_task.get("status") in {"completed", "shipped"}

    payload = {
        "ok": ok,
        "task_id": task_id,
        "message_id": message_id,
        "task_text": task_text,
        "intake_result": intake_result,
        "execute_runs": execute_runs,
        "complete_runs": complete_runs,
        "final_task_status": final_task.get("status"),
        "final_task": final_task,
        "status_counts": status_result.get("counts", {}),
        "rebuild_ok": rebuild_result.get("ok", False),
        "rebuild_errors": rebuild_result.get("errors", []),
    }

    print(json.dumps(payload, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
