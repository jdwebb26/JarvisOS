#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SCRIPT_PATHS = [
    "runtime/core/check_ops_report_regression.py",
    "runtime/core/e2e_ops_report_executor_smoke.py",
    "runtime/core/decision_router_idempotency_smoke.py",
    "runtime/core/approval_ready_to_ship_smoke.py",
    "runtime/core/e2e_publish_complete_chain_smoke.py",
]


def _head(text: str, limit: int = 600) -> str:
    return (text or "").strip()[:limit]


def _run_script(path: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    payload_ok = None
    try:
        payload = json.loads(stdout) if stdout.strip() else {}
        if isinstance(payload, dict) and "ok" in payload:
            payload_ok = bool(payload["ok"])
    except Exception:
        payload = None

    return {
        "script": str(path.relative_to(ROOT)),
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "payload_ok": payload_ok,
        "stdout_head": _head(stdout),
        "stderr_head": _head(stderr),
    }


def main() -> int:
    results: list[dict] = []
    for rel_path in SCRIPT_PATHS:
        path = ROOT / rel_path
        if not path.exists():
            results.append(
                {
                    "script": rel_path,
                    "ok": False,
                    "exit_code": None,
                    "payload_ok": None,
                    "stdout_head": "",
                    "stderr_head": "missing script",
                }
            )
            continue
        results.append(_run_script(path))

    passed = sum(1 for result in results if result["ok"])
    failed = len(results) - passed
    summary = {
        "ok": failed == 0,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "results": results,
    }
    print(json.dumps(summary, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
