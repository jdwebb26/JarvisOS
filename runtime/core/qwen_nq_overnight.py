#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

try:
    import requests
except Exception:
    requests = None

WORKSPACE = Path("/home/rollan/.openclaw/workspace")
JARVIS_V5 = WORKSPACE / "jarvis-v5"
BRIDGE = JARVIS_V5 / "runtime" / "core" / "qwen_live_bridge.py"
ARTIFACT_ROOT = WORKSPACE / "artifacts" / "qwen_live"

MODEL_SERVER = os.getenv("QWEN_AGENT_MODEL_SERVER", "http://100.70.114.34:1234/v1").rstrip("/")
MODEL_NAME = os.getenv("QWEN_AGENT_MODEL", "qwen3.5-35b-a3b")
API_KEY = os.getenv("QWEN_AGENT_API_KEY", "lm-studio")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def today_dir() -> Path:
    d = ARTIFACT_ROOT / datetime.now().strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    return d


def strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def run_bridge(limit: int) -> dict:
    proc = subprocess.run(
        ["python3", str(BRIDGE), "--json", "--limit", str(limit)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"bridge failed: {proc.stderr or proc.stdout}")
    return json.loads(proc.stdout)


def read_text(path: Path, max_chars: int) -> str:
    if not path.exists() or not path.is_file():
        return f"[missing file] {path}"
    return path.read_text(encoding="utf-8", errors="replace")[:max_chars]


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


def is_nq_candidate(title: str) -> bool:
    t = (title or "").lower()
    return ("nq sf" in t) or ("strategy factory" in t) or ("nq" in t and "implement" in t)


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
                    "You are a read-only overnight NQ strategy reviewer.\n"
                    "Do not propose uncontrolled autonomy.\n"
                    "Base your review only on provided task/result/file contents.\n"
                    "Do not claim you inspected files that were not included.\n"
                    "Return concise markdown."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
            "max_tokens": 1200,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    r = requests.post(f"{MODEL_SERVER}/chat/completions", headers=headers, json=payload, timeout=180)
    r.raise_for_status()
    data = r.json()
    text = data["choices"][0]["message"]["content"]
    return strip_think(text)


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
        "## What Looks Complete\n"
        "## Risks or Thin Areas\n"
        "## Next Read-Only Inspection\n"
        "## Smallest Safe Next Improvement\n\n"
        "Keep it grounded and under 500 words."
    )
    return "\n".join(parts)


def write_artifact(candidate: dict, report: str, bridge_payload: dict, result_preview: str) -> Path:
    out_dir = today_dir()
    task_id = candidate.get("task_id", "unknown")
    out_path = out_dir / f"{now_stamp()}_task_{task_id}_overnight_review.md"

    meta = [
        "# Qwen Overnight NQ Review",
        "",
        f"- timestamp: {datetime.now().isoformat()}",
        f"- task_id: {candidate.get('task_id')}",
        f"- title: {candidate.get('title')}",
        f"- priority: {candidate.get('priority')}",
        f"- status: {candidate.get('status')}",
        f"- model: {MODEL_NAME}",
        "",
        "## Bridge Payload",
        "```json",
        json.dumps(bridge_payload, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Result Preview",
        "```text",
        result_preview[:2000],
        "```",
        "",
        report,
        "",
    ]
    out_path.write_text("\n".join(meta), encoding="utf-8")
    latest = out_dir / "latest.md"
    latest.write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
    return out_path


def write_skip(reason: str, bridge_payload: dict) -> Path:
    out_dir = today_dir()
    out_path = out_dir / f"{now_stamp()}_skip.md"
    text = [
        "# Qwen Overnight NQ Review Skip",
        "",
        f"- timestamp: {datetime.now().isoformat()}",
        f"- reason: {reason}",
        "",
        "## Bridge Payload",
        "```json",
        json.dumps(bridge_payload, indent=2, ensure_ascii=False),
        "```",
        "",
    ]
    out_path.write_text("\n".join(text), encoding="utf-8")
    latest = out_dir / "latest.md"
    latest.write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only overnight NQ Qwen reviewer.")
    ap.add_argument("--limit", type=int, default=20, help="How many recent tasks to scan.")
    ap.add_argument("--max-file-chars", type=int, default=6000, help="Max chars per file.")
    args = ap.parse_args()

    bridge_payload = run_bridge(args.limit)

    if not bridge_payload.get("candidate_found"):
        out = write_skip("no in-scope candidate found", bridge_payload)
        print(f"Wrote: {out}")
        return 0

    title = str(bridge_payload.get("title") or "")
    if not is_nq_candidate(title):
        out = write_skip("top candidate is not NQ-related", bridge_payload)
        print(f"Wrote: {out}")
        return 0

    result_info = bridge_payload.get("result", {})
    result_path_rel = result_info.get("path")
    if not result_path_rel:
        out = write_skip("candidate has no result artifact path", bridge_payload)
        print(f"Wrote: {out}")
        return 0

    result_path = WORKSPACE / result_path_rel
    result_text = read_text(result_path, 12000)
    written_files = extract_written_files(result_text)

    file_blobs: list[tuple[str, str]] = []
    for p in written_files:
        rel = str(p.relative_to(WORKSPACE))
        file_blobs.append((rel, read_text(p, args.max_file_chars)))

    candidate = {
        "task_id": bridge_payload.get("task_id"),
        "title": bridge_payload.get("title"),
        "status": bridge_payload.get("status"),
        "priority": bridge_payload.get("priority"),
        "kind": bridge_payload.get("kind"),
        "payload_path": bridge_payload.get("payload_path"),
        "scope": bridge_payload.get("scope"),
    }

    prompt = build_prompt(candidate, result_text, file_blobs)
    report = call_model(prompt)
    out = write_artifact(candidate, report, bridge_payload, result_text)
    print(f"Wrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
