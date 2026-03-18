#!/usr/bin/env python3
"""Ralph v1 — Bounded autonomy loop.

One cycle. One task. One step forward. Stop at approval.

Cycle order (highest stage wins, so the queue drains forward):
  1. Health gates → any fail → emit blocked digest → exit(0)
  2. Stage scan (pick first match):
     a. task in waiting_review  + execution_backend==ralph_adapter
        + latest review approved
        → request_approval → exit
     b. task in queued + eligible
        → take ownership → start → call Qwen (HAL proxy) → complete
        → request_review(archimedes) → exit
  3. Idle → emit idle digest → exit(0)

State mapping (Ralph labels → live TaskStatus values):
  running_hal        → TaskStatus.RUNNING
  waiting_archimedes → TaskStatus.WAITING_REVIEW
  waiting_approval   → TaskStatus.WAITING_APPROVAL
  done               → TaskStatus.COMPLETED
  failed             → TaskStatus.FAILED
  blocked            → TaskStatus.BLOCKED

Allowed transitions exercised by Ralph:
  queued           → running        (start_task)
  running          → completed      (complete_task)
  running          → failed         (fail_task)
  running          → blocked        (block_task)
  completed        → waiting_review (request_review — via task_store.transition_task)
  waiting_review   → waiting_approval (request_approval — via task_store.transition_task)

Retry paths (operator-initiated only, not touched by Ralph v1):
  failed  → queued  (explicit retry)
  blocked → queued  (explicit retry)
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Top-level imports so tests can patch them on the module.
from runtime.core.discord_event_router import emit_event  # noqa: E402

log = logging.getLogger("ralph.v1")

ACTOR = "ralph"
LANE = "ralph"

# Execution backends Ralph is eligible to take ownership of.
# ralph_adapter = explicitly routed to Ralph.
# qwen_executor / qwen_planner = routed to Qwen; Ralph may pick these up if stale.
# unassigned = not yet routed; Ralph can take.
ELIGIBLE_BACKENDS = frozenset({"ralph_adapter", "qwen_executor", "qwen_planner", "unassigned"})

# Task types Ralph will not touch in v1 (belong to dedicated pipelines).
BLOCKED_TASK_TYPES = frozenset({"deploy"})

# Risk levels Ralph will not touch in v1.
BLOCKED_RISK_LEVELS = frozenset({"high_stakes"})

# Staleness before Ralph steals a qwen_executor/qwen_planner task (seconds).
# ralph_adapter and unassigned tasks are picked up immediately.
STEAL_AFTER_SECONDS = 3600  # 1 hour

# A Ralph-owned task stuck in "running" longer than this is considered stale
# and will be recovered (transitioned to "failed") at cycle start.
STALE_RUNNING_SECONDS = 600  # 10 minutes (HAL timeout is 120s + overhead)


# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------

def _load_env(root: Path) -> None:
    """Load secrets from ~/.openclaw/secrets.env then ~/.openclaw/.env (first wins)."""
    home = Path.home()
    for env_file in [home / ".openclaw" / "secrets.env", home / ".openclaw" / ".env"]:
        if not env_file.exists():
            continue
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


# ---------------------------------------------------------------------------
# Health gates
# ---------------------------------------------------------------------------

def _check_gateway(url: str = "http://127.0.0.1:18789/health") -> dict[str, Any]:
    try:
        import requests as _req
        r = _req.get(url, timeout=5)
        if r.ok and r.json().get("ok"):
            return {"ok": True, "gate": "gateway"}
        return {"ok": False, "gate": "gateway", "error": f"http {r.status_code}"}
    except Exception as exc:
        return {"ok": False, "gate": "gateway", "error": str(exc)}


def _check_model_backend() -> dict[str, Any]:
    base = os.getenv("QWEN_AGENT_MODEL_SERVER", "http://100.70.114.34:1234/v1").rstrip("/")
    api_key = os.getenv("QWEN_AGENT_API_KEY", "lm-studio")
    try:
        import requests as _req
        r = _req.get(
            f"{base}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=8,
        )
        if r.ok:
            models = [m.get("id", "") for m in (r.json().get("data") or [])]
            if models:
                return {"ok": True, "gate": "model_backend", "models": models[:3]}
            return {"ok": False, "gate": "model_backend", "error": "no models loaded"}
        return {"ok": False, "gate": "model_backend", "error": f"http {r.status_code}"}
    except Exception as exc:
        return {"ok": False, "gate": "model_backend", "error": str(exc)}


def _check_hal_status(root: Path) -> dict[str, Any]:
    """Non-blocking: HAL error state is a warning, not a hard block for v1."""
    try:
        from runtime.core.agent_status_store import get_agent_status
        status = get_agent_status("hal", root=root)
        if status is None:
            return {"ok": True, "gate": "hal_status", "note": "no status file — assuming ok"}
        if status.get("state") == "error":
            return {
                "ok": False,
                "gate": "hal_status",
                "error": f"HAL state=error: {status.get('headline', 'unknown')}",
            }
        return {"ok": True, "gate": "hal_status", "state": status.get("state", "unknown")}
    except Exception as exc:
        return {"ok": True, "gate": "hal_status", "note": f"check skipped: {exc}"}


def _check_discord_outbox(root: Path) -> dict[str, Any]:
    """Fail if >20 outbox entries are stuck failed (delivery path broken)."""
    outbox_dir = root / "state" / "discord_outbox"
    if not outbox_dir.exists():
        return {"ok": True, "gate": "discord_outbox", "note": "outbox dir absent"}
    try:
        failed = 0
        pending = 0
        for p in outbox_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                s = data.get("status", "")
                if s in ("failed", "error"):
                    failed += 1
                elif s == "pending":
                    pending += 1
            except Exception:
                continue
        if failed > 20:
            return {
                "ok": False,
                "gate": "discord_outbox",
                "error": f"{failed} failed outbox entries — notification delivery broken",
            }
        return {"ok": True, "gate": "discord_outbox", "pending": pending, "failed": failed}
    except Exception as exc:
        return {"ok": True, "gate": "discord_outbox", "note": f"check skipped: {exc}"}


def run_health_gates(root: Path) -> tuple[bool, list[dict[str, Any]]]:
    """Run all health gates. Returns (all_healthy, gate_results_list)."""
    results = [
        _check_gateway(),
        _check_model_backend(),
        _check_hal_status(root),
        _check_discord_outbox(root),
    ]
    return all(r["ok"] for r in results), results


# ---------------------------------------------------------------------------
# Task eligibility
# ---------------------------------------------------------------------------

def _task_age_seconds(task: Any) -> float:
    try:
        created = datetime.datetime.fromisoformat(task.created_at)
        now = datetime.datetime.now(tz=created.tzinfo)
        return (now - created).total_seconds()
    except Exception:
        return 9999.0


def _is_eligible_queued(task: Any, *, root: Path) -> tuple[bool, str]:
    """Return (eligible, reason_if_not) for a candidate queued task."""
    from runtime.core.models import TaskStatus

    if task.status != TaskStatus.QUEUED.value:
        return False, f"status={task.status}"

    if task.task_type in BLOCKED_TASK_TYPES:
        return False, f"task_type={task.task_type} blocked in v1"

    if task.risk_level in BLOCKED_RISK_LEVELS:
        return False, f"risk_level={task.risk_level} blocked in v1"

    if task.execution_backend not in ELIGIBLE_BACKENDS:
        return False, f"execution_backend={task.execution_backend} not eligible"

    # For non-ralph backends, only steal if sufficiently stale.
    if task.execution_backend in {"qwen_executor", "qwen_planner"}:
        age = _task_age_seconds(task)
        if age < STEAL_AFTER_SECONDS:
            return (
                False,
                f"execution_backend={task.execution_backend} not stale yet "
                f"({age:.0f}s < {STEAL_AFTER_SECONDS}s)",
            )

    # Defense-in-depth: never re-execute a task that already has completed
    # execution (final_outcome), a review, and an approval record.
    # This catches any future bug that incorrectly re-queues a finished task.
    if (
        task.final_outcome
        and task.related_review_ids
        and task.related_approval_ids
    ):
        return (
            False,
            "already has final_outcome + review + approval (re-queue guard)",
        )

    # Check dependency block.
    try:
        from runtime.core.task_store import task_dependency_summary
        dep = task_dependency_summary(task.task_id, root=root)
        if dep.get("hard_block"):
            return False, f"dependency blocked: {dep.get('reason', '')}"
    except Exception:
        pass  # If check fails, allow task (dependency check is best-effort)

    return True, ""


def pick_queued_task(root: Path) -> Optional[Any]:
    """Return the best eligible queued task, or None.

    Priority: ralph_adapter tasks first, then others ordered oldest-first.
    """
    from runtime.core.task_store import list_tasks
    from runtime.core.models import TaskStatus

    tasks = list_tasks(root=root, limit=200)
    queued = [t for t in tasks if t.status == TaskStatus.QUEUED.value]

    # ralph_adapter tasks take priority; within group, oldest first.
    ralph_first = sorted(
        [t for t in queued if t.execution_backend == "ralph_adapter"],
        key=lambda t: t.created_at,
    )
    others = sorted(
        [t for t in queued if t.execution_backend != "ralph_adapter"],
        key=lambda t: t.created_at,
    )

    for task in ralph_first + others:
        eligible, reason = _is_eligible_queued(task, root=root)
        if eligible:
            log.info("Selected queued task %s  backend=%s  req=%s",
                     task.task_id, task.execution_backend, task.normalized_request[:60])
            return task
        log.debug("Skip %s: %s", task.task_id, reason)

    return None


def pick_review_ready_task(root: Path) -> Optional[Any]:
    """Find a Ralph-owned waiting_review task whose review is now approved."""
    from runtime.core.task_store import list_tasks
    from runtime.core.models import TaskStatus
    from runtime.core.review_store import latest_review_for_task

    tasks = list_tasks(root=root, limit=200)
    for task in tasks:
        if task.status != TaskStatus.WAITING_REVIEW.value:
            continue
        if task.execution_backend != "ralph_adapter":
            continue
        review = latest_review_for_task(task.task_id, root=root)
        if review and review.status == "approved":
            log.info("Review-ready task: %s  review=%s", task.task_id, review.review_id)
            return task
    return None


def pick_pending_review_task(root: Path) -> Optional[Any]:
    """Find a Ralph-owned waiting_review task with a pending review."""
    from runtime.core.task_store import list_tasks
    from runtime.core.models import TaskStatus
    from runtime.core.review_store import latest_review_for_task

    tasks = list_tasks(root=root, limit=200)
    for task in tasks:
        if task.status != TaskStatus.WAITING_REVIEW.value:
            continue
        if task.execution_backend != "ralph_adapter":
            continue
        review = latest_review_for_task(task.task_id, root=root)
        if review and review.status == "pending":
            log.info("Pending-review task: %s  review=%s", task.task_id, review.review_id)
            return task
    return None


# ---------------------------------------------------------------------------
# Stale-running recovery
# ---------------------------------------------------------------------------

def recover_stale_running(root: Path) -> Optional[str]:
    """Find and fail any Ralph-owned task stuck in 'running' beyond the threshold.

    Returns the recovered task_id or None.
    This runs once per cycle before any stage, so at most one task is recovered.
    """
    from runtime.core.task_store import list_tasks
    from runtime.core.models import TaskStatus
    from runtime.core.task_runtime import fail_task

    tasks = list_tasks(root=root, limit=200)
    for task in tasks:
        if task.status != TaskStatus.RUNNING.value:
            continue
        if task.execution_backend != "ralph_adapter":
            continue
        age = _task_age_seconds(task)
        # Use updated_at for age, since that reflects the last write
        try:
            updated = datetime.datetime.fromisoformat(task.updated_at)
            stale_age = (
                datetime.datetime.now(tz=updated.tzinfo) - updated
            ).total_seconds()
        except Exception:
            stale_age = age

        if stale_age < STALE_RUNNING_SECONDS:
            continue

        log.warning(
            "[RECOVERY] Stale running task %s (%.0fs since last update). Marking failed.",
            task.task_id, stale_age,
        )
        try:
            fail_task(
                root=root,
                task_id=task.task_id,
                actor=ACTOR,
                lane=LANE,
                reason=(
                    f"Stale-running recovery: task stuck in 'running' for "
                    f"{stale_age:.0f}s (threshold {STALE_RUNNING_SECONDS}s). "
                    f"Likely crashed mid-cycle."
                ),
            )
            emit_event(
                "warning", ACTOR,
                task_id=task.task_id,
                detail=f"Recovered stale running task {task.task_id} ({stale_age:.0f}s)",
                root=root,
            )
        except Exception as exc:
            log.error("Failed to recover stale task %s: %s", task.task_id, exc)
        return task.task_id
    return None


# ---------------------------------------------------------------------------
# Retry / requeue
# ---------------------------------------------------------------------------

def retry_task(task_id: str, *, root: Path) -> dict[str, Any]:
    """Requeue a failed or blocked Ralph-owned task for re-execution.

    Clears error state so the task is eligible for pickup.
    Returns a summary dict.
    """
    from runtime.core.task_store import load_task, save_task, transition_task
    from runtime.core.models import TaskStatus

    task = load_task(task_id, root=root)
    if task is None:
        return {"ok": False, "error": f"Task not found: {task_id}"}

    if task.execution_backend != "ralph_adapter":
        return {"ok": False, "error": f"Not a Ralph-owned task (backend={task.execution_backend})"}

    if task.status not in {TaskStatus.FAILED.value, TaskStatus.BLOCKED.value}:
        return {"ok": False, "error": f"Task status is '{task.status}', not failed or blocked"}

    previous_status = task.status

    # Clear error state so the task is eligible for dispatch
    task.error_count = 0
    task.last_error = ""
    task.final_outcome = ""
    task.related_review_ids = []
    task.related_approval_ids = []
    task.checkpoint_summary = ""
    save_task(task, root=root)

    transition_task(
        task_id=task_id,
        to_status=TaskStatus.QUEUED.value,
        actor=ACTOR,
        lane=LANE,
        summary=f"Ralph retry: {previous_status} → queued",
        root=root,
        details=f"Operator-initiated retry from {previous_status}",
    )

    log.info("[RETRY] %s: %s → queued", task_id, previous_status)
    return {
        "ok": True,
        "task_id": task_id,
        "previous_status": previous_status,
        "new_status": "queued",
    }


# ---------------------------------------------------------------------------
# HAL proxy — Qwen execution
# ---------------------------------------------------------------------------

def call_hal_via_qwen(task: Any) -> dict[str, Any]:
    """Execute task via Qwen API.  Returns {ok, content, error, elapsed, model}.

    This is Ralph v1's HAL proxy. v2 will dispatch via real ACP/HAL session.
    """
    import requests as _req

    base = os.getenv("QWEN_AGENT_MODEL_SERVER", "http://100.70.114.34:1234/v1").rstrip("/")
    model = os.getenv("QWEN_AGENT_MODEL", "qwen3.5-35b-a3b")
    api_key = os.getenv("QWEN_AGENT_API_KEY", "lm-studio")

    system_prompt = (
        "You are HAL, a precise technical executor inside the OpenClaw autonomous trading system. "
        "Complete the following task concisely and produce a structured result. "
        "Format: ## Result\n<what was done>\n## Output\n<deliverable>\n## Issues\n<any problems or none>. "
        "/no_think"
    )
    user_prompt = (task.normalized_request or task.raw_request or "").strip()

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    t0 = time.time()
    try:
        r = _req.post(f"{base}/chat/completions", headers=headers, json=payload, timeout=(8, 120))
        elapsed = round(time.time() - t0, 2)
        if not r.ok:
            return {"ok": False, "content": "", "error": f"http {r.status_code}: {r.text[:200]}",
                    "elapsed": elapsed, "model": model}
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        content = str((choice.get("message") or {}).get("content") or "").strip()
        if not content:
            return {"ok": False, "content": "", "error": "empty response from model",
                    "elapsed": elapsed, "model": model}
        return {"ok": True, "content": content, "error": "", "elapsed": elapsed, "model": model}
    except Exception as exc:
        return {"ok": False, "content": "", "error": str(exc),
                "elapsed": round(time.time() - t0, 2), "model": model}


def _record_hal_result(task: Any, result: dict[str, Any], *, root: Path) -> str:
    """Write BackendExecutionResultRecord. Returns the result record ID."""
    from runtime.core.execution_contracts import save_backend_execution_result
    from runtime.core.models import BackendExecutionResultRecord, new_id, now_iso

    record = BackendExecutionResultRecord(
        backend_execution_result_id=new_id("bkres"),
        backend_execution_request_id=task.backend_assignment_id or "",
        task_id=task.task_id,
        created_at=now_iso(),
        updated_at=now_iso(),
        actor=ACTOR,
        lane=LANE,
        request_kind=task.task_type or "general",
        execution_backend="ralph_adapter",
        provider_id="qwen",
        model_name=result.get("model", ""),
        status="completed" if result["ok"] else "failed",
        outcome_summary=result.get("content", "")[:500],
        error=result.get("error", ""),
        metadata={"elapsed_seconds": result.get("elapsed", 0.0)},
    )
    save_backend_execution_result(record, root=root)
    return record.backend_execution_result_id


# ---------------------------------------------------------------------------
# Archimedes proxy — Qwen review
# ---------------------------------------------------------------------------

def call_archimedes_via_qwen(task: Any, review_details: str) -> dict[str, Any]:
    """Evaluate HAL output via Qwen with Archimedes review persona.

    Returns {approved: bool, reason: str, elapsed: float, model: str}.
    """
    import requests as _req

    base = os.getenv("QWEN_AGENT_MODEL_SERVER", "http://100.70.114.34:1234/v1").rstrip("/")
    # Use the reviewer-tier model (35B) for reviews, not the default 9B.
    model = os.getenv("QWEN_REVIEW_MODEL", "qwen3.5-35b-a3b")
    api_key = os.getenv("QWEN_AGENT_API_KEY", "lm-studio")

    system_prompt = (
        "You are Archimedes, the technical reviewer for the OpenClaw autonomous system. "
        "Your job is to evaluate whether HAL's output meets the task requirements. "
        "Evaluate these criteria:\n"
        "1. Does the output directly answer the task request?\n"
        "2. Is the output well-structured and clear?\n"
        "3. Are there obvious factual errors or fabrications?\n"
        "4. Is the scope appropriate (not too broad, not too narrow)?\n\n"
        "Respond with EXACTLY this format:\n"
        "VERDICT: APPROVED or REJECTED\n"
        "REASON: <one paragraph explaining your decision>\n"
        "/no_think"
    )
    user_prompt = (
        f"## Task Request\n{task.normalized_request or task.raw_request}\n\n"
        f"## HAL Output\n{review_details}\n\n"
        "Evaluate the output above. Is it acceptable?"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 512,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    t0 = time.time()
    try:
        r = _req.post(f"{base}/chat/completions", headers=headers, json=payload, timeout=(8, 60))
        elapsed = round(time.time() - t0, 2)
        if not r.ok:
            # Transport/model error — NOT a review verdict. Mark as error so
            # stage_auto_review does not record a false rejection.
            return {"approved": None, "error": True,
                    "reason": f"Model error: http {r.status_code}: {r.text[:200]}",
                    "elapsed": elapsed, "model": model}
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        content = str((choice.get("message") or {}).get("content") or "").strip()
        if not content:
            return {"approved": None, "error": True,
                    "reason": "Empty response from reviewer model",
                    "elapsed": elapsed, "model": model}

        # Parse verdict
        content_upper = content.upper()
        if "VERDICT: APPROVED" in content_upper or "VERDICT:APPROVED" in content_upper:
            approved = True
        elif "VERDICT: REJECTED" in content_upper or "VERDICT:REJECTED" in content_upper:
            approved = False
        else:
            # If format is unclear, default to approved (fail-open for reviews,
            # since approval gate is the hard stop).
            approved = "REJECTED" not in content_upper
            log.warning("Archimedes verdict unclear, defaulting to %s: %s",
                        "approved" if approved else "rejected", content[:100])

        # Extract reason
        reason = content
        for prefix in ("REASON:", "REASON :", "Reason:"):
            if prefix in content:
                reason = content.split(prefix, 1)[1].strip()
                break

        return {"approved": approved, "reason": reason[:500], "elapsed": elapsed, "model": model}
    except Exception as exc:
        return {"approved": None, "error": True,
                "reason": f"Review call failed: {exc}",
                "elapsed": round(time.time() - t0, 2), "model": model}


# ---------------------------------------------------------------------------
# Cycle stages
# ---------------------------------------------------------------------------

def stage_auto_review(task: Any, *, root: Path) -> str:
    """Stage: waiting_review + pending review → invoke Archimedes via Qwen → record verdict.

    Returns: "review_approved:<rev_id>" or "review_rejected:<rev_id>" or "failed:<reason>"
    """
    from runtime.core.review_store import latest_review_for_task, record_review_verdict
    from runtime.core.task_store import load_task

    # Consistency guard
    fresh = load_task(task.task_id, root=root)
    if fresh is None:
        return f"failed:task_missing:{task.task_id}"
    if fresh.status != "waiting_review":
        return f"blocked:task_not_in_waiting_review (status={fresh.status})"

    review = latest_review_for_task(task.task_id, root=root)
    if review is None or review.status != "pending":
        return f"blocked:no_pending_review for {task.task_id}"

    log.info("[STAGE] auto_review  task=%s  review=%s", task.task_id, review.review_id)

    # Get HAL output from the review details
    hal_output = review.details or ""

    # Call Archimedes via Qwen
    log.info("[ARCHIMEDES] Calling Qwen reviewer for task %s ...", task.task_id)
    result = call_archimedes_via_qwen(task, hal_output)
    log.info("[ARCHIMEDES] Done  elapsed=%.1fs  approved=%s", result["elapsed"], result["approved"])

    # Transport/model errors: do NOT record a verdict. Leave the review pending
    # so the next cycle can retry.
    if result.get("error"):
        log.warning("[ARCHIMEDES] Model error (not recording verdict): %s", result["reason"][:120])
        return f"failed:archimedes_error:{result['reason'][:80]}"

    verdict = "approved" if result["approved"] else "rejected"
    reason = f"Archimedes auto-review ({result['model']}, {result['elapsed']}s): {result['reason']}"

    # Record verdict via the proper API (safe for ralph_adapter tasks after our fix)
    try:
        record_review_verdict(
            review_id=review.review_id,
            verdict=verdict,
            actor="archimedes",
            lane="review",
            reason=reason,
            root=root,
        )
    except Exception as exc:
        log.error("record_review_verdict failed: %s", exc)
        return f"failed:review_verdict:{exc}"

    log.info("[OK] Review %s: %s  task=%s", verdict, review.review_id, task.task_id)
    return f"review_{verdict}:{review.review_id}"


def stage_review_to_approval(task: Any, *, root: Path) -> str:
    """Stage: waiting_review + approved review → request_approval.

    Guards:
      - task must still be in waiting_review (re-checked from store)
      - latest review must have status == "approved"
      - reviewer is chosen by task type/risk (operator for normal, anton for deploy/quant/high_stakes)

    Returns: "approval_requested:<apr_id>" or "blocked:<reason>" or "failed:<reason>"
    """
    from runtime.core.approval_store import request_approval
    from runtime.core.models import TaskStatus
    from runtime.core.review_store import choose_followup_approval_reviewer, latest_review_for_task
    from runtime.core.task_runtime import checkpoint_task
    from runtime.core.task_store import load_task

    # Consistency guard: re-read from store to avoid acting on a stale in-memory snapshot.
    fresh = load_task(task.task_id, root=root)
    if fresh is None:
        return f"blocked:task_missing:{task.task_id}"
    if fresh.status != TaskStatus.WAITING_REVIEW.value:
        return (
            f"blocked:task_not_in_waiting_review "
            f"(current status={fresh.status})"
        )

    review = latest_review_for_task(task.task_id, root=root)
    if review is None:
        return f"blocked:no_review_found for {task.task_id}"
    if review.status != "approved":
        return f"blocked:review_not_approved (status={review.status}) for {task.task_id}"

    reviewer = choose_followup_approval_reviewer(fresh)
    log.info(
        "[STAGE] review_to_approval  task=%s  review=%s  reviewer=%s",
        fresh.task_id, review.review_id, reviewer,
    )

    # Write checkpoint before requesting approval so the approval record has full context.
    try:
        checkpoint_task(
            root=root,
            task_id=fresh.task_id,
            actor=ACTOR,
            lane=LANE,
            checkpoint_summary=(
                f"Archimedes review {review.review_id} approved. "
                f"Requesting {reviewer} approval."
            ),
        )
    except Exception as exc:
        log.warning("checkpoint_task failed (non-fatal): %s", exc)

    try:
        approval = request_approval(
            task_id=fresh.task_id,
            approval_type=fresh.task_type or "general",
            requested_by=ACTOR,
            requested_reviewer=reviewer,
            lane=LANE,
            summary=(
                f"Ralph v1: Archimedes review approved. "
                f"{reviewer.capitalize()} approval requested for: {fresh.normalized_request[:80]}"
            ),
            details=(
                f"Task: {fresh.normalized_request}\n"
                f"Type: {fresh.task_type}  Risk: {fresh.risk_level}\n"
                f"Review: {review.review_id}  Verdict: {review.verdict_reason or 'approved'}\n"
                f"HAL result: {fresh.final_outcome or 'n/a'}"
            ),
            root=root,
        )
    except Exception as exc:
        log.error("request_approval failed: %s", exc)
        return f"failed:request_approval:{exc}"

    log.info("[OK] Approval requested: %s  reviewer=%s  task=%s",
             approval.approval_id, reviewer, fresh.task_id)
    return f"approval_requested:{approval.approval_id}"


def stage_dispatch_and_review(task: Any, *, root: Path) -> str:
    """Stage: queued → take ownership → start → Qwen/HAL → complete → request_review.

    Returns: "review_requested:<rev_id>" or "failed:<reason>"
    """
    from runtime.core.agent_status_store import update_agent_status
    from runtime.core.review_store import request_review
    from runtime.core.task_runtime import block_task, complete_task, fail_task, start_task
    from runtime.core.task_store import load_task, save_task

    log.info("[STAGE] dispatch_and_review  task=%s  backend=%s  req=%s",
             task.task_id, task.execution_backend, task.normalized_request[:60])

    # Take ownership: reassign backend to ralph_adapter.
    fresh = load_task(task.task_id, root=root)
    if fresh is None:
        return f"failed:task_missing:{task.task_id}"
    fresh.execution_backend = "ralph_adapter"
    save_task(fresh, root=root)

    # --- Mark running ---
    try:
        start_task(
            root=root,
            task_id=task.task_id,
            actor=ACTOR,
            lane=LANE,
            reason="Ralph v1: dispatching to HAL via Qwen proxy",
        )
    except Exception as exc:
        log.error("start_task failed: %s", exc)
        return f"failed:start_task:{exc}"

    update_agent_status(
        ACTOR,
        f"Running task {task.task_id}: {task.normalized_request[:60]}",
        state="running",
        current_task_id=task.task_id,
        root=root,
    )

    # --- Call HAL (Qwen proxy) ---
    log.info("[HAL] Calling Qwen for task %s ...", task.task_id)
    result = call_hal_via_qwen(task)
    log.info("[HAL] Done  elapsed=%.1fs  ok=%s", result["elapsed"], result["ok"])

    result_id = _record_hal_result(task, result, root=root)

    if not result["ok"]:
        fail_task(
            root=root,
            task_id=task.task_id,
            actor=ACTOR,
            lane=LANE,
            reason=f"HAL execution failed: {result['error']}",
        )
        update_agent_status(
            ACTOR,
            f"Task {task.task_id} failed",
            state="error",
            current_task_id=None,
            last_result=result["error"][:200],
            root=root,
        )
        log.error("[FAIL] task=%s  error=%s", task.task_id, result["error"][:120])
        return f"failed:hal:{result['error'][:80]}"

    # --- Mark completed ---
    try:
        complete_task(
            root=root,
            task_id=task.task_id,
            actor=ACTOR,
            lane=LANE,
            final_outcome=(
                f"HAL executed via Qwen in {result['elapsed']}s. "
                f"Model: {result['model']}. Result id: {result_id}"
            ),
        )
    except Exception as exc:
        log.error("complete_task failed: %s", exc)
        return f"failed:complete_task:{exc}"

    # --- Request Archimedes review ---
    try:
        review = request_review(
            task_id=task.task_id,
            reviewer_role="archimedes",
            requested_by=ACTOR,
            lane=LANE,
            summary=f"Ralph v1: HAL execution complete. Requesting Archimedes review.",
            details=(
                f"Task: {task.normalized_request}\n\n"
                f"Model: {result['model']}  Elapsed: {result['elapsed']}s\n"
                f"Backend result: {result_id}\n\n"
                f"=== HAL Output ===\n{result['content'][:4000]}"
            ),
            root=root,
        )
    except Exception as exc:
        # Review request failed — task is completed but stuck without review.
        # Block it so the operator can see it.
        try:
            block_task(
                root=root,
                task_id=task.task_id,
                actor=ACTOR,
                lane=LANE,
                reason=f"HAL completed but review request failed: {exc}",
            )
        except Exception:
            pass
        log.error("request_review failed: %s", exc)
        return f"failed:request_review:{exc}"

    update_agent_status(
        ACTOR,
        f"Waiting archimedes review for {task.task_id}",
        state="waiting",
        current_task_id=task.task_id,
        last_result=f"HAL done in {result['elapsed']}s. Review: {review.review_id}",
        root=root,
    )
    log.info("[OK] Review requested: %s  task=%s", review.review_id, task.task_id)
    return f"review_requested:{review.review_id}"


# ---------------------------------------------------------------------------
# Main cycle entry point
# ---------------------------------------------------------------------------

def run_cycle(root: Path) -> dict[str, Any]:
    """Run one Ralph v1 cycle. Returns a result dict.

    Stage priority (first match wins):
      2a. review approved → request approval
      2b. review pending  → Archimedes auto-review
      2c. task queued     → HAL dispatch → request review

    Outcome values:
      "blocked"                — health gate failed; no task processed
      "idle"                   — no eligible tasks found
      "review_requested:<id>"  — task dispatched through HAL, awaiting review
      "review_approved:<id>"   — Archimedes approved the review
      "review_rejected:<id>"   — Archimedes rejected the review
      "approval_requested:<id>"— review approved, approval pending
      "failed:<reason>"        — a stage failed; task marked failed/blocked
    """
    from runtime.core.models import new_id

    _load_env(root)
    cycle_id = new_id("rcycle")
    log.info("=== Ralph v1 cycle %s start ===", cycle_id)

    # ------------------------------------------------------------------
    # 1. Health gates
    # ------------------------------------------------------------------
    healthy, gate_results = run_health_gates(root)
    if not healthy:
        failed_gates = [g for g in gate_results if not g["ok"]]
        msg = "; ".join(
            f"{g['gate']}: {g.get('error', 'failed')}" for g in failed_gates
        )
        log.warning("[BLOCKED] Health gates failed: %s", msg)
        try:
            emit_event("warning", ACTOR, detail=f"Ralph v1 cycle {cycle_id} blocked: {msg}", root=root)
        except Exception:
            pass
        return {
            "cycle_id": cycle_id,
            "outcome": "blocked",
            "stage": "health_gates",
            "details": msg,
            "gates": gate_results,
        }

    log.info("[OK] Health gates passed (%d checks)", len(gate_results))

    # ------------------------------------------------------------------
    # 1b. Stale-running recovery (before any stage)
    # ------------------------------------------------------------------
    recovered = recover_stale_running(root)
    if recovered:
        log.info("[CYCLE] Recovered stale task %s — will be eligible for retry", recovered)

    # ------------------------------------------------------------------
    # 2a. Stage: review approved → request approval
    # ------------------------------------------------------------------
    review_ready = pick_review_ready_task(root)
    if review_ready:
        outcome = stage_review_to_approval(review_ready, root=root)
        log.info("[CYCLE] stage=review_to_approval  task=%s  outcome=%s",
                 review_ready.task_id, outcome)
        return {
            "cycle_id": cycle_id,
            "outcome": outcome,
            "stage": "review_to_approval",
            "task_id": review_ready.task_id,
        }

    # ------------------------------------------------------------------
    # 2b. Stage: pending review → Archimedes auto-review
    # ------------------------------------------------------------------
    pending_review = pick_pending_review_task(root)
    if pending_review:
        outcome = stage_auto_review(pending_review, root=root)
        log.info("[CYCLE] stage=auto_review  task=%s  outcome=%s",
                 pending_review.task_id, outcome)
        return {
            "cycle_id": cycle_id,
            "outcome": outcome,
            "stage": "auto_review",
            "task_id": pending_review.task_id,
        }

    # ------------------------------------------------------------------
    # 2c. Stage: queued → HAL dispatch → request review
    # ------------------------------------------------------------------
    queued_task = pick_queued_task(root)
    if queued_task:
        outcome = stage_dispatch_and_review(queued_task, root=root)
        log.info("[CYCLE] stage=dispatch_and_review  task=%s  outcome=%s",
                 queued_task.task_id, outcome)
        return {
            "cycle_id": cycle_id,
            "outcome": outcome,
            "stage": "dispatch_and_review",
            "task_id": queued_task.task_id,
        }

    # ------------------------------------------------------------------
    # 3. Idle
    # ------------------------------------------------------------------
    log.info("[IDLE] No eligible tasks")
    try:
        emit_event("agent_status", ACTOR,
                   detail=f"Ralph v1 idle — no eligible tasks (cycle {cycle_id})", root=root)
    except Exception:
        pass

    return {
        "cycle_id": cycle_id,
        "outcome": "idle",
        "stage": "idle",
        "details": "No eligible queued tasks and no review-ready tasks found",
    }
