#!/usr/bin/env python3
"""Ralph v1 — Bounded autonomy loop.

One cycle. One task. One step forward.

Cycle order (highest stage wins, so the queue drains forward):
  0. Health gates → any fail → emit blocked digest → exit(0)
  0b. Stale-running recovery → fail stuck tasks
  1a. approval granted → finalize task (mark completed)
  1b. review approved  → request approval
  1c. review rejected  → fail task (operator can --retry)
  1d. review pending   → invoke Archimedes auto-review
  1e. task queued      → take ownership → HAL proxy → request review
  2. Idle → clear error state → exit(0)

Operator commands:
  python3 scripts/run_ralph_v1.py               # run one cycle
  python3 scripts/run_ralph_v1.py --status       # show state + tasks
  python3 scripts/run_ralph_v1.py --approve TID  # approve pending task
  python3 scripts/run_ralph_v1.py --reject TID   # reject pending task
  python3 scripts/run_ralph_v1.py --retry TID    # requeue failed task
  python3 scripts/run_ralph_v1.py --dry-run      # health gates only

Allowed transitions exercised by Ralph:
  queued           → running          (start_task)
  running          → completed        (complete_task)
  running          → failed           (fail_task / stale recovery)
  running          → blocked          (block_task)
  completed        → waiting_review   (request_review)
  waiting_review   → waiting_approval (request_approval, after approved review)
  waiting_review   → failed           (after rejected review)
  waiting_approval → completed        (after approved approval)
  failed           → queued           (operator --retry)
  blocked          → queued           (operator --retry)
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

# Task types Ralph will not touch (belong to dedicated pipelines).
BLOCKED_TASK_TYPES = frozenset({"deploy"})

# Risk levels Ralph will not touch.
BLOCKED_RISK_LEVELS = frozenset({"high_stakes"})

# ---------------------------------------------------------------------------
# Backend selection — picks the right executor for a task
# ---------------------------------------------------------------------------

# Keywords / patterns that signal a specific backend.
_BACKEND_KEYWORDS: dict[str, list[str]] = {
    "kitt_quant": [
        "nq", "futures", "e-mini", "regime", "market condition", "quant",
        "trading signal", "backtest", "strategy", "price action", "volatility",
        "momentum", "mean-revert", "drawdown", "profit factor",
    ],
    "browser_backend": [
        "browse to", "navigate to", "screenshot", "scrape", "web page", "website",
        "open url", "fetch page", "login to", "take a screenshot",
    ],
    "scout_search": [
        "search for", "look up", "find information", "research",
        "what is", "who is", "latest news", "current status of",
    ],
    "muse_creative": [
        "write a story", "creative", "poem", "design", "brainstorm",
        "generate ideas", "marketing copy", "tagline", "slogan",
    ],
}

# Task type → default backend when keywords don't match.
_TYPE_DEFAULTS: dict[str, str] = {
    "quant": "kitt_quant",
    "browser": "browser_backend",
    "research": "scout_search",
    "creative": "muse_creative",
    "code": "hal",
    "general": "hal",
}


def select_backend_for_task(task: Any) -> str:
    """Pick the best execution backend for a task.

    Priority:
      1. If task already has a specific backend (not ralph_adapter/unassigned), keep it.
      2. Keyword match against normalized_request.
      3. Task type default.
      4. Fallback to hal.

    Returns a backend name: hal, kitt_quant, browser_backend, scout_search, muse_creative.
    """
    # If the task was explicitly routed to a real backend, respect it.
    current = task.execution_backend or ""
    if current and current not in {"ralph_adapter", "unassigned", "qwen_executor", "qwen_planner"}:
        return current

    request = (task.normalized_request or task.raw_request or "").lower()

    # Keyword scoring — pick the backend with the most keyword hits.
    scores: dict[str, int] = {}
    for backend, keywords in _BACKEND_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in request)
        if score > 0:
            scores[backend] = score

    if scores:
        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        log.info("Backend selected by keywords: %s (score=%d) for: %s",
                 best, scores[best], request[:60])
        return best

    # Task type default.
    task_type = (task.task_type or "").lower()
    if task_type in _TYPE_DEFAULTS:
        backend = _TYPE_DEFAULTS[task_type]
        log.info("Backend selected by task_type=%s: %s", task_type, backend)
        return backend

    log.info("Backend defaulting to hal for: %s", request[:60])
    return "hal"

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


def pick_rejected_review_task(root: Path) -> Optional[Any]:
    """Find a Ralph-owned waiting_review task whose review was rejected."""
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
        if review and review.status == "rejected":
            log.info("Rejected-review task: %s  review=%s", task.task_id, review.review_id)
            return task
    return None


def pick_approved_approval_task(root: Path) -> Optional[Any]:
    """Find a Ralph-owned waiting_approval task whose approval is granted."""
    from runtime.core.task_store import list_tasks
    from runtime.core.models import TaskStatus
    from runtime.core.approval_store import latest_approval_for_task

    tasks = list_tasks(root=root, limit=200)
    for task in tasks:
        if task.status != TaskStatus.WAITING_APPROVAL.value:
            continue
        if task.execution_backend != "ralph_adapter":
            continue
        approval = latest_approval_for_task(task.task_id, root=root)
        if approval and approval.status == "approved":
            log.info("Approved-approval task: %s  approval=%s", task.task_id, approval.approval_id)
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
# Unified backend dispatch
# ---------------------------------------------------------------------------

def dispatch_task(task: Any, backend: str, *, root: Path) -> dict[str, Any]:
    """Execute a task through the selected backend.

    Returns {ok, content, error, elapsed, model, backend, agent, usage}.
    All backends normalize to this shape.
    """
    if backend == "hal":
        result = call_hal_via_qwen(task)
        result["backend"] = "hal"
        result["agent"] = "hal"
        return result

    if backend == "kitt_quant":
        result = call_kitt_quant(task, root=root)
        result["backend"] = "kitt_quant"
        result["agent"] = "kitt"
        return result

    if backend == "scout_search":
        result = call_scout_search(task, root=root)
        result["backend"] = "scout_search"
        result["agent"] = "scout"
        return result

    if backend == "browser_backend":
        result = call_browser(task, root=root)
        result["backend"] = "browser_backend"
        result["agent"] = "bowser"
        return result

    if backend == "muse_creative":
        result = call_muse_via_qwen(task)
        result["backend"] = "muse_creative"
        result["agent"] = "muse"
        return result

    # Fallback: treat as HAL
    log.warning("Unknown backend '%s', falling back to hal", backend)
    result = call_hal_via_qwen(task)
    result["backend"] = "hal"
    result["agent"] = "hal"
    return result


# ---------------------------------------------------------------------------
# Scout — SearXNG web search
# ---------------------------------------------------------------------------

def call_scout_search(task: Any, *, root: Path) -> dict[str, Any]:
    """Execute task via SearXNG web search. Returns unified result dict."""
    t0 = time.time()
    try:
        from runtime.integrations.searxng_client import search
        raw_query = (task.normalized_request or task.raw_request or "").strip()
        # Extract a focused search query — strip common prefixes
        query = raw_query
        for prefix in ("search for ", "look up ", "find information about ",
                       "find ", "what is ", "who is "):
            if query.lower().startswith(prefix):
                query = query[len(prefix):]
                break
        # Truncate to a reasonable search query length
        if len(query) > 80:
            query = query[:80]
        search_result = search(
            query_text=query,
            actor="scout",
            lane="ralph",
            max_results=5,
            root=root,
        )
        elapsed = round(time.time() - t0, 2)

        if search_result.get("status") not in ("ok", "completed") and not search_result.get("ok"):
            return {"ok": False, "content": "", "error": search_result.get("error", "search failed"),
                    "elapsed": elapsed, "model": "searxng", "usage": {}}

        results = search_result.get("results", [])
        if not results:
            return {"ok": False, "content": "", "error": "no search results",
                    "elapsed": elapsed, "model": "searxng", "usage": {}}

        lines = [f"## Search Results for: {query}", ""]
        for i, r in enumerate(results[:5], 1):
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = r.get("content", r.get("snippet", ""))[:200]
            lines.append(f"### {i}. {title}")
            lines.append(f"URL: {url}")
            lines.append(f"{snippet}")
            lines.append("")

        content = "\n".join(lines)
        return {"ok": True, "content": content, "error": "", "elapsed": elapsed,
                "model": "searxng", "usage": {}}
    except Exception as exc:
        return {"ok": False, "content": "", "error": str(exc),
                "elapsed": round(time.time() - t0, 2), "model": "searxng", "usage": {}}


# ---------------------------------------------------------------------------
# Kitt quant — delegates to backend_dispatch
# ---------------------------------------------------------------------------

def call_kitt_quant(task: Any, *, root: Path) -> dict[str, Any]:
    """Execute task via the Kitt quant workflow (SearXNG → Bowser → Kimi K2.5)."""
    t0 = time.time()
    try:
        from runtime.executor.backend_dispatch import dispatch_to_backend
        messages = [{"role": "user", "content": task.normalized_request or task.raw_request or ""}]
        result = dispatch_to_backend(
            execution_backend="kitt_quant",
            task_id=task.task_id,
            actor=ACTOR,
            lane=LANE,
            messages=messages,
            root=root,
        )
        elapsed = round(time.time() - t0, 2)
        content = result.get("content", result.get("brief_preview", ""))
        if not content and result.get("brief_artifact"):
            content = f"Brief artifact: {result['brief_artifact']}"
        return {
            "ok": result.get("status") in ("completed", "ok"),
            "content": str(content)[:4000],
            "error": result.get("error", ""),
            "elapsed": elapsed,
            "model": result.get("model", "kimi-k2.5"),
            "usage": result.get("usage", {}),
        }
    except Exception as exc:
        return {"ok": False, "content": "", "error": str(exc),
                "elapsed": round(time.time() - t0, 2), "model": "kitt_quant", "usage": {}}


# ---------------------------------------------------------------------------
# Browser — delegates to backend_dispatch
# ---------------------------------------------------------------------------

def call_browser(task: Any, *, root: Path) -> dict[str, Any]:
    """Execute task via the Bowser browser backend (PinchTab)."""
    t0 = time.time()
    try:
        from runtime.executor.backend_dispatch import dispatch_to_backend
        messages = [{"role": "user", "content": task.normalized_request or task.raw_request or ""}]
        result = dispatch_to_backend(
            execution_backend="browser_backend",
            task_id=task.task_id,
            actor=ACTOR,
            lane=LANE,
            messages=messages,
            root=root,
        )
        elapsed = round(time.time() - t0, 2)
        content = result.get("content", result.get("text", ""))
        return {
            "ok": result.get("status") in ("completed", "ok"),
            "content": str(content)[:4000],
            "error": result.get("error", ""),
            "elapsed": elapsed,
            "model": "pinchtab",
            "usage": {},
        }
    except Exception as exc:
        return {"ok": False, "content": "", "error": str(exc),
                "elapsed": round(time.time() - t0, 2), "model": "pinchtab", "usage": {}}


# ---------------------------------------------------------------------------
# Muse creative — Qwen with creative persona
# ---------------------------------------------------------------------------

def call_muse_via_qwen(task: Any) -> dict[str, Any]:
    """Execute task via Qwen with Muse creative persona."""
    import requests as _req

    base = os.getenv("QWEN_AGENT_MODEL_SERVER", "http://100.70.114.34:1234/v1").rstrip("/")
    model = os.getenv("QWEN_AGENT_MODEL", "qwen3.5-35b-a3b")
    api_key = os.getenv("QWEN_AGENT_API_KEY", "lm-studio")

    system_prompt = (
        "You are Muse, the creative specialist in the OpenClaw system. "
        "Your strength is imaginative, well-crafted output: writing, design concepts, "
        "brainstorming, marketing copy, and creative problem-solving. "
        "Be original, clear, and concise. "
        "Format: ## Creative Output\n<your work>\n## Notes\n<brief process notes>. "
        "/no_think"
    )
    user_prompt = (task.normalized_request or task.raw_request or "").strip()

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
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
                    "elapsed": elapsed, "model": model, "usage": {}}
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        content = str((choice.get("message") or {}).get("content") or "").strip()
        usage = data.get("usage") or {}
        if not content:
            return {"ok": False, "content": "", "error": "empty response from model",
                    "elapsed": elapsed, "model": model, "usage": usage}
        return {"ok": True, "content": content, "error": "", "elapsed": elapsed,
                "model": model, "usage": usage}
    except Exception as exc:
        return {"ok": False, "content": "", "error": str(exc),
                "elapsed": round(time.time() - t0, 2), "model": model, "usage": {}}


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
        usage = data.get("usage") or {}
        if not content:
            return {"ok": False, "content": "", "error": "empty response from model",
                    "elapsed": elapsed, "model": model, "usage": usage}
        return {"ok": True, "content": content, "error": "", "elapsed": elapsed,
                "model": model, "usage": usage}
    except Exception as exc:
        return {"ok": False, "content": "", "error": str(exc),
                "elapsed": round(time.time() - t0, 2), "model": model, "usage": {}}


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


def _track_usage(task: Any, result: dict[str, Any], *, agent: str, root: Path) -> None:
    """Track token usage from a Qwen API call against the global budget."""
    try:
        from runtime.core.token_budget import apply_budget_usage
        usage = result.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        total = prompt_tokens + completion_tokens
        if total > 0:
            apply_budget_usage(
                task_id=task.task_id,
                execution_backend=f"ralph_{agent}_proxy",
                token_usage=total,
                root=root,
            )
            log.info("[BUDGET] %s usage: %d tokens (prompt=%d, completion=%d)",
                     agent, total, prompt_tokens, completion_tokens)
    except Exception as exc:
        log.debug("Budget tracking skipped: %s", exc)


def _record_execution_trace(
    task: Any, result: dict[str, Any], *, agent: str, result_id: str, root: Path,
) -> None:
    """Record a run trace for the HAL/Archimedes execution."""
    try:
        from runtime.evals.trace_store import save_run_trace
        from runtime.core.models import RunTraceRecord, new_id, now_iso

        usage = result.get("usage") or {}
        trace = RunTraceRecord(
            trace_id=new_id("trace"),
            task_id=task.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=ACTOR,
            lane=LANE,
            trace_kind=f"ralph_{agent}_proxy",
            execution_backend=f"ralph_{agent}_proxy",
            status="completed" if result.get("ok") or result.get("approved") is not None else "failed",
            request_payload={
                "normalized_request": (task.normalized_request or "")[:500],
                "task_type": task.task_type or "",
                "model": result.get("model", ""),
            },
            response_payload={
                "ok": result.get("ok"),
                "approved": result.get("approved"),
                "content_length": len(result.get("content", result.get("reason", ""))),
                "elapsed": result.get("elapsed", 0),
                "model": result.get("model", ""),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            },
            replay_payload={},
            source_refs={"result_id": result_id, "agent": agent},
            candidate_artifact_id="",
        )
        save_run_trace(trace, root=root)
    except Exception as exc:
        log.debug("Trace recording skipped: %s", exc)


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

        usage = data.get("usage") or {}
        return {"approved": approved, "reason": reason[:500], "elapsed": elapsed, "model": model, "usage": usage}
    except Exception as exc:
        return {"approved": None, "error": True,
                "reason": f"Review call failed: {exc}",
                "elapsed": round(time.time() - t0, 2), "model": model, "usage": {}}


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

    # --- Token budget tracking + trace recording ---
    _track_usage(task, result, agent="archimedes", root=root)
    _record_execution_trace(task, result, agent="archimedes", result_id=review.review_id, root=root)

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


def stage_rejected_review(task: Any, *, root: Path) -> str:
    """Stage: waiting_review + rejected review → fail the task with reason.

    The operator can then --retry to re-dispatch, or leave it failed.
    Returns: "task_failed:<task_id>" or "failed:<reason>"
    """
    from runtime.core.review_store import latest_review_for_task
    from runtime.core.task_runtime import fail_task
    from runtime.core.task_store import load_task

    fresh = load_task(task.task_id, root=root)
    if fresh is None:
        return f"failed:task_missing:{task.task_id}"

    review = latest_review_for_task(task.task_id, root=root)
    reason_text = review.verdict_reason if review else "Review rejected (no details)"

    log.info("[STAGE] rejected_review  task=%s  reason=%s", task.task_id, reason_text[:80])

    try:
        fail_task(
            root=root,
            task_id=task.task_id,
            actor=ACTOR,
            lane=LANE,
            reason=f"Archimedes review rejected: {reason_text[:300]}",
        )
    except Exception as exc:
        log.error("fail_task after rejected review failed: %s", exc)
        return f"failed:fail_task:{exc}"

    from runtime.core.agent_status_store import update_agent_status
    update_agent_status(
        ACTOR,
        f"Task {task.task_id} rejected by Archimedes",
        state="idle",
        current_task_id=None,
        last_result=f"Rejected: {reason_text[:100]}",
        root=root,
    )

    log.info("[OK] Task %s failed after rejected review", task.task_id)
    return f"task_failed:{task.task_id}"


def stage_approval_complete(task: Any, *, root: Path) -> str:
    """Stage: waiting_approval + approved → mark task fully done.

    Returns: "task_done:<task_id>" or "failed:<reason>"
    """
    from runtime.core.approval_store import latest_approval_for_task
    from runtime.core.task_store import load_task, transition_task
    from runtime.core.models import TaskStatus

    fresh = load_task(task.task_id, root=root)
    if fresh is None:
        return f"failed:task_missing:{task.task_id}"

    approval = latest_approval_for_task(task.task_id, root=root)
    if approval is None or approval.status != "approved":
        return f"blocked:approval_not_approved for {task.task_id}"

    log.info("[STAGE] approval_complete  task=%s  approval=%s", task.task_id, approval.approval_id)

    try:
        transition_task(
            task_id=task.task_id,
            to_status=TaskStatus.COMPLETED.value,
            actor=ACTOR,
            lane=LANE,
            summary=f"Approval granted by {approval.decided_by or 'operator'}. Task complete.",
            root=root,
            details=f"Approval {approval.approval_id}: {approval.reason or 'approved'}",
        )
    except Exception as exc:
        log.error("transition_task to completed failed: %s", exc)
        return f"failed:transition_task:{exc}"

    from runtime.core.agent_status_store import update_agent_status
    update_agent_status(
        ACTOR,
        f"Task {task.task_id} approved and complete",
        state="idle",
        current_task_id=None,
        last_result=f"Approved by {approval.decided_by or 'operator'}",
        root=root,
    )

    log.info("[OK] Task %s approved and completed", task.task_id)
    return f"task_done:{task.task_id}"


def stage_dispatch_and_review(task: Any, *, root: Path) -> str:
    """Stage: queued → take ownership → start → Qwen/HAL → complete → request_review.

    Returns: "review_requested:<rev_id>" or "failed:<reason>"
    """
    from runtime.core.agent_status_store import update_agent_status
    from runtime.core.review_store import request_review
    from runtime.core.task_runtime import block_task, complete_task, fail_task, start_task
    from runtime.core.task_store import load_task, save_task

    # --- Select backend ---
    backend = select_backend_for_task(task)
    agent = {"hal": "hal", "kitt_quant": "kitt", "scout_search": "scout",
             "browser_backend": "bowser", "muse_creative": "muse"}.get(backend, backend)

    log.info("[STAGE] dispatch_and_review  task=%s  selected_backend=%s  req=%s",
             task.task_id, backend, task.normalized_request[:60])

    # Take ownership: reassign backend to ralph_adapter.
    fresh = load_task(task.task_id, root=root)
    if fresh is None:
        return f"failed:task_missing:{task.task_id}"
    fresh.execution_backend = "ralph_adapter"
    save_task(fresh, root=root)

    # --- Chunking: split large tasks into children ---
    from runtime.core.task_chunking import should_chunk, chunk_task
    if should_chunk(fresh):
        log.info("[CHUNK] Task %s qualifies for chunking — decomposing", task.task_id)
        child_ids = chunk_task(fresh, root=root)
        if child_ids:
            try:
                complete_task(
                    root=root,
                    task_id=task.task_id,
                    actor=ACTOR,
                    lane=LANE,
                    final_outcome=f"Chunked into {len(child_ids)} subtasks: {', '.join(child_ids)}",
                )
            except Exception:
                pass
            update_agent_status(
                ACTOR,
                f"Chunked {task.task_id} into {len(child_ids)} subtasks",
                state="idle",
                current_task_id=None,
                root=root,
            )
            log.info("[CHUNK] %d children created — parent marked completed", len(child_ids))
            return f"chunked:{len(child_ids)}:{','.join(child_ids)}"

    # --- Mark running ---
    try:
        start_task(
            root=root,
            task_id=task.task_id,
            actor=ACTOR,
            lane=LANE,
            reason=f"Ralph: dispatching to {backend}",
        )
    except Exception as exc:
        log.error("start_task failed: %s", exc)
        return f"failed:start_task:{exc}"

    update_agent_status(
        ACTOR,
        f"Running task {task.task_id} via {backend}: {task.normalized_request[:50]}",
        state="running",
        current_task_id=task.task_id,
        root=root,
    )

    # --- Dispatch to selected backend ---
    log.info("[DISPATCH] Calling %s for task %s ...", backend, task.task_id)
    result = dispatch_task(task, backend, root=root)
    log.info("[DISPATCH] %s done  elapsed=%.1fs  ok=%s", backend, result["elapsed"], result["ok"])

    result_id = _record_hal_result(task, result, root=root)

    # --- Token budget tracking + trace recording ---
    _track_usage(task, result, agent=result.get("agent", agent), root=root)
    _record_execution_trace(task, result, agent=result.get("agent", agent),
                            result_id=result_id, root=root)

    if not result["ok"]:
        fail_task(
            root=root,
            task_id=task.task_id,
            actor=ACTOR,
            lane=LANE,
            reason=f"{backend} execution failed: {result['error']}",
        )
        update_agent_status(
            ACTOR,
            f"Task {task.task_id} failed ({backend})",
            state="error",
            current_task_id=None,
            last_result=result["error"][:200],
            root=root,
        )
        log.error("[FAIL] task=%s  backend=%s  error=%s", task.task_id, backend, result["error"][:120])
        return f"failed:{backend}:{result['error'][:80]}"

    # --- Mark completed ---
    try:
        complete_task(
            root=root,
            task_id=task.task_id,
            actor=ACTOR,
            lane=LANE,
            final_outcome=(
                f"{backend} executed in {result['elapsed']}s. "
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
            summary=f"Ralph: {backend} execution complete. Requesting Archimedes review.",
            details=(
                f"Task: {task.normalized_request}\n\n"
                f"Backend: {backend}  Model: {result['model']}  Elapsed: {result['elapsed']}s\n"
                f"Backend result: {result_id}\n\n"
                f"=== Output ===\n{result['content'][:4000]}"
            ),
            root=root,
        )
    except Exception as exc:
        try:
            block_task(
                root=root,
                task_id=task.task_id,
                actor=ACTOR,
                lane=LANE,
                reason=f"{backend} completed but review request failed: {exc}",
            )
        except Exception:
            pass
        log.error("request_review failed: %s", exc)
        return f"failed:request_review:{exc}"

    update_agent_status(
        ACTOR,
        f"Waiting review for {task.task_id} ({backend})",
        state="waiting",
        current_task_id=task.task_id,
        last_result=f"{backend} done in {result['elapsed']}s. Review: {review.review_id}",
        root=root,
    )
    log.info("[OK] Review requested: %s  task=%s  backend=%s", review.review_id, task.task_id, backend)
    return f"review_requested:{review.review_id}"


# ---------------------------------------------------------------------------
# Main cycle entry point
# ---------------------------------------------------------------------------

def ralph_status(root: Path) -> dict[str, Any]:
    """Return a snapshot of Ralph's current state and owned tasks.

    Designed for operator visibility — shows what Ralph is doing, what
    tasks he owns, and what needs operator action.
    """
    from runtime.core.task_store import list_tasks
    from runtime.core.models import TaskStatus
    from runtime.core.agent_status_store import get_agent_status
    from runtime.core.review_store import latest_review_for_task
    from runtime.core.approval_store import latest_approval_for_task

    agent = get_agent_status(ACTOR, root=root) or {}
    tasks = list_tasks(root=root, limit=200)

    ralph_tasks: list[dict[str, Any]] = []
    needs_action: list[dict[str, Any]] = []

    for t in tasks:
        if t.execution_backend != "ralph_adapter":
            continue
        info: dict[str, Any] = {
            "task_id": t.task_id,
            "status": t.status,
            "type": t.task_type,
            "request": (t.normalized_request or "")[:80],
        }

        if t.status == TaskStatus.WAITING_APPROVAL.value:
            apr = latest_approval_for_task(t.task_id, root=root)
            info["approval_status"] = apr.status if apr else "none"
            if apr and apr.status == "pending":
                needs_action.append({
                    "action": "approve_or_reject",
                    "task_id": t.task_id,
                    "approval_id": apr.approval_id,
                    "summary": apr.summary[:80] if apr.summary else "",
                })
            elif apr and apr.status == "approved":
                needs_action.append({
                    "action": "run_ralph_cycle",
                    "reason": f"Approval granted for {t.task_id} — next cycle will finalize",
                })

        elif t.status == TaskStatus.FAILED.value:
            info["error"] = t.last_error[:80] if t.last_error else ""
            needs_action.append({
                "action": "retry_or_dismiss",
                "task_id": t.task_id,
                "hint": f"python3 scripts/run_ralph_v1.py --retry {t.task_id}",
            })

        ralph_tasks.append(info)

    return {
        "agent_state": agent.get("state", "unknown"),
        "headline": agent.get("headline", ""),
        "last_result": agent.get("last_result", ""),
        "ralph_tasks": ralph_tasks,
        "needs_operator_action": needs_action,
        "total_ralph_tasks": len(ralph_tasks),
    }


def approve_task(task_id: str, *, decision: str = "approved", reason: str = "",
                 root: Path) -> dict[str, Any]:
    """Approve or reject a pending Ralph approval from the CLI.

    Args:
        task_id: The task to approve/reject.
        decision: "approved" or "rejected".
        reason: Optional reason text.
    Returns:
        Summary dict.
    """
    from runtime.core.approval_store import latest_approval_for_task, record_approval_decision

    if decision not in ("approved", "rejected"):
        return {"ok": False, "error": f"Invalid decision: {decision}. Use 'approved' or 'rejected'."}

    approval = latest_approval_for_task(task_id, root=root)
    if approval is None:
        return {"ok": False, "error": f"No approval found for task {task_id}"}
    if approval.status != "pending":
        return {"ok": False, "error": f"Approval {approval.approval_id} is '{approval.status}', not pending"}

    record_approval_decision(
        approval_id=approval.approval_id,
        decision=decision,
        actor="operator",
        lane="operator",
        reason=reason or f"Operator {decision} via CLI",
        root=root,
    )

    log.info("[APPROVE] %s: %s  approval=%s  task=%s", decision, reason or "(no reason)", approval.approval_id, task_id)
    return {
        "ok": True,
        "task_id": task_id,
        "approval_id": approval.approval_id,
        "decision": decision,
    }


def run_cycle(root: Path) -> dict[str, Any]:
    """Run one Ralph v1 cycle. Returns a result dict.

    Stage priority (first match wins — highest stage first so queue drains forward):
      1a. approval granted → finalize task
      1b. review approved  → request approval
      1c. review rejected  → fail task (operator can --retry)
      1d. review pending   → Archimedes auto-review
      1e. task queued      → HAL dispatch → request review

    Outcome values:
      "blocked"                — health gate failed; no task processed
      "idle"                   — no eligible tasks found
      "task_done:<id>"         — approval granted, task finalized
      "approval_requested:<id>"— review approved, approval pending
      "task_failed:<id>"       — review rejected, task failed
      "review_approved:<id>"   — Archimedes approved the review
      "review_rejected:<id>"   — Archimedes rejected the review
      "review_requested:<id>"  — task dispatched through HAL, awaiting review
      "failed:<reason>"        — a stage failed; task marked failed/blocked
    """
    from runtime.core.agent_status_store import update_agent_status
    from runtime.core.models import new_id

    _load_env(root)
    cycle_id = new_id("rcycle")
    log.info("=== Ralph v1 cycle %s start ===", cycle_id)

    # ------------------------------------------------------------------
    # 0. Health gates
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
    # 0b. Stale-running recovery (before any stage)
    # ------------------------------------------------------------------
    recovered = recover_stale_running(root)
    if recovered:
        log.info("[CYCLE] Recovered stale task %s — will be eligible for retry", recovered)

    # ------------------------------------------------------------------
    # 0c. Parent rollup — check if any chunked parent's children are all done
    # ------------------------------------------------------------------
    from runtime.core.task_chunking import rollup_parent
    from runtime.core.task_store import list_tasks as _list_tasks
    for _t in _list_tasks(root=root, limit=200):
        if _t.child_task_ids and _t.status == "completed" and "Chunked into" in (_t.final_outcome or ""):
            status_check = rollup_parent(_t.task_id, root=root)
            if status_check.get("action") == "completed":
                log.info("[ROLLUP] Parent %s rolled up: all children done", _t.task_id)

    # ------------------------------------------------------------------
    # 1a. Stage: approval granted → finalize task
    # ------------------------------------------------------------------
    approved_task = pick_approved_approval_task(root)
    if approved_task:
        outcome = stage_approval_complete(approved_task, root=root)
        log.info("[CYCLE] stage=approval_complete  task=%s  outcome=%s",
                 approved_task.task_id, outcome)
        return {
            "cycle_id": cycle_id,
            "outcome": outcome,
            "stage": "approval_complete",
            "task_id": approved_task.task_id,
        }

    # ------------------------------------------------------------------
    # 1b. Stage: review approved → request approval
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
    # 1c. Stage: review rejected → fail task
    # ------------------------------------------------------------------
    rejected_task = pick_rejected_review_task(root)
    if rejected_task:
        outcome = stage_rejected_review(rejected_task, root=root)
        log.info("[CYCLE] stage=rejected_review  task=%s  outcome=%s",
                 rejected_task.task_id, outcome)
        return {
            "cycle_id": cycle_id,
            "outcome": outcome,
            "stage": "rejected_review",
            "task_id": rejected_task.task_id,
        }

    # ------------------------------------------------------------------
    # 1d. Stage: pending review → Archimedes auto-review
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
    # 1e. Stage: queued → HAL dispatch → request review
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
    # 2. Idle — clear error state if nothing to do
    # ------------------------------------------------------------------
    log.info("[IDLE] No eligible tasks")
    update_agent_status(
        ACTOR,
        "Ralph v1 idle — no eligible tasks",
        state="idle",
        current_task_id=None,
        root=root,
    )

    return {
        "cycle_id": cycle_id,
        "outcome": "idle",
        "stage": "idle",
        "details": "No eligible queued tasks and no review-ready tasks found",
    }
