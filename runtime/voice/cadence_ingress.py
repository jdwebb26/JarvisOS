#!/usr/bin/env python3
"""cadence_ingress — Cadence voice ingress pipeline.

Cadence is the dedicated voice ingress agent for OpenClaw.  It owns:
- utterance receipt and wake-phrase validation
- lightweight voice session state
- intent classification (which specialist should handle this?)
- routing to the right downstream agent

Jarvis stays lean: raw voice transcripts go to Cadence, not Jarvis.

Intent classes
--------------
voice_subsystem     matched by the existing voice router (spotify, discord,
                    tradingview, desktop, notification, browser-direct)
browser_action      utterance describes a browser task; routes to Bowser via
                    run_browser_task()
hal_task            coding/implementation request; queued via intake
kitt_quant          quant / strategy research request; queued via intake
scout_research      web research request; queued via intake
jarvis_orchestration status/summary/approval orchestration; forwarded to Jarvis
approval_confirmation yes/no/approve/reject confirmation; handled conservatively
local_quick         simple one-liner (greeting, time, help); answered inline
unclassified        no clear match; preview returned without routing

Entry points
------------
classify_cadence_intent(utterance)   — pure classification, no side-effects
route_cadence_utterance(utterance, ...)  — full pipeline, may create tasks
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import new_id
from runtime.voice.router import classify_voice_route, maybe_route_voice_command


# ---------------------------------------------------------------------------
# URL / site detection (for browser_action intent)
# ---------------------------------------------------------------------------

_URL_RE = re.compile(
    r"https?://[^\s\"'<>]+"
    r"|(?:^|\s)((?:www\.|(?:[a-z0-9-]+\.)+[a-z]{2,6})(?:/[^\s\"'<>]*)?)",
    re.IGNORECASE,
)


def _extract_url(text: str) -> str:
    m = re.search(r"https?://[^\s\"'<>]+", text)
    if m:
        return m.group(0).rstrip(".,;)")
    m = re.search(
        r"\b([a-z0-9-]+\.(?:com|org|net|gov|io|finance|xyz)(?:/[^\s\"'<>]*)?)\b",
        text,
        re.IGNORECASE,
    )
    if m:
        return "https://" + m.group(1)
    return ""


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

# Single-word tokens (matched against whole-word tokens only — avoids
# "test" matching inside "backtest" or "nq" matching inside "unique").
_APPROVAL_TOKENS  = frozenset(["yes", "no", "approve", "reject", "confirm", "deny", "cancel"])
_LOCAL_QUICK_TOKENS = frozenset(["hello", "hi", "hey", "thanks", "help"])
_HAL_TOKENS   = frozenset(["implement", "code", "fix", "patch", "refactor", "write", "build", "debug", "test", "edit"])
_KITT_TOKENS  = frozenset(["strategy", "backtest", "sharpe", "sortino", "nq", "futures", "nasdaq", "quant", "alpha", "robustness", "perturbation"])
_SCOUT_TOKENS = frozenset(["research", "find", "summarize", "summary", "explain", "gather"])
_JARVIS_TOKENS = frozenset(["status", "report", "approval"])

# Multi-word phrases (substring match against lowered text is fine here).
_LOCAL_QUICK_PHRASES = ("thank you", "what time", "what date")
_HAL_PHRASES   = ("change the", "change this")
_KITT_PHRASES  = ("profit factor", "walk-forward", "walk forward")
_SCOUT_PHRASES = ("look up", "what is", "who is", "how does", "tell me about")
_JARVIS_PHRASES = ("what's happening", "what happened", "show me", "give me")


def classify_cadence_intent(utterance: str) -> dict:
    """Classify a voice utterance into a Cadence intent class.

    Returns a dict with:
      intent        — one of the intent class strings
      confidence    — "high" | "medium" | "low"
      reason        — short string explaining the match
      url           — extracted URL if any (for browser_action)
    """
    text = (utterance or "").strip()
    lowered = text.lower()

    # 1. Check existing voice-subsystem router first (spotify, discord, etc.)
    voice_route = classify_voice_route(text)
    if voice_route["matched"] and voice_route["subsystem"] not in ("browser",):
        return {
            "intent": "voice_subsystem",
            "confidence": "high",
            "reason": f"voice_router_matched:{voice_route['subsystem']}:{voice_route['intent']}",
            "url": "",
            "voice_route": voice_route,
        }

    # 2. Approval / confirmation (single-word yes/no/approve)
    tokens = set(re.findall(r"[a-z0-9]+", lowered))
    if tokens.intersection(_APPROVAL_TOKENS) and len(tokens) <= 4:
        return {
            "intent": "approval_confirmation",
            "confidence": "high",
            "reason": "short_approval_token_match",
            "url": "",
            "voice_route": None,
        }

    # 3. Browser action — explicit browse/screenshot/snapshot + URL present,
    #    OR voice router matched browser subsystem
    url = _extract_url(text)
    browser_tokens = frozenset(["browse", "screenshot", "snapshot"])
    browser_phrases = ("open website", "inspect page", "navigate to", "go to")
    has_browser_kw = tokens.intersection(browser_tokens) or any(p in lowered for p in browser_phrases)
    if voice_route["matched"] and voice_route["subsystem"] == "browser":
        return {
            "intent": "browser_action",
            "confidence": "high",
            "reason": f"voice_router_browser:{voice_route['intent']}",
            "url": url or voice_route.get("target", ""),
            "voice_route": voice_route,
        }
    if has_browser_kw and url:
        return {
            "intent": "browser_action",
            "confidence": "high",
            "reason": "browser_keyword_plus_url",
            "url": url,
            "voice_route": None,
        }

    # 4. Local quick (greetings, simple queries — no need to route anywhere)
    if (tokens.intersection(_LOCAL_QUICK_TOKENS) or any(p in lowered for p in _LOCAL_QUICK_PHRASES)) and len(tokens) <= 6:
        return {
            "intent": "local_quick",
            "confidence": "medium",
            "reason": "local_quick_keyword_short_utterance",
            "url": "",
            "voice_route": None,
        }

    # 5a. Kitt quant phrases (specific terms beat generic "what is" scout pattern)
    if any(p in lowered for p in _KITT_PHRASES):
        return {
            "intent": "kitt_quant",
            "confidence": "high",
            "reason": "kitt_phrase_match",
            "url": "",
            "voice_route": None,
        }

    # 5b. Scout research task — token-based (before kitt tokens; "summarize NQ" = research)
    if tokens.intersection(_SCOUT_TOKENS):
        return {
            "intent": "scout_research",
            "confidence": "medium",
            "reason": "scout_token_match",
            "url": "",
            "voice_route": None,
        }

    # 6. Kitt quant task — tokens
    if tokens.intersection(_KITT_TOKENS):
        return {
            "intent": "kitt_quant",
            "confidence": "medium",
            "reason": "kitt_keyword_match",
            "url": "",
            "voice_route": None,
        }

    # 6b. Scout phrases ("what is", "who is", "look up") — after kitt tokens
    if any(p in lowered for p in _SCOUT_PHRASES):
        return {
            "intent": "scout_research",
            "confidence": "medium",
            "reason": "scout_phrase_match",
            "url": "",
            "voice_route": None,
        }

    # 7. HAL coding task (after scout/kitt — "test" must be a standalone token)
    if tokens.intersection(_HAL_TOKENS) or any(p in lowered for p in _HAL_PHRASES):
        return {
            "intent": "hal_task",
            "confidence": "medium",
            "reason": "hal_keyword_match",
            "url": "",
            "voice_route": None,
        }

    # 8. Jarvis orchestration
    if tokens.intersection(_JARVIS_TOKENS) or any(p in lowered for p in _JARVIS_PHRASES):
        return {
            "intent": "jarvis_orchestration",
            "confidence": "medium",
            "reason": "jarvis_keyword_match",
            "url": "",
            "voice_route": None,
        }

    # 9. Browser: URL present even without explicit keyword
    if url:
        return {
            "intent": "browser_action",
            "confidence": "low",
            "reason": "url_present_no_explicit_keyword",
            "url": url,
            "voice_route": None,
        }

    return {
        "intent": "unclassified",
        "confidence": "low",
        "reason": "no_intent_pattern_matched",
        "url": "",
        "voice_route": None,
    }


# ---------------------------------------------------------------------------
# Delegation helpers
# ---------------------------------------------------------------------------

def _delegate_browser(utterance: str, url: str, *, actor: str, lane: str, root: Path) -> dict:
    """Delegate a browser_action intent to Bowser via run_browser_task()."""
    from runtime.core.browser_task import infer_browser_action_spec, run_browser_task

    if not url:
        spec = infer_browser_action_spec(utterance)
        url = spec.get("target_url", "")
        action_type = spec.get("action_type", "snapshot")
    else:
        spec = infer_browser_action_spec(utterance)
        action_type = spec.get("action_type", "snapshot")

    if not url:
        return {
            "ok": False,
            "error": "no_url_extracted",
            "message": "Cannot delegate browser action: no URL found in utterance.",
        }

    result = run_browser_task(
        action_type=action_type,
        target_url=url,
        actor=actor,
        lane=lane,
        root=root,
    )
    return {
        "ok": result.get("status") == "completed",
        "delegation_target": "bowser",
        "task_id": result.get("task_id"),
        "status": result.get("status"),
        "final_outcome": result.get("final_outcome", ""),
        "artifact_id": result.get("artifact_id"),
        "browser_result": result.get("browser_result"),
        "dispatch_result": result.get("dispatch_result"),
    }


def _delegate_personaplex(utterance: str, *, base: dict, vsid: str, root: Path) -> dict:
    """Route an utterance to the conversational engine for handling.

    The engine is read-only for conversational intents and proposes (never
    auto-executes) for command intents, so this is safe even without execute
    gating.
    """
    try:
        from runtime.personaplex.engine import chat
        ppx_result = chat(utterance, root=root, voice_session_id=vsid)
        response = ppx_result.get("response", "")
        ppx_intent = ppx_result.get("intent", {})
        action_proposed = ppx_result.get("action_proposed")
        session = ppx_result.get("session")
        return {
            **base,
            "routed": True,
            "route_reason": "personaplex_conversation",
            "delegation_result": {
                "response": response,
                "personaplex_intent": ppx_intent.get("intent", ""),
                "action_proposed": action_proposed,
                "conversation_id": session.conversation_id if session else "",
                "llm_usage": ppx_result.get("llm_usage", {}),
            },
        }
    except Exception as exc:
        return {
            **base,
            "routed": False,
            "route_reason": "personaplex_error",
            "delegation_result": {
                "error": str(exc),
                "note": "Conversation delegation failed; utterance not handled.",
            },
        }


def _delegate_intake_task(utterance: str, *, actor: str, lane: str, channel: str, root: Path) -> dict:
    """Queue an intake task for hal/kitt/scout by prepending 'task:' and routing through intake."""
    from runtime.core.intake import create_task_from_message_result
    from runtime.core.models import new_id

    text = f"task: {utterance}" if not utterance.lower().startswith("task:") else utterance
    result = create_task_from_message_result(
        text=text,
        user=actor,
        lane=lane,
        channel=channel,
        message_id=new_id("vmsg"),
        root=root,
    )
    return {
        "ok": result.get("ok", False) or result.get("task_created", False),
        "task_created": result.get("task_created", False),
        "task_id": result.get("task_id"),
        "task_type": result.get("task_type"),
        "assigned_model": result.get("assigned_model"),
        "initial_status": result.get("initial_status"),
        "error": result.get("message") if not result.get("ok") else None,
        "_raw": result,
    }


# ---------------------------------------------------------------------------
# Main ingress function
# ---------------------------------------------------------------------------

def route_cadence_utterance(
    utterance: str,
    *,
    voice_session_id: str = "",
    actor: str = "cadence",
    lane: str = "voice",
    task_id: str = "",
    execute: bool = False,
    root=None,
) -> dict:
    """Full Cadence ingress pipeline for a single utterance.

    Steps:
    1. Classify intent.
    2. If execute=False: return preview (intent + route, no side-effects).
    3. If execute=True: delegate to appropriate backend/specialist.

    Returns a dict with:
      utterance, voice_session_id, intent_result, execute,
      delegation_result (if execute=True), routed, route_reason
    """
    resolved_root = Path(root or ROOT).resolve()
    vsid = voice_session_id or new_id("vsession")

    intent_result = classify_cadence_intent(utterance)
    intent = intent_result["intent"]

    base = {
        "utterance": utterance,
        "voice_session_id": vsid,
        "intent_result": intent_result,
        "execute": execute,
    }

    # Conversation-eligible intents are safe in both preview and execute mode
    # (the conversational engine is read-only for conversational, proposes for commands).
    # Route them early before the execute gate.
    _personaplex_intents = {"jarvis_orchestration", "unclassified", "approval_confirmation"}
    if intent in _personaplex_intents:
        return _delegate_personaplex(utterance, base=base, vsid=vsid, root=resolved_root)

    if not execute:
        return {
            **base,
            "routed": False,
            "route_reason": "preview_only",
            "delegation_result": None,
        }

    # --- voice_subsystem: delegate to existing voice router ---
    if intent == "voice_subsystem":
        voice_result = maybe_route_voice_command(
            utterance,
            actor=actor,
            lane=lane,
            task_id=task_id,
            root=resolved_root,
            execute=True,
        )
        return {
            **base,
            "routed": voice_result.get("routed", False),
            "route_reason": voice_result.get("route_reason", "voice_subsystem_dispatch"),
            "delegation_result": voice_result,
        }

    # --- browser_action: delegate to Bowser ---
    if intent == "browser_action":
        delegation = _delegate_browser(
            utterance,
            url=intent_result.get("url", ""),
            actor=actor,
            lane=lane,
            root=resolved_root,
        )
        return {
            **base,
            "routed": delegation.get("ok", False),
            "route_reason": "bowser_run_browser_task",
            "delegation_result": delegation,
        }

    # --- hal_task / kitt_quant / scout_research: queue via intake ---
    if intent in ("hal_task", "kitt_quant", "scout_research"):
        channel_map = {
            "hal_task": "tasks",
            "kitt_quant": "kitt",
            "scout_research": "research",
        }
        delegation = _delegate_intake_task(
            utterance,
            actor=actor,
            lane=lane,
            channel=channel_map[intent],
            root=resolved_root,
        )
        return {
            **base,
            "routed": delegation.get("task_created", False),
            "route_reason": f"intake_task_created:{intent}",
            "delegation_result": delegation,
        }

    # --- local_quick: inline response ---
    if intent == "local_quick":
        return {
            **base,
            "routed": True,
            "route_reason": "local_quick_inline",
            "delegation_result": {
                "response": "Ready. What can I help you with?",
            },
        }

    # --- fallback: route to conversational engine ---
    return _delegate_personaplex(utterance, base=base, vsid=vsid, root=resolved_root)
