#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path("/home/rollan/.openclaw/workspace")
ROOT = WORKSPACE / "jarvis-v5"
ARTIFACT_ROOT = WORKSPACE / "artifacts" / "qwen_live"


def now_iso() -> str:
    return datetime.now().isoformat()


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def today_dir() -> Path:
    out = ARTIFACT_ROOT / datetime.now().strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)
    return out


def latest_patch_plan(task_id: str = "") -> Path | None:
    today = today_dir()
    task_id = (task_id or "").strip()
    if task_id:
        task_latest = today / f"latest_task_{task_id}_patch_plan.md"
        if task_latest.exists():
            return task_latest
    latest = today / "latest_patch_plan.md"
    if latest.exists():
        return latest
    matches = sorted(today.glob("*_patch_plan.md"))
    if matches:
        return matches[-1]
    return None


def extract_target_files(text: str) -> list[str]:
    matches = re.findall(
        r"/home/rollan/\.openclaw/workspace/[A-Za-z0-9_\-./]+",
        text,
    )

    files = []
    seen = set()
    for path in matches:
        if not (
            path.endswith(".py")
            or path.endswith(".md")
            or path.endswith(".yaml")
            or path.endswith(".yml")
            or path.endswith(".json")
        ):
            continue
        if path not in seen:
            seen.add(path)
            files.append(path)
    return files


def write_artifact(name: str, body: str) -> Path:
    out = today_dir() / f"{now_stamp()}_{name}.md"
    out.write_text(body, encoding="utf-8")
    latest = today_dir() / f"latest_{name}.md"
    latest.write_text(body, encoding="utf-8")
    return out


def run_json(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        )

    if not stdout:
        return {"ok": True, "stdout": "", "stderr": stderr}

    try:
        return json.loads(stdout)
    except Exception:
        return {
            "ok": True,
            "stdout": stdout,
            "stderr": stderr,
        }


def verify_writer_patch_plan(*, patch_plan: Path, writer_result: dict, explicit_requested: bool) -> tuple[bool, str]:
    writer_plan = str(writer_result.get("patch_plan") or "").strip()
    if not writer_plan:
        return False, "writer_result.patch_plan missing"
    if Path(writer_plan).resolve() != patch_plan:
        return False, f"writer used unexpected patch plan: {writer_plan}"
    if explicit_requested and writer_result.get("patch_plan_source") != "explicit":
        return False, f"writer patch_plan_source was {writer_result.get('patch_plan_source')!r}, expected 'explicit'"
    artifact_path = str(writer_result.get("artifact") or "").strip()
    if artifact_path:
        artifact_text = Path(artifact_path).read_text(encoding="utf-8", errors="replace")
        if f"- patch_plan: {patch_plan}" not in artifact_text:
            return False, "writer artifact did not record the expected patch plan"
        if explicit_requested and "- patch_plan_source: explicit" not in artifact_text:
            return False, "writer artifact did not record explicit patch_plan_source"
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Orchestrate arm -> candidate-writer for a real Jarvis task.")
    ap.add_argument("--task-id", required=True, help="Real Jarvis task id, for example task_cec3239feefb")
    ap.add_argument("--patch-plan", default="", help="Optional explicit patch plan path.")
    ap.add_argument("--mode", default="dry_run", choices=["dry_run", "apply_live"])
    ap.add_argument("--approval-note", default="")
    ap.add_argument("--gate-note", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    task_path = ROOT / "state" / "tasks" / f"{args.task_id}.json"
    if not task_path.exists():
        raise SystemExit(f"Task not found: {task_path}")

    patch_plan = Path(args.patch_plan).resolve() if args.patch_plan.strip() else latest_patch_plan(args.task_id)
    patch_plan_source = "explicit" if args.patch_plan.strip() else "task_latest_or_global_latest"
    if patch_plan is None:
        out = write_artifact(
            "patch_execution",
            "\n".join(
                [
                    "# Qwen Patch Executor",
                    "",
                    f"- timestamp: {now_iso()}",
                    f"- task_id: {args.task_id}",
                    "- ok: false",
                    "- reason: no latest patch plan found",
                    "",
                ]
            ),
        )
        payload = {
            "ok": False,
            "task_id": args.task_id,
            "reason": "no latest patch plan found",
            "artifact": str(out),
        }
        print(json.dumps(payload, indent=2) if args.json else f"Wrote: {out}")
        return 1

    patch_text = patch_plan.read_text(encoding="utf-8", errors="replace")
    target_files = extract_target_files(patch_text)
    if not target_files:
        out = write_artifact(
            "patch_execution",
            "\n".join(
                [
                    "# Qwen Patch Executor",
                    "",
                    f"- timestamp: {now_iso()}",
                    f"- task_id: {args.task_id}",
                    "- ok: false",
                    "- reason: patch plan has no extracted target files",
                    "",
                ]
            ),
        )
        payload = {
            "ok": False,
            "task_id": args.task_id,
            "reason": "patch plan has no extracted target files",
            "artifact": str(out),
        }
        print(json.dumps(payload, indent=2) if args.json else f"Wrote: {out}")
        return 1

    arm_cmd = [
        sys.executable,
        str(ROOT / "runtime" / "core" / "qwen_arm_task.py"),
        "--task-id",
        args.task_id,
        "--mode",
        args.mode,
        "--approval-note",
        args.approval_note,
        "--gate-note",
        args.gate_note,
        "--json",
    ]
    for path in target_files:
        arm_cmd.extend(["--target-path", path])

    arm_result = run_json(arm_cmd)

    writer_cmd = [
        sys.executable,
        str(ROOT / "runtime" / "core" / "qwen_candidate_writer.py"),
        "--patch-plan",
        str(patch_plan),
        "--json",
    ]
    writer_result = run_json(writer_cmd)
    writer_patch_plan_verified, writer_patch_plan_error = verify_writer_patch_plan(
        patch_plan=patch_plan,
        writer_result=writer_result,
        explicit_requested=bool(args.patch_plan.strip()),
    )
    if not writer_patch_plan_verified:
        raise RuntimeError(writer_patch_plan_error)
    writer_result_kind = (
        "real_candidate_accepted"
        if writer_result.get("real_candidate")
        else "fallback_baseline_only"
    )

    body = "\n".join(
        [
            "# Qwen Patch Executor",
            "",
            f"- timestamp: {now_iso()}",
            f"- task_id: {args.task_id}",
            f"- mode: {args.mode}",
            f"- patch_plan: {patch_plan}",
            f"- patch_plan_source: {patch_plan_source}",
            f"- writer_patch_plan_verified: {writer_patch_plan_verified}",
            f"- writer_result_kind: {writer_result_kind}",
            "",
            "## Target Files",
            "```json",
            json.dumps(target_files, indent=2, ensure_ascii=False),
            "```",
            "",
            "## Arm Result",
            "```json",
            json.dumps(arm_result, indent=2, ensure_ascii=False),
            "```",
            "",
            "## Candidate Writer Result",
            "```json",
            json.dumps(writer_result, indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    )

    out = write_artifact("patch_execution", body)
    payload = {
        "ok": True,
        "task_id": args.task_id,
        "mode": args.mode,
        "patch_plan": str(patch_plan),
        "patch_plan_source": patch_plan_source,
        "writer_patch_plan_verified": writer_patch_plan_verified,
        "writer_result_kind": writer_result_kind,
        "target_files": target_files,
        "arm_result": arm_result,
        "writer_result": writer_result,
        "artifact": str(out),
    }

    print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else f"Wrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
