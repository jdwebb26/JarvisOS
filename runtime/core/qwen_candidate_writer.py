#!/usr/bin/env python3
import argparse
import ast
import json
import os
import py_compile
import re
from datetime import datetime
from pathlib import Path

try:
    import requests
except Exception:
    requests = None

WORKSPACE = Path("/home/rollan/.openclaw/workspace")
ALLOWED_EXTRA_ROOT = WORKSPACE / "tasks"
ARTIFACT_ROOT = WORKSPACE / "artifacts" / "qwen_live"
APPROVAL_PATH = WORKSPACE / "jarvis-v5" / "runtime" / "core" / "qwen_approval_state.json"
WRITE_GATE_PATH = WORKSPACE / "jarvis-v5" / "runtime" / "core" / "qwen_write_gate.json"
TASKS_DIR = WORKSPACE / "jarvis-v5" / "state" / "tasks"

MODEL_SERVER = os.getenv("QWEN_AGENT_MODEL_SERVER", "http://172.23.64.1:1234/v1").rstrip("/")
MODEL_NAME = os.getenv("QWEN_AGENT_MODEL", "qwen/qwen3.5-9b")
API_KEY = os.getenv("QWEN_AGENT_API_KEY", "lm-studio")
MAX_FULL_REWRITE_CHARS = 6000
MAX_MODEL_OUTPUT_TOKENS = 2400
PREFERRED_SCOPE_HINTS = {
    "/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/decision_router.py": [
        "route_task_for_decision",
    ],
    "/home/rollan/.openclaw/workspace/tasks/local_executor.py": [
        "build_ops_report_snapshot",
        "write_ops_report_artifact",
    ],
}
PREFERRED_MICRO_SCOPE_HINTS = {
    "/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/decision_router.py": {
        "route_task_for_decision": [
            {"label": "review_required_branch", "test_contains": "task.review_required"},
            {"label": "approval_required_branch", "test_contains": "task.approval_required"},
        ],
    },
}
PREFERRED_NANO_SCOPE_HINTS = {
    "/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/decision_router.py": {
        "route_task_for_decision": [
            {"label": "latest_review_missing_branch", "parent_test_contains": "task.review_required", "test_contains": "latest_review is None"},
            {"label": "latest_review_pending_branch", "parent_test_contains": "task.review_required", "test_contains": "latest_review.status == \"pending\""},
            {"label": "latest_review_blocked_branch", "parent_test_contains": "task.review_required", "test_contains": "latest_review.status != \"approved\""},
        ],
    },
}
PREFERRED_LEAF_SCOPE_HINTS = {
    "/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/decision_router.py": {
        "route_task_for_decision": [
            {"label": "latest_review_missing_return", "parent_test_contains": "task.review_required", "test_contains": "latest_review is None"},
            {"label": "latest_review_pending_return", "parent_test_contains": "task.review_required", "test_contains": "latest_review.status == \"pending\""},
            {"label": "latest_review_blocked_return", "parent_test_contains": "task.review_required", "test_contains": "latest_review.status != \"approved\""},
        ],
    },
}
MAX_LEAF_SCOPE_REWRITE_CHARS = 700
MAX_NANO_SCOPE_REWRITE_CHARS = 1200
MAX_MICRO_SCOPE_REWRITE_CHARS = 2400
MAX_SCOPE_REWRITE_CHARS = 5000
DECISION_ROUTER_TARGET = "/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/decision_router.py"
DECISION_ROUTER_PROTECTED_KINDS = (
    "review_requested",
    "waiting_review",
    "blocked_by_review",
    "approval_requested",
    "waiting_approval",
    "blocked_by_approval",
    "no_action",
)
DECISION_ROUTER_PROTECTED_KEYS = (
    "review_id",
    "approval_id",
    "reviewer_role",
    "requested_reviewer",
    "status",
    "message",
    "task_id",
    "kind",
)
DECISION_ROUTER_PROTECTED_MESSAGES = (
    "A review already exists and is still pending.",
    "The latest review is not approved, so the task cannot proceed.",
    "An approval request already exists and is still pending.",
    "The latest approval is not approved, so the task cannot proceed.",
    "No new review or approval request was needed.",
)
DECISION_ROUTER_BRANCH_SPECS = (
    ("latest_review_none", "task.review_required", "latest_review is None"),
    ("latest_review_pending", "task.review_required", 'latest_review.status == "pending"'),
    ("latest_review_blocked", "task.review_required", 'latest_review.status != "approved"'),
    ("latest_approval_none", "task.approval_required", "latest_approval is None"),
    ("latest_approval_pending", "task.approval_required", 'latest_approval.status == "pending"'),
    ("latest_approval_blocked", "task.approval_required", 'latest_approval.status != "approved"'),
)
ANALYSIS_PREFIXES = (
    "the user wants",
    "here is",
    "here's",
    "below is",
    "i will",
    "i'll",
    "i can",
    "i need to",
    "we need to",
    "this patch",
    "this file",
    "analysis:",
)
ANALYSIS_MARKERS = (
    "<think>",
    "thinking process:",
    "patch plan:",
    "current file content:",
    "scoped file content:",
    "target file:",
    "task:",
)
class CandidateRejected(RuntimeError):
    def __init__(self, output_status: str, message: str, raw_text: str = ""):
        super().__init__(message)
        self.output_status = output_status
        self.message = message
        self.raw_text = raw_text


class ModelCallFailure(RuntimeError):
    def __init__(self, message: str, raw_text: str = ""):
        super().__init__(message)
        self.message = message
        self.raw_text = raw_text


def normalize_condition_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def semantic_text_mentions(text: str, needle: str) -> bool:
    lowered = (text or "").lower()
    needle_lower = needle.lower()
    return needle_lower in lowered or f'"{needle_lower}"' in lowered or f"'{needle_lower}'" in lowered


def semantic_change_allowed(old: str, new: str, patch_plan_text: str) -> bool:
    if not old or not new:
        return False
    lowered = (patch_plan_text or "").lower()
    old_lower = old.lower()
    new_lower = new.lower()
    patterns = (
        f"{old_lower} -> {new_lower}",
        f'"{old_lower}" -> "{new_lower}"',
        f"'{old_lower}' -> '{new_lower}'",
        f"{old_lower}->{new_lower}",
        f'"{old_lower}"=>"{new_lower}"',
        f"change {old_lower} to {new_lower}",
        f"rename {old_lower} to {new_lower}",
    )
    return any(pattern in lowered for pattern in patterns)


def extract_return_contract(return_node: ast.Return) -> dict | None:
    if not isinstance(return_node.value, ast.Dict):
        return None
    contract = {
        "kind": None,
        "keys": [],
        "message": None,
    }
    keys = []
    for key_node, value_node in zip(return_node.value.keys, return_node.value.values):
        if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
            continue
        key = key_node.value
        keys.append(key)
        if key == "kind" and isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
            contract["kind"] = value_node.value
        if key == "message" and isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
            contract["message"] = value_node.value
    contract["keys"] = sorted(keys)
    return contract


def extract_decision_router_branch_contracts(text: str) -> tuple[dict, list[str]]:
    failures = []
    try:
        tree = ast.parse(text, filename=DECISION_ROUTER_TARGET)
    except SyntaxError as exc:
        return {}, [f"parse_error: {exc}"]

    function_node = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "route_task_for_decision":
            function_node = node
            break
    if function_node is None:
        return {}, ["route_task_for_decision missing"]

    contracts = {}
    body = getattr(function_node, "body", [])
    for stmt in body:
        if isinstance(stmt, ast.If):
            parent_test = normalize_condition_text(ast.get_source_segment(text, stmt.test) or "")
            for nested in getattr(stmt, "body", []):
                if not isinstance(nested, ast.If):
                    continue
                nested_test = normalize_condition_text(ast.get_source_segment(text, nested.test) or "")
                for label, parent_match, nested_match in DECISION_ROUTER_BRANCH_SPECS:
                    if parent_test == parent_match and nested_test == nested_match:
                        return_node = next((item for item in getattr(nested, "body", []) if isinstance(item, ast.Return)), None)
                        if return_node is None:
                            failures.append(f"{label}: return missing")
                            continue
                        contract = extract_return_contract(return_node)
                        if contract is None:
                            failures.append(f"{label}: return payload not dict")
                            continue
                        contracts[label] = contract
        elif isinstance(stmt, ast.Return):
            contract = extract_return_contract(stmt)
            if contract is None:
                failures.append("terminal_no_action: return payload not dict")
            else:
                contracts["terminal_no_action"] = contract

    expected = {label for label, _parent, _nested in DECISION_ROUTER_BRANCH_SPECS} | {"terminal_no_action"}
    for label in sorted(expected - set(contracts)):
        failures.append(f"{label}: branch contract missing")
    return contracts, failures


