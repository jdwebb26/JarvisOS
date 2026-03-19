#!/usr/bin/env python3
"""PersonaPlex engine — the core conversation loop.

Ties together session, context, intent classification, and LLM calls
into a coherent multi-turn conversational copilot.

Safety model:
- Read-only by default. Context assembly reads runtime state; never modifies it.
- Command intents produce a PendingAction that must be explicitly confirmed.
- Escalation intents surface proposed actions but do not execute them.
- Only confirmed actions are executed, and only through well-known safe paths.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

try:
    import requests as _requests
except Exception:
    _requests = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.personaplex.session import (
    PersonaPlexSession,
    add_pending_action,
    add_turn,
    build_conversation_messages,
    clear_resolved_actions,
    create_session,
    load_session,
    resolve_pending_action,
    save_session,
)
from runtime.personaplex.context import (
    assemble_runtime_context,
    read_pending_approvals,
    safe_read_file,
)
from runtime.personaplex.intent import (
    INTENT_COMMAND,
    INTENT_CONVERSATIONAL,
    INTENT_ESCALATION,
    INTENT_META,
    classify_intent,
    is_read_only_intent,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LMSTUDIO_BASE_URL = os.environ.get("JARVIS_LMSTUDIO_BASE_URL", "http://100.70.114.34:1234/v1")
PERSONAPLEX_MODEL = os.environ.get("PERSONAPLEX_MODEL", "qwen3.5-35b-a3b")
PERSONAPLEX_MAX_TOKENS = int(os.environ.get("PERSONAPLEX_MAX_TOKENS", "2048"))
PERSONAPLEX_TEMPERATURE = float(os.environ.get("PERSONAPLEX_TEMPERATURE", "0.3"))

SYSTEM_PROMPT = """\
You are Cadence, the voice assistant and conversational copilot for OpenClaw/Jarvis — a multi-agent \
AI system for discovering NQ futures trading strategies.

Your role:
- Answer questions about the current state of the system (tasks, approvals, agents, services)
- Help the operator understand what needs attention
- Summarize recent activity and system health
- Read and explain workspace files when asked
- If the operator asks you to take an action (approve, reject, retry), propose the action \
  clearly and wait for explicit confirmation — never execute silently

You have access to live runtime context injected into this conversation. Use it to answer \
questions accurately. If you don't have enough context, say so rather than guessing.

Keep responses concise and operator-focused. Use markdown formatting sparingly. \
When referencing task/approval/review IDs, include them so the operator can act on them.
"""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_llm(
    messages: list[dict[str, str]],
    *,
    model: str = "",
    max_tokens: int = 0,
    temperature: float = -1.0,
) -> dict[str, Any]:
    """Call LM Studio with the given messages. Returns parsed response dict."""
    if _requests is None:
        return {"error": "requests library not installed", "content": ""}

    model = model or PERSONAPLEX_MODEL
    max_tokens = max_tokens or PERSONAPLEX_MAX_TOKENS
    temperature = temperature if temperature >= 0 else PERSONAPLEX_TEMPERATURE

    url = f"{LMSTUDIO_BASE_URL.rstrip('/')}/chat/completions"
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        resp = _requests.post(url, json=body, timeout=(5, 120))
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        content = ""
        if choices:
            content = (choices[0].get("message") or {}).get("content", "")
        usage = data.get("usage") or {}
        return {
            "content": content,
            "model": data.get("model", model),
            "usage": {
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "total_tokens": int(usage.get("total_tokens") or 0),
            },
            "error": "",
        }
    except Exception as exc:
        return {"content": "", "model": model, "usage": {}, "error": str(exc)}


# ---------------------------------------------------------------------------
# Action execution (safe, bounded)
# ---------------------------------------------------------------------------

def _execute_confirmed_action(action_type: str, params: dict[str, Any], root: Path) -> str:
    """Execute a confirmed action. Returns human-readable result."""
    task_id = params.get("task_id", "")

    if action_type == "approve_task" and task_id:
        try:
            from runtime.core.task_runtime import transition_task_status
            from runtime.core.task_store import load_task
            task = load_task(task_id, root=root)
            if task is None:
                return f"Task {task_id} not found."
            if task.status not in ("waiting_approval",):
                return f"Task {task_id} is in status '{task.status}', not waiting_approval."
            transition_task_status(task_id, "completed", actor="personaplex", lane="personaplex", root=root)
            return f"Task {task_id} approved and completed."
        except Exception as exc:
            return f"Failed to approve task: {exc}"

    if action_type == "reject_task" and task_id:
        try:
            from runtime.core.task_runtime import transition_task_status
            transition_task_status(task_id, "failed", actor="personaplex", lane="personaplex", root=root)
            return f"Task {task_id} rejected (failed)."
        except Exception as exc:
            return f"Failed to reject task: {exc}"

    if action_type == "retry_task" and task_id:
        try:
            from runtime.core.task_runtime import transition_task_status
            transition_task_status(task_id, "queued", actor="personaplex", lane="personaplex", root=root)
            return f"Task {task_id} re-queued for retry."
        except Exception as exc:
            return f"Failed to retry task: {exc}"

    return f"Action type '{action_type}' is not supported for execution."


# ---------------------------------------------------------------------------
# Core conversation turn
# ---------------------------------------------------------------------------

def process_turn(
    user_input: str,
    session: PersonaPlexSession,
    *,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Process a single user turn and return the assistant response.

    Returns dict with:
        response: str — the assistant's reply
        intent: dict — classified intent
        action_proposed: Optional[PendingAction dict] — if a command was proposed
        action_executed: Optional[str] — if a confirmed action was run
        session: PersonaPlexSession — updated session
        llm_usage: dict — token usage
        error: str — any error
    """
    root_path = Path(root or ROOT).resolve()
    result: dict[str, Any] = {
        "response": "",
        "intent": {},
        "action_proposed": None,
        "action_executed": None,
        "session": session,
        "llm_usage": {},
        "error": "",
    }

    # 1. Classify intent
    intent = classify_intent(user_input)
    result["intent"] = intent

    # 2. Handle meta intents directly (no LLM needed)
    if intent["intent"] == INTENT_META:
        return _handle_meta(user_input, intent, session, result, root=root_path)

    # 3. Handle escalation — check for pending action confirmation
    if intent["intent"] == INTENT_ESCALATION and intent["command_type"] == "confirm_pending":
        return _handle_confirmation(user_input, session, result, root=root_path)

    # 4. Handle command intents — propose action, don't execute
    if intent["intent"] == INTENT_COMMAND:
        return _handle_command(user_input, intent, session, result, root=root_path)

    # 5. Conversational — assemble context + call LLM
    return _handle_conversation(user_input, intent, session, result, root=root_path)


