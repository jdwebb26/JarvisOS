#!/usr/bin/env python3
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT.parent
TASK_DB = WORKSPACE / "tasks" / "tasks.db"
ARTIFACT_ROOT = WORKSPACE / "artifacts" / "qwen_live"
STATE_PATH = ROOT / "runtime" / "core" / "qwen_live_state.json"


def now_iso() -> str:
    return datetime.now().isoformat()


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def today_dir() -> Path:
    out = ARTIFACT_ROOT / datetime.now().strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)
    return out


def read_state() -> dict:
    if not STATE_PATH.exists():
        return {
            "last_reviewed_task_id": None,
            "last_reviewed_at": None,
            "reviewed_task_ids": [],
        }
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def classify_lane(task: dict) -> str:
    title = str(task.get("title", "") or "").lower()
    notes = str(task.get("notes", "") or "").lower()

    if "nq sf" in title or "strategy factory" in title or "nq" in title:
        return "nq_strategy"
    if "ops report" in title or "ops report" in notes:
        return "ops_report"
    if any(tok in title for tok in ["infra", "gateway", "worker", "executor", "dashboard", "bot"]):
        return "infra_impl"
    return "general_impl"


def scope_decision(task: dict) -> dict:
    title = str(task.get("title", "") or "").lower()
    status = str(task.get("status", "") or "").lower()
    priority = task.get("priority", 0)
    kind = str(task.get("kind", "") or "").lower()
    notes = str(task.get("notes", "") or "").lower()
    payload_path = str(task.get("payload_path", "") or "").strip()

    reasons = []
    allowed = True

    positive_signals = []
    if "strategy factory" in title or "nq sf" in title:
        positive_signals.append("strategy-factory workflow")
    if "ops report" in title:
        positive_signals.append("ops-report workflow")
    if any(tok in title for tok in ["p1.", "p2.", "phase", "step"]):
        positive_signals.append("structured phase/step naming")
    if any(tok in title for tok in ["implement", "build", "create", "fix"]):
        positive_signals.append("implementation-oriented title")

    has_impl_shape = len(positive_signals) >= 2 or (
        "implementation-oriented title" in positive_signals and int(priority or 0) >= 5
    )

    if status and status not in {"pending", "running", "done", "completed"}:
        allowed = False
        reasons.append(f"unexpected status={status}")

    try:
        prio = int(priority)
        if prio < 5:
            allowed = False
            reasons.append(f"priority too low ({priority})")
    except Exception:
        reasons.append(f"non-integer priority={priority}")

    if "helper" in title or "stub" in notes:
        allowed = False
        reasons.append("generic helper/stub task")

    if "smoke test" in title and not has_impl_shape:
        allowed = False
        reasons.append("generic smoke test without strong implementation signals")

    if not positive_signals:
        allowed = False
        reasons.append("missing structured implementation signals")

    if not payload_path:
        reasons.append("no payload_path present")

    if kind and kind not in {"prompt", "plan", "task", "strategy_factory"}:
        reasons.append(f"unrecognized kind={kind}")

    return {
        "allowed": allowed,
        "positive_signals": positive_signals,
        "reasons": reasons,
    }


def read_recent_tasks(limit: int) -> list[dict]:
    if not TASK_DB.exists():
        raise FileNotFoundError(f"Database not found: {TASK_DB}")

    conn = sqlite3.connect(str(TASK_DB))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        if row is None:
            raise RuntimeError("No 'tasks' table found in database.")

        pragma_rows = conn.execute("PRAGMA table_info(tasks)").fetchall()
        cols = [r["name"] if "name" in r.keys() else r[1] for r in pragma_rows]
        order_col = "created_at" if "created_at" in cols else ("updated_at" if "updated_at" in cols else "id")
        rows = conn.execute(
            f"SELECT * FROM tasks ORDER BY {order_col} DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{col: r[col] for col in r.keys()} for r in rows]
    finally:
        conn.close()


def score_task(task: dict, decision: dict, reviewed_ids: set[int]) -> int:
    lane = classify_lane(task)
    lane_weight = {
        "nq_strategy": 40,
        "ops_report": 30,
        "infra_impl": 20,
        "general_impl": 10,
    }

    try:
        priority = int(task.get("priority", 0) or 0)
    except Exception:
        priority = 0

    task_id = int(task.get("id", 0) or 0)
    title = str(task.get("title", "") or "").lower()

    score = 0
    score += lane_weight.get(lane, 0)
    score += priority * 5
    score += len(decision["positive_signals"]) * 8

    if "retry" in title:
        score -= 4
    if task_id in reviewed_ids:
        score -= 1000

    return score


def rank_candidates(tasks: list[dict], state: dict, top_n: int) -> list[dict]:
    reviewed_ids = {int(x) for x in state.get("reviewed_task_ids", []) if str(x).isdigit()}
    ranked = []

    for task in tasks:
        status = str(task.get("status", "") or "").lower()
        if status not in {"done", "completed"}:
            continue

        decision = scope_decision(task)
        if not decision["allowed"]:
            continue

        task_id = int(task.get("id", 0) or 0)
        lane = classify_lane(task)
        score = score_task(task, decision, reviewed_ids)

        ranked.append(
            {
                "task_id": task_id,
                "title": task.get("title"),
                "priority": task.get("priority"),
                "status": task.get("status"),
                "lane": lane,
                "score": score,
                "positive_signals": decision["positive_signals"],
                "reasons": decision["reasons"],
                "already_reviewed": task_id in reviewed_ids,
                "payload_path": task.get("payload_path"),
            }
        )

    ranked.sort(key=lambda x: (x["score"], x["task_id"]), reverse=True)
    return ranked[:top_n]


def write_artifact(tasks: list[dict], state: dict, limit: int) -> Path:
    out_dir = today_dir()
    out_path = out_dir / f"{now_stamp()}_recommendations.md"

    lines = [
        "# Qwen Live Recommendations",
        "",
        f"- timestamp: {now_iso()}",
        f"- scanned_recent_tasks: {limit}",
        f"- recommendations_returned: {len(tasks)}",
        "",
        "## Worker State",
        "```json",
        json.dumps(state, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Ranked Candidates",
        "",
    ]

    if not tasks:
        lines.append("No in-scope candidates found.")
    else:
        for i, task in enumerate(tasks, start=1):
            lines.extend(
                [
                    f"### {i}. Task {task['task_id']} — {task['title']}",
                    f"- lane: {task['lane']}",
                    f"- priority: {task['priority']}",
                    f"- status: {task['status']}",
                    f"- score: {task['score']}",
                    f"- already_reviewed: {task['already_reviewed']}",
                    f"- payload_path: {task['payload_path']}",
                    f"- positive_signals: {', '.join(task['positive_signals']) if task['positive_signals'] else '(none)'}",
                    f"- notes: {', '.join(task['reasons']) if task['reasons'] else '(none)'}",
                    "",
                ]
            )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    latest = out_dir / "latest_recommendations.md"
    latest.write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Rank live in-scope candidates for Qwen.")
    ap.add_argument("--limit", type=int, default=25, help="How many recent tasks to scan.")
    ap.add_argument("--top", type=int, default=5, help="How many recommendations to return.")
    ap.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = ap.parse_args()

    state = read_state()
    tasks = read_recent_tasks(args.limit)
    ranked = rank_candidates(tasks, state, args.top)
    artifact = write_artifact(ranked, state, args.limit)

    payload = {
        "ok": True,
        "scanned": len(tasks),
        "returned": len(ranked),
        "artifact": str(artifact),
        "recommendations": ranked,
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Wrote: {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
