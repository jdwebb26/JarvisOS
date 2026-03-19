#!/usr/bin/env python3
"""Quant Lanes — Strategy Registry with locking and transition validation.

Single source of truth for strategy lifecycle state.
Per QUANT_LANES_OPERATING_SPEC v3.5.1 §4.

Hard contracts:
  1. Single writer function — all transitions through transition_strategy()
  2. Append-only state history
  3. File locking mandatory (5s timeout)
  4. Transition validation against authority table
  5. Stale-state guard
  6. Idempotent for exact duplicates
  7. Failure logging
"""
from __future__ import annotations

import fcntl
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Lifecycle states
# ---------------------------------------------------------------------------

LIFECYCLE_STATES = {
    "IDEA", "CANDIDATE", "VALIDATING", "REJECTED",
    "PROMOTED", "PAPER_QUEUED", "PAPER_ACTIVE", "PAPER_REVIEW",
    "PAPER_KILLED", "ITERATE",
    "LIVE_QUEUED", "LIVE_ACTIVE", "LIVE_REVIEW",
    "LIVE_KILLED", "RETIRED",
}

TERMINAL_STATES = {"REJECTED", "PAPER_KILLED", "LIVE_KILLED", "RETIRED"}

# Transition authority table — (from_state, to_state) → set of allowed actors
TRANSITION_AUTHORITY: dict[tuple[str, str], set[str]] = {
    # Discovery
    (None, "IDEA"):               {"atlas", "kitt"},
    ("IDEA", "CANDIDATE"):        {"atlas"},
    ("CANDIDATE", "VALIDATING"):  {"sigma"},
    # Validation outcomes
    ("VALIDATING", "REJECTED"):   {"sigma"},
    ("VALIDATING", "PROMOTED"):   {"sigma"},
    # Paper trade path
    ("PROMOTED", "PAPER_QUEUED"): {"kitt"},
    ("PAPER_QUEUED", "PAPER_ACTIVE"): {"executor"},
    ("PAPER_ACTIVE", "PAPER_REVIEW"): {"sigma", "kitt"},
    # Paper review outcomes
    ("PAPER_REVIEW", "LIVE_QUEUED"):  {"kitt"},
    ("PAPER_REVIEW", "ITERATE"):      {"sigma"},
    ("PAPER_REVIEW", "PAPER_KILLED"): {"kitt", "operator"},
    # Iterate loops back
    ("ITERATE", "CANDIDATE"):    {"atlas", "sigma"},
    # Live trade path
    ("LIVE_QUEUED", "LIVE_ACTIVE"):  {"executor"},
    ("LIVE_ACTIVE", "LIVE_REVIEW"):  {"sigma", "kitt"},
    ("LIVE_REVIEW", "LIVE_ACTIVE"):  {"sigma", "kitt"},
    ("LIVE_REVIEW", "LIVE_KILLED"):  {"kitt", "operator"},
    ("LIVE_ACTIVE", "LIVE_KILLED"):  {"operator", "kill_switch"},
    # Retirement (from any non-terminal)
    # Handled specially — kitt, sigma, or operator can retire
}

RETIREMENT_ACTORS = {"kitt", "sigma", "operator"}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StateHistoryEntry:
    state: str
    at: str
    by: str
    approval_ref: Optional[str] = None
    note: Optional[str] = None
    retirement_reason: Optional[str] = None
    iteration_guidance: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "StateHistoryEntry":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class StrategyEntry:
    strategy_id: str
    lifecycle_state: str
    state_history: list[StateHistoryEntry] = field(default_factory=list)
    parent_id: Optional[str] = None
    lineage_note: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "strategy_id": self.strategy_id,
            "lifecycle_state": self.lifecycle_state,
            "state_history": [e.to_dict() for e in self.state_history],
        }
        if self.parent_id:
            d["parent_id"] = self.parent_id
        if self.lineage_note:
            d["lineage_note"] = self.lineage_note
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "StrategyEntry":
        history = [StateHistoryEntry.from_dict(h) for h in data.get("state_history", [])]
        return cls(
            strategy_id=data["strategy_id"],
            lifecycle_state=data["lifecycle_state"],
            state_history=history,
            parent_id=data.get("parent_id"),
            lineage_note=data.get("lineage_note"),
        )


