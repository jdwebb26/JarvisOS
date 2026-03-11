#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT.parent
ARTIFACT_ROOT = WORKSPACE / "artifacts" / "qwen_live"

APPROVAL_PATH = ROOT / "runtime" / "core" / "qwen_approval_state.json"
WRITE_GATE_PATH = ROOT / "runtime" / "core" / "qwen_write_gate.json"
LIVE_APPLY_PATH = ROOT / "runtime" / "core" / "qwen_live_apply.py"
VENV_PYTHON = ROOT / ".venv-qwen-agent" / "bin" / "python"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.artifact_store import write_text_artifact
from runtime.core.execution_contracts import record_backend_execution_request, record_backend_execution_result
from runtime.core.models import TaskStatus
from runtime.core.task_store import add_checkpoint, load_task, save_task, transition_task


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


def latest_candidate_artifact() -> Path | None:
    direct_candidates = []

    for latest_name in ("latest_candidate_write.md",):
        for day_dir in sorted(ARTIFACT_ROOT.glob("20*-*-*"), reverse=True):
            p = day_dir / latest_name
            if p.exists():
                direct_candidates.append(p)

    numbered_candidates = sorted(
        ARTIFACT_ROOT.glob("20*-*-*/*_candidate_write.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    all_candidates = direct_candidates + [p for p in numbered_candidates if p not in direct_candidates]
    return all_candidates[0] if all_candidates else None


def parse_candidate_artifact(text: str) -> tuple[str | None, str | None]:
    target_match = re.search(r"^- target_file: (.+)$", text, flags=re.MULTILINE)
    candidate_match = re.search(r"^- candidate_file: (.+)$", text, flags=re.MULTILINE)

    target_file = target_match.group(1).strip() if target_match else None
    candidate_file = candidate_match.group(1).strip() if candidate_match else None
    return target_file, candidate_file


def default_smoke_cmd(target_file: Path) -> str:
    if target_file.name == "local_executor.py":
        smoke_script = ROOT / "runtime" / "core" / "live_apply_smoke_local_executor.py"
        if VENV_PYTHON.exists() and smoke_script.exists():
            return f"{VENV_PYTHON} {smoke_script}"
    return ""


def run_live_apply(
    *,
    target_file: Path,
    candidate_file: Path,
    smoke_cmd: str,
    dry_run: bool,
) -> tuple[bool, dict, str]:
    python_bin = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

    cmd = [
        python_bin,
        str(LIVE_APPLY_PATH),
        "--target-file",
        str(target_file),
        "--candidate-file",
        str(candidate_file),
        "--json",
    ]

    if smoke_cmd:
        cmd.extend(["--smoke-cmd", smoke_cmd])

    if dry_run:
        cmd.append("--dry-run")

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    try:
        payload = json.loads(stdout) if stdout else {}
    except Exception:
        payload = {
            "ok": False,
            "error": f"Could not parse qwen_live_apply JSON. stdout={stdout[:1200]} stderr={stderr[:1200]}",
        }

    if proc.returncode != 0 and "error" not in payload:
        payload["error"] = stderr[:1200] or stdout[:1200] or f"qwen_live_apply exited with {proc.returncode}"

    ok = bool(payload.get("ok"))
    raw_msg = stderr[:1200] or stdout[:1200]
    return ok, payload, raw_msg


def write_artifact(name: str, body: str) -> Path:
    out = today_dir() / f"{now_stamp()}_{name}.md"
    out.write_text(body, encoding="utf-8")
    latest = today_dir() / f"latest_{name}.md"
    latest.write_text(body, encoding="utf-8")
    return out


def operator_handoff(*, ready: bool, dry_run: bool, pre_status: str | None, post_status: str | None, reasons: list[str], live_apply_ok: bool, live_apply_result: dict) -> tuple[str, str]:
    if not ready:
        blockers = "; ".join(reasons[:3]) if reasons else "unknown prerequisites"
        return (
            f"Candidate apply is blocked. Resolve approval, write-gate, or target-file prerequisites first: {blockers}.",
            "Clear the listed prerequisites, confirm the task is still ready_to_ship, then retry apply.",
        )
    if dry_run and live_apply_ok:
        return (
            "Dry run passed. Approval and write-gate look good, and the task remains ready_to_ship for a real live apply.",
            "Run live apply without --dry-run when you are ready to ship the candidate.",
        )
    if live_apply_ok and live_apply_result.get("applied") and not live_apply_result.get("rolled_back"):
        if post_status == TaskStatus.SHIPPED.value:
            return (
                "Live apply succeeded. The task is now shipped and waiting for publish-complete or final verification.",
                "Confirm the linked artifact, then run publish-complete to land the task in completed.",
            )
        elif post_status == TaskStatus.COMPLETED.value:
            return (
                "Live apply succeeded and the task already reached completed.",
                "Confirm the published output and close the loop with the operator.",
            )
        return (
            f"Live apply succeeded and task moved from {pre_status} to {post_status}.",
            "Verify runtime behavior and publish-complete next.",
        )
    if live_apply_result.get("rolled_back"):
        return (
            "Live apply attempted changes and rolled them back. The task did not advance to shipped.",
            "Inspect rollback details, fix the candidate or smoke command, then rerun apply.",
        )
    if ready and not live_apply_ok:
        return (
            "Live apply failed before reaching a clean shipped/completed handoff.",
            "Inspect live_apply_result and checkpoint notes, then decide whether to retry, repair, or cancel the apply path.",
        )
    if ready:
        return (
            "Candidate apply ran but did not produce a clear shipped/completed handoff.",
            "Inspect live_apply_result to decide whether to retry, repair, or cancel the apply path.",
        )
    return ("Candidate apply was not run.", "Inspect prerequisites and operator inputs.")


def register_live_apply_artifact(
    *,
    task_id: str,
    live_apply_result: dict,
    actor: str = "qwen_candidate_applier",
    lane: str = "apply",
) -> dict | None:
    artifact_path_str = str(live_apply_result.get("artifact") or "").strip()
    if not artifact_path_str:
        return None

    artifact_path = Path(artifact_path_str)
    if not artifact_path.exists():
        return None

    content = artifact_path.read_text(encoding="utf-8", errors="replace")
    target_name = Path(str(live_apply_result.get("target_file") or "target")).name
    summary = (
        f"Live apply result for {target_name}; "
        f"applied={bool(live_apply_result.get('applied'))}; "
        f"rolled_back={bool(live_apply_result.get('rolled_back'))}; "
        f"smoke_ok={bool(live_apply_result.get('smoke_ok'))}"
    )

    return write_text_artifact(
        task_id=task_id,
        artifact_type="live_apply_report",
        title=f"Live Apply Report — {target_name}",
        summary=summary,
        content=content,
        actor=actor,
        lane=lane,
        root=ROOT,
    )


def record_qwen_live_apply_execution(
    *,
    task_id: str | None,
    target_file: str,
    candidate_file: str,
    smoke_cmd: str,
    dry_run: bool,
    ready: bool,
    live_apply_ok: bool,
    live_apply_result: dict,
    linked_live_apply_artifact: dict | None,
    artifact_path: str,
    root: Path = ROOT,
) -> dict | None:
    if not task_id:
        return None
    task = load_task(task_id, root=root)
    if task is None:
        return None

    routing_meta = (task.backend_metadata or {}).get("routing") or {}
    request = record_backend_execution_request(
        task_id=task_id,
        actor="qwen_candidate_applier",
        lane="apply",
        request_kind="qwen_live_apply",
        execution_backend=task.execution_backend or "qwen_executor",
        provider_id=str(routing_meta.get("provider_id") or "qwen"),
        model_name=task.assigned_model or "Qwen3.5-35B",
        routing_decision_id=routing_meta.get("routing_decision_id"),
        provider_adapter_result_id=routing_meta.get("provider_adapter_result_id"),
        input_summary=f"Apply candidate for {Path(target_file).name if target_file else task_id}",
        input_refs={
            "target_file": target_file,
            "candidate_file": candidate_file,
            "smoke_cmd": smoke_cmd,
            "dry_run": dry_run,
        },
        source_refs={"task_source_message_id": task.source_message_id},
        status="pending" if ready else "blocked",
        root=root,
    )

    if not ready:
        result_status = "blocked"
    elif dry_run and live_apply_ok:
        result_status = "dry_run"
    elif live_apply_result.get("rolled_back"):
        result_status = "rolled_back"
    elif live_apply_ok and live_apply_result.get("applied"):
        result_status = "completed"
    else:
        result_status = "failed"

    result = record_backend_execution_result(
        backend_execution_request_id=request.backend_execution_request_id,
        task_id=task_id,
        actor="qwen_candidate_applier",
        lane="apply",
        request_kind="qwen_live_apply",
        execution_backend=task.execution_backend or "qwen_executor",
        provider_id=str(routing_meta.get("provider_id") or "qwen"),
        model_name=task.assigned_model or "Qwen3.5-35B",
        status=result_status,
        candidate_artifact_id=str((linked_live_apply_artifact or {}).get("artifact_id") or "") or None,
        outcome_summary=(
            "live apply blocked"
            if not ready
            else "live apply dry run passed"
            if dry_run and live_apply_ok
            else "live apply completed"
            if live_apply_ok and live_apply_result.get("applied") and not live_apply_result.get("rolled_back")
            else "live apply rolled back"
            if live_apply_result.get("rolled_back")
            else "live apply failed"
        ),
        error=str(live_apply_result.get("error") or ""),
        source_refs={
            "artifact_path": artifact_path,
            "live_apply_artifact": str(live_apply_result.get("artifact") or ""),
        },
        metadata={
            "target_file": target_file,
            "candidate_file": candidate_file,
            "smoke_cmd": smoke_cmd,
            "dry_run": dry_run,
            "ready": ready,
            "applied": bool(live_apply_result.get("applied")),
            "rolled_back": bool(live_apply_result.get("rolled_back")),
        },
        root=root,
    )
    task.backend_metadata.setdefault("execution_contracts", {})
    task.backend_metadata["execution_contracts"]["latest_backend_execution_request_id"] = request.backend_execution_request_id
    task.backend_metadata["execution_contracts"]["latest_backend_execution_result_id"] = result.backend_execution_result_id
    save_task(task, root=root)
    return {
        "backend_execution_request_id": request.backend_execution_request_id,
        "backend_execution_result_id": result.backend_execution_result_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply an approved ready_to_ship candidate by delegating to qwen_live_apply."
    )
    parser.add_argument("--task-id", default="")
    parser.add_argument("--target-file", default="")
    parser.add_argument("--candidate-file", default="")
    parser.add_argument("--smoke-cmd", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

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

    candidate_artifact = latest_candidate_artifact()
    artifact_target = None
    artifact_candidate = None
    if candidate_artifact is not None:
        artifact_text = candidate_artifact.read_text(encoding="utf-8", errors="replace")
        artifact_target, artifact_candidate = parse_candidate_artifact(artifact_text)

    task_id = args.task_id or approval.get("approved_task_id")
    target_path_str = args.target_file or artifact_target or ""
    candidate_path_str = args.candidate_file or artifact_candidate or ""

    target_file = Path(target_path_str) if target_path_str else None
    candidate_file = Path(candidate_path_str) if candidate_path_str else None

    task = load_task(task_id, root=ROOT) if task_id else None
    pre_status = task.status if task else None
    post_status = pre_status

    reasons: list[str] = []
    if not task_id:
        reasons.append("no task id was provided and approval state has no approved_task_id")
    if task is None:
        reasons.append(f"task not found: {task_id}")
    if approval.get("approved_task_id") is None:
        reasons.append("approval file has no approved_task_id")
    if gate.get("approved_task_id") is None:
        reasons.append("write gate has no approved_task_id")
    if approval.get("approved_task_id") != gate.get("approved_task_id"):
        reasons.append("approval task id does not match write gate task id")
    if approval.get("mode") != "apply_live":
        reasons.append("approval mode is not apply_live")
    if not gate.get("enabled"):
        reasons.append("write gate is disabled")
    if not target_path_str:
        reasons.append("no target_file was resolved")
    if not candidate_path_str:
        reasons.append("no candidate_file was resolved")
    if target_file and str(target_file) not in set(gate.get("allowed_paths", [])):
        reasons.append("target file is outside the allowlist")
    if target_file and not target_file.exists():
        reasons.append(f"target file does not exist: {target_file}")
    if candidate_file and not candidate_file.exists():
        reasons.append(f"candidate file does not exist: {candidate_file}")
    if task and task.status not in {TaskStatus.READY_TO_SHIP.value, TaskStatus.SHIPPED.value}:
        reasons.append(f"task is not ready_to_ship or shipped: current_status={task.status}")

    smoke_cmd = args.smoke_cmd.strip()
    if not smoke_cmd and target_file is not None:
        smoke_cmd = default_smoke_cmd(target_file)

    live_apply_ok = False
    live_apply_result: dict = {
        "ok": False,
        "error": "not run",
    }
    live_apply_raw = ""
    status_note = "not run"

    ready = len(reasons) == 0

    if ready and target_file and candidate_file:
        live_apply_ok, live_apply_result, live_apply_raw = run_live_apply(
            target_file=target_file,
            candidate_file=candidate_file,
            smoke_cmd=smoke_cmd,
            dry_run=bool(args.dry_run),
        )

        if live_apply_ok and args.dry_run:
            status_note = "dry run passed; task remains ready_to_ship"

        elif live_apply_ok and live_apply_result.get("applied") and not live_apply_result.get("rolled_back"):
            linked_artifact = None
            artifact_id = ""
            artifact_link_error = ""

            try:
                linked_artifact = register_live_apply_artifact(
                    task_id=task_id,
                    live_apply_result=live_apply_result,
                )
                artifact_id = str((linked_artifact or {}).get("artifact_id") or "")
            except Exception as exc:
                artifact_link_error = str(exc)[:400]

            if task is not None and task.status != TaskStatus.SHIPPED.value:
                details_lines = [
                    f"target_file={target_file}",
                    f"candidate_file={candidate_file}",
                    f"live_apply_artifact={live_apply_result.get('artifact', '')}",
                ]
                if artifact_id:
                    details_lines.append(f"artifact_id={artifact_id}")
                if artifact_link_error:
                    details_lines.append(f"artifact_link_error={artifact_link_error}")

                updated = transition_task(
                    task_id=task_id,
                    to_status=TaskStatus.SHIPPED.value,
                    actor="qwen_candidate_applier",
                    lane="apply",
                    summary="Live candidate apply succeeded",
                    root=ROOT,
                    details="\n".join(details_lines),
                )
                post_status = updated.status

                if artifact_id or artifact_link_error:
                    updated.final_outcome = (
                        "live_apply_succeeded_waiting_publish_complete"
                        if artifact_id
                        else "live_apply_succeeded_artifact_link_failed"
                    )
                    save_task(updated, root=ROOT)
            else:
                post_status = TaskStatus.SHIPPED.value if task is not None else pre_status
            status_note = "live apply succeeded; task transitioned to shipped"
        else:
            if task is not None and not args.dry_run:
                checkpoint = (
                    f"live apply did not ship task; "
                    f"ok={live_apply_result.get('ok')} "
                    f"applied={live_apply_result.get('applied')} "
                    f"rolled_back={live_apply_result.get('rolled_back')} "
                    f"error={live_apply_result.get('error', '')[:400]}"
                )
                add_checkpoint(task_id, checkpoint, root=ROOT)
            if live_apply_result.get("rolled_back"):
                status_note = "live apply rolled back; task left unchanged"
            else:
                status_note = "live apply did not reach shipped/completed; task left unchanged"

    operator_note, next_action = operator_handoff(
        ready=ready,
        dry_run=bool(args.dry_run),
        pre_status=pre_status,
        post_status=post_status,
        reasons=reasons,
        live_apply_ok=live_apply_ok,
        live_apply_result=live_apply_result,
    )

    summary = "\n".join(
        [
            "# Qwen Candidate Applier",
            "",
            f"- timestamp: {now_iso()}",
            f"- task_id: {task_id}",
            f"- ready: {str(ready).lower()}",
            f"- dry_run: {str(bool(args.dry_run)).lower()}",
            f"- pre_status: {pre_status}",
            f"- post_status: {post_status}",
            f"- target_file: {target_path_str}",
            f"- candidate_file: {candidate_path_str}",
            f"- candidate_artifact: {candidate_artifact}",
            f"- smoke_cmd: {smoke_cmd}",
            f"- live_apply_ok: {live_apply_ok}",
            f"- status_note: {status_note}",
            f"- operator_note: {operator_note}",
            f"- next_action: {next_action}",
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
            "## Reasons",
            "```json",
            json.dumps(reasons, indent=2, ensure_ascii=False),
            "```",
            "",
            "## Live Apply Result",
            "```json",
            json.dumps(live_apply_result, indent=2, ensure_ascii=False),
            "```",
            "",
            "## Linked Live Apply Artifact",
            "```json",
            json.dumps(linked_artifact if "linked_artifact" in locals() else None, indent=2, ensure_ascii=False),
            "```",
            "",
            "## Live Apply Raw",
            "```text",
            live_apply_raw,
            "```",
            "",
        ]
    )

    artifact = write_artifact("candidate_apply", summary)

    payload = {
        "ok": ready and live_apply_ok,
        "ready": ready,
        "dry_run": bool(args.dry_run),
        "task_id": task_id,
        "pre_status": pre_status,
        "post_status": post_status,
        "target_file": target_path_str,
        "candidate_file": candidate_path_str,
        "candidate_artifact": str(candidate_artifact) if candidate_artifact else "",
        "smoke_cmd": smoke_cmd,
        "live_apply_ok": live_apply_ok,
        "live_apply_result": live_apply_result,
        "linked_live_apply_artifact": linked_artifact if "linked_artifact" in locals() else None,
        "reasons": reasons,
        "status_note": status_note,
        "operator_note": operator_note,
        "next_action": next_action,
        "artifact": str(artifact),
    }
    execution_contract = record_qwen_live_apply_execution(
        task_id=task_id if isinstance(task_id, str) else None,
        target_file=target_path_str,
        candidate_file=candidate_path_str,
        smoke_cmd=smoke_cmd,
        dry_run=bool(args.dry_run),
        ready=ready,
        live_apply_ok=live_apply_ok,
        live_apply_result=live_apply_result,
        linked_live_apply_artifact=linked_artifact if "linked_artifact" in locals() else None,
        artifact_path=str(artifact),
    )
    payload["execution_contract"] = execution_contract

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Wrote: {artifact}")

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
