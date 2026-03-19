#!/usr/bin/env python3
"""PersonaPlex session — persistent multi-turn conversation state.

Each session tracks:
- conversation_id and metadata
- ordered turn history (user + assistant)
- rolling summary distilled from older turns
- active mode (conversational / command / escalation)
- pending action proposals awaiting confirmation
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import new_id, now_iso


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RECENT_TURNS = 12          # Keep last N turns in active window
SUMMARY_TRIGGER_TURNS = 8     # Start summarizing when this many turns accumulate
SESSIONS_DIR_NAME = "personaplex_sessions"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Turn:
    role: str          # "user" | "assistant" | "system"
    content: str
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content,
                "timestamp": self.timestamp, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Turn:
        return cls(role=d["role"], content=d["content"],
                   timestamp=d.get("timestamp", ""),
                   metadata=d.get("metadata", {}))


@dataclass
class PendingAction:
    """An action proposed by PersonaPlex that requires user confirmation."""
    action_id: str
    description: str
    action_type: str       # "approve_task" | "reject_task" | "retry_task" | "run_command"
    action_params: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # "pending" | "confirmed" | "cancelled"
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PendingAction:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class PersonaPlexSession:
    conversation_id: str
    created_at: str
    updated_at: str
    actor: str = "operator"
    mode: str = "conversational"   # "conversational" | "command" | "escalation"
    turns: list[Turn] = field(default_factory=list)
    rolling_summary: str = ""
    turn_count: int = 0
    pending_actions: list[PendingAction] = field(default_factory=list)
    voice_session_id: str = ""     # Link to Cadence voice session if applicable
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "actor": self.actor,
            "mode": self.mode,
            "turns": [t.to_dict() for t in self.turns],
            "rolling_summary": self.rolling_summary,
            "turn_count": self.turn_count,
            "pending_actions": [a.to_dict() for a in self.pending_actions],
            "voice_session_id": self.voice_session_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PersonaPlexSession:
        return cls(
            conversation_id=d["conversation_id"],
            created_at=d["created_at"],
            updated_at=d["updated_at"],
            actor=d.get("actor", "operator"),
            mode=d.get("mode", "conversational"),
            turns=[Turn.from_dict(t) for t in d.get("turns", [])],
            rolling_summary=d.get("rolling_summary", ""),
            turn_count=d.get("turn_count", 0),
            pending_actions=[PendingAction.from_dict(a) for a in d.get("pending_actions", [])],
            voice_session_id=d.get("voice_session_id", ""),
            metadata=d.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _sessions_dir(root: Optional[Path] = None) -> Path:
    base = Path(root or ROOT).resolve()
    d = base / "state" / SESSIONS_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_session(session: PersonaPlexSession, root: Optional[Path] = None) -> PersonaPlexSession:
    session.updated_at = now_iso()
    path = _sessions_dir(root) / f"{session.conversation_id}.json"
    path.write_text(json.dumps(session.to_dict(), indent=2) + "\n", encoding="utf-8")
    return session


def load_session(conversation_id: str, root: Optional[Path] = None) -> Optional[PersonaPlexSession]:
    path = _sessions_dir(root) / f"{conversation_id}.json"
    if not path.exists():
        return None
    try:
        return PersonaPlexSession.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def list_sessions(root: Optional[Path] = None, limit: int = 20) -> list[PersonaPlexSession]:
    d = _sessions_dir(root)
    sessions: list[PersonaPlexSession] = []
    def _sort_key(p: Path) -> str:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data.get("updated_at", "")
        except Exception:
            return ""
    for path in sorted(d.glob("*.json"), key=_sort_key, reverse=True):
        try:
            sessions.append(PersonaPlexSession.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
        if len(sessions) >= limit:
            break
    return sessions


def create_session(
    *,
    actor: str = "operator",
    voice_session_id: str = "",
    root: Optional[Path] = None,
) -> PersonaPlexSession:
    now = now_iso()
    session = PersonaPlexSession(
        conversation_id=new_id("ppx"),
        created_at=now,
        updated_at=now,
        actor=actor,
        voice_session_id=voice_session_id,
    )
    return save_session(session, root=root)


def latest_session(root: Optional[Path] = None) -> Optional[PersonaPlexSession]:
    sessions = list_sessions(root=root, limit=1)
    return sessions[0] if sessions else None


# ---------------------------------------------------------------------------
# Turn management
# ---------------------------------------------------------------------------

def add_turn(
    session: PersonaPlexSession,
    role: str,
    content: str,
    *,
    metadata: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> PersonaPlexSession:
    turn = Turn(role=role, content=content, timestamp=now_iso(), metadata=metadata or {})
    session.turns.append(turn)
    session.turn_count += 1

    # Trim old turns, keeping rolling summary fresh
    if len(session.turns) > MAX_RECENT_TURNS:
        overflow = session.turns[:-MAX_RECENT_TURNS]
        session.turns = session.turns[-MAX_RECENT_TURNS:]
        # Build summary from overflow
        overflow_text = "\n".join(
            f"[{t.role}]: {t.content[:200]}" for t in overflow
        )
        if session.rolling_summary:
            session.rolling_summary = (
                f"{session.rolling_summary}\n\n"
                f"[Earlier turns {session.turn_count - MAX_RECENT_TURNS - len(overflow) + 1}"
                f"-{session.turn_count - MAX_RECENT_TURNS}]:\n{overflow_text}"
            )
        else:
            session.rolling_summary = f"[Earlier turns]:\n{overflow_text}"
        # Keep summary bounded
        if len(session.rolling_summary) > 4000:
            session.rolling_summary = session.rolling_summary[-4000:]

    return save_session(session, root=root)


def add_pending_action(
    session: PersonaPlexSession,
    *,
    description: str,
    action_type: str,
    action_params: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> PendingAction:
    action = PendingAction(
        action_id=new_id("pact"),
        description=description,
        action_type=action_type,
        action_params=action_params or {},
        created_at=now_iso(),
    )
    session.pending_actions.append(action)
    save_session(session, root=root)
    return action


def resolve_pending_action(
    session: PersonaPlexSession,
    action_id: str,
    status: str,  # "confirmed" | "cancelled"
    *,
    root: Optional[Path] = None,
) -> Optional[PendingAction]:
    for action in session.pending_actions:
        if action.action_id == action_id:
            action.status = status
            save_session(session, root=root)
            return action
    return None


def clear_resolved_actions(
    session: PersonaPlexSession,
    *,
    root: Optional[Path] = None,
) -> PersonaPlexSession:
    session.pending_actions = [a for a in session.pending_actions if a.status == "pending"]
    return save_session(session, root=root)


def build_conversation_messages(session: PersonaPlexSession) -> list[dict[str, str]]:
    """Build the LLM message list from session state."""
    messages: list[dict[str, str]] = []
    if session.rolling_summary:
        messages.append({
            "role": "system",
            "content": f"[Conversation history summary]\n{session.rolling_summary}",
        })
    for turn in session.turns:
        messages.append({"role": turn.role, "content": turn.content})
    return messages
