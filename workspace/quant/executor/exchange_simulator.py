#!/usr/bin/env python3
"""Simulated Exchange — realistic exchange behavior for testing live execution.

Unlike the PaperBrokerAdapter which fills instantly, this simulates:
  - Order queuing with configurable latency
  - Partial fills based on simulated liquidity
  - Order rejections (margin, risk, connectivity)
  - Slippage based on order size relative to simulated book depth
  - Fill status tracking (filled, partial, rejected)

This is the testing bridge between paper trading and live broker integration.
When a real broker SDK is integrated, it replaces this adapter.

Usage:
    adapter = SimulatedExchangeAdapter(state_dir)
    fill = adapter.place_order(order, market_price=24500.0)
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from workspace.quant.executor.paper_adapter import (
    FillResult, Order, Position, _now_iso, _short_id,
)


@dataclass
class ExchangeConfig:
    """Configurable exchange simulation parameters."""
    # Latency simulation (seconds)
    min_latency_ms: int = 5
    max_latency_ms: int = 50

    # Fill probability (0-1): chance of full fill vs partial/reject
    full_fill_rate: float = 0.85
    partial_fill_rate: float = 0.10
    # Remaining probability = rejection rate (0.05 default)

    # Slippage: basis points per contract
    base_slippage_bps: float = 1.0     # 1 basis point base
    size_impact_bps: float = 0.5       # additional bps per contract above 1
    volatility_mult: float = 1.0       # multiplied by VIX/20 if available

    # Partial fill: min/max fill ratio
    partial_fill_min: float = 0.3
    partial_fill_max: float = 0.8

    # Rejection reasons (weighted random selection)
    rejection_reasons: list[str] = field(default_factory=lambda: [
        "insufficient_margin",
        "risk_limit_exceeded",
        "market_closed",
        "price_away_from_market",
        "connectivity_timeout",
    ])

    # NQ tick size
    tick_size: float = 0.25


class SimulatedExchangeAdapter:
    """Simulated exchange with realistic fill behavior.

    Implements the same interface as PaperBrokerAdapter and LiveBrokerAdapter.
    """

    def __init__(self, state_dir: Path, config: ExchangeConfig | None = None):
        self.state_dir = state_dir
        self.config = config or ExchangeConfig()
        self._orders_dir = state_dir / "sim_orders"
        self._fills_dir = state_dir / "sim_fills"
        self._positions_dir = state_dir / "sim_positions"
        self._rejection_log = state_dir / "sim_rejections.jsonl"
        for d in [self._orders_dir, self._fills_dir, self._positions_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self._fill_count = 0
        self._reject_count = 0
        self._partial_count = 0

    def place_order(
        self,
        order: Order,
        market_price: float = 24500.0,
        vix: float = 20.0,
    ) -> FillResult:
        """Place an order on the simulated exchange.

        Args:
            order: The order to execute.
            market_price: Current market price for fill simulation.
            vix: Current VIX level (affects slippage).

        Returns:
            FillResult with status: 'filled', 'partial', or 'rejected'.
        """
        order_id = f"sim-{_short_id(f'{order.strategy_id}{order.symbol}{_now_iso()}{random.random()}')}"

        # Simulate latency
        latency_ms = random.randint(self.config.min_latency_ms, self.config.max_latency_ms)
        time.sleep(latency_ms / 1000.0)

        # Determine fill outcome
        roll = random.random()
        if roll < self.config.full_fill_rate:
            return self._full_fill(order, order_id, market_price, vix)
        elif roll < self.config.full_fill_rate + self.config.partial_fill_rate:
            return self._partial_fill(order, order_id, market_price, vix)
        else:
            return self._reject(order, order_id)

    def _compute_slippage(self, order: Order, market_price: float, vix: float) -> float:
        """Compute realistic slippage based on order size and volatility."""
        cfg = self.config
        vol_mult = (vix / 20.0) * cfg.volatility_mult
        size_impact = max(0, (order.quantity - 1)) * cfg.size_impact_bps
        total_bps = (cfg.base_slippage_bps + size_impact) * vol_mult

        # Random component: 0 to 2x the calculated slippage
        jitter = random.uniform(0.0, 2.0)
        slippage_pts = market_price * (total_bps * jitter / 10000.0)

        # Round to tick size
        slippage_pts = round(slippage_pts / cfg.tick_size) * cfg.tick_size

        # Direction: adverse slippage (buy higher, sell lower)
        if order.side == "long":
            return slippage_pts
        else:
            return -slippage_pts

    def _full_fill(self, order: Order, order_id: str, market_price: float, vix: float) -> FillResult:
        """Generate a full fill."""
        slippage = self._compute_slippage(order, market_price, vix)
        fill_price = round(market_price + slippage, 2)

        fill = FillResult(
            order_id=order_id,
            strategy_id=order.strategy_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            fill_price=fill_price,
            slippage=round(abs(slippage), 2),
            status="filled",
            filled_at=_now_iso(),
        )
        self._record_fill(order, fill)
        self._fill_count += 1
        return fill

    def _partial_fill(self, order: Order, order_id: str, market_price: float, vix: float) -> FillResult:
        """Generate a partial fill (only some contracts filled)."""
        fill_ratio = random.uniform(self.config.partial_fill_min, self.config.partial_fill_max)
        filled_qty = max(1, int(order.quantity * fill_ratio))

        slippage = self._compute_slippage(order, market_price, vix)
        fill_price = round(market_price + slippage, 2)

        fill = FillResult(
            order_id=order_id,
            strategy_id=order.strategy_id,
            symbol=order.symbol,
            side=order.side,
            quantity=filled_qty,
            fill_price=fill_price,
            slippage=round(abs(slippage), 2),
            status="partial",
            filled_at=_now_iso(),
        )
        self._record_fill(order, fill)
        self._partial_count += 1
        return fill

    def _reject(self, order: Order, order_id: str) -> FillResult:
        """Generate an order rejection."""
        reason = random.choice(self.config.rejection_reasons)
        fill = FillResult(
            order_id=order_id,
            strategy_id=order.strategy_id,
            symbol=order.symbol,
            side=order.side,
            quantity=0,
            fill_price=0.0,
            slippage=0.0,
            status="rejected",
            filled_at=_now_iso(),
            error=reason,
        )
        self._record_rejection(order, fill, reason)
        self._reject_count += 1
        return fill

    def _record_fill(self, order: Order, fill: FillResult) -> None:
        """Persist fill and update position."""
        (self._orders_dir / f"{fill.order_id}.json").write_text(
            json.dumps({"order": order.to_dict(), "fill": fill.to_dict()}, indent=2) + "\n",
            encoding="utf-8",
        )
        (self._fills_dir / f"{fill.order_id}.json").write_text(
            json.dumps(fill.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
        self._update_position(order, fill)

    def _record_rejection(self, order: Order, fill: FillResult, reason: str) -> None:
        """Log rejection for analysis."""
        record = {
            "order_id": fill.order_id,
            "timestamp": _now_iso(),
            "strategy_id": order.strategy_id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "reason": reason,
        }
        with open(self._rejection_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def _update_position(self, order: Order, fill: FillResult) -> None:
        """Update position state from fill."""
        pos_file = self._positions_dir / f"{order.strategy_id}_{order.symbol}.json"
        if pos_file.exists():
            pos_data = json.loads(pos_file.read_text(encoding="utf-8"))
            pos = Position(**pos_data)
            if pos.side == order.side:
                # Adding to position — weighted average entry
                total_qty = pos.quantity + fill.quantity
                pos.avg_entry_price = round(
                    (pos.avg_entry_price * pos.quantity + fill.fill_price * fill.quantity) / total_qty,
                    2,
                )
                pos.quantity = total_qty
            else:
                # Reducing/closing position
                if fill.quantity >= pos.quantity:
                    # Fully closed or reversed
                    pos_file.unlink(missing_ok=True)
                    return
                else:
                    pos.quantity -= fill.quantity
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

    def check_status(self, order_id: str) -> dict | None:
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

    def get_positions(self, strategy_id: str | None = None) -> list[Position]:
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
        return True

    def get_stats(self) -> dict:
        """Return execution stats for monitoring."""
        return {
            "fills": self._fill_count,
            "partials": self._partial_count,
            "rejections": self._reject_count,
            "fill_rate": round(
                self._fill_count / max(self._fill_count + self._reject_count, 1) * 100, 1
            ),
        }


def reconcile_positions(
    adapter_positions: list[Position],
    db_positions: list[dict],
) -> dict:
    """Reconcile broker/exchange positions with our database positions.

    Returns dict with:
      - matched: positions that agree
      - mismatched: positions where quantity or price differs
      - broker_only: positions in broker but not in DB
      - db_only: positions in DB but not in broker
    """
    adapter_by_key: dict[str, Position] = {}
    for p in adapter_positions:
        key = f"{p.strategy_id}_{p.symbol}"
        adapter_by_key[key] = p

    db_by_key: dict[str, dict] = {}
    for p in db_positions:
        sid = p.get("strategy_id") or p.get("position_id", "unknown")
        key = f"{sid}_{p.get('symbol', 'NQ')}"
        db_by_key[key] = p

    matched = []
    mismatched = []
    broker_only = []
    db_only = []

    all_keys = set(adapter_by_key.keys()) | set(db_by_key.keys())
    for key in sorted(all_keys):
        in_broker = key in adapter_by_key
        in_db = key in db_by_key

        if in_broker and in_db:
            bp = adapter_by_key[key]
            dp = db_by_key[key]
            db_qty = dp.get("quantity", 1)
            db_entry = dp.get("entry_price", 0)
            if bp.quantity == db_qty and abs(bp.avg_entry_price - db_entry) < 1.0:
                matched.append({"key": key, "quantity": bp.quantity, "entry": bp.avg_entry_price})
            else:
                mismatched.append({
                    "key": key,
                    "broker": {"quantity": bp.quantity, "entry": bp.avg_entry_price},
                    "db": {"quantity": db_qty, "entry": db_entry},
                })
        elif in_broker:
            bp = adapter_by_key[key]
            broker_only.append({"key": key, "quantity": bp.quantity, "entry": bp.avg_entry_price})
        else:
            dp = db_by_key[key]
            db_only.append({"key": key, "quantity": dp.get("quantity", 1), "entry": dp.get("entry_price", 0)})

    return {
        "matched": matched,
        "mismatched": mismatched,
        "broker_only": broker_only,
        "db_only": db_only,
        "reconciled": len(mismatched) == 0 and len(broker_only) == 0 and len(db_only) == 0,
    }
