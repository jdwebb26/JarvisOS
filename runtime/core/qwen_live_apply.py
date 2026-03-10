#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path("/home/rollan/.openclaw/workspace/jarvis-v5")
WORKSPACE = Path("/home/rollan/.openclaw/workspace")
ARTIFACT_ROOT = WORKSPACE / "artifacts" / "qwen_live"

GATE_PATH = ROOT / "runtime" / "core" / "qwen_write_gate.json"
APPROVAL_PATH = ROOT / "runtime" / "core" / "qwen_approval_state.json"


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


def validate_python(path: Path) -> tuple[bool, str]:
    p = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        capture_output=True,
        text=True,
    )
    if p.returncode == 0:
        return True, "py_compile ok"
    msg = (p.stderr or p.stdout or "").strip()
    return False, (msg[:600] if msg else "py_compile failed")


def run_smoke_cmd(smoke_cmd: str, timeout_sec: int) -> tuple[bool, int, str, str]:
    out_dir = today_dir() / "smoke_logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"{now_stamp()}_live_apply_smoke.log"

    p = subprocess.run(
        smoke_cmd,
        shell=True,
        executable="/bin/bash",
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )

    combined = []
    if p.stdout:
        combined.append("STDOUT:\n" + p.stdout.rstrip())
    if p.stderr:
        combined.append("STDERR:\n" + p.stderr.rstrip())

    log_path.write_text(
        ("\n\n".join(combined).rstrip() + "\n") if combined else "",
        encoding="utf-8",
    )

    return p.returncode == 0, p.returncode, str(log_path), (p.stderr or p.stdout or "").strip()[:600]


def write_artifact(result: dict, approval: dict, gate: dict) -> Path:
    out_dir = today_dir()
    out_path = out_dir / f"{now_stamp()}_live_apply.md"

    lines = [
        "# Qwen Live Apply",
        "",
        f"- timestamp: {now_iso()}",
        f"- mode: {'dry_run' if result['dry_run'] else 'apply_live'}",
        f"- target_file: {result['target_file']}",
        f"- candidate_file: {result['candidate_file']}",
        f"- candidate_matches_live: {result['candidate_matches_live']}",
        f"- syntax_valid: {result['syntax_valid']}",
        f"- validation_msg: {result['validation_msg']}",
        f"- live_syntax_valid: {result['live_syntax_valid']}",
        f"- live_validation_msg: {result['live_validation_msg']}",
        f"- backup_path: {result['backup_path'] or ''}",
        f"- smoke_cmd: {result['smoke_cmd'] or ''}",
        f"- smoke_ran: {result['smoke_ran']}",
        f"- smoke_ok: {result['smoke_ok']}",
        f"- smoke_exit_code: {result['smoke_exit_code']}",
        f"- smoke_log: {result['smoke_log'] or ''}",
        f"- applied: {result['applied']}",
        f"- rolled_back: {result['rolled_back']}",
        f"- error: {(result['error'] or '')[:300]}",
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
        "## Outcome",
        "- Live file unchanged during dry-run." if result["dry_run"] else "- Live file apply attempted.",
        "- Backup created before apply." if result["backup_path"] else "- No backup created.",
        "- Smoke executed." if result["smoke_ran"] else "- No smoke executed.",
        "- Rollback executed." if result["rolled_back"] else "- No rollback executed.",
        "",
    ]

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    latest = out_dir / "latest_live_apply.md"
    latest.write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Controlled live apply for approved Qwen candidates.")
    ap.add_argument("--target-file", required=True)
    ap.add_argument("--candidate-file", required=True)
    ap.add_argument("--smoke-cmd", default="")
    ap.add_argument("--smoke-timeout-sec", type=int, default=120)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    target_file = Path(args.target_file)
    candidate_file = Path(args.candidate_file)

    approval = read_json(APPROVAL_PATH, {})
    gate = read_json(
        GATE_PATH,
        {
            "enabled": False,
            "mode": "allowlist_only",
            "approved_task_id": None,
            "allowed_paths": [],
        },
    )

    result = {
        "ok": False,
        "dry_run": bool(args.dry_run),
        "target_file": str(target_file),
        "candidate_file": str(candidate_file),
        "candidate_matches_live": False,
        "syntax_valid": None,
        "validation_msg": "not validated",
        "live_syntax_valid": None,
        "live_validation_msg": "not validated",
        "backup_path": "",
        "smoke_cmd": args.smoke_cmd or "",
        "smoke_ran": False,
        "smoke_ok": None,
        "smoke_exit_code": None,
        "smoke_log": "",
        "applied": False,
        "rolled_back": False,
        "artifact": "",
        "error": "",
    }

    try:
        if approval.get("approved_task_id") != gate.get("approved_task_id"):
            raise RuntimeError("Approval task id does not match write gate task id.")
        if not gate.get("enabled"):
            raise RuntimeError("Write gate is disabled.")
        if str(target_file) not in set(gate.get("allowed_paths", [])):
            raise RuntimeError("Target path is outside the allowlist.")
        if not target_file.exists():
            raise RuntimeError(f"Target file does not exist: {target_file}")
        if not candidate_file.exists():
            raise RuntimeError(f"Candidate file does not exist: {candidate_file}")

        result["candidate_matches_live"] = (target_file.read_bytes() == candidate_file.read_bytes())

        if candidate_file.suffix == ".py":
            syntax_valid, validation_msg = validate_python(candidate_file)
            result["syntax_valid"] = syntax_valid
            result["validation_msg"] = validation_msg
            if not syntax_valid:
                raise RuntimeError(f"Candidate validation failed: {validation_msg}")
        else:
            result["syntax_valid"] = None
            result["validation_msg"] = "not validated"

        if args.dry_run:
            result["ok"] = True
        else:
            backup_path = target_file.with_name(f"{target_file.name}.live_apply_backup_{now_stamp()}")
            shutil.copy2(target_file, backup_path)
            result["backup_path"] = str(backup_path)

            shutil.copy2(candidate_file, target_file)
            result["applied"] = True

            if target_file.suffix == ".py":
                live_ok, live_msg = validate_python(target_file)
                result["live_syntax_valid"] = live_ok
                result["live_validation_msg"] = live_msg
                if not live_ok:
                    shutil.copy2(backup_path, target_file)
                    result["rolled_back"] = True
                    raise RuntimeError(f"Live validation failed after apply: {live_msg}")
            else:
                result["live_syntax_valid"] = None
                result["live_validation_msg"] = "not validated"

            if args.smoke_cmd:
                result["smoke_ran"] = True
                smoke_ok, smoke_exit, smoke_log, smoke_msg = run_smoke_cmd(
                    args.smoke_cmd,
                    args.smoke_timeout_sec,
                )
                result["smoke_ok"] = smoke_ok
                result["smoke_exit_code"] = smoke_exit
                result["smoke_log"] = smoke_log

                if not smoke_ok:
                    shutil.copy2(backup_path, target_file)
                    result["rolled_back"] = True
                    raise RuntimeError(f"Smoke failed after apply: exit={smoke_exit} {smoke_msg}")

            result["ok"] = True

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

        if result["applied"] and not result["rolled_back"] and result["backup_path"]:
            try:
                shutil.copy2(Path(result["backup_path"]), target_file)
                result["rolled_back"] = True
            except Exception as restore_e:
                result["error"] += f" | rollback_failed: {type(restore_e).__name__}: {restore_e}"

    artifact = write_artifact(result, approval, gate)
    result["artifact"] = str(artifact)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Wrote: {artifact}")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
