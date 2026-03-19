#!/usr/bin/env python3
"""PersonaPlex intent classification — separates conversation from commands.

Three intent categories:
1. conversational — questions, discussion, status inquiries (read-only)
2. command — requests to take action (approve, reject, retry, run)
3. escalation — conversational intent that requires command confirmation

The classifier is rule-based for safety. It does not use an LLM to decide
whether to execute actions — that decision is always explicit.
"""
from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Intent types
# ---------------------------------------------------------------------------

INTENT_CONVERSATIONAL = "conversational"
INTENT_COMMAND = "command"
INTENT_ESCALATION = "escalation"
INTENT_META = "meta"  # session management (new session, history, help)

# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------

# Command patterns — things that ask PersonaPlex to DO something
_COMMAND_PATTERNS = [
    (r"\bapprove\b.*\btask\b", "approve_task"),
    (r"\breject\b.*\btask\b", "reject_task"),
    (r"\bretry\b.*\btask\b", "retry_task"),
    (r"\bapprove\b\s+(task_\w+|apr_\w+)", "approve_task"),
    (r"\breject\b\s+(task_\w+|apr_\w+)", "reject_task"),
    (r"\bretry\b\s+(task_\w+)", "retry_task"),
    (r"\brun\s+ralph\b", "run_ralph"),
    (r"\brestart\b.*\b(service|gateway|ralph)\b", "restart_service"),
    (r"\bkill\b|\bstop\b|\bhalt\b", "stop_action"),
    (r"\bpromote\b.*\b(task|artifact|output)\b", "promote"),
    (r"\bcancel\b.*\btask\b", "cancel_task"),
]

# Escalation patterns — conversational questions that might lead to action
_ESCALATION_PATTERNS = [
    r"\bshould\s+(?:i|we)\s+(?:approve|reject|retry|run|cancel)\b",
    r"\bcan\s+you\s+(?:approve|reject|retry|run|cancel)\b",
    r"\bwant\s+(?:me\s+)?to\s+(?:approve|reject|retry|run|cancel)\b",
    r"\bgo\s+ahead\s+and\b",
    r"\bdo\s+it\b",
    r"\byes\b.*\bconfirm\b",
    r"^(?:yes|y|confirm|do it|go ahead|approved?|proceed)\s*[.!]?\s*$",
]

# Meta patterns — session management
_META_PATTERNS = [
    (r"\bnew\s+(?:session|conversation|chat)\b", "new_session"),
    (r"\b(?:clear|reset)\s+(?:session|conversation|chat|history)\b", "new_session"),
    (r"\bhelp\b", "help"),
    (r"\bhistory\b|\bprevious\s+(?:session|conversation)s?\b", "history"),
    (r"^/?(?:quit|exit|bye|goodbye)\s*$", "quit"),
]


def classify_intent(utterance: str) -> dict[str, Any]:
    """Classify user utterance into intent category.

    Returns:
        dict with keys:
            intent: "conversational" | "command" | "escalation" | "meta"
            command_type: str (if command/escalation, e.g. "approve_task")
            confidence: "high" | "medium" | "low"
            extracted_ids: list of task_id/approval_id patterns found
            reason: str
    """
    text = utterance.strip()
    text_lower = text.lower()

    # Extract IDs
    extracted_ids = re.findall(r"(task_[a-f0-9]+|apr_[a-f0-9]+|art_[a-f0-9]+)", text_lower)

    # Check meta first
    for pattern, meta_type in _META_PATTERNS:
        if re.search(pattern, text_lower):
            return {
                "intent": INTENT_META,
                "command_type": meta_type,
                "confidence": "high",
                "extracted_ids": extracted_ids,
                "reason": f"Matched meta pattern: {meta_type}",
            }

    # Check escalation patterns BEFORE command patterns — "should I approve" is
    # escalation (asking about an action), not a direct command.
    for pattern in _ESCALATION_PATTERNS:
        if re.search(pattern, text_lower):
            # Bare confirmations ("yes", "confirm") are high-confidence escalation
            is_bare_confirm = re.match(
                r"^(?:yes|y|confirm|do it|go ahead|approved?|proceed)\s*[.!]?\s*$",
                text_lower,
            )
            return {
                "intent": INTENT_ESCALATION,
                "command_type": "confirm_pending" if is_bare_confirm else "escalation_query",
                "confidence": "high" if is_bare_confirm else "medium",
                "extracted_ids": extracted_ids,
                "reason": "User appears to be confirming or requesting action",
            }

    # Check command patterns (after escalation, so "should I approve" doesn't match here)
    for pattern, cmd_type in _COMMAND_PATTERNS:
        if re.search(pattern, text_lower):
            return {
                "intent": INTENT_COMMAND,
                "command_type": cmd_type,
                "confidence": "high" if extracted_ids else "medium",
                "extracted_ids": extracted_ids,
                "reason": f"Matched command pattern: {cmd_type}",
            }

    # Default: conversational
    return {
        "intent": INTENT_CONVERSATIONAL,
        "command_type": "",
        "confidence": "high",
        "extracted_ids": extracted_ids,
        "reason": "No command or escalation pattern matched",
    }


def is_read_only_intent(intent_result: dict[str, Any]) -> bool:
    """Return True if this intent is safe to handle without confirmation."""
    return intent_result["intent"] in {INTENT_CONVERSATIONAL, INTENT_META}