def _handle_meta(
    user_input: str, intent: dict, session: PersonaPlexSession,
    result: dict[str, Any], *, root: Path,
) -> dict[str, Any]:
    cmd = intent["command_type"]
    if cmd == "help":
        response = (
            "I'm Cadence, your conversational copilot. I can:\n"
            "- Tell you what needs approval, what failed, what's queued\n"
            "- Summarize what agents did recently\n"
            "- Show recent git commits and repo changes\n"
            "- Read workspace files safely\n"
            "- Propose actions (approve/reject/retry tasks) — with your explicit confirmation\n\n"
            "Try: 'what needs approval?' or 'what failed today?' or 'show me the queued tasks'"
        )
    elif cmd == "quit":
        response = "Session ended. Goodbye."
        session.mode = "ended"
    elif cmd == "history":
        from runtime.personaplex.session import list_sessions
        sessions = list_sessions(root=root, limit=5)
        if sessions:
            lines = [f"Recent sessions ({len(sessions)}):"]
            for s in sessions:
                lines.append(f"  - {s.conversation_id} ({s.turn_count} turns, {s.updated_at[:19]})")
            response = "\n".join(lines)
        else:
            response = "No previous sessions found."
    elif cmd == "new_session":
        session = create_session(actor=session.actor, root=root)
        response = f"New session started: {session.conversation_id}"
    else:
        response = f"Unknown meta command: {cmd}"

    session = add_turn(session, "user", user_input, root=root)
    session = add_turn(session, "assistant", response, root=root)
    result["response"] = response
    result["session"] = session
    return result


def _handle_confirmation(
    user_input: str, session: PersonaPlexSession,
    result: dict[str, Any], *, root: Path,
) -> dict[str, Any]:
    pending = [a for a in session.pending_actions if a.status == "pending"]
    if not pending:
        # No pending action — treat as conversational
        return _handle_conversation(user_input, result["intent"], session, result, root=root)

    # Confirm the most recent pending action
    action = pending[-1]
    resolve_pending_action(session, action.action_id, "confirmed", root=root)
    exec_result = _execute_confirmed_action(action.action_type, action.action_params, root)
    clear_resolved_actions(session, root=root)

    response = f"Executed: {action.description}\nResult: {exec_result}"
    session = add_turn(session, "user", user_input, root=root)
    session = add_turn(session, "assistant", response, root=root)
    session.mode = "conversational"
    save_session(session, root=root)

    result["response"] = response
    result["action_executed"] = exec_result
    result["session"] = session
    return result


