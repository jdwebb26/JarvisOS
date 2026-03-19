"""DuckDB warehouse data loading utilities.

Used by lane modules to write records into the warehouse.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

THIS_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = THIS_DIR / "quant.duckdb"


def get_connection(db_path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Get a DuckDB connection to the warehouse."""
    path = db_path or DEFAULT_DB_PATH
    return duckdb.connect(str(path))


def insert_paper_position(con: duckdb.DuckDBPyConnection, position: dict) -> str:
    """Insert a new paper position. Returns position_id."""
    con.execute("""
        INSERT INTO kitt_paper_positions
        (position_id, opened_at, symbol, direction, quantity, entry_price,
         stop_loss, take_profit, status, reasoning, upstream_packet)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
    """, [
        position["position_id"],
        position["opened_at"],
        position.get("symbol", "NQ"),
        position["direction"],
        position.get("quantity", 1),
        position["entry_price"],
        position.get("stop_loss"),
        position.get("take_profit"),
        position.get("reasoning", ""),
        position.get("upstream_packet", ""),
    ])
    return position["position_id"]


def close_paper_position(
    con: duckdb.DuckDBPyConnection,
    position_id: str,
    exit_price: float,
    status: str = "closed",
) -> None:
    """Close an open paper position and calculate P&L."""
    row = con.execute(
        "SELECT direction, entry_price, quantity FROM kitt_paper_positions WHERE position_id = ?",
        [position_id]
    ).fetchone()
    if not row:
        raise ValueError(f"Position {position_id} not found")

    direction, entry_price, quantity = row
    if direction == "long":
        pnl = (exit_price - entry_price) * quantity * 20  # NQ point value = $20
    else:
        pnl = (entry_price - exit_price) * quantity * 20
    pnl_pct = ((exit_price - entry_price) / entry_price * 100) if direction == "long" else (
        (entry_price - exit_price) / entry_price * 100
    )

    con.execute("""
        UPDATE kitt_paper_positions
        SET closed_at = ?, exit_price = ?, status = ?, pnl = ?, pnl_pct = ?
        WHERE position_id = ?
    """, [
        datetime.now(timezone.utc).isoformat(),
        exit_price,
        status,
        round(pnl, 2),
        round(pnl_pct, 4),
        position_id,
    ])


def mark_position(con: duckdb.DuckDBPyConnection, position_id: str, mark_price: float) -> None:
    """Update mark-to-market price on an open position."""
    con.execute("""
        UPDATE kitt_paper_positions
        SET mark_price = ?, marked_at = ?
        WHERE position_id = ? AND status = 'open'
    """, [mark_price, datetime.now(timezone.utc).isoformat(), position_id])


def insert_trade_decision(con: duckdb.DuckDBPyConnection, decision: dict) -> str:
    """Insert a trade decision record. Returns decision_id."""
    con.execute("""
        INSERT INTO kitt_trade_decisions
        (decision_id, decided_at, action, symbol, reasoning, confidence,
         market_context, position_id, upstream_packets)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        decision["decision_id"],
        decision["decided_at"],
        decision["action"],
        decision.get("symbol", "NQ"),
        decision["reasoning"],
        decision.get("confidence"),
        decision.get("market_context"),
        decision.get("position_id"),
        decision.get("upstream_packets"),
    ])
    return decision["decision_id"]


def insert_scenario(con: duckdb.DuckDBPyConnection, scenario: dict) -> str:
    """Insert a Fish scenario. Returns scenario_id."""
    con.execute("""
        INSERT INTO fish_scenarios
        (scenario_id, created_at, scenario_type, symbol, description, probability,
         impact, target_price, invalidation_price, timeframe, kitt_position_id,
         upstream_packet)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        scenario["scenario_id"],
        scenario["created_at"],
        scenario["scenario_type"],
        scenario.get("symbol", "NQ"),
        scenario["description"],
        scenario.get("probability"),
        scenario.get("impact"),
        scenario.get("target_price"),
        scenario.get("invalidation_price"),
        scenario.get("timeframe", "1D"),
        scenario.get("kitt_position_id"),
        scenario.get("upstream_packet"),
    ])
    return scenario["scenario_id"]


def insert_experiment(con: duckdb.DuckDBPyConnection, experiment: dict) -> str:
    """Insert an Atlas experiment input. Returns experiment_id."""
    con.execute("""
        INSERT INTO atlas_experiment_inputs
        (experiment_id, submitted_at, experiment_type, symbol, timeframe,
         hypothesis, parameters_json, data_range_start, data_range_end)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        experiment["experiment_id"],
        experiment["submitted_at"],
        experiment["experiment_type"],
        experiment.get("symbol", "NQ"),
        experiment.get("timeframe"),
        experiment.get("hypothesis"),
        json.dumps(experiment.get("parameters", {})),
        experiment.get("data_range_start"),
        experiment.get("data_range_end"),
    ])
    return experiment["experiment_id"]


def insert_validation(con: duckdb.DuckDBPyConnection, validation: dict) -> str:
    """Insert a Sigma validation input. Returns validation_id."""
    con.execute("""
        INSERT INTO sigma_validation_inputs
        (validation_id, submitted_at, strategy_id, source_lane, symbol, timeframe,
         parameters_json, validation_status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
    """, [
        validation["validation_id"],
        validation["submitted_at"],
        validation["strategy_id"],
        validation.get("source_lane", "atlas"),
        validation.get("symbol", "NQ"),
        validation.get("timeframe"),
        json.dumps(validation.get("parameters", {})),
        validation.get("notes"),
    ])
    return validation["validation_id"]


def insert_token_usage(con: duckdb.DuckDBPyConnection, usage: dict) -> None:
    """Insert a token usage record for Jarvis observability."""
    con.execute("""
        INSERT INTO token_usage
        (usage_id, recorded_at, lane, model, prompt_tokens, completion_tokens,
         total_tokens, estimated_cost_usd, session_id, task_description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        usage["usage_id"],
        usage["recorded_at"],
        usage["lane"],
        usage.get("model"),
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        usage.get("total_tokens", 0),
        usage.get("estimated_cost_usd"),
        usage.get("session_id"),
        usage.get("task_description"),
    ])
