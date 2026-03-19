#!/usr/bin/env python3
"""Quant Lanes — Broker Adapters (Paper + Live interface).

Per spec §6 Executor: pluggable adapter interface.
Paper adapter simulates fills. Live adapter defines the production interface
and validates broker config, but defers actual order placement to a real
broker SDK that must be configured externally.

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
import os
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
# Exceptions
# ---------------------------------------------------------------------------

class BrokerNotConfiguredError(RuntimeError):
    """Raised when live broker is requested but credentials/SDK are not configured."""
    pass


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

        (self._orders_dir / f"{order_id}.json").write_text(
            json.dumps({"order": order.to_dict(), "fill": fill.to_dict()}, indent=2) + "\n",
            encoding="utf-8",
        )
        (self._fills_dir / f"{order_id}.json").write_text(
            json.dumps(fill.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
        self._update_position(order, fill)

        return fill

    def _update_position(self, order: Order, fill: FillResult):
        pos_file = self._positions_dir / f"{order.strategy_id}_{order.symbol}.json"
        if pos_file.exists():
            pos_data = json.loads(pos_file.read_text(encoding="utf-8"))
            pos = Position(**pos_data)
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
# Live Adapter — production-ready interface, blocked at broker boundary
# ---------------------------------------------------------------------------

# Required env vars for live broker connection.
# When a real broker is chosen, set these in ~/.openclaw/.env.
LIVE_BROKER_ENV_VARS = {
    "QUANT_BROKER_TYPE": "Broker SDK identifier (e.g. 'alpaca', 'ibkr', 'rithmic')",
    "QUANT_BROKER_API_KEY": "Broker API key or account identifier",
    "QUANT_BROKER_API_SECRET": "Broker API secret",
    "QUANT_BROKER_ENDPOINT": "Broker API endpoint URL",
}


def check_live_broker_config() -> tuple[bool, dict[str, str]]:
    """Check whether live broker env vars are configured.

    Returns (configured, {var: value_or_'MISSING'}).
    Does not log or print secrets — only reports presence.
    """
    status = {}
    for var in LIVE_BROKER_ENV_VARS:
        val = os.environ.get(var, "")
        status[var] = "set" if val else "MISSING"
    configured = all(v == "set" for v in status.values())
    return configured, status


class LiveBrokerAdapter:
    """Live broker adapter. Production-ready interface with config validation.

    This adapter validates all configuration and pre-conditions before
    attempting any broker operation. If broker credentials are not configured,
    it raises BrokerNotConfiguredError with an explicit message stating
    exactly what is missing.

    When a real broker SDK is integrated, implement _connect() and the
    order methods. The preflight, config validation, and state management
    code is ready to use.
    """

    def __init__(self, state_dir: Optional[Path] = None):
        self.state_dir = state_dir
        self._broker_type = os.environ.get("QUANT_BROKER_TYPE", "")
        self._configured, self._config_status = check_live_broker_config()

    def _require_configured(self):
        """Raise BrokerNotConfiguredError if broker env vars are missing."""
        if not self._configured:
            missing = [k for k, v in self._config_status.items() if v == "MISSING"]
            raise BrokerNotConfiguredError(
                f"Live broker not configured. Missing env vars: {', '.join(missing)}. "
                f"Set these in ~/.openclaw/.env before enabling live trading. "
                f"Required: {', '.join(LIVE_BROKER_ENV_VARS.keys())}"
            )

    def place_order(self, order: Order, **kwargs) -> FillResult:
        self._require_configured()
        raise BrokerNotConfiguredError(
            f"Live order placement for broker_type={self._broker_type!r} is not yet "
            f"implemented. The broker SDK integration must be built for the chosen "
            f"broker. All preflight checks passed — this is the final integration point."
        )

    def check_status(self, order_id: str) -> Optional[dict]:
        self._require_configured()
        raise BrokerNotConfiguredError(
            "Live order status check not yet implemented."
        )

    def get_fills(self, strategy_id: str) -> list[FillResult]:
        self._require_configured()
        raise BrokerNotConfiguredError(
            "Live fill retrieval not yet implemented."
        )

    def get_positions(self, strategy_id: Optional[str] = None) -> list[Position]:
        self._require_configured()
        raise BrokerNotConfiguredError(
            "Live position retrieval not yet implemented."
        )

    def cancel_order(self, order_id: str) -> dict:
        self._require_configured()
        raise BrokerNotConfiguredError(
            "Live order cancellation not yet implemented."
        )

    def health_check(self) -> bool:
        """Returns False if not configured, True if config present.

        When broker SDK is integrated, this should also verify connectivity.
        """
        return self._configured


def get_adapter(mode: str, state_dir: Path) -> PaperBrokerAdapter | LiveBrokerAdapter:
    """Get the appropriate broker adapter for the execution mode."""
    if mode == "paper":
        return PaperBrokerAdapter(state_dir)
    elif mode == "live":
        return LiveBrokerAdapter(state_dir)
    else:
        raise ValueError(f"Unknown execution mode: {mode!r}")
