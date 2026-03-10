#!/usr/bin/env python3
import argparse
import json
import re
from datetime import datetime
from pathlib import Path

WORKSPACE = Path("/home/rollan/.openclaw/workspace")
ARTIFACT_ROOT = WORKSPACE / "artifacts" / "qwen_live"
APPROVAL_PATH = WORKSPACE / "jarvis-v5" / "runtime" / "core" / "qwen_approval_state.json"
WRITE_GATE_PATH = WORKSPACE / "jarvis-v5" / "runtime" / "core" / "qwen_write_gate.json"


def now_iso() -> str:
    return datetime.now().isoformat()


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def today_dir() -> Path:
    out = ARTIFACT_ROOT / datetime.now().strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)
    return out


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


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


def main() -> int:
    ap = argparse.ArgumentParser(description="Check whether an approved patch is eligible for narrow write mode.")
    ap.add_argument("--patch-plan", default="", help="Optional explicit patch plan path.")
    ap.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = ap.parse_args()

    approval = read_json(
        APPROVAL_PATH,
        {
            "approved_task_id": None,
            "approved_at": None,
            "approval_note": None,
            "mode": "dry_run",
        },
    )
    gate = read_json(
        WRITE_GATE_PATH,
        {
            "enabled": False,
            "mode": "allowlist_only",
            "approved_task_id": None,
            "allowed_paths": [],
            "note": None,
        },
    )

    approved_task_id = approval.get("approved_task_id")
    patch_plan = Path(args.patch_plan).resolve() if args.patch_plan.strip() else latest_patch_plan(str(approved_task_id or ""))
    patch_plan_source = "explicit" if args.patch_plan.strip() else "task_latest_or_global_latest"
    if patch_plan is None:
        out = write_artifact(
            "write_gate_check",
            "\n".join(
                [
                    "# Qwen Write Gate Check",
                    "",
                    f"- timestamp: {now_iso()}",
                    "- eligible: false",
                    "- reason: no latest patch plan found",
                    "",
                ]
            ),
        )
        payload = {"ok": True, "eligible": False, "reason": "no latest patch plan", "artifact": str(out)}
        print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else f"Wrote: {out}")
        return 0

    patch_text = patch_plan.read_text(encoding="utf-8", errors="replace")
    target_files = extract_target_files(patch_text)

    gate_task_id = gate.get("approved_task_id")
    gate_enabled = bool(gate.get("enabled"))
    allowed_paths = set(gate.get("allowed_paths", []))

    eligible = True
    reasons = []

    if approved_task_id is None:
        eligible = False
        reasons.append("approval file has no approved_task_id")
    if gate_task_id is None:
        eligible = False
        reasons.append("write gate has no approved_task_id")
    if approved_task_id != gate_task_id:
        eligible = False
        reasons.append("approval task id does not match write gate task id")
    if not gate_enabled:
        eligible = False
        reasons.append("write gate is disabled")
    if not target_files:
        eligible = False
        reasons.append("patch plan has no extracted target files")
    if any(path not in allowed_paths for path in target_files):
        eligible = False
        reasons.append("one or more target files are outside the allowlist")

    body = "\n".join(
        [
            "# Qwen Write Gate Check",
            "",
            f"- timestamp: {now_iso()}",
            f"- eligible: {str(eligible).lower()}",
            f"- patch_plan: {patch_plan}",
            f"- patch_plan_source: {patch_plan_source}",
            "",
            "## Approval State",
            "```json",
            json.dumps(approval, indent=2, ensure_ascii=False),
            "```",
            "",
            "## Write Gate",
            "```json",
            json.dumps(gate, indent=2, ensure_ascii=False),
            "```",
            "",
            "## Target Files",
            "```json",
            json.dumps(target_files, indent=2, ensure_ascii=False),
            "```",
            "",
            "## Reasons",
            "```json",
            json.dumps(reasons, indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    )

    out = write_artifact("write_gate_check", body)
    payload = {
        "ok": True,
        "eligible": eligible,
        "artifact": str(out),
        "patch_plan": str(patch_plan),
        "patch_plan_source": patch_plan_source,
        "target_files": target_files,
        "reasons": reasons,
    }

    print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else f"Wrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