def check_decision_router_semantic_guard(
    *,
    target_path: str,
    live_text: str,
    candidate_text: str,
    patch_plan_text: str,
) -> dict:
    result = {
        "applied": False,
        "passed": True,
        "reason": "",
        "drifted_tokens": [],
        "target": "",
        "mode": "",
        "branch_checks": [],
        "branch_failures": [],
        "allowlisted_changes": [],
    }
    target = Path(target_path)
    if not (target.name == "decision_router.py" and target.parent.name == "core" and target.parent.parent.name == "runtime"):
        return result

    result["applied"] = True
    result["target"] = str(target)
    result["mode"] = "branch_local_contract"

    live_contracts, live_failures = extract_decision_router_branch_contracts(live_text)
    candidate_contracts, candidate_failures = extract_decision_router_branch_contracts(candidate_text)
    if live_failures or candidate_failures:
        result["passed"] = False
        result["branch_failures"] = live_failures + candidate_failures
        result["reason"] = "decision_router branch-contract extraction failed"
        return result

    drifted = []
    branch_failures = []
    allowlisted = []
    branch_checks = []
    for label in sorted(live_contracts):
        live_contract = live_contracts.get(label)
        candidate_contract = candidate_contracts.get(label)
        branch_checks.append(
            {
                "branch": label,
                "live_kind": None if not live_contract else live_contract.get("kind"),
                "candidate_kind": None if not candidate_contract else candidate_contract.get("kind"),
                "live_keys": [] if not live_contract else live_contract.get("keys", []),
                "candidate_keys": [] if not candidate_contract else candidate_contract.get("keys", []),
                "live_message": None if not live_contract else live_contract.get("message"),
                "candidate_message": None if not candidate_contract else candidate_contract.get("message"),
            }
        )
        if live_contract is None or candidate_contract is None:
            branch_failures.append(f"{label}: branch contract missing")
            continue

        live_kind = live_contract.get("kind")
        candidate_kind = candidate_contract.get("kind")
        if live_kind != candidate_kind:
            if semantic_change_allowed(live_kind or "", candidate_kind or "", patch_plan_text):
                allowlisted.append(f"{label}: kind {live_kind} -> {candidate_kind}")
            else:
                branch_failures.append(f"{label}: kind {live_kind} -> {candidate_kind}")
                if live_kind:
                    drifted.append(live_kind)

        live_keys_all = set(live_contract.get("keys", []))
        candidate_keys_all = set(candidate_contract.get("keys", []))
        live_keys = {key for key in live_keys_all if key in DECISION_ROUTER_PROTECTED_KEYS}
        candidate_keys = {key for key in candidate_keys_all if key in DECISION_ROUTER_PROTECTED_KEYS}
        removed_keys = sorted(live_keys - candidate_keys_all)
        added_keys_all = sorted(candidate_keys_all - live_keys_all)
        if removed_keys or added_keys_all:
            if len(removed_keys) == 1 and len(added_keys_all) == 1 and semantic_change_allowed(removed_keys[0], added_keys_all[0], patch_plan_text):
                allowlisted.append(f"{label}: key {removed_keys[0]} -> {added_keys_all[0]}")
            else:
                for key in removed_keys:
                    branch_failures.append(f"{label}: removed key {key}")
                    drifted.append(key)
                for key in added_keys_all:
                    if key in DECISION_ROUTER_PROTECTED_KEYS:
                        branch_failures.append(f"{label}: added key {key}")
                        drifted.append(key)

        live_message = live_contract.get("message")
        candidate_message = candidate_contract.get("message")
        if live_message != candidate_message:
            if semantic_change_allowed(live_message or "", candidate_message or "", patch_plan_text):
                allowlisted.append(f"{label}: message {live_message!r} -> {candidate_message!r}")
            else:
                branch_failures.append(f"{label}: message {live_message!r} -> {candidate_message!r}")
                if live_message:
                    drifted.append(live_message)

    drifted = list(dict.fromkeys(drifted))
    result["drifted_tokens"] = drifted
    result["branch_checks"] = branch_checks
    result["branch_failures"] = branch_failures
    result["allowlisted_changes"] = allowlisted
    if branch_failures:
        result["passed"] = False
        result["reason"] = "decision_router branch-contract drift rejected: " + "; ".join(branch_failures)
    return result


def now_iso() -> str:
    return datetime.now().isoformat()


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def today_dir() -> Path:
    out = ARTIFACT_ROOT / datetime.now().strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)
    return out


