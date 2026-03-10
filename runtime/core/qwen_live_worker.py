#!/usr/bin/env python3
import argparse
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

try:
    import requests
except Exception:
    requests = None

WORKSPACE = Path("/home/rollan/.openclaw/workspace")
TASK_DB = WORKSPACE / "tasks" / "tasks.db"
RESULTS_DIR = WORKSPACE / "tasks" / "results"
ARTIFACT_ROOT = WORKSPACE / "artifacts" / "qwen_live"
STATE_PATH = WORKSPACE / "jarvis-v5" / "runtime" / "core" / "qwen_live_state.json"

MODEL_SERVER = os.getenv("QWEN_AGENT_MODEL_SERVER", "http://100.70.114.34:1234/v1").rstrip("/")
MODEL_NAME = os.getenv("QWEN_AGENT_MODEL", "qwen3.5-35b-a3b")
API_KEY = os.getenv("QWEN_AGENT_API_KEY", "lm-studio")


def now_iso() -> str:
    return datetime.now().isoformat()


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def today_dir() -> Path:
    out = ARTIFACT_ROOT / datetime.now().strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)
    return out


def strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def read_state() -> dict:
    if not STATE_PATH.exists():
        return {
            "last_reviewed_task_id": None,
            "last_reviewed_at": None,
            "reviewed_task_ids": [],
        }
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def write_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


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


def pick_next_candidate(tasks: list[dict], state: dict) -> tuple[dict | None, dict | None]:
    reviewed = {int(x) for x in state.get("reviewed_task_ids", []) if str(x).isdigit()}
    candidates: list[tuple[dict, dict]] = []

    for task in tasks:
        task_id = int(task.get("id", 0) or 0)
        status = str(task.get("status", "") or "").lower()

        if task_id in reviewed:
            continue
        if status not in {"done", "completed"}:
            continue

        decision = scope_decision(task)
        if not decision["allowed"]:
            continue
        candidates.append((task, decision))

    if not candidates:
        return None, None

    lane_weight = {
        "nq_strategy": 4,
        "ops_report": 3,
        "infra_impl": 2,
        "general_impl": 1,
    }

    def sort_key(item: tuple[dict, dict]):
        task, decision = item
        lane = classify_lane(task)
        try:
            priority = int(task.get("priority", 0) or 0)
        except Exception:
            priority = 0
        task_id = int(task.get("id", 0) or 0)
        return (
            lane_weight.get(lane, 0),
            priority,
            len(decision["positive_signals"]),
            task_id,
        )

    candidates.sort(key=sort_key, reverse=True)
    return candidates[0]


def read_text(path: Path, max_chars: int) -> str:
    if not path.exists() or not path.is_file():
        return f"[missing file] {path}"
    return path.read_text(encoding="utf-8", errors="replace")[:max_chars]


def read_result_preview(task_id: int, max_chars: int = 12000) -> dict:
    path = RESULTS_DIR / f"{task_id}.md"
    if not path.exists() or not path.is_file():
        return {
            "path": str(path),
            "exists": False,
            "preview": "",
        }

    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": str(path.relative_to(WORKSPACE)),
        "exists": True,
        "preview": text[:max_chars],
        "truncated": len(text) > max_chars,
        "total_chars": len(text),
    }


def extract_written_files(result_markdown: str) -> list[Path]:
    files: list[Path] = []
    for line in result_markdown.splitlines():
        line = line.strip()
        if not line.startswith("- /home/rollan/.openclaw/workspace/"):
            continue
        p = Path(line[2:].strip())
        try:
            p.resolve().relative_to(WORKSPACE)
            files.append(p)
        except Exception:
            continue
    return files[:6]


def call_model(prompt: str) -> str:
    if requests is None:
        raise RuntimeError("requests is not installed. Install with: pip install requests")
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": (
                    "/no_think\n"
                    "You are a read-only live task reviewer for Jarvis v5.\n"
                    "Base your review only on provided task/result/file contents.\n"
                    "Do not claim you inspected files that were not included.\n"
                    "Return concise markdown."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
            "max_tokens": 900,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    r = requests.post(f"{MODEL_SERVER}/chat/completions", headers=headers, json=payload, timeout=180)
    r.raise_for_status()
    data = r.json()
    return strip_think(data["choices"][0]["message"]["content"])


def build_prompt(candidate: dict, result_text: str, file_blobs: list[tuple[str, str]]) -> str:
    parts = []
    parts.append("# Candidate")
    parts.append(json.dumps(candidate, indent=2, ensure_ascii=False))
    parts.append("")
    parts.append("# Result Artifact")
    parts.append(result_text)
    parts.append("")

    for name, content in file_blobs:
        parts.append(f"# File: {name}")
        parts.append(content)
        parts.append("")

    parts.append(
        "Write a markdown review with these sections only:\n"
        "## Summary\n"
        "## Lane Classification\n"
        "## What Looks Complete\n"
        "## Risks or Thin Areas\n"
        "## Next Read-Only Inspection\n"
        "## Smallest Safe Next Improvement\n\n"
        "Keep it grounded and under 550 words."
    )
    return "\n".join(parts)


