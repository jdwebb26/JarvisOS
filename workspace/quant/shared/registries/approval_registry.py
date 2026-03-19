#!/usr/bin/env python3
"""Quant Lanes — Approval Registry.

Structured approval objects per QUANT_LANES_OPERATING_SPEC v3.5.1 §5.
Executor validates against these during pre-flight.

Rules:
  - Stored in approvals.jsonl (append-only)
  - Revocation adds a new entry, does not delete
  - Expired approvals are invalid
  - Executor must validate the full object, not just check existence
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_approval_ref(strategy_id: str, ts: str) -> str:
    """Generate a short, review-poller-compatible approval ref.

    Format: qpt_<12-char-hex>  (matches the review poller's ID pattern)
    """
    raw = f"{strategy_id}{ts}"
    return "qpt_" + hashlib.sha256(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ApprovedActions:
    execution_mode: str  # "paper" or "live"
    symbols: list[str] = field(default_factory=list)
    max_position_size: int = 1
    max_loss_per_trade: float = 500.0
    max_total_drawdown: float = 2000.0
    slippage_tolerance: float = 0.05
    valid_from: str = ""
    valid_until: str = ""
    broker_target: str = "paper_adapter"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ApprovedActions":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ApprovalObject:
    approval_ref: str
    created_at: str
    approved_by: str  # Always "operator" for paper/live
    approval_type: str  # "paper_trade" or "live_trade"
    strategy_id: str
    approved_actions: ApprovedActions = field(default_factory=lambda: ApprovedActions(execution_mode="paper"))
    conditions: str = ""
    revoked: bool = False
    revoked_at: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "ApprovalObject":
        actions_data = data.get("approved_actions", {})
        actions = ApprovedActions.from_dict(actions_data) if actions_data else ApprovedActions(execution_mode="paper")
        return cls(
            approval_ref=data["approval_ref"],
            created_at=data["created_at"],
            approved_by=data["approved_by"],
            approval_type=data["approval_type"],
            strategy_id=data["strategy_id"],
            approved_actions=actions,
            conditions=data.get("conditions", ""),
            revoked=data.get("revoked", False),
            revoked_at=data.get("revoked_at"),
        )

    def is_valid(self) -> tuple[bool, str]:
        """Check if this approval is currently valid. Returns (valid, reason)."""
        if self.revoked:
            return False, "approval revoked"
        now = datetime.now(timezone.utc)
        if self.approved_actions.valid_until:
            try:
                expiry = datetime.fromisoformat(self.approved_actions.valid_until)
                if now > expiry:
                    return False, "approval expired"
            except ValueError:
                pass
        if self.approved_actions.valid_from:
            try:
                start = datetime.fromisoformat(self.approved_actions.valid_from)
                if now < start:
                    return False, "approval not yet active"
            except ValueError:
                pass
        return True, "valid"


# ---------------------------------------------------------------------------
# Registry operations
# ---------------------------------------------------------------------------

def _registry_path(root: Path) -> Path:
    p = root / "workspace" / "quant" / "shared" / "registries" / "approvals.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _acquire_lock(fp, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Could not acquire approvals lock within {timeout}s")
            time.sleep(0.05)


def create_approval(
    root: Path,
    strategy_id: str,
    approval_type: str,
    approved_actions: ApprovedActions,
    conditions: str = "",
    approved_by: str = "operator",
) -> ApprovalObject:
    """Create a new approval object and append to registry."""
    if approval_type not in {"paper_trade", "live_trade"}:
        raise ValueError(f"approval_type must be paper_trade or live_trade, got {approval_type!r}")
    if approved_actions.execution_mode not in {"paper", "live"}:
        raise ValueError(f"execution_mode must be paper or live, got {approved_actions.execution_mode!r}")

    ts = _now_iso()

    approval = ApprovalObject(
        approval_ref=_make_approval_ref(strategy_id, ts),
        created_at=ts,
        approved_by=approved_by,
        approval_type=approval_type,
        strategy_id=strategy_id,
        approved_actions=approved_actions,
        conditions=conditions,
    )

    path = _registry_path(root)
    with open(path, "a", encoding="utf-8") as f:
        _acquire_lock(f)
        f.write(json.dumps(approval.to_dict()) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)

    return approval


def load_all_approvals(root: Path) -> list[ApprovalObject]:
    """Load all approval objects from the registry."""
    path = _registry_path(root)
    if not path.exists():
        return []
    approvals = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        approvals.append(ApprovalObject.from_dict(json.loads(line)))
    return approvals


def get_approval(root: Path, approval_ref: str) -> Optional[ApprovalObject]:
    """Get a specific approval by reference."""
    for a in load_all_approvals(root):
        if a.approval_ref == approval_ref:
            return a
    return None


def validate_approval_for_execution(
    root: Path,
    approval_ref: str,
    strategy_id: str,
    execution_mode: str,
    symbol: str,
) -> tuple[bool, str]:
    """Full pre-flight approval validation per spec §6 Executor pre-flight checks.

    Returns (valid, reason).
    """
    approval = get_approval(root, approval_ref)
    if approval is None:
        return False, "invalid_approval: approval_ref not found"

    valid, reason = approval.is_valid()
    if not valid:
        return False, f"{reason}"

    if approval.strategy_id != strategy_id:
        return False, f"strategy_id mismatch: approval covers {approval.strategy_id}, got {strategy_id}"

    mode_map = {"paper_trade": "paper", "live_trade": "live"}
    expected_mode = mode_map.get(approval.approval_type, "")
    if execution_mode != expected_mode:
        return False, f"mode_mismatch: approval is {approval.approval_type}, execution_mode is {execution_mode}"

    if symbol not in approval.approved_actions.symbols:
        return False, f"symbol_not_approved: {symbol} not in {approval.approved_actions.symbols}"

    return True, "approved"


def revoke_approval(root: Path, approval_ref: str) -> Optional[ApprovalObject]:
    """Revoke an approval. Appends revocation entry (append-only)."""
    path = _registry_path(root)

    with open(path, "a+", encoding="utf-8") as f:
        _acquire_lock(f)
        f.seek(0)
        lines = f.readlines()

        updated = False
        new_lines = []
        revoked_obj = None
        for line in lines:
            if not line.strip():
                new_lines.append(line)
                continue
            obj = json.loads(line)
            if obj.get("approval_ref") == approval_ref and not obj.get("revoked"):
                obj["revoked"] = True
                obj["revoked_at"] = _now_iso()
                revoked_obj = ApprovalObject.from_dict(obj)
                updated = True
            new_lines.append(json.dumps(obj) + "\n")

        if updated:
            f.seek(0)
            f.truncate()
            f.writelines(new_lines)

        fcntl.flock(f, fcntl.LOCK_UN)

    return revoked_obj
