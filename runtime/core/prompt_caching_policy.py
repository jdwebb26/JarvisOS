#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_TIMESTAMP_PATTERNS = [
    re.compile(r"\b20\d{2}-\d{2}-\d{2}\b"),
    re.compile(r"\b20\d{6}_\d{6}\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"),
]
_APPROVAL_CODE_PATTERNS = [
    re.compile(r"\bapproval code\b", re.IGNORECASE),
    re.compile(r"\bcode:\s*\S+", re.IGNORECASE),
]
_VOLATILE_HINT_PATTERNS = [
    re.compile(r"\bstatus\b", re.IGNORECASE),
    re.compile(r"\bcurrent task\b", re.IGNORECASE),
    re.compile(r"\blatest output\b", re.IGNORECASE),
    re.compile(r"\bright now\b", re.IGNORECASE),
    re.compile(r"\btoday\b", re.IGNORECASE),
]


def _normalize_block(text: str) -> str:
    return (text or "").strip()


def _stable_prefix(system_prompt: str, developer_prompt: str, task_context: str) -> str:
    parts = [part for part in (_normalize_block(system_prompt), _normalize_block(developer_prompt), _normalize_block(task_context)) if part]
    return "\n\n".join(parts)


def split_prompt_for_cacheability(
    *,
    system_prompt: str = "",
    developer_prompt: str = "",
    task_context: str = "",
    volatile_suffix: str = "",
) -> dict:
    stable_prefix = _stable_prefix(system_prompt, developer_prompt, task_context)
    volatile = _normalize_block(volatile_suffix)
    return {
        "stable_prefix": stable_prefix,
        "volatile_suffix": volatile,
        "stable_prefix_char_count": len(stable_prefix),
        "volatile_suffix_char_count": len(volatile),
    }


def classify_prompt_cacheability(
    *,
    system_prompt: str = "",
    developer_prompt: str = "",
    task_context: str = "",
    volatile_suffix: str = "",
) -> dict:
    split = split_prompt_for_cacheability(
        system_prompt=system_prompt,
        developer_prompt=developer_prompt,
        task_context=task_context,
        volatile_suffix=volatile_suffix,
    )
    stable_prefix = split["stable_prefix"]
    volatile = split["volatile_suffix"]
    stable_len = split["stable_prefix_char_count"]
    volatile_len = split["volatile_suffix_char_count"]
    findings: list[str] = []

    for pattern in _TIMESTAMP_PATTERNS:
        if pattern.search(stable_prefix):
            findings.append("timestamp_in_stable_prefix")
            break
    for pattern in _APPROVAL_CODE_PATTERNS:
        if pattern.search(stable_prefix):
            findings.append("approval_code_in_stable_prefix")
            break
    for pattern in _VOLATILE_HINT_PATTERNS:
        if pattern.search(stable_prefix):
            findings.append("volatile_status_text_in_stable_prefix")
            break

    total_len = stable_len + volatile_len
    stable_ratio = (stable_len / total_len) if total_len > 0 else 0.0

    if stable_len == 0 and volatile_len > 0:
        cacheability = "low"
        reason = "no_stable_prefix_material"
    elif findings:
        cacheability = "low"
        reason = "stable_prefix_contains_volatile_material"
    elif stable_ratio >= 0.7 and stable_len >= 200:
        cacheability = "high"
        reason = "large_stable_prefix_small_volatile_suffix"
    elif stable_ratio >= 0.4 and stable_len >= 50:
        cacheability = "medium"
        reason = "mixed_stable_and_volatile_material"
    else:
        cacheability = "low"
        reason = "mostly_volatile_prompt_material"

    return {
        **split,
        "cacheability": cacheability,
        "findings": findings,
        "reason": reason,
    }


def build_prompt_caching_policy_summary(root: Optional[Path] = None) -> dict:
    del root
    return {
        "prompt_caching_policy_present": True,
        "supported_checks": [
            "stable_prefix_split",
            "volatile_suffix_split",
            "timestamp_in_stable_prefix",
            "approval_code_in_stable_prefix",
            "volatile_status_text_in_stable_prefix",
        ],
        "example_cacheability_levels": ["high", "medium", "low"],
        "notes": [
            "Stable prefix should hold system, developer, and reusable task scaffold material.",
            "Volatile suffix should hold per-run operator text, timestamps, status snippets, and approval codes.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the prompt-caching policy summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_prompt_caching_policy_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
