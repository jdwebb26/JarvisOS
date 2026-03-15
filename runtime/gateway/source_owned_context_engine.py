#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from runtime.core.agent_roster import filter_tools_for_agent, infer_agent_id
from runtime.core.models import now_iso
from runtime.memory.brief_builder import build_session_context_brief_payload
from runtime.memory.governance import retrieve_memory_for_context
from runtime.memory.vault_index import load_session_context_summary, save_session_context_summary


DEFAULT_RAW_USER_TURN_WINDOW = 6
SAFE_BUDGET_RATIO = 0.72
HARD_BUDGET_RATIO = 0.82
DEFAULT_RETRIEVAL_BUDGET_TOKENS = 1200
DEFAULT_EPISODIC_LIMIT = 4
DEFAULT_SEMANTIC_LIMIT = 4
SIMPLE_CHAT_TOOL_RE = re.compile(
    r"(```|`[^`]+`|(?:^|\s)(?:read|open|inspect|edit|write|patch|diff|run|exec|bash|shell|terminal|command|script|file|directory|repo|workspace|json|yaml|yml|toml|python|node|npm|pnpm|pytest|test|rg|grep|ls|cat|sed|git)\b|(?:^|\s)(?:\.{1,2}/|~/|/)[^\s]+|[A-Za-z0-9._-]+\.(?:ts|tsx|js|jsx|mjs|cjs|py|json|yaml|yml|toml|md|sh|bash)\b)",
    re.IGNORECASE,
)
METADATA_BLOCK_RE = re.compile(
    r"^(?:Conversation info \(untrusted metadata\):|Sender \(untrusted metadata\):|Thread starter \(untrusted, for context\):|Replied message \(untrusted, for context\):|Forwarded message context \(untrusted metadata\):|Chat history since last reply \(untrusted, for context\):)\n```json\n[\s\S]*?\n```\s*",
    re.MULTILINE,
)
QUESTION_RE = re.compile(r"([^\n?]+\?)")
CONSTRAINT_RE = re.compile(r"\b(?:must|must not|do not|don't|never|keep|preserve|require|required|constraint|bounded|fail-closed)\b", re.IGNORECASE)
DECISION_RE = re.compile(r"\b(?:i will|we will|let's|decided|decision|plan|next step)\b", re.IGNORECASE)
PREFERENCE_RE = re.compile(r"\b(?:prefer|preference|always|never|keep .* as|default to)\b", re.IGNORECASE)