def write_artifact(candidate: dict, report: str, result_preview: dict, state: dict) -> Path:
    out_dir = today_dir()
    task_id = candidate.get("task_id", "unknown")
    lane = candidate.get("lane", "unknown")
    out_path = out_dir / f"{now_stamp()}_{lane}_task_{task_id}_live_review.md"

    text = [
        "# Qwen Live Worker Review",
        "",
        f"- timestamp: {now_iso()}",
        f"- task_id: {candidate.get('task_id')}",
        f"- title: {candidate.get('title')}",
        f"- priority: {candidate.get('priority')}",
        f"- status: {candidate.get('status')}",
        f"- lane: {candidate.get('lane')}",
        f"- model: {MODEL_NAME}",
        "",
        "## Scope Decision",
        "```json",
        json.dumps(candidate.get("scope", {}), indent=2, ensure_ascii=False),
        "```",
        "",
        "## Result Preview",
        "```text",
        result_preview.get("preview", "")[:2000],
        "```",
        "",
        "## Worker State Before Write",
        "```json",
        json.dumps(state, indent=2, ensure_ascii=False),
        "```",
        "",
        report,
        "",
    ]
    out_path.write_text("\n".join(text), encoding="utf-8")
    latest = out_dir / "latest.md"
    latest.write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
    return out_path


def write_skip(reason: str, state: dict, scanned: int) -> Path:
    out_dir = today_dir()
    out_path = out_dir / f"{now_stamp()}_skip.md"
    text = [
        "# Qwen Live Worker Skip",
        "",
        f"- timestamp: {now_iso()}",
        f"- reason: {reason}",
        f"- scanned: {scanned}",
        "",
        "## Worker State",
        "```json",
        json.dumps(state, indent=2, ensure_ascii=False),
        "```",
        "",
    ]
    out_path.write_text("\n".join(text), encoding="utf-8")
    latest = out_dir / "latest.md"
    latest.write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
    return out_path


def write_error(reason: str) -> Path:
    out_dir = today_dir()
    out_path = out_dir / f"{now_stamp()}_error.md"
    text = [
        "# Qwen Live Worker Error",
        "",
        f"- timestamp: {now_iso()}",
        f"- reason: {reason}",
        "",
    ]
    out_path.write_text("\n".join(text), encoding="utf-8")
    latest = out_dir / "latest.md"
    latest.write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only live Qwen worker across all in-scope lanes.")
    ap.add_argument("--limit", type=int, default=20, help="How many recent tasks to scan.")
    ap.add_argument("--max-file-chars", type=int, default=6000, help="Max chars per related file.")
    ap.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = ap.parse_args()

    try:
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        state = read_state()
        tasks = read_recent_tasks(args.limit)
        task, decision = pick_next_candidate(tasks, state)

        if task is None:
            out = write_skip("no new in-scope candidate found", state, len(tasks))
            payload = {
                "ok": True,
                "candidate_found": False,
                "scanned": len(tasks),
                "artifact": str(out),
            }
            print(json.dumps(payload, indent=2) if args.json else f"Wrote: {out}")
            return 0

        task_id = int(task["id"])
        lane = classify_lane(task)
        result_preview = read_result_preview(task_id)
        result_text = result_preview.get("preview", "")
        written_files = extract_written_files(result_text)

        file_blobs: list[tuple[str, str]] = []
        for p in written_files:
            rel = str(p.relative_to(WORKSPACE))
            file_blobs.append((rel, read_text(p, args.max_file_chars)))

        candidate = {
            "task_id": task.get("id"),
            "title": task.get("title"),
            "status": task.get("status"),
            "priority": task.get("priority"),
            "kind": task.get("kind"),
            "payload_path": task.get("payload_path"),
            "lane": lane,
            "scope": decision,
        }

        prompt = build_prompt(candidate, result_text, file_blobs)
        report = call_model(prompt)
        out = write_artifact(candidate, report, result_preview, state)

        reviewed = [int(x) for x in state.get("reviewed_task_ids", []) if str(x).isdigit()]
        if task_id not in reviewed:
            reviewed.append(task_id)
        state["reviewed_task_ids"] = reviewed[-50:]
        state["last_reviewed_task_id"] = task_id
        state["last_reviewed_at"] = now_iso()
        write_state(state)

        payload = {
            "ok": True,
            "candidate_found": True,
            "task_id": task_id,
            "title": task.get("title"),
            "lane": lane,
            "artifact": str(out),
            "state_path": str(STATE_PATH),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else f"Wrote: {out}")
        return 0

    except Exception as e:
        out = write_error(str(e))
        print(json.dumps({"ok": False, "error": str(e), "artifact": str(out)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
