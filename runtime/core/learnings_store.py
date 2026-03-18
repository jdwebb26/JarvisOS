#!/usr/bin/env python3
"""learnings_store — lightweight durable learnings ledger for cross-session agent improvement.

Stores lessons learned from meaningful events:
  - repeated task failures
  - review rejections with reason
  - approval rejections with reason
  - operator corrections
  - successful fixes after failures
  - environment gotchas

Storage:
  state/learnings/global.jsonl      — all learnings (append-only)
  state/learnings/agents/<id>.jsonl  — per-agent subset (append-only)

Each line is a self-contained JSON record. Easy to inspect with cat/jq/tail.

API:
    record_learning(...)             — write a learning from any trigger
    get_learnings_for_agent(...)     — retrieve relevant learnings for an agent/task scope
    get_recent_learnings(...)        — retrieve N most recent global learnings
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import new_id, now_iso


# ---------------------------------------------------------------------------
# Trigger types — what kind of event produced this learning
# ---------------------------------------------------------------------------

VALID_TRIGGERS = {
    "task_failure",
    "repeated_failure",
    "review_rejection",
    "approval_rejection",
    "operator_correction",
    "successful_fix",
    "environment_gotcha",
    "routing_insight",
    "manual",
}

# ---------------------------------------------------------------------------
# State directories
# ---------------------------------------------------------------------------

def _learnings_dir(root: Optional[Path] = None) -> Path:
    d = Path(root or ROOT).resolve() / "state" / "learnings"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _agents_dir(root: Optional[Path] = None) -> Path:
    d = _learnings_dir(root) / "agents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _global_path(root: Optional[Path] = None) -> Path:
    return _learnings_dir(root) / "global.jsonl"


def _agent_path(agent_id: str, root: Optional[Path] = None) -> Path:
    # Sanitize agent_id to prevent path traversal
    safe_id = agent_id.replace("/", "_").replace("..", "_").strip(".")
    return _agents_dir(root) / f"{safe_id}.jsonl"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def record_learning(
    *,
    trigger: str,
    lesson: str,
    agent_id: str = "",
    scope: str = "global",
    evidence: str = "",
    task_id: str = "",
    task_type: str = "",
    confidence: float = 0.7,
    applies_to: Optional[list[str]] = None,
    expires_after_days: Optional[int] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Record a learning to the durable ledger.

    Args:
        trigger: What event type caused this learning (see VALID_TRIGGERS).
        lesson: The actual lesson — plain English, concise, actionable.
        agent_id: Which agent produced/owns this learning (empty = system-level).
        scope: "global" | "agent" | "task_type" — how broadly this applies.
        evidence: What specifically happened (task_id, error message, etc).
        task_id: Related task if any.
        task_type: Related task type if any (code, quant, deploy, etc).
        confidence: 0.0-1.0 how confident we are this lesson is correct.
        applies_to: List of agent_ids this is relevant to (None = all).
        expires_after_days: Auto-expire after N days (None = permanent).
        root: Project root override.

    Returns:
        The learning record dict.
    """
    if not lesson or len(lesson.strip()) < 10:
        return {"status": "skipped", "reason": "lesson too short"}

    if trigger not in VALID_TRIGGERS:
        return {"status": "skipped", "reason": f"unknown trigger: {trigger}"}

    learning_id = new_id("lrn")
    created_at = now_iso()

    record: dict[str, Any] = {
        "learning_id": learning_id,
        "created_at": created_at,
        "trigger": trigger,
        "scope": scope,
        "agent_id": agent_id,
        "lesson": lesson.strip()[:500],
        "evidence": evidence.strip()[:300] if evidence else "",
        "task_id": task_id,
        "task_type": task_type,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "applies_to": applies_to or [],
        "expires_after_days": expires_after_days,
    }

    resolved_root = Path(root or ROOT).resolve()
    line = json.dumps(record, separators=(",", ":")) + "\n"

    # Append to global ledger
    with open(_global_path(resolved_root), "a", encoding="utf-8") as f:
        f.write(line)

    # Append to agent-specific ledger if agent_id is set
    if agent_id:
        with open(_agent_path(agent_id, resolved_root), "a", encoding="utf-8") as f:
            f.write(line)

    # Also append to each applies_to agent's ledger
    for target_agent in (applies_to or []):
        if target_agent and target_agent != agent_id:
            with open(_agent_path(target_agent, resolved_root), "a", encoding="utf-8") as f:
                f.write(line)

    return record