# ---------------------------------------------------------------------------
# Registry file operations
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _registry_path(root: Path) -> Path:
    p = root / "workspace" / "quant" / "shared" / "registries" / "strategies.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _failure_log_path(root: Path) -> Path:
    p = root / "workspace" / "quant" / "shared" / "registries" / "transition_failures.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _log_failure(root: Path, strategy_id: str, from_state: str, to_state: str, actor: str, reason: str):
    """Log a failed transition attempt."""
    entry = {
        "strategy_id": strategy_id,
        "from_state": from_state,
        "to_state": to_state,
        "actor": actor,
        "reason": reason,
        "at": _now_iso(),
    }
    with open(_failure_log_path(root), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _acquire_lock(fp, timeout: float = 5.0):
    """Acquire an exclusive file lock with timeout."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Could not acquire registry lock within {timeout}s")
            time.sleep(0.05)


def load_all_strategies(root: Path) -> dict[str, StrategyEntry]:
    """Load all strategies from the registry file. Returns {strategy_id: StrategyEntry}."""
    path = _registry_path(root)
    if not path.exists():
        return {}
    strategies = {}
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        entry = StrategyEntry.from_dict(json.loads(line))
        strategies[entry.strategy_id] = entry
    return strategies


def get_strategy(root: Path, strategy_id: str) -> Optional[StrategyEntry]:
    """Load a single strategy by ID."""
    all_strats = load_all_strategies(root)
    return all_strats.get(strategy_id)


def _rewrite_registry(root: Path, strategies: dict[str, StrategyEntry]):
    """Rewrite the full registry file (under lock)."""
    path = _registry_path(root)
    lines = [json.dumps(s.to_dict()) + "\n" for s in strategies.values()]
    path.write_text("".join(lines), encoding="utf-8")


def create_strategy(
    root: Path,
    strategy_id: str,
    initial_state: str = "IDEA",
    actor: str = "atlas",
    parent_id: Optional[str] = None,
    lineage_note: Optional[str] = None,
    note: Optional[str] = None,
) -> StrategyEntry:
    """Create a new strategy entry. Validates actor can create IDEA."""
    if initial_state != "IDEA":
        raise ValueError(f"New strategies must start as IDEA, got {initial_state}")
    if actor not in TRANSITION_AUTHORITY.get((None, "IDEA"), set()):
        raise ValueError(f"Actor {actor!r} cannot create IDEA")

    path = _registry_path(root)
    with open(path, "a+", encoding="utf-8") as f:
        _acquire_lock(f)
        # Check for duplicates
        f.seek(0)
        for line in f:
            if not line.strip():
                continue
            existing = json.loads(line)
            if existing["strategy_id"] == strategy_id:
                raise ValueError(f"Strategy {strategy_id} already exists")

        entry = StrategyEntry(
            strategy_id=strategy_id,
            lifecycle_state="IDEA",
            state_history=[StateHistoryEntry(state="IDEA", at=_now_iso(), by=actor, note=note)],
            parent_id=parent_id,
            lineage_note=lineage_note,
        )
        f.write(json.dumps(entry.to_dict()) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)

    return entry


def transition_strategy(
    root: Path,
    strategy_id: str,
    to_state: str,
    actor: str,
    approval_ref: Optional[str] = None,
    note: Optional[str] = None,
    retirement_reason: Optional[str] = None,
    iteration_guidance: Optional[str] = None,
) -> StrategyEntry:
    """Transition a strategy to a new state. Validates authority and current state.

    This is the ONLY function that should modify strategy state.
    """
    if to_state not in LIFECYCLE_STATES:
        raise ValueError(f"Invalid target state: {to_state!r}")

    path = _registry_path(root)
    with open(path, "a+", encoding="utf-8") as f:
        _acquire_lock(f)
        try:
            # Read current state
            f.seek(0)
            strategies = {}
            for line in f:
                if not line.strip():
                    continue
                s = StrategyEntry.from_dict(json.loads(line))
                strategies[s.strategy_id] = s

            if strategy_id not in strategies:
                _log_failure(root, strategy_id, "N/A", to_state, actor, "strategy not found")
                raise ValueError(f"Strategy {strategy_id} not found")

            current = strategies[strategy_id]
            from_state = current.lifecycle_state

            # Terminal state guard
            if from_state in TERMINAL_STATES:
                _log_failure(root, strategy_id, from_state, to_state, actor, "strategy in terminal state")
                raise ValueError(f"Strategy {strategy_id} is in terminal state {from_state}")

            # Idempotent check
            if current.state_history and current.state_history[-1].state == to_state and current.state_history[-1].by == actor:
                return current

            # Retirement special case
            if to_state == "RETIRED":
                if actor not in RETIREMENT_ACTORS:
                    _log_failure(root, strategy_id, from_state, to_state, actor, "not authorized for retirement")
                    raise ValueError(f"Actor {actor!r} cannot retire strategies")
                if not retirement_reason:
                    _log_failure(root, strategy_id, from_state, to_state, actor, "retirement_reason required")
                    raise ValueError("retirement_reason is required for RETIRED transition")
            else:
                # Standard transition check
                key = (from_state, to_state)
                allowed = TRANSITION_AUTHORITY.get(key)
                if allowed is None:
                    _log_failure(root, strategy_id, from_state, to_state, actor, f"transition {from_state}→{to_state} not defined")
                    raise ValueError(f"Transition {from_state} → {to_state} is not defined")
                if actor not in allowed:
                    _log_failure(root, strategy_id, from_state, to_state, actor, f"actor not authorized for {from_state}→{to_state}")
                    raise ValueError(f"Actor {actor!r} cannot transition {from_state} → {to_state}")

            # Paper/Live queue require approval_ref
            if to_state in {"PAPER_QUEUED", "LIVE_QUEUED"} and not approval_ref:
                _log_failure(root, strategy_id, from_state, to_state, actor, "approval_ref required")
                raise ValueError(f"approval_ref is required for {to_state} transition")

            # Apply transition
            history_entry = StateHistoryEntry(
                state=to_state,
                at=_now_iso(),
                by=actor,
                approval_ref=approval_ref,
                note=note,
                retirement_reason=retirement_reason,
                iteration_guidance=iteration_guidance,
            )
            current.lifecycle_state = to_state
            current.state_history.append(history_entry)

            # Rewrite file
            _rewrite_registry(root, strategies)

        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

    return current


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_lineage(root: Path, strategy_id: str) -> list[StrategyEntry]:
    """Walk parent_id chain from oldest ancestor to this strategy.

    Returns [] if strategy not found.
    """
    all_strats = load_all_strategies(root)
    if strategy_id not in all_strats:
        return []

    chain = []
    current = strategy_id
    seen = set()
    while current and current not in seen:
        seen.add(current)
        entry = all_strats.get(current)
        if entry is None:
            break
        chain.append(entry)
        current = entry.parent_id

    chain.reverse()
    return chain


def get_children(root: Path, parent_id: str) -> list[StrategyEntry]:
    """Find all strategies whose parent_id matches."""
    all_strats = load_all_strategies(root)
    return [s for s in all_strats.values() if s.parent_id == parent_id]


def get_strategies_by_state(root: Path, state: str) -> list[StrategyEntry]:
    """Find all strategies in a given lifecycle state."""
    all_strats = load_all_strategies(root)
    return [s for s in all_strats.values() if s.lifecycle_state == state]
