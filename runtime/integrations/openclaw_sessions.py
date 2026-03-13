#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import now_iso


SESSION_TEMPLATE_ERROR_TOKENS = (
    "error rendering prompt with jinja template",
    "no user query found in messages",
)

USER_FACING_REPLY_TAG_LINES = {
    "</context>",
    "<system_status>",
    "</system_status>",
    "<system_instructions>",
    "</system_instructions>",
    "<system_prompt>",
    "</system_prompt>",
    "<agent>",
    "</agent>",
    "<user_ping>",
    "</user_ping>",
}
USER_FACING_REPLY_DROP_PATTERNS = (
    re.compile(r"^\[MISSING\]\s+Expected at:\s+.+$", re.IGNORECASE),
    re.compile(r"^(i('| a)?m|i have|i've)\s+(read|checked|loaded)\s+(soul\.md|user\.md|agents\.md).*$", re.IGNORECASE),
    re.compile(r"^(checked|read|loaded)\s+(soul\.md|user\.md|agents\.md).*$", re.IGNORECASE),
)
USER_FACING_REPLY_QUESTION_PATTERNS = (
    re.compile(r"\bwhat'?s your model\b", re.IGNORECASE),
    re.compile(r"\bwhat is your model\b", re.IGNORECASE),
    re.compile(r"\bdo we have access to shadowbroker yet\b", re.IGNORECASE),
    re.compile(r"\bshadowbroker\b", re.IGNORECASE),
)


def resolve_openclaw_root(*, repo_root: Optional[Path] = None, openclaw_root: Optional[Path] = None) -> Path | None:
    if openclaw_root is not None:
        path = Path(openclaw_root).expanduser().resolve()
        return path if path.exists() else None
    env_root = Path(Path.home(), ".openclaw")
    if "OPENCLAW_HOME" in __import__("os").environ:
        path = Path(__import__("os").environ["OPENCLAW_HOME"]).expanduser().resolve()
        return path if path.exists() else None
    if repo_root is not None:
        repo_root = Path(repo_root).resolve()
        if repo_root.name == "jarvis-v5" and repo_root.parent.name == "workspace":
            candidate = repo_root.parent.parent
            if candidate.exists():
                return candidate
    return env_root if env_root.exists() else None


def jarvis_sessions_dir(*, repo_root: Optional[Path] = None, openclaw_root: Optional[Path] = None) -> Path | None:
    root = resolve_openclaw_root(repo_root=repo_root, openclaw_root=openclaw_root)
    if root is None:
        return None
    path = root / "agents" / "jarvis" / "sessions"
    return path if path.exists() else None


def _sessions_index_path(*, repo_root: Optional[Path] = None, openclaw_root: Optional[Path] = None) -> Path | None:
    sessions_dir = jarvis_sessions_dir(repo_root=repo_root, openclaw_root=openclaw_root)
    if sessions_dir is None:
        return None
    return sessions_dir / "sessions.json"


def load_sessions_index(*, repo_root: Optional[Path] = None, openclaw_root: Optional[Path] = None) -> dict[str, Any]:
    path = _sessions_index_path(repo_root=repo_root, openclaw_root=openclaw_root)
    if path is None or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text = str(item.get("text") or "").strip()
                    if text:
                        chunks.append(text)
            elif isinstance(item, str):
                text = item.strip()
                if text:
                    chunks.append(text)
        return "\n".join(chunks)
    if isinstance(content, dict):
        return str(content.get("text") or "").strip()
    return ""