def _handle_command(
    user_input: str, intent: dict, session: PersonaPlexSession,
    result: dict[str, Any], *, root: Path,
) -> dict[str, Any]:
    cmd_type = intent["command_type"]
    ids = intent["extracted_ids"]
    task_id = ""
    for id_str in ids:
        if id_str.startswith("task_") or id_str.startswith("apr_"):
            task_id = id_str
            break

    if not task_id and cmd_type in ("approve_task", "reject_task", "retry_task", "cancel_task"):
        # No ID found — ask for it
        response = f"I can {cmd_type.replace('_', ' ')}, but I need a task or approval ID. Which one?"
        session = add_turn(session, "user", user_input, root=root)
        session = add_turn(session, "assistant", response, root=root)
        result["response"] = response
        result["session"] = session
        return result

    # Propose the action
    description = f"{cmd_type.replace('_', ' ').title()}: {task_id}"
    action = add_pending_action(
        session,
        description=description,
        action_type=cmd_type,
        action_params={"task_id": task_id},
        root=root,
    )
    session.mode = "command"

    response = (
        f"Proposed action: **{description}**\n"
        f"Action ID: {action.action_id}\n\n"
        f"Type 'yes' or 'confirm' to execute, or 'no'/'cancel' to abort."
    )
    session = add_turn(session, "user", user_input, root=root)
    session = add_turn(session, "assistant", response, root=root)

    result["response"] = response
    result["action_proposed"] = action.to_dict()
    result["session"] = session
    return result


def _handle_conversation(
    user_input: str, intent: dict, session: PersonaPlexSession,
    result: dict[str, Any], *, root: Path,
) -> dict[str, Any]:
    # Check for file read requests
    file_context = ""
    file_patterns = [
        r"(?:read|show|open|cat|display|inspect)\s+(?:file\s+)?([^\s]+\.\w+)",
        r"(?:what'?s?\s+in|contents?\s+of)\s+([^\s]+\.\w+)",
    ]
    import re
    for pattern in file_patterns:
        match = re.search(pattern, user_input.lower())
        if match:
            file_result = safe_read_file(match.group(1), root=root)
            if not file_result["error"]:
                file_context = (
                    f"\n\n[File: {file_result['path']}]\n"
                    f"{file_result['content']}"
                )
                if file_result.get("truncated"):
                    file_context += "\n[... truncated]"
            else:
                file_context = f"\n\n[File read error: {file_result['error']}]"
            break

    # Assemble runtime context
    runtime_ctx = assemble_runtime_context(root=root)

    # Build messages
    system_msg = (
        f"{SYSTEM_PROMPT}\n\n"
        f"[LIVE RUNTIME STATE as of now]\n{runtime_ctx}"
    )
    if file_context:
        system_msg += file_context

    # Add pending actions context
    pending = [a for a in session.pending_actions if a.status == "pending"]
    if pending:
        system_msg += "\n\n[PENDING ACTIONS requiring confirmation]:\n"
        for a in pending:
            system_msg += f"  - {a.action_id}: {a.description} ({a.action_type})\n"

    messages: list[dict[str, str]] = [{"role": "system", "content": system_msg}]

    # Add conversation history
    conv_msgs = build_conversation_messages(session)
    messages.extend(conv_msgs)

    # Add current user message
    messages.append({"role": "user", "content": user_input})

    # Call LLM
    llm_result = _call_llm(messages)
    if llm_result["error"]:
        response = f"LLM error: {llm_result['error']}\n\nI can still answer from runtime state directly."
        # Provide a basic fallback
        if "approval" in user_input.lower() or "approve" in user_input.lower():
            approvals = read_pending_approvals(root=root)
            if approvals:
                lines = [f"Pending approvals ({len(approvals)}):"]
                for a in approvals:
                    lines.append(f"  - {a['approval_id']} for {a['task_id']}: {a['summary'][:80]}")
                response += "\n\n" + "\n".join(lines)
            else:
                response += "\n\nNo pending approvals."
    else:
        response = llm_result["content"]

    result["llm_usage"] = llm_result.get("usage", {})

    # Record turns
    session = add_turn(session, "user", user_input, root=root)
    session = add_turn(session, "assistant", response, root=root)

    result["response"] = response
    result["session"] = session
    return result


# ---------------------------------------------------------------------------
# High-level API
# ---------------------------------------------------------------------------

def chat(
    user_input: str,
    *,
    conversation_id: Optional[str] = None,
    voice_session_id: Optional[str] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Top-level chat entry point. Loads or creates session, processes turn, returns result."""
    root_path = Path(root or ROOT).resolve()

    session = None
    if conversation_id:
        session = load_session(conversation_id, root=root_path)
    if session is None:
        session = create_session(voice_session_id=voice_session_id or "", root=root_path)
    elif voice_session_id and not session.voice_session_id:
        session.voice_session_id = voice_session_id
        save_session(session, root=root_path)

    return process_turn(user_input, session, root=root_path)