# ---------------------------------------------------------------------------
# Convenience writers for specific event types
# ---------------------------------------------------------------------------

def record_task_failure_learning(
    *,
    task_id: str,
    agent_id: str,
    task_type: str,
    failure_reason: str,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Extract a learning from a task failure."""
    if not failure_reason or len(failure_reason.strip()) < 15:
        return {"status": "skipped", "reason": "failure_reason too short"}

    lesson = f"Task type '{task_type}' failed: {failure_reason.strip()[:200]}. Check prerequisites and inputs before retrying."
    return record_learning(
        trigger="task_failure",
        lesson=lesson,
        agent_id=agent_id,
        scope="agent",
        evidence=f"task={task_id}, type={task_type}, reason={failure_reason[:150]}",
        task_id=task_id,
        task_type=task_type,
        confidence=0.6,
        root=root,
    )


def record_review_rejection_learning(
    *,
    task_id: str,
    reviewer: str,
    agent_id: str,
    task_type: str,
    reason: str,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Extract a learning from a review rejection."""
    if not reason or len(reason.strip()) < 10:
        return {"status": "skipped", "reason": "rejection reason too short"}

    lesson = f"Review rejected by {reviewer} for {task_type} work: {reason.strip()[:200]}. Adjust approach before resubmitting."
    return record_learning(
        trigger="review_rejection",
        lesson=lesson,
        agent_id=agent_id,
        scope="agent",
        evidence=f"task={task_id}, reviewer={reviewer}, verdict=rejected",
        task_id=task_id,
        task_type=task_type,
        confidence=0.75,
        applies_to=[agent_id] if agent_id else [],
        root=root,
    )


def record_approval_rejection_learning(
    *,
    task_id: str,
    approver: str,
    agent_id: str,
    task_type: str,
    reason: str,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Extract a learning from an approval rejection."""
    if not reason or len(reason.strip()) < 10:
        return {"status": "skipped", "reason": "rejection reason too short"}

    lesson = f"Approval rejected by {approver} for {task_type}: {reason.strip()[:200]}. This type of work needs different handling."
    return record_learning(
        trigger="approval_rejection",
        lesson=lesson,
        agent_id=agent_id,
        scope="agent",
        evidence=f"task={task_id}, approver={approver}, decision=rejected",
        task_id=task_id,
        task_type=task_type,
        confidence=0.8,
        applies_to=[agent_id] if agent_id else [],
        root=root,
    )


def record_operator_correction(
    *,
    agent_id: str,
    correction: str,
    context: str = "",
    applies_to: Optional[list[str]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Record a direct operator correction as a learning."""
    return record_learning(
        trigger="operator_correction",
        lesson=correction,
        agent_id=agent_id,
        scope="global" if not agent_id else "agent",
        evidence=context,
        confidence=0.9,
        applies_to=applies_to,
        root=root,
    )


# ---------------------------------------------------------------------------
# Read / Retrieve
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load all records from a JSONL file."""
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def get_learnings_for_agent(
    agent_id: str,
    *,
    task_type: str = "",
    max_results: int = 15,
    min_confidence: float = 0.5,
    root: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Retrieve relevant learnings for a specific agent.

    Checks:
      1. Agent-specific ledger
      2. Global learnings that apply to this agent or have no restriction

    Filters by confidence and optional task_type.
    Returns most recent first, capped at max_results.
    """
    resolved_root = Path(root or ROOT).resolve()
    seen_ids: set[str] = set()
    candidates: list[dict[str, Any]] = []

    # Agent-specific learnings
    for rec in _load_jsonl(_agent_path(agent_id, resolved_root)):
        lid = rec.get("learning_id", "")
        if lid and lid not in seen_ids:
            seen_ids.add(lid)
            candidates.append(rec)

    # Global learnings that apply to this agent or everyone
    for rec in _load_jsonl(_global_path(resolved_root)):
        lid = rec.get("learning_id", "")
        if lid in seen_ids:
            continue
        applies = rec.get("applies_to", [])
        rec_agent = rec.get("agent_id", "")
        # Include if: explicitly applies to this agent, OR has no restriction
        # and is not owned by a different specific agent.
        if agent_id in applies:
            seen_ids.add(lid)
            candidates.append(rec)
        elif not applies and (not rec_agent or rec_agent == agent_id):
            seen_ids.add(lid)
            candidates.append(rec)

    # Filter
    filtered = []
    for rec in candidates:
        if rec.get("confidence", 0) < min_confidence:
            continue
        if task_type and rec.get("task_type") and rec["task_type"] != task_type:
            continue
        filtered.append(rec)

    # Sort by created_at descending, take most recent
    filtered.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return filtered[:max_results]


def get_recent_learnings(
    *,
    n: int = 20,
    root: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return the N most recent global learnings."""
    resolved_root = Path(root or ROOT).resolve()
    records = _load_jsonl(_global_path(resolved_root))
    records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return records[:n]


def compile_learnings_digest(
    agent_id: str,
    *,
    task_type: str = "",
    max_items: int = 8,
    root: Optional[Path] = None,
) -> str:
    """Compile a concise text digest of relevant learnings for an agent.

    Returns a short plain-text block suitable for inclusion in a context
    packet or prompt — NOT the full ledger. Designed for minimal token cost.
    """
    learnings = get_learnings_for_agent(
        agent_id,
        task_type=task_type,
        max_results=max_items,
        root=root,
    )
    if not learnings:
        return ""

    lines = [f"## Learnings for {agent_id}"]
    for i, rec in enumerate(learnings, 1):
        trigger = rec.get("trigger", "")
        lesson = rec.get("lesson", "")
        conf = rec.get("confidence", 0)
        lines.append(f"{i}. [{trigger}] (conf={conf}) {lesson}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Learnings ledger CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_record = sub.add_parser("record", help="Record a learning")
    p_record.add_argument("--trigger", required=True, choices=sorted(VALID_TRIGGERS))
    p_record.add_argument("--lesson", required=True)
    p_record.add_argument("--agent-id", default="")
    p_record.add_argument("--scope", default="global")
    p_record.add_argument("--evidence", default="")
    p_record.add_argument("--task-id", default="")
    p_record.add_argument("--task-type", default="")
    p_record.add_argument("--confidence", type=float, default=0.7)

    p_agent = sub.add_parser("agent", help="Get learnings for an agent")
    p_agent.add_argument("agent_id")
    p_agent.add_argument("--task-type", default="")
    p_agent.add_argument("--max", type=int, default=15)

    p_digest = sub.add_parser("digest", help="Compile learnings digest for an agent")
    p_digest.add_argument("agent_id")
    p_digest.add_argument("--task-type", default="")
    p_digest.add_argument("--max", type=int, default=8)

    p_recent = sub.add_parser("recent", help="Show recent global learnings")
    p_recent.add_argument("--n", type=int, default=20)

    args = parser.parse_args()

    if args.cmd == "record":
        result = record_learning(
            trigger=args.trigger,
            lesson=args.lesson,
            agent_id=args.agent_id,
            scope=args.scope,
            evidence=args.evidence,
            task_id=args.task_id,
            task_type=args.task_type,
            confidence=args.confidence,
        )
        print(json.dumps(result, indent=2))
    elif args.cmd == "agent":
        results = get_learnings_for_agent(args.agent_id, task_type=args.task_type, max_results=args.max)
        print(json.dumps(results, indent=2))
    elif args.cmd == "digest":
        print(compile_learnings_digest(args.agent_id, task_type=args.task_type, max_items=args.max))
    elif args.cmd == "recent":
        results = get_recent_learnings(n=args.n)
        print(json.dumps(results, indent=2))
    else:
        parser.print_help()
