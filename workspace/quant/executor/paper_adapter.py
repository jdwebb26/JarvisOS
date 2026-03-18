#!/usr/bin/env python3
"""Quant Lanes — Paper Trade Broker Adapter.

Per spec §6 Executor: pluggable adapter interface.
This is the paper adapter — simulates order placement against paper environment.
Live adapter is stubbed behind the same interface.

Interface methods:
  - place_order(order) -> fill_result
  - check_status(order_id) -> status
  - get_fills(strategy_id) -> list[fill]
  - get_positions(strategy_id) -> list[position]
  - cancel_order(order_id) -> cancel_result
  - health_check() -> bool
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import hashlib


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_id(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Order:
    strategy_id: str
    symbol: str
    side: str  # "long" or "short"
    order_type: str  # "market", "limit", "stop"
    quantity: int = 1
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    approval_ref: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class FillResult:
    order_id: str
    strategy_id: str
    symbol: str
    side: str
    quantity: int
    fill_price: float
    slippage: float
    status: str  # "filled", "partial", "rejected"
    filled_at: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Position:
    strategy_id: str
    symbol: str
    side: str
    quantity: int
    avg_entry_price: float
    unrealized_pnl: float = 0.0
    opened_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Paper Adapter
# ---------------------------------------------------------------------------

class PaperBrokerAdapter:
    """Simulated broker for paper trading. All fills are synthetic."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self._orders_dir = state_dir / "paper_orders"
        self._fills_dir = state_dir / "paper_fills"
        self._positions_dir = state_dir / "paper_positions"
        for d in [self._orders_dir, self._fills_dir, self._positions_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def place_order(self, order: Order, simulated_price: float = 18250.0) -> FillResult:
        """Place a paper order. Immediately fills at simulated_price with small random slippage."""
        import random
        order_id = f"paper-{_short_id(f'{order.strategy_id}{order.symbol}{_now_iso()}')}"

        # Simulate fill with small slippage
        slippage = round(random.uniform(-0.03, 0.05), 4)
        fill_price = round(simulated_price + (simulated_price * slippage / 100), 2)

        fill = FillResult(
            order_id=order_id,
            strategy_id=order.strategy_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            fill_price=fill_price,
            slippage=slippage,
            status="filled",
            filled_at=_now_iso(),
        )

        # Persist
        (self._orders_dir / f"{order_id}.json").write_text(
            json.dumps({"order": order.to_dict(), "fill": fill.to_dict()}, indent=2) + "\n",
            encoding="utf-8",
        )
        (self._fills_dir / f"{order_id}.json").write_text(
            json.dumps(fill.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )

        # Update position
        self._update_position(order, fill)

        return fill

    def _update_position(self, order: Order, fill: FillResult):
        pos_file = self._positions_dir / f"{order.strategy_id}_{order.symbol}.json"
        if pos_file.exists():
            pos_data = json.loads(pos_file.read_text(encoding="utf-8"))
            pos = Position(**pos_data)
            # Simple update: add to position
            pos.quantity += fill.quantity
            pos.avg_entry_price = round(
                (pos.avg_entry_price + fill.fill_price) / 2, 2
            )
        else:
            pos = Position(
                strategy_id=order.strategy_id,
                symbol=order.symbol,
                side=order.side,
                quantity=fill.quantity,
                avg_entry_price=fill.fill_price,
                opened_at=fill.filled_at,
            )
        pos_file.write_text(json.dumps(pos.to_dict(), indent=2) + "\n", encoding="utf-8")

    def check_status(self, order_id: str) -> Optional[dict]:
        path = self._orders_dir / f"{order_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get_fills(self, strategy_id: str) -> list[FillResult]:
        fills = []
        for f in sorted(self._fills_dir.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("strategy_id") == strategy_id:
                fills.append(FillResult(**data))
        return fills

    def get_positions(self, strategy_id: Optional[str] = None) -> list[Position]:
        positions = []
        for f in sorted(self._positions_dir.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            if strategy_id is None or data.get("strategy_id") == strategy_id:
                positions.append(Position(**data))
        return positions

    def cancel_order(self, order_id: str) -> dict:
        path = self._orders_dir / f"{order_id}.json"
        if not path.exists():
            return {"status": "not_found", "order_id": order_id}
        data = json.loads(path.read_text(encoding="utf-8"))
        data["fill"]["status"] = "cancelled"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return {"status": "cancelled", "order_id": order_id}

    def health_check(self) -> bool:
        """Paper adapter is always healthy."""
        return True


# ---------------------------------------------------------------------------
# Live Adapter (stub)
# ---------------------------------------------------------------------------

class LiveBrokerAdapter:
    """Live broker adapter stub. All methods raise NotImplementedError.

    Per spec: stubbed behind the same interface. Live methods throw
    'not implemented' until live trading is explicitly built and tested.
    """

    def place_order(self, order: Order, **kwargs) -> FillResult:
        raise NotImplementedError("Live broker adapter not implemented. Paper trade path must be proven first.")

    def check_status(self, order_id: str) -> Optional[dict]:
        raise NotImplementedError("Live broker adapter not implemented.")

    def get_fills(self, strategy_id: str) -> list[FillResult]:
        raise NotImplementedError("Live broker adapter not implemented.")

    def get_positions(self, strategy_id: Optional[str] = None) -> list[Position]:
        raise NotImplementedError("Live broker adapter not implemented.")

    def cancel_order(self, order_id: str) -> dict:
        raise NotImplementedError("Live broker adapter not implemented.")

    def health_check(self) -> bool:
        return False


def get_adapter(mode: str, state_dir: Path) -> PaperBrokerAdapter | LiveBrokerAdapter:
    """Get the appropriate broker adapter for the execution mode."""
    if mode == "paper":
        return PaperBrokerAdapter(state_dir)
    elif mode == "live":
        return LiveBrokerAdapter()
    else:
        raise ValueError(f"Unknown execution mode: {mode!r}")
