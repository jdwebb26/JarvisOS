#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path


ARTIFACT_ROOT = Path("/home/rollan/.openclaw/workspace/artifacts/qwen_live")


def now_iso() -> str:
    return datetime.now().isoformat()


def today_dir() -> Path:
    out = ARTIFACT_ROOT / datetime.now().strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_artifact(name: str, body: str) -> Path:
    out = today_dir() / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{name}.md"
    out.write_text(body, encoding="utf-8")
    latest = today_dir() / f"latest_{name}.md"
    latest.write_text(body, encoding="utf-8")
    return out


def validate_python(path: Path) -> tuple[bool, str]:
    p = subprocess.run(
        ["python3", "-m", "py_compile", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if p.returncode == 0:
        return True, "py_compile ok"
    return False, (p.stdout or "").strip()[:4000]


def extract_first_function_name(text: str) -> str:
    m = re.search(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text, flags=re.MULTILINE)
    if not m:
        raise RuntimeError("No Python function definition found in candidate scope file.")
    return m.group(1)


def strip_block_marker(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("# BLOCK: "):
        lines = lines[1:]
    return "\n".join(lines).lstrip("\n")


def extract_top_level_function_block(text: str, func_name: str) -> tuple[int, int, str]:
    lines = text.splitlines()
    start = None

    for i, line in enumerate(lines):
        if line.startswith(f"def {func_name}("):
            start = i
            break

    if start is None:
        raise RuntimeError(f"Function not found in target file: {func_name}")

    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.startswith("def ") or line.startswith("class "):
            end = i
            break

    block = "\n".join(lines[start:end]).rstrip() + "\n"
    return start, end, block


def replace_top_level_function_block(target_text: str, func_name: str, replacement_block: str) -> str:
    lines = target_text.splitlines()
    start, end, _old = extract_top_level_function_block(target_text, func_name)
    replacement_lines = replacement_block.rstrip("\n").splitlines()
    if end < len(lines) and (lines[end].startswith("def ") or lines[end].startswith("class ")):
        if not replacement_lines or replacement_lines[-1].strip() != "":
            replacement_lines.append("")
    new_lines = lines[:start] + replacement_lines + lines[end:]
    return "\n".join(new_lines).rstrip() + "\n"

def main() -> int:
    ap = argparse.ArgumentParser(description="Safely graft a single top-level Python function block into a target file.")
    ap.add_argument("--target-file", required=True)
    ap.add_argument("--scope-candidate", required=True)
    ap.add_argument("--out-file", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    target_file = Path(args.target_file)
    scope_candidate = Path(args.scope_candidate)

    if not target_file.exists():
        raise RuntimeError(f"Target file not found: {target_file}")
    if not scope_candidate.exists():
        raise RuntimeError(f"Scope candidate not found: {scope_candidate}")

    target_text = target_file.read_text(encoding="utf-8", errors="replace")
    scope_text_raw = scope_candidate.read_text(encoding="utf-8", errors="replace")
    scope_text = strip_block_marker(scope_text_raw)

    func_name = extract_first_function_name(scope_text)
    _start, _end, old_block = extract_top_level_function_block(target_text, func_name)
    new_text = replace_top_level_function_block(target_text, func_name, scope_text)

    out_file = Path(args.out_file) if args.out_file else (today_dir() / "apply_candidates" / target_file.name)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(new_text, encoding="utf-8")

    syntax_valid, validation_msg = validate_python(out_file)

    body = "\n".join(
        [
            "# Qwen Scope Apply",
            "",
            f"- timestamp: {now_iso()}",
            f"- target_file: {target_file}",
            f"- scope_candidate: {scope_candidate}",
            f"- out_file: {out_file}",
            f"- function_name: {func_name}",
            f"- syntax_valid: {syntax_valid}",
            f"- validation_msg: {validation_msg}",
            "",
            "## Outcome",
            "- Created a grafted full-file candidate only.",
            "- No live file was modified.",
        ]
    )
    artifact = write_artifact("scope_apply", body)

    payload = {
        "ok": True,
        "target_file": str(target_file),
        "scope_candidate": str(scope_candidate),
        "out_file": str(out_file),
        "function_name": func_name,
        "syntax_valid": syntax_valid,
        "validation_msg": validation_msg,
        "artifact": str(artifact),
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Wrote: {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
