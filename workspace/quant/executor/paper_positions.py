#!/usr/bin/env python3
"""Paper position accounting — entry/exit tracking for real proof metrics.

Tracks open paper positions per strategy/symbol. Only closed trades
produce realized PnL that feeds into proof_tracker.record_fill().

Entry fill: opens or adds to position (no proof metric yet).
Exit fill: closes or reduces position (produces realized PnL).

Exit detection: a fill whose side is opposite to the open position.
  - open long + fill short → close long → PnL = (exit - entry) * qty
  - open short + fill long → close short → PnL = (entry - exit) * qty
  - fill same side as open → adds to position (updates avg entry)

This is paper-only. Live positions are tracked by the real broker.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class PaperPosition:
    strategy_id: str
    symbol: str
    side: str               # "long" or "short"
    quantity: int
    avg_entry_price: float
    opened_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PaperPosition":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ClosedTrade:
    """Result of closing a paper position."""
    strategy_id: str
    symbol: str
    side: str               # side of the original position
    quantity: int
    entry_price: float
    exit_price: float
    realized_pnl: float
    is_winner: bool
    closed_at: str = ""


def _positions_dir(root: Path) -> Path:
    d = root / "workspace" / "quant" / "executor" / "proof_positions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pos_path(root: Path, strategy_id: str, symbol: str) -> Path:
    return _positions_dir(root) / f"{strategy_id}_{symbol}.json"


def get_open_position(root: Path, strategy_id: str, symbol: str) -> Optional[PaperPosition]:
    """Get the current open paper position for a strategy/symbol, or None."""
    path = _pos_path(root, strategy_id, symbol)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pos = PaperPosition.from_dict(data)
        if pos.quantity <= 0:
            return None
        return pos
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def _save_position(root: Path, pos: PaperPosition):
    path = _pos_path(root, pos.strategy_id, pos.symbol)
    path.write_text(json.dumps(pos.to_dict(), indent=2) + "\n", encoding="utf-8")


def _clear_position(root: Path, strategy_id: str, symbol: str):
    path = _pos_path(root, strategy_id, symbol)
    if path.exists():
        path.unlink()


def _opposite_side(side: str) -> str:
    return "short" if side == "long" else "long"


def process_fill(
    root: Path,
    strategy_id: str,
    symbol: str,
    side: str,
    fill_price: float,
    quantity: int = 1,
) -> Optional[ClosedTrade]:
    """Process a paper fill against position state.

    Returns a ClosedTrade if this fill closes/reduces a position.
    Returns None if this fill opens or adds to a position (no realized PnL).
    """
    pos = get_open_position(root, strategy_id, symbol)

    if pos is None:
        # No open position — this fill opens one
        new_pos = PaperPosition(
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            avg_entry_price=fill_price,
            opened_at=datetime.now(timezone.utc).isoformat(),
        )
        _save_position(root, new_pos)
        return None  # Entry — no realized PnL

    if pos.side == side:
        # Same side — add to position, update avg entry
        total_qty = pos.quantity + quantity
        pos.avg_entry_price = round(
            (pos.avg_entry_price * pos.quantity + fill_price * quantity) / total_qty, 2
        )
        pos.quantity = total_qty
        _save_position(root, pos)
        return None  # Adding — no realized PnL

    # Opposite side — closing/reducing the position
    close_qty = min(quantity, pos.quantity)

    if pos.side == "long":
        pnl = round((fill_price - pos.avg_entry_price) * close_qty, 2)
    else:  # short
        pnl = round((pos.avg_entry_price - fill_price) * close_qty, 2)

    trade = ClosedTrade(
        strategy_id=strategy_id,
        symbol=symbol,
        side=pos.side,
        quantity=close_qty,
        entry_price=pos.avg_entry_price,
        exit_price=fill_price,
        realized_pnl=pnl,
        is_winner=pnl > 0,
        closed_at=datetime.now(timezone.utc).isoformat(),
    )

    remaining = pos.quantity - close_qty
    if remaining <= 0:
        _clear_position(root, strategy_id, symbol)
    else:
        pos.quantity = remaining
        _save_position(root, pos)

    # If the closing fill was larger than the open position, open a new position
    # in the fill's direction for the remainder
    leftover = quantity - close_qty
    if leftover > 0:
        new_pos = PaperPosition(
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            quantity=leftover,
            avg_entry_price=fill_price,
            opened_at=datetime.now(timezone.utc).isoformat(),
        )
        _save_position(root, new_pos)

    return trade