def _is_real_user_query(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if not lowered.startswith("conversation info (untrusted metadata):"):
        return True
    marker = "\n\nsender (untrusted metadata):"
    marker_index = lowered.find(marker)
    if marker_index == -1:
        return False
    trailing = normalized[marker_index + len(marker):].strip()
    if not trailing:
        return False
    lines = [line.rstrip() for line in trailing.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return False
    last_line = lines[-1].strip()
    if not last_line or last_line.startswith("```") or last_line.startswith("{") or last_line.startswith("}"):
        return False
    return True


def _load_jsonl_rows(path: Path) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    parse_errors = 0
    if not path.exists():
        return rows, parse_errors
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            parse_errors += 1
    return rows, parse_errors


def sanitize_user_facing_assistant_reply(text: Any) -> dict[str, Any]:
    raw = str(text or "").replace("\r\n", "\n")
    if not raw.strip():
        return {
            "raw_text": raw,
            "clean_text": "",
            "was_sanitized": False,
            "removed_fragments": [],
            "contains_status_question": False,
        }

    removed_fragments: list[str] = []
    clean_lines: list[str] = []
    for original_line in raw.splitlines():
        line = original_line.strip()
        if not line:
            clean_lines.append("")
            continue
        if line in USER_FACING_REPLY_TAG_LINES:
            removed_fragments.append(line)
            continue
        if any(pattern.match(line) for pattern in USER_FACING_REPLY_DROP_PATTERNS):
            removed_fragments.append(line)
            continue
        clean_lines.append(original_line.rstrip())

    clean_text = "\n".join(clean_lines)
    clean_text = re.sub(r"\n{3,}", "\n\n", clean_text).strip()
    contains_status_question = any(pattern.search(raw) for pattern in USER_FACING_REPLY_QUESTION_PATTERNS)
    return {
        "raw_text": raw,
        "clean_text": clean_text,
        "was_sanitized": clean_text != raw.strip(),
        "removed_fragments": removed_fragments,
        "contains_status_question": contains_status_question,
    }


def list_discord_session_bindings(
    *,
    repo_root: Optional[Path] = None,
    openclaw_root: Optional[Path] = None,
) -> list[dict[str, Any]]:
    index = load_sessions_index(repo_root=repo_root, openclaw_root=openclaw_root)
    sessions_dir = jarvis_sessions_dir(repo_root=repo_root, openclaw_root=openclaw_root)
    rows: list[dict[str, Any]] = []
    for session_key, row in index.items():
        payload = dict(row or {})
        if "discord" not in session_key and str(payload.get("lastChannel") or "").lower() != "discord":
            continue
        session_file = payload.get("sessionFile")
        if session_file:
            session_path = Path(session_file)
        elif sessions_dir is not None and payload.get("sessionId"):
            session_path = sessions_dir / f"{payload['sessionId']}.jsonl"
        else:
            session_path = None
        rows.append(
            {
                "session_key": session_key,
                "session_id": str(payload.get("sessionId") or ""),
                "provider_override": str(payload.get("providerOverride") or ""),
                "model_override": str(payload.get("modelOverride") or ""),
                "compaction_count": int(payload.get("compactionCount") or 0),
                "last_channel": str(payload.get("lastChannel") or ""),
                "session_file": str(session_path) if session_path else "",
                "session_path": session_path,
                "raw": payload,
            }
        )
    rows.sort(key=lambda row: str(row["raw"].get("updatedAt") or ""), reverse=True)
    return rows


def inspect_discord_session_binding(binding: dict[str, Any]) -> dict[str, Any]:
    session_path = binding.get("session_path")
    session_file_missing = isinstance(session_path, Path) and not session_path.exists()
    rows, parse_errors = _load_jsonl_rows(session_path) if isinstance(session_path, Path) else ([], 0)
    valid_user_query_count = 0
    last_user_query = ""
    explicit_template_error = False
    latest_template_error = ""
    selected_provider_id = binding.get("provider_override") or ""
    selected_model_name = binding.get("model_override") or ""
    last_template_error_at = ""
    latest_assistant_reply_raw = ""
    latest_user_facing_reply = ""
    latest_assistant_reply_findings: list[str] = []
    latest_assistant_reply_contaminated = False
    for row in rows:
        if row.get("type") == "custom" and row.get("customType") == "model-snapshot":
            data = dict(row.get("data") or {})
            selected_provider_id = str(data.get("provider") or selected_provider_id)
            selected_model_name = str(data.get("modelId") or selected_model_name)
        message = dict(row.get("message") or {})
        role = str(message.get("role") or "").lower()
        text = _extract_text(message.get("content"))
        if role == "user" and _is_real_user_query(text):
            valid_user_query_count += 1
            last_user_query = text
        if role == "assistant":
            latest_assistant_reply_raw = text or str(row.get("errorMessage") or "")
            sanitized = sanitize_user_facing_assistant_reply(latest_assistant_reply_raw)
            latest_user_facing_reply = str(sanitized.get("clean_text") or "")
            latest_assistant_reply_findings = list(sanitized.get("removed_fragments") or [])
            latest_assistant_reply_contaminated = bool(sanitized.get("was_sanitized"))
        searchable = " ".join([json.dumps(row, sort_keys=True), text]).lower()
        if any(token in searchable for token in SESSION_TEMPLATE_ERROR_TOKENS):
            explicit_template_error = True
            latest_template_error = text or str(row.get("error") or "No user query found in messages.")
            last_template_error_at = str(row.get("timestamp") or "")

    malformed_reason = ""
    if session_file_missing:
        malformed_reason = "malformed_session_file_missing"
    elif explicit_template_error:
        malformed_reason = "malformed_session_template_no_user_query"
    elif valid_user_query_count == 0:
        malformed_reason = "malformed_session_no_valid_user_query"
    elif parse_errors:
        malformed_reason = "malformed_session_jsonl_parse_error"

    malformed = bool(malformed_reason)
    session_id = str(binding.get("session_id") or "")
    session_key = str(binding.get("session_key") or "")
    return {
        "session_key": session_key,
        "session_id": session_id,
        "provider_override": str(binding.get("provider_override") or ""),
        "model_override": str(binding.get("model_override") or ""),
        "selected_provider_id": selected_provider_id,
        "selected_model_name": selected_model_name,
        "session_file": str(binding.get("session_file") or ""),
        "compaction_count": int(binding.get("compaction_count") or 0),
        "valid_user_query_count": valid_user_query_count,
        "last_user_query": last_user_query,
        "latest_assistant_reply_raw": latest_assistant_reply_raw,
        "latest_user_facing_reply": latest_user_facing_reply,
        "latest_assistant_reply_contaminated": latest_assistant_reply_contaminated,
        "latest_assistant_reply_findings": latest_assistant_reply_findings,
        "explicit_template_error": explicit_template_error,
        "latest_template_error": latest_template_error,
        "last_template_error_at": last_template_error_at,
        "parse_error_count": parse_errors,
        "session_file_missing": session_file_missing,
        "malformed": malformed,
        "malformed_reason": malformed_reason,
        "operator_action_required": (
            f"Run `python3 scripts/repair_discord_sessions.py --session-id {session_id} --repair`."
            if malformed and session_id
            else ""
        ),
    }


def build_openclaw_discord_session_integrity_summary(
    *,
    repo_root: Optional[Path] = None,
    openclaw_root: Optional[Path] = None,
) -> dict[str, Any]:
    root = resolve_openclaw_root(repo_root=repo_root, openclaw_root=openclaw_root)
    bindings = list_discord_session_bindings(repo_root=repo_root, openclaw_root=openclaw_root)
    rows = [inspect_discord_session_binding(binding) for binding in bindings]
    malformed_rows = [row for row in rows if row.get("malformed")]
    latest_malformed = malformed_rows[0] if malformed_rows else None
    return {
        "summary_kind": "openclaw_discord_session_integrity",
        "openclaw_root": str(root) if root else "",
        "configured": root is not None,
        "detected_session_count": len(rows),
        "malformed_session_count": len(malformed_rows),
        "latest_malformed_session": latest_malformed,
        "recent_discord_sessions": rows[:10],
    }


def repair_discord_sessions(
    *,
    repo_root: Optional[Path] = None,
    openclaw_root: Optional[Path] = None,
    session_id: str = "",
    session_key: str = "",
    repair_all_malformed: bool = False,
    apply: bool = False,
) -> dict[str, Any]:
    root = resolve_openclaw_root(repo_root=repo_root, openclaw_root=openclaw_root)
    if root is None:
        return {
            "ok": False,
            "openclaw_root": "",
            "message": "OpenClaw home not found.",
            "repaired_sessions": [],
            "target_count": 0,
            "applied": apply,
        }
    index_path = _sessions_index_path(repo_root=repo_root, openclaw_root=root)
    index = load_sessions_index(repo_root=repo_root, openclaw_root=root)
    bindings = list_discord_session_bindings(repo_root=repo_root, openclaw_root=root)
    inspected = [inspect_discord_session_binding(binding) for binding in bindings]
    inspected_by_id = {row["session_id"]: row for row in inspected}
    inspected_by_key = {row["session_key"]: row for row in inspected}
    targets: list[dict[str, Any]] = []
    if repair_all_malformed:
        targets = [row for row in inspected if row.get("malformed")]
    elif session_id:
        row = inspected_by_id.get(session_id)
        if row is not None:
            targets = [row]
    elif session_key:
        row = inspected_by_key.get(session_key)
        if row is not None:
            targets = [row]
    timestamp = now_iso().replace(":", "-")
    repaired_sessions: list[dict[str, Any]] = []
    if apply and index_path and index_path.exists():
        shutil.copy2(index_path, index_path.with_name(f"{index_path.name}.bak_{timestamp}"))
    for row in targets:
        result = {
            "session_key": row["session_key"],
            "session_id": row["session_id"],
            "malformed_reason": row["malformed_reason"],
            "session_file": row["session_file"],
            "applied": apply,
            "archived_session_file": "",
            "removed_binding": False,
        }
        if apply:
            session_file = Path(row["session_file"]) if row.get("session_file") else None
            if session_file and session_file.exists():
                archived = session_file.with_name(f"{session_file.name}.malformed_{timestamp}")
                session_file.rename(archived)
                result["archived_session_file"] = str(archived)
            if row["session_key"] in index:
                index.pop(row["session_key"], None)
                result["removed_binding"] = True
        repaired_sessions.append(result)
    if apply and index_path is not None:
        index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "openclaw_root": str(root),
        "message": (
            "Malformed Discord sessions repaired."
            if apply
            else "Dry-run only. Re-run with --repair to archive malformed sessions and clear bindings."
        ),
        "repaired_sessions": repaired_sessions,
        "target_count": len(targets),
        "applied": apply,
    }