def extract_patch_intent_summary(patch_plan_text: str, limit: int = 240) -> str:
    items = []
    active = False
    for line in (patch_plan_text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            active = stripped in {"## Smallest Safe Patch", "## Summary"}
            continue
        if active and stripped.startswith("- "):
            item = stripped[2:].strip()
            if item and "/home/rollan/" not in item:
                items.append(item)
        if len(" ".join(items)) >= limit:
            break
    if not items:
        fallback = re.sub(r"\s+", " ", patch_plan_text or "").strip()
        return fallback[:limit]
    return "; ".join(items)[:limit]


def preferred_scope_names(target_path: str, patch_plan_text: str) -> list[str]:
    names = list(PREFERRED_SCOPE_HINTS.get(target_path, []))
    if not names:
        target_name = Path(target_path).name
        for hint_path, hint_names in PREFERRED_SCOPE_HINTS.items():
            if Path(hint_path).name == target_name:
                names = list(hint_names)
                break
    lowered_plan = (patch_plan_text or "").lower()
    for name in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", patch_plan_text or ""):
        if name.lower() in lowered_plan:
            if name not in names:
                names.append(name)
    return names


def select_python_scope(target_path: str, current_text: str, patch_plan_text: str) -> dict | None:
    try:
        tree = ast.parse(current_text, filename=target_path)
    except SyntaxError:
        return None

    top_level = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", None)
            if start is None or end is None:
                continue
            top_level.append(
                {
                    "name": node.name,
                    "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                    "start_line": start,
                    "end_line": end,
                }
            )

    if not top_level:
        return None

    preferred = preferred_scope_names(target_path, patch_plan_text)
    chosen = None
    for name in preferred:
        for block in top_level:
            if block["name"] == name:
                chosen = block
                break
        if chosen is not None:
            break
    if chosen is None:
        lowered_plan = (patch_plan_text or "").lower()
        for block in top_level:
            if block["name"].lower() in lowered_plan:
                chosen = block
                break
    if chosen is None:
        return None

    lines = current_text.splitlines(keepends=True)
    chosen["text"] = "".join(lines[chosen["start_line"] - 1 : chosen["end_line"]])
    chosen["strategy"] = "python_top_level_block"
    return chosen


def write_scope_target_artifact(target_path: str, scope: dict) -> str:
    if not scope:
        return ""
    out_dir = today_dir() / "scope_targets"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(target_path).stem
    scope_path = out_dir / f"{stem}__{scope['name']}.py"
    body = "\n".join(
        [
            f"# BLOCK: {scope['name']}",
            f"# START_LINE: {scope['start_line']}",
            f"# END_LINE: {scope['end_line']}",
            scope["text"].rstrip(),
            "",
        ]
    ).rstrip() + "\n"
    scope_path.write_text(body, encoding="utf-8")
    return str(scope_path)


def stitch_python_scope(current_text: str, scope: dict, replacement_text: str) -> str:
    lines = current_text.splitlines(keepends=True)
    replacement = replacement_text
    if replacement and not replacement.endswith("\n"):
        replacement += "\n"
    replacement_lines = replacement.splitlines(keepends=True)
    stitched = lines[: scope["start_line"] - 1] + replacement_lines + lines[scope["end_line"] :]
    return "".join(stitched)


def detect_indent(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line[: len(line) - len(line.lstrip(" "))]
    return ""


def extract_line_block(text: str, start_line: int, end_line: int) -> str:
    lines = text.splitlines(keepends=True)
    return "".join(lines[start_line - 1 : end_line])


def preferred_micro_scope_specs(target_path: str, scope_name: str) -> list[dict]:
    specs = list(PREFERRED_MICRO_SCOPE_HINTS.get(target_path, {}).get(scope_name, []))
    if specs:
        return specs
    target_name = Path(target_path).name
    for hint_path, scope_map in PREFERRED_MICRO_SCOPE_HINTS.items():
        if Path(hint_path).name == target_name:
            return list(scope_map.get(scope_name, []))
    return []


def preferred_nano_scope_specs(target_path: str, scope_name: str) -> list[dict]:
    specs = list(PREFERRED_NANO_SCOPE_HINTS.get(target_path, {}).get(scope_name, []))
    if specs:
        return specs
    target_name = Path(target_path).name
    for hint_path, scope_map in PREFERRED_NANO_SCOPE_HINTS.items():
        if Path(hint_path).name == target_name:
            return list(scope_map.get(scope_name, []))
    return []


def preferred_leaf_scope_specs(target_path: str, scope_name: str) -> list[dict]:
    specs = list(PREFERRED_LEAF_SCOPE_HINTS.get(target_path, {}).get(scope_name, []))
    if specs:
        return specs
    target_name = Path(target_path).name
    for hint_path, scope_map in PREFERRED_LEAF_SCOPE_HINTS.items():
        if Path(hint_path).name == target_name:
            return list(scope_map.get(scope_name, []))
    return []


def select_python_micro_scope(target_path: str, current_text: str, top_scope: dict) -> dict | None:
    specs = preferred_micro_scope_specs(target_path, top_scope["name"])
    if not specs:
        return None
    try:
        tree = ast.parse(current_text, filename=target_path)
    except SyntaxError:
        return None

    function_node = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == top_scope["name"]:
            if getattr(node, "lineno", None) == top_scope["start_line"]:
                function_node = node
                break
    if function_node is None:
        return None

    candidates = []
    for stmt in getattr(function_node, "body", []):
        if not isinstance(stmt, ast.If):
            continue
        start_line = getattr(stmt, "lineno", None)
        end_line = getattr(stmt, "end_lineno", None)
        if start_line is None or end_line is None:
            continue
        test_text = ast.get_source_segment(current_text, stmt.test) or ""
        block_text = extract_line_block(current_text, start_line, end_line)
        candidates.append(
            {
                "label": f"if_block_{start_line}",
                "strategy": "python_if_block",
                "start_line": start_line,
                "end_line": end_line,
                "test_text": test_text,
                "text": block_text,
                "indent": detect_indent(block_text),
            }
        )

    if not candidates:
        return None

    for spec in specs:
        for candidate in candidates:
            if spec["test_contains"] in candidate["test_text"]:
                candidate["label"] = spec["label"]
                return candidate
    return None


def select_python_nano_scope(target_path: str, current_text: str, top_scope: dict) -> dict | None:
    specs = preferred_nano_scope_specs(target_path, top_scope["name"])
    if not specs:
        return None
    try:
        tree = ast.parse(current_text, filename=target_path)
    except SyntaxError:
        return None

    function_node = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == top_scope["name"]:
            if getattr(node, "lineno", None) == top_scope["start_line"]:
                function_node = node
                break
    if function_node is None:
        return None

    candidates = []
    for stmt in getattr(function_node, "body", []):
        if not isinstance(stmt, ast.If):
            continue
        parent_test_text = ast.get_source_segment(current_text, stmt.test) or ""
        for nested in getattr(stmt, "body", []):
            if not isinstance(nested, ast.If):
                continue
            start_line = getattr(nested, "lineno", None)
            end_line = getattr(nested, "end_lineno", None)
            if start_line is None or end_line is None:
                continue
            test_text = ast.get_source_segment(current_text, nested.test) or ""
            block_text = extract_line_block(current_text, start_line, end_line)
            candidates.append(
                {
                    "label": f"if_block_{start_line}",
                    "strategy": "python_nested_if_block",
                    "parent_test_text": parent_test_text,
                    "test_text": test_text,
                    "start_line": start_line,
                    "end_line": end_line,
                    "text": block_text,
                    "indent": detect_indent(block_text),
                }
            )

    if not candidates:
        return None

    for spec in specs:
        for candidate in candidates:
            if spec["parent_test_contains"] in candidate["parent_test_text"] and spec["test_contains"] in candidate["test_text"]:
                candidate["label"] = spec["label"]
                return candidate
    return None


def select_python_leaf_scope(target_path: str, current_text: str, top_scope: dict) -> dict | None:
    specs = preferred_leaf_scope_specs(target_path, top_scope["name"])
    if not specs:
        return None
    try:
        tree = ast.parse(current_text, filename=target_path)
    except SyntaxError:
        return None

    function_node = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == top_scope["name"]:
            if getattr(node, "lineno", None) == top_scope["start_line"]:
                function_node = node
                break
    if function_node is None:
        return None

    candidates = []
    for stmt in getattr(function_node, "body", []):
        if not isinstance(stmt, ast.If):
            continue
        parent_test_text = ast.get_source_segment(current_text, stmt.test) or ""
        for nested in getattr(stmt, "body", []):
            if not isinstance(nested, ast.If):
                continue
            test_text = ast.get_source_segment(current_text, nested.test) or ""
            return_node = next((item for item in getattr(nested, "body", []) if isinstance(item, ast.Return)), None)
            if return_node is None:
                continue
            start_line = getattr(return_node, "lineno", None)
            end_line = getattr(return_node, "end_lineno", None)
            if start_line is None or end_line is None:
                continue
            block_text = extract_line_block(current_text, start_line, end_line)
            candidates.append(
                {
                    "label": f"return_block_{start_line}",
                    "strategy": "python_return_block",
                    "parent_test_text": parent_test_text,
                    "test_text": test_text,
                    "start_line": start_line,
                    "end_line": end_line,
                    "text": block_text,
                    "indent": detect_indent(block_text),
                }
            )

    if not candidates:
        return None

    for spec in specs:
        for candidate in candidates:
            if spec["parent_test_contains"] in candidate["parent_test_text"] and spec["test_contains"] in candidate["test_text"]:
                candidate["label"] = spec["label"]
                return candidate
    return None


def write_micro_scope_target_artifact(target_path: str, micro_scope: dict) -> str:
    if not micro_scope:
        return ""
    out_dir = today_dir() / "micro_scope_targets"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(target_path).stem
    micro_path = out_dir / f"{stem}__{micro_scope['label']}.pyfrag"
    body = "\n".join(
        [
            f"# MICRO_BLOCK: {micro_scope['label']}",
            f"# START_LINE: {micro_scope['start_line']}",
            f"# END_LINE: {micro_scope['end_line']}",
            micro_scope["text"].rstrip(),
            "",
        ]
    ).rstrip() + "\n"
    micro_path.write_text(body, encoding="utf-8")
    return str(micro_path)


def write_nano_scope_target_artifact(target_path: str, nano_scope: dict) -> str:
    if not nano_scope:
        return ""
    out_dir = today_dir() / "nano_scope_targets"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(target_path).stem
    nano_path = out_dir / f"{stem}__{nano_scope['label']}.pyfrag"
    body = "\n".join(
        [
            f"# NANO_BLOCK: {nano_scope['label']}",
            f"# START_LINE: {nano_scope['start_line']}",
            f"# END_LINE: {nano_scope['end_line']}",
            nano_scope["text"].rstrip(),
            "",
        ]
    ).rstrip() + "\n"
    nano_path.write_text(body, encoding="utf-8")
    return str(nano_path)


def write_leaf_scope_target_artifact(target_path: str, leaf_scope: dict) -> str:
    if not leaf_scope:
        return ""
    out_dir = today_dir() / "leaf_scope_targets"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(target_path).stem
    leaf_path = out_dir / f"{stem}__{leaf_scope['label']}.pyfrag"
    body = "\n".join(
        [
            f"# LEAF_BLOCK: {leaf_scope['label']}",
            f"# START_LINE: {leaf_scope['start_line']}",
            f"# END_LINE: {leaf_scope['end_line']}",
            leaf_scope["text"].rstrip(),
            "",
        ]
    ).rstrip() + "\n"
    leaf_path.write_text(body, encoding="utf-8")
    return str(leaf_path)


def stitch_micro_scope(current_text: str, micro_scope: dict, replacement_text: str) -> str:
    lines = current_text.splitlines(keepends=True)
    replacement = replacement_text
    if replacement and not replacement.endswith("\n"):
        replacement += "\n"
    replacement_lines = replacement.splitlines(keepends=True)
    stitched = lines[: micro_scope["start_line"] - 1] + replacement_lines + lines[micro_scope["end_line"] :]
    return "".join(stitched)


def stitch_nano_scope(current_text: str, nano_scope: dict, replacement_text: str) -> str:
    lines = current_text.splitlines(keepends=True)
    replacement = replacement_text
    if replacement and not replacement.endswith("\n"):
        replacement += "\n"
    replacement_lines = replacement.splitlines(keepends=True)
    stitched = lines[: nano_scope["start_line"] - 1] + replacement_lines + lines[nano_scope["end_line"] :]
    return "".join(stitched)


def stitch_leaf_scope(current_text: str, leaf_scope: dict, replacement_text: str) -> str:
    lines = current_text.splitlines(keepends=True)
    replacement = replacement_text
    if replacement and not replacement.endswith("\n"):
        replacement += "\n"
    replacement_lines = replacement.splitlines(keepends=True)
    stitched = lines[: leaf_scope["start_line"] - 1] + replacement_lines + lines[leaf_scope["end_line"] :]
    return "".join(stitched)

def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def latest_patch_plan(task_id: str = "") -> Path | None:
    direct_candidates = []
    task_id = (task_id or "").strip()

    if task_id:
        latest_name = f"latest_task_{task_id}_patch_plan.md"
        for day_dir in sorted(ARTIFACT_ROOT.glob("20*-*-*"), reverse=True):
            p = day_dir / latest_name
            if p.exists():
                direct_candidates.append(p)

    for latest_name in ("latest_patch_plan.md",):
        for day_dir in sorted(ARTIFACT_ROOT.glob("20*-*-*"), reverse=True):
            p = day_dir / latest_name
            if p.exists():
                direct_candidates.append(p)

    numbered_candidates = sorted(
        ARTIFACT_ROOT.glob("20*-*-*/*_patch_plan.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    all_candidates = direct_candidates + [p for p in numbered_candidates if p not in direct_candidates]
    return all_candidates[0] if all_candidates else None


def extract_target_files(text: str) -> list[str]:
    matches = re.findall(
        r"/home/rollan/\.openclaw/workspace/[A-Za-z0-9_\-./]+",
        text,
    )
    files = []
    seen = set()
    for path in matches:
        if not (
            path.endswith(".py")
            or path.endswith(".md")
            or path.endswith(".yaml")
            or path.endswith(".yml")
            or path.endswith(".json")
        ):
            continue
        if path not in seen:
            seen.add(path)
            files.append(path)
    return files


def detect_thinking_contamination(text: str) -> bool:
    t = (text or "").strip().lower()
    return "thinking process:" in t or t.startswith("thinking process")

def strip_think(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
    return cleaned.strip("\r\n")


def strip_code_fences(text: str) -> str:
    lines = text.replace("\r\n", "\n").splitlines()
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def extract_first_fenced_code_if_clean(text: str) -> str:
    cleaned = text.replace("\r\n", "\n")
    match = re.search(r"```[A-Za-z0-9_-]*\n(.*?)\n```", cleaned, flags=re.DOTALL)
    if not match:
        return cleaned
    if cleaned[: match.start()].strip() or cleaned[match.end() :].strip():
        return cleaned
    return match.group(1)


def normalize_model_candidate_text(raw_text: str) -> str:
    cleaned = strip_think(raw_text)
    cleaned = extract_first_fenced_code_if_clean(cleaned)
    return strip_code_fences(cleaned)


def sanitize_preview(text: str, limit: int = 280) -> tuple[str, bool]:
    cleaned = strip_think(text or "")
    cleaned = cleaned.replace(API_KEY, "[redacted-api-key]") if API_KEY else cleaned
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return "", False
    truncated = len(cleaned) > limit
    preview = cleaned[:limit]
    return preview, truncated


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def detect_candidate_contamination(text: str, target_suffix: str) -> str | None:
    lowered = (text or "").strip().lower()
    if not lowered:
        return "model returned empty output"
    for marker in ANALYSIS_MARKERS:
        if marker in lowered:
            return f"model output contained contamination marker: {marker}"
    first_line = first_nonempty_line(text).lower()
    if first_line.startswith(ANALYSIS_PREFIXES):
        return "model returned analysis-style prose instead of raw file content"
    if first_line.startswith(("```", "- ", "1.", "2.", "3.")):
        return "model returned markdown instead of raw file content"
    if target_suffix == ".py" and first_line.startswith(("the ", "this ", "here ", "i ", "we ")):
        return "model returned prose instead of raw python"
    return None


def call_model(prompt: str) -> str:
    if requests is None:
        raise ModelCallFailure("requests is not installed. Install with: pip install requests")
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
                    "You are a single-file patch materializer.\n"
                    "Return only the full replacement file content.\n"
                    "No explanation.\n"
                    "No markdown.\n"
                    "No code fences unless unavoidable.\n"
                    "No analysis.\n"
                    "No thinking text.\n"
                    "No preamble.\n"
                    "Start directly with the file contents.\n"
                    "Preserve unchanged parts when possible.\n"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
            "max_tokens": MAX_MODEL_OUTPUT_TOKENS,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    try:
        response = requests.post(
            f"{MODEL_SERVER}/chat/completions",
            headers=headers,
            json=payload,
            timeout=(10,120),
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except requests.Timeout as exc:
        raise ModelCallFailure(f"{type(exc).__name__}: {exc}") from exc
    except requests.HTTPError as exc:
        response_text = ""
        if getattr(exc, "response", None) is not None:
            response_text = exc.response.text or ""
        raise ModelCallFailure(f"{type(exc).__name__}: {exc}", raw_text=response_text) from exc
    except requests.RequestException as exc:
        raise ModelCallFailure(f"{type(exc).__name__}: {exc}") from exc


def build_prompt(target_path: str, current_text: str, patch_plan_text: str) -> str:
    intent = extract_patch_intent_summary(patch_plan_text, limit=320)
    return "\n".join(
        [
            f"file {Path(target_path).name}",
            f"intent {intent}",
            "return only the full replacement file content",
            "no prose",
            "no markdown",
            "no planning text",
            "",
            current_text[:8000],
        ]
    )


def validate_python(path: Path) -> tuple[bool, str]:
    try:
        py_compile.compile(str(path), doraise=True)
        return True, "py_compile ok"
    except Exception as e:
        return False, str(e)


def build_scope_prompt(target_path: str, scope_path: str, scope_text: str, patch_plan_text: str) -> str:
    intent = extract_patch_intent_summary(patch_plan_text, limit=180)
    return "\n".join([
        f"file {Path(target_path).name}",
        f"block {Path(scope_path).name}",
        f"intent {intent}",
        "edit only this top-level python block",
        "return only replacement code for this block",
        "no prose",
        "no markdown",
        "no planning text",
        "",
        scope_text[:2200],
    ])


def validate_scoped_python_candidate(candidate_text: str, scope_name: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(candidate_text)
    except SyntaxError as exc:
        return False, f"scoped parse failed: {exc}"
    if not tree.body:
        return False, "scoped candidate was empty"
    first = tree.body[0]
    if not isinstance(first, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return False, "scoped candidate did not start with a top-level function or class"
    if getattr(first, "name", None) != scope_name:
        return False, f"scoped candidate started with {getattr(first, 'name', None)!r}, expected {scope_name!r}"
    return True, "scoped parse ok"


def build_micro_scope_prompt(target_path: str, scope_name: str, micro_scope_path: str, micro_scope_text: str, patch_plan_text: str) -> str:
    intent = extract_patch_intent_summary(patch_plan_text, limit=160)
    return "\n".join(
        [
            f"file {Path(target_path).name}",
            f"scope {scope_name}",
            f"block {Path(micro_scope_path).name}",
            f"intent {intent}",
            "edit only this indented python block",
            "keep the same indentation depth",
            "return only replacement code for this block",
            "no prose",
            "no markdown",
            "no planning text",
            "",
            micro_scope_text[:1800],
        ]
    )


def validate_micro_scope_candidate(candidate_text: str, micro_scope: dict) -> tuple[bool, str]:
    lines = candidate_text.splitlines()
    if not lines:
        return False, "micro-scope candidate was empty"
    indent = micro_scope.get("indent", "")
    stripped_lines = []
    for line in lines:
        if not line.strip():
            stripped_lines.append("")
            continue
        if indent and not line.startswith(indent):
            return False, f"micro-scope line did not preserve required indentation: {line!r}"
        stripped_lines.append(line[len(indent):] if indent else line)
    wrapped = "def _micro_scope_probe():\n"
    if stripped_lines:
        wrapped += "\n".join(("    " + line) if line else "" for line in stripped_lines) + "\n"
    try:
        ast.parse(wrapped)
    except SyntaxError as exc:
        return False, f"micro-scope parse failed: {exc}"
    first_line = first_nonempty_line(candidate_text).strip()
    if not first_line:
        return False, "micro-scope candidate had no code"
    if first_line.startswith(("def ", "class ")):
        return False, "micro-scope candidate returned a top-level definition instead of a block"
    return True, "micro-scope parse ok"


def build_nano_scope_prompt(target_path: str, scope_name: str, nano_scope_path: str, nano_scope_text: str, patch_plan_text: str) -> str:
    intent = extract_patch_intent_summary(patch_plan_text, limit=140)
    return "\n".join(
        [
            f"file {Path(target_path).name}",
            f"scope {scope_name}",
            f"block {Path(nano_scope_path).name}",
            f"intent {intent}",
            "edit only this smallest branch block",
            "keep the same indentation depth",
            "return only replacement code for this block",
            "no prose",
            "no markdown",
            "no planning text",
            "",
            nano_scope_text[:1000],
        ]
    )


def validate_nano_scope_candidate(candidate_text: str, nano_scope: dict) -> tuple[bool, str]:
    return validate_micro_scope_candidate(candidate_text, nano_scope)


def build_leaf_scope_prompt(target_path: str, scope_name: str, leaf_scope_path: str, leaf_scope_text: str, patch_plan_text: str) -> str:
    intent = extract_patch_intent_summary(patch_plan_text, limit=120)
    return "\n".join(
        [
            f"file {Path(target_path).name}",
            f"scope {scope_name}",
            f"block {Path(leaf_scope_path).name}",
            f"intent {intent}",
            "edit only this return block",
            "keep the same indentation depth",
            "return only replacement code for this block",
            "no prose",
            "no markdown",
            "no planning text",
            "",
            leaf_scope_text[:700],
        ]
    )


def validate_leaf_scope_candidate(candidate_text: str, leaf_scope: dict) -> tuple[bool, str]:
    return validate_micro_scope_candidate(candidate_text, leaf_scope)

def write_artifact(name: str, body: str) -> Path:
    out = today_dir() / f"{now_stamp()}_{name}.md"
    out.write_text(body, encoding="utf-8")
    latest = today_dir() / f"latest_{name}.md"
    latest.write_text(body, encoding="utf-8")
    return out


def mark_task_candidate_ready(task_id: str, artifact_path: str) -> dict | None:
    if not task_id:
        return None
    task_path = TASKS_DIR / f"{task_id}.json"
    if not task_path.exists():
        return None

    data = json.loads(task_path.read_text(encoding="utf-8"))
    status = str(data.get("status") or "")
    if status in {"completed", "shipped", "failed", "cancelled", "archived"}:
        return {
            "task_id": task_id,
            "skipped": True,
            "status": status,
            "reason": "task already terminal/shipped; final_outcome not changed",
            "artifact": artifact_path,
        }

    data["final_outcome"] = "candidate_ready_for_live_apply"
    data["updated_at"] = now_iso()
    data["checkpoint_summary"] = "Candidate file generated and armed for live apply."
    task_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {
        "task_id": task_id,
        "skipped": False,
        "status": data.get("status"),
        "final_outcome": data["final_outcome"],
        "checkpoint_summary": data["checkpoint_summary"],
        "artifact": artifact_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a candidate replacement file for an approved patch."
    )
    parser.add_argument("--patch-plan", default="", help="Optional explicit patch plan path.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
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

    approved_task_id = approval.get("approved_task_id")
    patch_plan = (
        Path(args.patch_plan).resolve()
        if args.patch_plan.strip()
        else latest_patch_plan(approved_task_id if isinstance(approved_task_id, str) else "")
    )
    patch_plan_source = "explicit" if args.patch_plan.strip() else "task_latest_or_global_latest"
    if patch_plan is None:
        raise RuntimeError("No latest patch plan found.")
    if not patch_plan.exists():
        raise RuntimeError(f"Patch plan does not exist: {patch_plan}")

    patch_plan_text = patch_plan.read_text(encoding="utf-8", errors="replace")
    target_files = extract_target_files(patch_plan_text)

    if not target_files:
        raise RuntimeError("No target files found in patch plan.")
    if len(target_files) != 1:
        raise RuntimeError(f"Expected exactly one target file, got {len(target_files)}.")

    target_path = target_files[0]

    if approval.get("approved_task_id") != gate.get("approved_task_id"):
        raise RuntimeError("Approval task id does not match write gate task id.")
    if not gate.get("enabled"):
        raise RuntimeError("Write gate is disabled.")
    if target_path not in set(gate.get("allowed_paths", [])):
        raise RuntimeError("Target path is outside the allowlist.")

    target_file = Path(target_path)
    if not target_file.exists():
        raise RuntimeError(f"Target file does not exist: {target_file}")

    current_text = target_file.read_text(encoding="utf-8", errors="replace")
    generation_mode = ""
    generation_error = ""
    output_status = ""
    rejection_reason = ""
    raw_model_preview = ""
    raw_model_preview_truncated = False
    candidate_is_fallback = False
    candidate_matches_live = False
    model_candidate_accepted = False
    rewrite_level = "fallback"
    leaf_scope_strategy = ""
    leaf_scope_label = ""
    leaf_scope_start_line = None
    leaf_scope_end_line = None
    leaf_scope_chars = 0
    leaf_scope_attempted = False
    leaf_scope_accepted = False
    leaf_scope_stitch_valid = None
    leaf_scope_artifact = ""
    leaf_scope_candidate_file = ""
    leaf_scope_generation_mode = ""
    leaf_scope_generation_error = ""
    nano_scope_strategy = ""
    nano_scope_label = ""
    nano_scope_start_line = None
    nano_scope_end_line = None
    nano_scope_chars = 0
    nano_scope_attempted = False
    nano_scope_accepted = False
    nano_scope_stitch_valid = None
    nano_scope_artifact = ""
    nano_scope_candidate_file = ""
    nano_scope_generation_mode = ""
    nano_scope_generation_error = ""
    micro_scope_strategy = ""
    micro_scope_label = ""
    micro_scope_start_line = None
    micro_scope_end_line = None
    micro_scope_chars = 0
    micro_scope_attempted = False
    micro_scope_accepted = False
    micro_scope_stitch_valid = None
    micro_scope_artifact = ""
    micro_scope_candidate_file = ""
    micro_scope_generation_mode = ""
    micro_scope_generation_error = ""
    top_level_scope_attempted = False
    top_level_scope_accepted = False
    scope_strategy = ""
    selected_scope_name = ""
    selected_scope_start_line = None
    selected_scope_end_line = None
    scope_stitch_valid = None
    scope_rewrite_attempted = False
    scope_rewrite_accepted = False
    scope_artifact = ""
    scope_candidate_file = ""
    scope_generation_mode = ""
    scope_generation_error = ""
    scope_syntax_valid = None
    scope_validation_msg = "not attempted"
    scope_chars = 0
    semantic_guard_applied = False
    semantic_guard_passed = True
    semantic_guard_reason = ""
    semantic_guard_drifted_tokens = []
    semantic_guard_target = ""
    semantic_guard_mode = ""
    semantic_guard_branch_checks = []
    semantic_guard_branch_failures = []
    semantic_guard_allowlisted_changes = []

    candidate_text = current_text
    selected_scope = None
    leaf_scope = None
    nano_scope = None
    micro_scope = None
    if target_file.suffix == ".py":
        selected_scope = select_python_scope(target_path, current_text, patch_plan_text)
        if selected_scope is not None:
            scope_strategy = selected_scope["strategy"]
            selected_scope_name = selected_scope["name"]
            selected_scope_start_line = selected_scope["start_line"]
            selected_scope_end_line = selected_scope["end_line"]
            scope_artifact = write_scope_target_artifact(target_path, selected_scope)
            scope_chars = len(selected_scope["text"])
            leaf_scope = select_python_leaf_scope(target_path, current_text, selected_scope)
            if leaf_scope is not None:
                leaf_scope_strategy = leaf_scope["strategy"]
                leaf_scope_label = leaf_scope["label"]
                leaf_scope_start_line = leaf_scope["start_line"]
                leaf_scope_end_line = leaf_scope["end_line"]
                leaf_scope_chars = len(leaf_scope["text"])
                leaf_scope_artifact = write_leaf_scope_target_artifact(target_path, leaf_scope)
            nano_scope = select_python_nano_scope(target_path, current_text, selected_scope)
            if nano_scope is not None:
                nano_scope_strategy = nano_scope["strategy"]
                nano_scope_label = nano_scope["label"]
                nano_scope_start_line = nano_scope["start_line"]
                nano_scope_end_line = nano_scope["end_line"]
                nano_scope_chars = len(nano_scope["text"])
                nano_scope_artifact = write_nano_scope_target_artifact(target_path, nano_scope)
            micro_scope = select_python_micro_scope(target_path, current_text, selected_scope)
            if micro_scope is not None:
                micro_scope_strategy = micro_scope["strategy"]
                micro_scope_label = micro_scope["label"]
                micro_scope_start_line = micro_scope["start_line"]
                micro_scope_end_line = micro_scope["end_line"]
                micro_scope_chars = len(micro_scope["text"])
                micro_scope_artifact = write_micro_scope_target_artifact(target_path, micro_scope)

    if leaf_scope is not None:
        leaf_scope_attempted = True
        if leaf_scope_chars > MAX_LEAF_SCOPE_REWRITE_CHARS:
            leaf_scope_generation_mode = "leaf_scope_size_guard"
            leaf_scope_generation_error = f"leaf-scope too large for bounded rewrite: {leaf_scope_chars} chars"
        else:
            try:
                leaf_prompt = build_leaf_scope_prompt(
                    target_path,
                    selected_scope_name,
                    leaf_scope_artifact or f"{target_file.name}:{leaf_scope_label}",
                    leaf_scope["text"],
                    patch_plan_text,
                )
                raw_leaf = call_model(leaf_prompt)
                if detect_thinking_contamination(raw_leaf):
                    raise CandidateRejected(
                        "rejected_contamination",
                        "model returned Thinking Process contamination",
                        raw_text=raw_leaf,
                    )
                leaf_candidate_text = normalize_model_candidate_text(raw_leaf)
                contamination_error = detect_candidate_contamination(leaf_candidate_text, target_file.suffix)
                if contamination_error:
                    raise CandidateRejected("rejected_contamination", contamination_error, raw_text=raw_leaf)
                leaf_valid, leaf_validation_msg = validate_leaf_scope_candidate(leaf_candidate_text, leaf_scope)
                if not leaf_valid:
                    raise CandidateRejected(
                        "fallback_live_baseline_invalid_python",
                        leaf_validation_msg,
                        raw_text=leaf_candidate_text,
                    )
                scope_candidates_dir = today_dir() / "scope_candidates"
                scope_candidates_dir.mkdir(parents=True, exist_ok=True)
                leaf_candidate_path = scope_candidates_dir / f"{target_file.stem}__{leaf_scope_label}.pyfrag"
                leaf_candidate_path.write_text(leaf_candidate_text, encoding="utf-8")
                leaf_scope_candidate_file = str(leaf_candidate_path)
                stitched_text = stitch_leaf_scope(current_text, leaf_scope, leaf_candidate_text)
                stitched_candidate_path = scope_candidates_dir / f"{target_file.stem}__{leaf_scope_label}__stitched.py"
                stitched_candidate_path.write_text(stitched_text, encoding="utf-8")
                leaf_scope_stitch_valid, stitched_validation_msg = validate_python(stitched_candidate_path)
                if not leaf_scope_stitch_valid:
                    raise CandidateRejected(
                        "fallback_live_baseline_invalid_python",
                        stitched_validation_msg,
                        raw_text=leaf_candidate_text,
                    )
                generation_mode = "model_leaf_scope_rewrite"
                output_status = "model_leaf_scope_rewrite_accepted"
                rewrite_level = "leaf_scope"
                validation_msg = stitched_validation_msg
                candidate_text = stitched_text
                leaf_scope_generation_mode = "model_leaf_scope_rewrite"
                leaf_scope_accepted = True
            except CandidateRejected as e:
                raw_model_preview, raw_model_preview_truncated = sanitize_preview(e.raw_text)
                leaf_scope_generation_mode = "leaf_scope_rewrite_fallback"
                leaf_scope_generation_error = e.message
                if leaf_scope_stitch_valid is None:
                    leaf_scope_stitch_valid = False
            except ModelCallFailure as e:
                raw_model_preview, raw_model_preview_truncated = sanitize_preview(e.raw_text)
                leaf_scope_generation_mode = "leaf_scope_rewrite_fallback"
                leaf_scope_generation_error = e.message
                leaf_scope_stitch_valid = False
            except Exception as e:
                leaf_scope_generation_mode = "leaf_scope_rewrite_fallback"
                leaf_scope_generation_error = f"{type(e).__name__}: {e}"
                leaf_scope_stitch_valid = False

    if not leaf_scope_accepted and nano_scope is not None:
        nano_scope_attempted = True
        if nano_scope_chars > MAX_NANO_SCOPE_REWRITE_CHARS:
            nano_scope_generation_mode = "nano_scope_size_guard"
            nano_scope_generation_error = f"nano-scope too large for bounded rewrite: {nano_scope_chars} chars"
        else:
            try:
                nano_prompt = build_nano_scope_prompt(
                    target_path,
                    selected_scope_name,
                    nano_scope_artifact or f"{target_file.name}:{nano_scope_label}",
                    nano_scope["text"],
                    patch_plan_text,
                )
                raw_nano = call_model(nano_prompt)
                if detect_thinking_contamination(raw_nano):
                    raise CandidateRejected(
                        "rejected_contamination",
                        "model returned Thinking Process contamination",
                        raw_text=raw_nano,
                    )
                nano_candidate_text = normalize_model_candidate_text(raw_nano)
                contamination_error = detect_candidate_contamination(nano_candidate_text, target_file.suffix)
                if contamination_error:
                    raise CandidateRejected("rejected_contamination", contamination_error, raw_text=raw_nano)
                nano_valid, nano_validation_msg = validate_nano_scope_candidate(nano_candidate_text, nano_scope)
                if not nano_valid:
                    raise CandidateRejected(
                        "fallback_live_baseline_invalid_python",
                        nano_validation_msg,
                        raw_text=nano_candidate_text,
                    )
                scope_candidates_dir = today_dir() / "scope_candidates"
                scope_candidates_dir.mkdir(parents=True, exist_ok=True)
                nano_candidate_path = scope_candidates_dir / f"{target_file.stem}__{nano_scope_label}.pyfrag"
                nano_candidate_path.write_text(nano_candidate_text, encoding="utf-8")
                nano_scope_candidate_file = str(nano_candidate_path)
                stitched_text = stitch_nano_scope(current_text, nano_scope, nano_candidate_text)
                stitched_candidate_path = scope_candidates_dir / f"{target_file.stem}__{nano_scope_label}__stitched.py"
                stitched_candidate_path.write_text(stitched_text, encoding="utf-8")
                nano_scope_stitch_valid, stitched_validation_msg = validate_python(stitched_candidate_path)
                if not nano_scope_stitch_valid:
                    raise CandidateRejected(
                        "fallback_live_baseline_invalid_python",
                        stitched_validation_msg,
                        raw_text=nano_candidate_text,
                    )
                generation_mode = "model_nano_scope_rewrite"
                output_status = "model_nano_scope_rewrite_accepted"
                rewrite_level = "nano_scope"
                validation_msg = stitched_validation_msg
                candidate_text = stitched_text
                nano_scope_generation_mode = "model_nano_scope_rewrite"
                nano_scope_accepted = True
            except CandidateRejected as e:
                raw_model_preview, raw_model_preview_truncated = sanitize_preview(e.raw_text)
                nano_scope_generation_mode = "nano_scope_rewrite_fallback"
                nano_scope_generation_error = e.message
                if nano_scope_stitch_valid is None:
                    nano_scope_stitch_valid = False
            except ModelCallFailure as e:
                raw_model_preview, raw_model_preview_truncated = sanitize_preview(e.raw_text)
                nano_scope_generation_mode = "nano_scope_rewrite_fallback"
                nano_scope_generation_error = e.message
                nano_scope_stitch_valid = False
            except Exception as e:
                nano_scope_generation_mode = "nano_scope_rewrite_fallback"
                nano_scope_generation_error = f"{type(e).__name__}: {e}"
                nano_scope_stitch_valid = False

    if not leaf_scope_accepted and not nano_scope_accepted and micro_scope is not None:
        micro_scope_attempted = True
        if micro_scope_chars > MAX_MICRO_SCOPE_REWRITE_CHARS:
            micro_scope_generation_mode = "micro_scope_size_guard"
            micro_scope_generation_error = f"micro-scope too large for bounded rewrite: {micro_scope_chars} chars"
        else:
            try:
                micro_prompt = build_micro_scope_prompt(
                    target_path,
                    selected_scope_name,
                    micro_scope_artifact or f"{target_file.name}:{micro_scope_label}",
                    micro_scope["text"],
                    patch_plan_text,
                )
                raw_micro = call_model(micro_prompt)
                if detect_thinking_contamination(raw_micro):
                    raise CandidateRejected(
                        "rejected_contamination",
                        "model returned Thinking Process contamination",
                        raw_text=raw_micro,
                    )
                micro_candidate_text = normalize_model_candidate_text(raw_micro)
                contamination_error = detect_candidate_contamination(micro_candidate_text, target_file.suffix)
                if contamination_error:
                    raise CandidateRejected("rejected_contamination", contamination_error, raw_text=raw_micro)
                micro_valid, micro_validation_msg = validate_micro_scope_candidate(micro_candidate_text, micro_scope)
                if not micro_valid:
                    raise CandidateRejected(
                        "fallback_live_baseline_invalid_python",
                        micro_validation_msg,
                        raw_text=micro_candidate_text,
                    )
                scope_candidates_dir = today_dir() / "scope_candidates"
                scope_candidates_dir.mkdir(parents=True, exist_ok=True)
                micro_candidate_path = scope_candidates_dir / f"{target_file.stem}__{micro_scope_label}.pyfrag"
                micro_candidate_path.write_text(micro_candidate_text, encoding="utf-8")
                micro_scope_candidate_file = str(micro_candidate_path)
                stitched_text = stitch_micro_scope(current_text, micro_scope, micro_candidate_text)
                stitched_candidate_path = scope_candidates_dir / f"{target_file.stem}__{micro_scope_label}__stitched.py"
                stitched_candidate_path.write_text(stitched_text, encoding="utf-8")
                micro_scope_stitch_valid, stitched_validation_msg = validate_python(stitched_candidate_path)
                if not micro_scope_stitch_valid:
                    raise CandidateRejected(
                        "fallback_live_baseline_invalid_python",
                        stitched_validation_msg,
                        raw_text=micro_candidate_text,
                    )
                generation_mode = "model_micro_scope_rewrite"
                output_status = "model_micro_scope_rewrite_accepted"
                rewrite_level = "micro_scope"
                validation_msg = stitched_validation_msg
                candidate_text = stitched_text
                micro_scope_generation_mode = "model_micro_scope_rewrite"
                micro_scope_accepted = True
            except CandidateRejected as e:
                raw_model_preview, raw_model_preview_truncated = sanitize_preview(e.raw_text)
                micro_scope_generation_mode = "micro_scope_rewrite_fallback"
                micro_scope_generation_error = e.message
                if micro_scope_stitch_valid is None:
                    micro_scope_stitch_valid = False
            except ModelCallFailure as e:
                raw_model_preview, raw_model_preview_truncated = sanitize_preview(e.raw_text)
                micro_scope_generation_mode = "micro_scope_rewrite_fallback"
                micro_scope_generation_error = e.message
                micro_scope_stitch_valid = False
            except Exception as e:
                micro_scope_generation_mode = "micro_scope_rewrite_fallback"
                micro_scope_generation_error = f"{type(e).__name__}: {e}"
                micro_scope_stitch_valid = False

    if not leaf_scope_accepted and not nano_scope_accepted and not micro_scope_accepted and selected_scope is not None:
        top_level_scope_attempted = True
        scope_rewrite_attempted = True
        if scope_chars > MAX_SCOPE_REWRITE_CHARS:
            scope_generation_mode = "scope_rewrite_size_guard"
            scope_generation_error = f"scope too large for bounded rewrite: {scope_chars} chars"
        else:
            try:
                scope_prompt = build_scope_prompt(
                    target_path,
                    scope_artifact or f"{target_file.name}:{selected_scope_name}",
                    selected_scope["text"],
                    patch_plan_text,
                )
                raw_scope = call_model(scope_prompt)
                if detect_thinking_contamination(raw_scope):
                    raise CandidateRejected(
                        "rejected_contamination",
                        "model returned Thinking Process contamination",
                        raw_text=raw_scope,
                    )
                scope_candidate_text = normalize_model_candidate_text(raw_scope)
                contamination_error = detect_candidate_contamination(scope_candidate_text, target_file.suffix)
                if contamination_error:
                    raise CandidateRejected("rejected_contamination", contamination_error, raw_text=raw_scope)
                scope_syntax_valid, scope_validation_msg = validate_scoped_python_candidate(
                    scope_candidate_text,
                    selected_scope_name,
                )
                if not scope_syntax_valid:
                    raise CandidateRejected(
                        "fallback_live_baseline_invalid_python",
                        scope_validation_msg,
                        raw_text=scope_candidate_text,
                    )
                scope_generation_mode = "model_scope_rewrite"
                scope_candidates_dir = today_dir() / "scope_candidates"
                scope_candidates_dir.mkdir(parents=True, exist_ok=True)
                scope_candidate_path = scope_candidates_dir / f"{target_file.stem}__{selected_scope_name}.py"
                scope_candidate_path.write_text(scope_candidate_text, encoding="utf-8")
                scope_candidate_file = str(scope_candidate_path)
                stitched_text = stitch_python_scope(current_text, selected_scope, scope_candidate_text)
                stitched_candidate_path = scope_candidates_dir / f"{target_file.stem}__{selected_scope_name}__stitched.py"
                stitched_candidate_path.write_text(stitched_text, encoding="utf-8")
                scope_stitch_valid, stitched_validation_msg = validate_python(stitched_candidate_path)
                if not scope_stitch_valid:
                    raise CandidateRejected(
                        "fallback_live_baseline_invalid_python",
                        stitched_validation_msg,
                        raw_text=scope_candidate_text,
                    )
                generation_mode = "model_scope_rewrite"
                output_status = "model_scope_rewrite_accepted"
                rewrite_level = "top_level_scope"
                validation_msg = stitched_validation_msg
                candidate_text = stitched_text
                scope_rewrite_accepted = True
                top_level_scope_accepted = True
            except CandidateRejected as e:
                generation_mode = "fallback_live_baseline"
                output_status = e.output_status
                generation_error = e.message
                rejection_reason = e.message
                if not raw_model_preview:
                    raw_model_preview, raw_model_preview_truncated = sanitize_preview(e.raw_text)
                candidate_text = current_text
                candidate_is_fallback = True
                scope_generation_mode = "scope_rewrite_fallback"
                scope_generation_error = e.message
                if scope_stitch_valid is None:
                    scope_stitch_valid = False
            except ModelCallFailure as e:
                generation_mode = "fallback_live_baseline"
                output_status = "fallback_live_baseline"
                generation_error = e.message
                rejection_reason = e.message
                if not raw_model_preview:
                    raw_model_preview, raw_model_preview_truncated = sanitize_preview(e.raw_text)
                candidate_text = current_text
                candidate_is_fallback = True
                scope_generation_mode = "scope_rewrite_fallback"
                scope_generation_error = e.message
                scope_stitch_valid = False
            except Exception as e:
                generation_mode = "fallback_live_baseline"
                output_status = "fallback_live_baseline"
                generation_error = f"{type(e).__name__}: {e}"
                rejection_reason = generation_error
                candidate_text = current_text
                candidate_is_fallback = True
                scope_generation_mode = "scope_rewrite_fallback"
                scope_generation_error = generation_error
                scope_stitch_valid = False
    elif selected_scope is None and len(current_text) > MAX_FULL_REWRITE_CHARS:
        generation_mode = "fallback_live_baseline_size_guard"
        output_status = "fallback_live_baseline_size_guard"
        generation_error = f"target too large for bounded full rewrite: {len(current_text)} chars"
        rejection_reason = generation_error
        candidate_text = current_text
        candidate_is_fallback = True
    elif selected_scope is None:
        prompt = build_prompt(target_path, current_text, patch_plan_text)
        generation_mode = "model_full_rewrite"
        output_status = "model_full_rewrite_accepted"
        rewrite_level = "full_file"
        try:
            raw = call_model(prompt)
            if detect_thinking_contamination(raw):
                raise CandidateRejected(
                    "rejected_contamination",
                    "model returned Thinking Process contamination",
                    raw_text=raw,
                )
            candidate_text = normalize_model_candidate_text(raw)
            contamination_error = detect_candidate_contamination(candidate_text, target_file.suffix)
            if contamination_error:
                raise CandidateRejected("rejected_contamination", contamination_error, raw_text=raw)
        except CandidateRejected as e:
            generation_mode = "fallback_live_baseline"
            output_status = e.output_status
            generation_error = e.message
            rejection_reason = e.message
            raw_model_preview, raw_model_preview_truncated = sanitize_preview(e.raw_text)
            candidate_text = current_text
            candidate_is_fallback = True
        except ModelCallFailure as e:
            generation_mode = "fallback_live_baseline"
            output_status = "fallback_live_baseline"
            generation_error = e.message
            rejection_reason = e.message
            raw_model_preview, raw_model_preview_truncated = sanitize_preview(e.raw_text)
            candidate_text = current_text
            candidate_is_fallback = True
        except Exception as e:
            generation_mode = "fallback_live_baseline"
            output_status = "fallback_live_baseline"
            generation_error = f"{type(e).__name__}: {e}"
            rejection_reason = generation_error
            candidate_text = current_text
            candidate_is_fallback = True

    if (
        not nano_scope_accepted
        and not micro_scope_accepted
        and not leaf_scope_accepted
        and selected_scope is not None
        and not candidate_is_fallback
        and not scope_rewrite_accepted
    ):
        generation_mode = "fallback_live_baseline"
        output_status = "fallback_live_baseline"
        generation_error = (
            generation_error
            or scope_generation_error
            or micro_scope_generation_error
            or nano_scope_generation_error
            or leaf_scope_generation_error
            or "scoped rewrite not accepted"
        )
        rejection_reason = rejection_reason or generation_error
        candidate_text = current_text
        candidate_is_fallback = True

    candidates_dir = today_dir() / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    candidate_file = candidates_dir / target_file.name
    candidate_file.write_text(candidate_text, encoding="utf-8")

    syntax_valid = None
    validation_msg = "not validated"
    if leaf_scope_accepted and leaf_scope_stitch_valid is not None:
        syntax_valid = leaf_scope_stitch_valid
        validation_msg = "py_compile ok (stitched leaf-scope)" if leaf_scope_stitch_valid else "stitched leaf-scope validation failed"
    elif nano_scope_accepted and nano_scope_stitch_valid is not None:
        syntax_valid = nano_scope_stitch_valid
        validation_msg = "py_compile ok (stitched nano-scope)" if nano_scope_stitch_valid else "stitched nano-scope validation failed"
    elif micro_scope_accepted and micro_scope_stitch_valid is not None:
        syntax_valid = micro_scope_stitch_valid
        validation_msg = "py_compile ok (stitched micro-scope)" if micro_scope_stitch_valid else "stitched micro-scope validation failed"
    elif top_level_scope_accepted and scope_stitch_valid is not None:
        syntax_valid = scope_stitch_valid
        validation_msg = "py_compile ok (stitched top-level scope)" if scope_stitch_valid else "stitched top-level scope validation failed"
    elif target_file.suffix == ".py":
        syntax_valid, validation_msg = validate_python(candidate_file)
        if not syntax_valid and not candidate_is_fallback:
            raw_model_preview, raw_model_preview_truncated = sanitize_preview(candidate_text)
            candidate_text = current_text
            candidate_file.write_text(candidate_text, encoding="utf-8")
            syntax_valid, validation_msg = validate_python(candidate_file)
            generation_mode = "fallback_live_baseline_invalid_python"
            output_status = "fallback_live_baseline_invalid_python"
            generation_error = generation_error or validation_msg
            rejection_reason = "candidate failed python validation"
            candidate_is_fallback = True

    if syntax_valid and not candidate_is_fallback:
        semantic_guard = check_decision_router_semantic_guard(
            target_path=target_path,
            live_text=current_text,
            candidate_text=candidate_text,
            patch_plan_text=patch_plan_text,
        )
        semantic_guard_applied = semantic_guard["applied"]
        semantic_guard_passed = semantic_guard["passed"]
        semantic_guard_reason = semantic_guard["reason"]
        semantic_guard_drifted_tokens = semantic_guard["drifted_tokens"]
        semantic_guard_target = semantic_guard["target"]
        semantic_guard_mode = semantic_guard["mode"]
        semantic_guard_branch_checks = semantic_guard["branch_checks"]
        semantic_guard_branch_failures = semantic_guard["branch_failures"]
        semantic_guard_allowlisted_changes = semantic_guard["allowlisted_changes"]
        if semantic_guard_applied and not semantic_guard_passed:
            candidate_text = current_text
            candidate_file.write_text(candidate_text, encoding="utf-8")
            syntax_valid, validation_msg = validate_python(candidate_file)
            generation_mode = "fallback_live_baseline_semantic_guard"
            output_status = "fallback_live_baseline_semantic_guard"
            generation_error = semantic_guard_reason
            rejection_reason = semantic_guard_reason
            candidate_is_fallback = True

    candidate_matches_live = candidate_text == current_text
    model_candidate_accepted = (not candidate_is_fallback) and bool(syntax_valid is not False)
    if candidate_is_fallback:
        rewrite_level = "fallback"

    summary = "\n".join(
        [
            "# Qwen Candidate Writer",
            "",
            f"- timestamp: {now_iso()}",
            f"- approved_task_id: {approved_task_id}",
            f"- target_file: {target_path}",
            f"- candidate_file: {candidate_file}",
            f"- patch_plan: {patch_plan}",
            f"- patch_plan_source: {patch_plan_source}",
            f"- syntax_valid: {syntax_valid}",
            f"- validation_msg: {validation_msg}",
            f"- candidate_is_fallback: {candidate_is_fallback}",
            f"- candidate_matches_live: {candidate_matches_live}",
            f"- model_candidate_accepted: {model_candidate_accepted}",
            f"- rewrite_level: {rewrite_level}",
            f"- target_chars: {len(current_text)}",
            f"- max_full_rewrite_chars: {MAX_FULL_REWRITE_CHARS}",
            f"- leaf_scope_strategy: {leaf_scope_strategy or ''}",
            f"- leaf_scope_label: {leaf_scope_label or ''}",
            f"- leaf_scope_start_line: {leaf_scope_start_line}",
            f"- leaf_scope_end_line: {leaf_scope_end_line}",
            f"- leaf_scope_chars: {leaf_scope_chars}",
            f"- leaf_scope_attempted: {leaf_scope_attempted}",
            f"- leaf_scope_accepted: {leaf_scope_accepted}",
            f"- leaf_scope_stitch_valid: {leaf_scope_stitch_valid}",
            f"- leaf_scope_artifact: {leaf_scope_artifact or ''}",
            f"- leaf_scope_candidate_file: {leaf_scope_candidate_file or ''}",
            f"- leaf_scope_generation_mode: {leaf_scope_generation_mode or ''}",
            f"- leaf_scope_generation_error: {leaf_scope_generation_error[:300] if leaf_scope_generation_error else ''}",
            f"- nano_scope_strategy: {nano_scope_strategy or ''}",
            f"- nano_scope_label: {nano_scope_label or ''}",
            f"- nano_scope_start_line: {nano_scope_start_line}",
            f"- nano_scope_end_line: {nano_scope_end_line}",
            f"- nano_scope_chars: {nano_scope_chars}",
            f"- nano_scope_attempted: {nano_scope_attempted}",
            f"- nano_scope_accepted: {nano_scope_accepted}",
            f"- nano_scope_stitch_valid: {nano_scope_stitch_valid}",
            f"- nano_scope_artifact: {nano_scope_artifact or ''}",
            f"- nano_scope_candidate_file: {nano_scope_candidate_file or ''}",
            f"- nano_scope_generation_mode: {nano_scope_generation_mode or ''}",
            f"- nano_scope_generation_error: {nano_scope_generation_error[:300] if nano_scope_generation_error else ''}",
            f"- micro_scope_strategy: {micro_scope_strategy or ''}",
            f"- micro_scope_label: {micro_scope_label or ''}",
            f"- micro_scope_start_line: {micro_scope_start_line}",
            f"- micro_scope_end_line: {micro_scope_end_line}",
            f"- micro_scope_chars: {micro_scope_chars}",
            f"- micro_scope_attempted: {micro_scope_attempted}",
            f"- micro_scope_accepted: {micro_scope_accepted}",
            f"- micro_scope_stitch_valid: {micro_scope_stitch_valid}",
            f"- micro_scope_artifact: {micro_scope_artifact or ''}",
            f"- micro_scope_candidate_file: {micro_scope_candidate_file or ''}",
            f"- micro_scope_generation_mode: {micro_scope_generation_mode or ''}",
            f"- micro_scope_generation_error: {micro_scope_generation_error[:300] if micro_scope_generation_error else ''}",
            f"- top_level_scope_attempted: {top_level_scope_attempted}",
            f"- top_level_scope_accepted: {top_level_scope_accepted}",
            f"- scope_strategy: {scope_strategy or ''}",
            f"- selected_scope_name: {selected_scope_name or ''}",
            f"- selected_scope_start_line: {selected_scope_start_line}",
            f"- selected_scope_end_line: {selected_scope_end_line}",
            f"- scope_rewrite_attempted: {scope_rewrite_attempted}",
            f"- scope_rewrite_accepted: {scope_rewrite_accepted}",
            f"- scope_stitch_valid: {scope_stitch_valid}",
            f"- scope_artifact: {scope_artifact or ""}",
            f"- scope_chars: {scope_chars}",
            f"- scope_candidate_file: {scope_candidate_file or ""}",
            f"- scope_generation_mode: {scope_generation_mode or ""}",
            f"- scope_generation_error: {scope_generation_error[:300] if scope_generation_error else ""}",
            f"- scope_syntax_valid: {scope_syntax_valid}",
            f"- scope_validation_msg: {scope_validation_msg}",
            f"- semantic_guard_applied: {semantic_guard_applied}",
            f"- semantic_guard_passed: {semantic_guard_passed}",
            f"- semantic_guard_mode: {semantic_guard_mode}",
            f"- semantic_guard_reason: {semantic_guard_reason[:300] if semantic_guard_reason else ''}",
            f"- semantic_guard_drifted_tokens: {', '.join(semantic_guard_drifted_tokens)}",
            f"- semantic_guard_target: {semantic_guard_target}",
            f"- semantic_guard_branch_failures: {' | '.join(semantic_guard_branch_failures[:6]) if semantic_guard_branch_failures else ''}",
            f"- semantic_guard_allowlisted_changes: {' | '.join(semantic_guard_allowlisted_changes[:6]) if semantic_guard_allowlisted_changes else ''}",
            f"- generation_mode: {generation_mode}",
            f"- output_status: {output_status}",
            f"- rejection_reason: {rejection_reason[:300] if rejection_reason else ''}",
            f"- generation_error: {generation_error[:300] if generation_error else ""}",
            f"- raw_model_preview_truncated: {raw_model_preview_truncated}",
            f"- raw_model_preview: {raw_model_preview}",
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
            "## Patch Plan",
            f"- {patch_plan}",
            "",
            "## Outcome",
            "",
            (
                "Result: fallback baseline only. No model candidate was accepted."
                if candidate_is_fallback
                else f"Result: model candidate accepted via {rewrite_level} rewrite."
            ),
            "Candidate file generated only. No live code was changed.",
            "",
        ]
    )

    artifact = write_artifact("candidate_write", summary)

    armed_task = None
    if isinstance(approved_task_id, str) and approved_task_id.startswith("task_") and model_candidate_accepted:
        armed_task = mark_task_candidate_ready(approved_task_id, str(artifact))
    elif isinstance(approved_task_id, str) and approved_task_id.startswith("task_"):
        armed_task = {
            "task_id": approved_task_id,
            "skipped": True,
            "reason": "candidate not accepted; task not marked ready for live apply",
            "artifact": str(artifact),
        }

    payload = {
        "ok": True,
        "target_file": target_path,
        "candidate_file": str(candidate_file),
        "patch_plan": str(patch_plan),
        "patch_plan_source": patch_plan_source,
        "syntax_valid": syntax_valid,
        "validation_msg": validation_msg,
        "artifact": str(artifact),
        "generation_mode": generation_mode,
        "output_status": output_status,
        "rejection_reason": rejection_reason,
        "generation_error": generation_error,
        "raw_model_preview": raw_model_preview,
        "raw_model_preview_truncated": raw_model_preview_truncated,
        "candidate_is_fallback": candidate_is_fallback,
        "candidate_matches_live": candidate_matches_live,
        "model_candidate_accepted": model_candidate_accepted,
        "real_candidate": model_candidate_accepted,
        "rewrite_level": rewrite_level,
        "leaf_scope_strategy": leaf_scope_strategy,
        "leaf_scope_label": leaf_scope_label,
        "leaf_scope_start_line": leaf_scope_start_line,
        "leaf_scope_end_line": leaf_scope_end_line,
        "leaf_scope_chars": leaf_scope_chars,
        "leaf_scope_attempted": leaf_scope_attempted,
        "leaf_scope_accepted": leaf_scope_accepted,
        "leaf_scope_stitch_valid": leaf_scope_stitch_valid,
        "leaf_scope_artifact": leaf_scope_artifact,
        "leaf_scope_candidate_file": leaf_scope_candidate_file,
        "leaf_scope_generation_mode": leaf_scope_generation_mode,
        "leaf_scope_generation_error": leaf_scope_generation_error,
        "nano_scope_strategy": nano_scope_strategy,
        "nano_scope_label": nano_scope_label,
        "nano_scope_start_line": nano_scope_start_line,
        "nano_scope_end_line": nano_scope_end_line,
        "nano_scope_chars": nano_scope_chars,
        "nano_scope_attempted": nano_scope_attempted,
        "nano_scope_accepted": nano_scope_accepted,
        "nano_scope_stitch_valid": nano_scope_stitch_valid,
        "nano_scope_artifact": nano_scope_artifact,
        "nano_scope_candidate_file": nano_scope_candidate_file,
        "nano_scope_generation_mode": nano_scope_generation_mode,
        "nano_scope_generation_error": nano_scope_generation_error,
        "micro_scope_strategy": micro_scope_strategy,
        "micro_scope_label": micro_scope_label,
        "micro_scope_start_line": micro_scope_start_line,
        "micro_scope_end_line": micro_scope_end_line,
        "micro_scope_chars": micro_scope_chars,
        "micro_scope_attempted": micro_scope_attempted,
        "micro_scope_accepted": micro_scope_accepted,
        "micro_scope_stitch_valid": micro_scope_stitch_valid,
        "micro_scope_artifact": micro_scope_artifact,
        "micro_scope_candidate_file": micro_scope_candidate_file,
        "micro_scope_generation_mode": micro_scope_generation_mode,
        "micro_scope_generation_error": micro_scope_generation_error,
        "top_level_scope_attempted": top_level_scope_attempted,
        "top_level_scope_accepted": top_level_scope_accepted,
        "scope_strategy": scope_strategy,
        "selected_scope_name": selected_scope_name,
        "selected_scope_start_line": selected_scope_start_line,
        "selected_scope_end_line": selected_scope_end_line,
        "scope_rewrite_attempted": scope_rewrite_attempted,
        "scope_rewrite_accepted": scope_rewrite_accepted,
        "scope_stitch_valid": scope_stitch_valid,
        "scope_artifact": scope_artifact,
        "scope_candidate_file": scope_candidate_file,
        "scope_generation_mode": scope_generation_mode,
        "scope_generation_error": scope_generation_error,
        "scope_syntax_valid": scope_syntax_valid,
        "scope_validation_msg": scope_validation_msg,
        "scope_chars": scope_chars,
        "semantic_guard_applied": semantic_guard_applied,
        "semantic_guard_passed": semantic_guard_passed,
        "semantic_guard_mode": semantic_guard_mode,
        "semantic_guard_reason": semantic_guard_reason,
        "semantic_guard_drifted_tokens": semantic_guard_drifted_tokens,
        "semantic_guard_target": semantic_guard_target,
        "semantic_guard_branch_checks": semantic_guard_branch_checks,
        "semantic_guard_branch_failures": semantic_guard_branch_failures,
        "semantic_guard_allowlisted_changes": semantic_guard_allowlisted_changes,
        "armed_task": armed_task,
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Wrote: {artifact}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