def estimate_tokens(text: Any) -> int:
    raw = str(text or "")
    return max(0, (len(raw) + 3) // 4)


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return str(content.get("text") or "").strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                if item.strip():
                    parts.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                text = str(item.get("text") or "").strip()
                if text:
                    parts.append(text)
            elif item.get("type") == "toolCall":
                try:
                    parts.append(json.dumps(item.get("arguments") or {}, sort_keys=True))
                except Exception:
                    continue
        return "\n".join(parts)
    return ""


def _message_text(message: dict[str, Any]) -> str:
    return _extract_text(message.get("content"))


def _tool_name(message: dict[str, Any]) -> str:
    return str(message.get("toolName") or message.get("name") or "tool")


def _split_metadata(text: str) -> tuple[str, int]:
    raw = str(text or "").replace("\r\n", "\n").strip()
    if not raw:
        return "", 0
    metadata_chars = 0
    body = raw
    while True:
        match = METADATA_BLOCK_RE.match(body)
        if not match:
            break
        metadata_chars += len(match.group(0))
        body = body[match.end():].lstrip()
    return body.strip(), metadata_chars


def _count_user_turns(messages: list[dict[str, Any]]) -> int:
    return sum(1 for msg in messages if str(msg.get("role") or "") == "user")


def _select_tool_exposure(prompt: str, tools: list[dict[str, Any]], *, channel: str, agent_id: str) -> dict[str, Any]:
    before_count = len(tools)
    if not tools:
        return {"mode": "none", "reason": "no_tools", "beforeCount": 0, "afterCount": 0, "agentId": agent_id, "tools": []}
    if channel != "discord":
        filtered = filter_tools_for_agent(agent_id, tools)
        return {
            "mode": "agent-scoped-full" if filtered["afterCount"] != before_count else "full",
            "reason": "agent_policy_non_discord_channel" if filtered["afterCount"] != before_count else "non_discord_channel",
            "beforeCount": before_count,
            "afterCount": filtered["afterCount"],
            "agentId": agent_id,
            "dropReasons": filtered["dropReasons"],
            "tools": filtered["tools"],
        }
    normalized = str(prompt or "").strip()
    if normalized and not SIMPLE_CHAT_TOOL_RE.search(normalized) and len(normalized) < 900:
        return {"mode": "chat-minimal", "reason": "simple_discord_chat", "beforeCount": before_count, "afterCount": 0, "agentId": agent_id, "tools": []}
    filtered = filter_tools_for_agent(agent_id, tools)
    return {
        "mode": "agent-scoped-full" if filtered["afterCount"] != before_count else "full",
        "reason": "agent_role_policy" if filtered["afterCount"] != before_count else "task_requires_tools",
        "beforeCount": before_count,
        "afterCount": filtered["afterCount"],
        "agentId": agent_id,
        "dropReasons": filtered["dropReasons"],
        "tools": filtered["tools"],
    }


def _distill_tool_result(message: dict[str, Any]) -> str:
    raw = _message_text(message).strip()
    refs = re.findall(r"(?:\.{1,2}/|~/|/)[^\s\"'`()\[\]{}]+", raw)
    ref_text = f" refs={', '.join(dict.fromkeys(refs[:3]))}" if refs else ""
    return f"[tool result distilled for context budget]: {_tool_name(message)}; omitted={len(raw)} chars{ref_text}"


def _apply_distillation(messages: list[dict[str, Any]], *, raw_user_turn_window: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    distilled: list[dict[str, Any]] = []
    user_seen = 0
    metadata_distilled = 0
    tool_distilled = 0
    for message in reversed(messages):
        role = str(message.get("role") or "")
        row = dict(message)
        if role == "user":
            user_seen += 1
            if user_seen > raw_user_turn_window:
                body, metadata_chars = _split_metadata(_message_text(row))
                if metadata_chars > 0:
                    metadata_distilled += 1
                    row["content"] = body or "[metadata wrapper removed for context budget]"
        elif role == "toolResult" and user_seen > raw_user_turn_window:
            tool_distilled += 1
            row["content"] = _distill_tool_result(row)
        distilled.append(row)
    distilled.reverse()
    return distilled, {
        "metadataDistilledCount": metadata_distilled,
        "toolResultDistilledCount": tool_distilled,
    }


def _bounded_recent_messages(messages: list[dict[str, Any]], *, raw_user_turn_window: int) -> list[dict[str, Any]]:
    if raw_user_turn_window <= 0:
        return list(messages)
    user_seen = 0
    start_index = 0
    for index in range(len(messages) - 1, -1, -1):
        if str(messages[index].get("role") or "") == "user":
            user_seen += 1
            if user_seen > raw_user_turn_window:
                start_index = index + 1
                break
    return list(messages[start_index:])


def _top_unique(items: list[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _build_summary_from_messages(
    *,
    session_key: str,
    messages: list[dict[str, Any]],
    prior_summary: dict[str, Any],
    retrieved_semantic: list[dict[str, Any]],
    distillation: dict[str, int],
) -> dict[str, Any]:
    user_texts = [_message_text(msg) for msg in messages if str(msg.get("role") or "") == "user"]
    assistant_texts = [_message_text(msg) for msg in messages if str(msg.get("role") or "") == "assistant"]
    tool_texts = [_message_text(msg) for msg in messages if str(msg.get("role") or "") == "toolResult"]
    objective = ""
    for candidate in reversed(user_texts):
        body, _ = _split_metadata(candidate)
        if body:
            objective = body.splitlines()[0].strip()
            break
    if not objective:
        objective = str(prior_summary.get("objective") or "")
    unresolved = _top_unique([match.group(1).strip() for text in user_texts for match in QUESTION_RE.finditer(text)], limit=5)
    constraints = _top_unique([line.strip() for text in [*user_texts, *assistant_texts] for line in text.splitlines() if CONSTRAINT_RE.search(line)], limit=6)
    decisions = _top_unique([line.strip() for text in assistant_texts for line in text.splitlines() if DECISION_RE.search(line)], limit=6)
    tool_findings = _top_unique([line.strip() for text in tool_texts for line in text.splitlines() if line.strip()], limit=6)
    operator_preferences = _top_unique(
        [str(item.get("summary") or item.get("title") or "").strip() for item in retrieved_semantic if str(item.get("memory_class") or "") == "operator_preference_memory"]
        + [line.strip() for text in user_texts for line in text.splitlines() if PREFERENCE_RE.search(line)],
        limit=6,
    )
    payload = build_session_context_brief_payload(
        session_key=session_key,
        objective=objective,
        unresolved_questions=unresolved or list(prior_summary.get("unresolved_questions") or []),
        active_constraints=constraints or list(prior_summary.get("active_constraints") or []),
        recent_decisions=decisions or list(prior_summary.get("recent_decisions") or []),
        tool_findings=tool_findings or list(prior_summary.get("tool_findings") or []),
        operator_preferences=operator_preferences or list(prior_summary.get("operator_preferences") or []),
        source_refs={
            "distillation": distillation,
            "session_key": session_key,
        },
    )
    return payload


def _tool_schema_tokens(tools: list[dict[str, Any]]) -> int:
    total = 0
    for tool in tools:
        total += estimate_tokens(tool.get("name") or "")
        total += estimate_tokens(json.dumps(tool.get("parameters") or {}, sort_keys=True))
        total += estimate_tokens(tool.get("description") or "")
    return total


def _retrieved_memory_text(items: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- {item.get('title') or item.get('memory_type')}: {item.get('summary') or item.get('content') or ''}".strip()
        for item in items
    ).strip()


def _build_prompt_budget(
    *,
    system_prompt: str,
    recent_messages: list[dict[str, Any]],
    current_prompt: str,
    tools: list[dict[str, Any]],
    retrieved_episodic: list[dict[str, Any]],
    retrieved_semantic: list[dict[str, Any]],
    rolling_summary: dict[str, Any],
    context_window_tokens: int,
    raw_user_turn_window: int,
    total_user_turns: int,
    distillation: dict[str, int],
    tool_exposure: dict[str, Any],
) -> dict[str, Any]:
    recent_chars = 0
    metadata_chars = 0
    tool_output_chars = 0
    for message in recent_messages:
        role = str(message.get("role") or "")
        text = _message_text(message)
        if role == "toolResult":
            tool_output_chars += len(text)
            continue
        body, metadata = _split_metadata(text)
        recent_chars += len(body)
        metadata_chars += metadata
    prompt_body, prompt_metadata = _split_metadata(current_prompt)
    recent_chars += len(prompt_body)
    metadata_chars += prompt_metadata
    summary_text = str(rolling_summary.get("markdown") or "")
    retrieved_items = [*retrieved_episodic, *retrieved_semantic]
    retrieved_text = _retrieved_memory_text(retrieved_items)
    categories = {
        "systemPrompt": {"tokens": estimate_tokens(system_prompt), "chars": len(system_prompt)},
        "recentConversationTurns": {"tokens": estimate_tokens(recent_chars), "chars": recent_chars},
        "toolSchemas": {"tokens": _tool_schema_tokens(tools), "chars": sum(len(json.dumps(tool, sort_keys=True)) for tool in tools)},
        "retrievedMemory": {"tokens": estimate_tokens(retrieved_text), "chars": len(retrieved_text)},
        "rawToolOutputs": {"tokens": estimate_tokens(tool_output_chars), "chars": tool_output_chars},
        "metadataWrappers": {"tokens": estimate_tokens(metadata_chars), "chars": metadata_chars},
        "rollingSessionSummary": {"tokens": estimate_tokens(summary_text), "chars": len(summary_text)},
    }
    estimated_total_tokens = sum(int(entry["tokens"]) for entry in categories.values())
    safe_threshold_tokens = max(1, int(context_window_tokens * SAFE_BUDGET_RATIO))
    hard_threshold_tokens = max(safe_threshold_tokens, int(context_window_tokens * HARD_BUDGET_RATIO))
    return {
        "estimatedTotalTokens": estimated_total_tokens,
        "safeThresholdTokens": safe_threshold_tokens,
        "hardThresholdTokens": hard_threshold_tokens,
        "overSafeThreshold": estimated_total_tokens > safe_threshold_tokens,
        "overHardThreshold": estimated_total_tokens > hard_threshold_tokens,
        "categories": categories,
        "workingMemory": {
            "rawUserTurnWindow": raw_user_turn_window,
            "userTurnsInSession": total_user_turns,
            "recentMessageCount": len(recent_messages),
        },
        "distillation": distillation,
        "retrieval": {
            "episodicCount": len(retrieved_episodic),
            "semanticCount": len(retrieved_semantic),
            "budgetTokens": DEFAULT_RETRIEVAL_BUDGET_TOKENS,
        },
        "toolExposure": {
            "mode": tool_exposure.get("mode") or "",
            "reason": tool_exposure.get("reason") or "",
            "beforeCount": int(tool_exposure.get("beforeCount") or 0),
            "afterCount": int(tool_exposure.get("afterCount") or 0),
            "agentId": str(tool_exposure.get("agentId") or ""),
            "dropReasons": dict(tool_exposure.get("dropReasons") or {}),
        },
    }


def build_context_packet(
    *,
    root: Path,
    session_key: str,
    system_prompt: str,
    current_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    agent_id: str = "",
    channel: str = "discord",
    context_window_tokens: int = 200000,
    raw_user_turn_window: int = DEFAULT_RAW_USER_TURN_WINDOW,
    retrieval_budget_tokens: int = DEFAULT_RETRIEVAL_BUDGET_TOKENS,
    episodic_limit: int = DEFAULT_EPISODIC_LIMIT,
    semantic_limit: int = DEFAULT_SEMANTIC_LIMIT,
) -> dict[str, Any]:
    root = Path(root).resolve()
    resolved_agent_id = infer_agent_id(agent_id=agent_id, session_key=session_key, lane=channel)
    total_user_turns = _count_user_turns(messages)
    distilled_messages, distillation = _apply_distillation(messages, raw_user_turn_window=raw_user_turn_window)
    recent_messages = _bounded_recent_messages(distilled_messages, raw_user_turn_window=raw_user_turn_window)
    prior_summary = load_session_context_summary(session_key, root=root)
    retrieval = retrieve_memory_for_context(
        actor="source_owned_context_engine",
        lane=channel,
        root=root,
        query_text=f"{current_prompt}\n\n{prior_summary.get('markdown') or ''}".strip(),
        task_id=None,
        retrieval_budget_tokens=retrieval_budget_tokens,
        episodic_limit=episodic_limit,
        semantic_limit=semantic_limit,
    )
    episodic = list(retrieval.get("episodic") or [])
    semantic = list(retrieval.get("semantic") or [])
    rolling_summary = _build_summary_from_messages(
        session_key=session_key,
        messages=distilled_messages,
        prior_summary=prior_summary,
        retrieved_semantic=semantic,
        distillation=distillation,
    )
    rolling_summary["source_refs"] = {
        **dict(rolling_summary.get("source_refs") or {}),
        "memory_retrieval_id": dict(retrieval.get("retrieval") or {}).get("memory_retrieval_id"),
    }
    save_session_context_summary(rolling_summary, root=root)
    tool_exposure = _select_tool_exposure(current_prompt, tools, channel=channel, agent_id=resolved_agent_id)
    visible_tools = list(tool_exposure.get("tools") or [])
    budget = _build_prompt_budget(
        system_prompt=system_prompt,
        recent_messages=recent_messages,
        current_prompt=current_prompt,
        tools=visible_tools,
        retrieved_episodic=episodic,
        retrieved_semantic=semantic,
        rolling_summary=rolling_summary,
        context_window_tokens=context_window_tokens,
        raw_user_turn_window=raw_user_turn_window,
        total_user_turns=total_user_turns,
        distillation=distillation,
        tool_exposure=tool_exposure,
    )
    compaction = {"requested": False, "reason": "none", "compacted": False}
    if budget["overSafeThreshold"] or total_user_turns > raw_user_turn_window:
        tighter_window = max(2, min(raw_user_turn_window, 3))
        compacted_messages = _bounded_recent_messages(distilled_messages, raw_user_turn_window=tighter_window)
        budget = _build_prompt_budget(
            system_prompt=system_prompt,
            recent_messages=compacted_messages,
            current_prompt=current_prompt,
            tools=visible_tools,
            retrieved_episodic=episodic[: max(1, episodic_limit - 1)],
            retrieved_semantic=semantic[: max(1, semantic_limit - 1)],
            rolling_summary=rolling_summary,
            context_window_tokens=context_window_tokens,
            raw_user_turn_window=tighter_window,
            total_user_turns=total_user_turns,
            distillation=distillation,
            tool_exposure=tool_exposure,
        )
        recent_messages = compacted_messages
        compaction = {
            "requested": True,
            "reason": "budget" if budget["overSafeThreshold"] else "raw_turn_window",
            "compacted": True,
        }
    budget["preflightCompaction"] = compaction
    blocked = bool(budget["overHardThreshold"])
    summary_stats = {
        "summary_id": str(rolling_summary.get("export_id") or ""),
        "chars": len(str(rolling_summary.get("markdown") or "")),
        "refreshedAt": str(rolling_summary.get("updated_at") or ""),
    }
    return {
        "sessionKey": session_key,
        "generatedAt": now_iso(),
        "workingMemoryMessages": recent_messages,
        "rollingSummary": rolling_summary,
        "retrievedMemory": {
            "episodic": episodic,
            "semantic": semantic,
            "retrieval": retrieval.get("retrieval") or {},
            "usedTokens": retrieval.get("used_tokens") or 0,
            "remainingBudgetTokens": retrieval.get("remaining_budget_tokens") or 0,
        },
        "toolExposure": {
            "mode": tool_exposure.get("mode") or "",
            "reason": tool_exposure.get("reason") or "",
            "beforeCount": int(tool_exposure.get("beforeCount") or 0),
            "afterCount": int(tool_exposure.get("afterCount") or 0),
            "agentId": resolved_agent_id,
            "dropReasons": dict(tool_exposure.get("dropReasons") or {}),
        },
        "visibleTools": visible_tools,
        "promptBudget": budget,
        "summaryStats": summary_stats,
        "blocked": blocked,
        "blockReason": "hard_threshold_exceeded" if blocked else "",
        "systemPromptReport": {
            "promptBudget": budget,
            "toolExposure": {
                "mode": tool_exposure.get("mode") or "",
                "reason": tool_exposure.get("reason") or "",
                "beforeCount": int(tool_exposure.get("beforeCount") or 0),
                "afterCount": int(tool_exposure.get("afterCount") or 0),
                "agentId": resolved_agent_id,
                "dropReasons": dict(tool_exposure.get("dropReasons") or {}),
            },
            "rollingSummary": summary_stats,
            "retrieval": {
                "episodicCount": len(episodic),
                "semanticCount": len(semantic),
                "usedTokens": retrieval.get("used_tokens") or 0,
                "remainingBudgetTokens": retrieval.get("remaining_budget_tokens") or 0,
            },
        },
    }
