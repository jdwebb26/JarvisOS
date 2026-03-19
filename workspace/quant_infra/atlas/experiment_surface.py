#!/usr/bin/env python3
"""Atlas Experiment Surface — experiment ingestion and preparation.

Receives structured experiment-ready packets from Fish/Kitt/upstream lanes
and prepares them for vectorbt-style exploration or custom experiment runs.

Usage:
    .venv/bin/python3 workspace/quant_infra/atlas/experiment_surface.py --submit <json_file>
    .venv/bin/python3 workspace/quant_infra/atlas/experiment_surface.py --pending
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from warehouse.loader import get_connection, insert_experiment
from packets.writer import write_packet, read_packet

QUANT_INFRA = Path(__file__).resolve().parent.parent
WAREHOUSE_PATH = QUANT_INFRA / "warehouse" / "quant.duckdb"
EXPERIMENTS_DIR = QUANT_INFRA / "experiments" / "atlas"


def submit_experiment(
    experiment_type: str,
    hypothesis: str,
    parameters: dict,
    symbol: str = "NQ",
    timeframe: str | None = None,
    data_range_start: str | None = None,
    data_range_end: str | None = None,
) -> str:
    """Submit a new experiment to the Atlas queue.

    Returns experiment_id.
    """
    exp_id = f"aex-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    con = get_connection(WAREHOUSE_PATH)
    try:
        insert_experiment(con, {
            "experiment_id": exp_id,
            "submitted_at": now,
            "experiment_type": experiment_type,
            "symbol": symbol,
            "timeframe": timeframe,
            "hypothesis": hypothesis,
            "parameters": parameters,
            "data_range_start": data_range_start,
            "data_range_end": data_range_end,
        })
    finally:
        con.close()

    # Save experiment file
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    exp_file = EXPERIMENTS_DIR / f"{exp_id}.json"
    exp_file.write_text(json.dumps({
        "experiment_id": exp_id,
        "submitted_at": now,
        "experiment_type": experiment_type,
        "hypothesis": hypothesis,
        "parameters": parameters,
        "symbol": symbol,
        "timeframe": timeframe,
        "status": "pending",
    }, indent=2) + "\n")

    # Update atlas packet
    _write_atlas_packet(exp_id, experiment_type, hypothesis)

    print(f"[atlas] Submitted experiment {exp_id}: {hypothesis}")
    return exp_id


def get_pending_experiments() -> list[dict]:
    """Get all pending experiments."""
    con = get_connection(WAREHOUSE_PATH)
    try:
        rows = con.execute("""
            SELECT experiment_id, submitted_at, experiment_type, hypothesis, parameters_json
            FROM atlas_experiment_inputs WHERE status = 'pending'
            ORDER BY submitted_at DESC
        """).fetchall()
        return [
            {
                "experiment_id": r[0], "submitted_at": str(r[1]),
                "type": r[2], "hypothesis": r[3], "parameters": r[4],
            }
            for r in rows
        ]
    finally:
        con.close()


def create_vectorbt_ready_data(experiment_id: str) -> dict | None:
    """Prepare data in a format suitable for vectorbt consumption.

    Returns a dict with OHLCV arrays and experiment parameters,
    or None if the experiment or data is not available.
    """
    con = get_connection(WAREHOUSE_PATH)
    try:
        exp = con.execute(
            "SELECT * FROM atlas_experiment_inputs WHERE experiment_id = ?",
            [experiment_id]
        ).fetchone()
        if not exp:
            return None

        # Pull OHLCV data
        rows = con.execute("""
            SELECT bar_date, open, high, low, close, volume
            FROM ohlcv_daily WHERE symbol = 'NQ'
            ORDER BY bar_date
        """).fetchall()

        return {
            "experiment_id": experiment_id,
            "ohlcv": {
                "dates": [str(r[0]) for r in rows],
                "open": [r[1] for r in rows],
                "high": [r[2] for r in rows],
                "low": [r[3] for r in rows],
                "close": [r[4] for r in rows],
                "volume": [r[5] for r in rows],
            },
            "parameters": json.loads(exp[7]) if exp[7] else {},
            "note": "vectorbt-ready: import as pd.DataFrame from ohlcv dict",
        }
    finally:
        con.close()


def _write_atlas_packet(exp_id: str, exp_type: str, hypothesis: str) -> None:
    """Write atlas experiment packet."""
    pending = get_pending_experiments()
    write_packet(
        lane="atlas",
        packet_type="experiment",
        summary=f"Atlas: {len(pending)} pending experiments | latest: {exp_id}",
        data={
            "latest_experiment": {"id": exp_id, "type": exp_type, "hypothesis": hypothesis},
            "pending_count": len(pending),
            "pending_ids": [p["experiment_id"] for p in pending[:10]],
        },
        upstream=["fish_scenario", "kitt_quant"],
        source_module="atlas.experiment_surface",
        confidence=0.5,
    )


def main():
    parser = argparse.ArgumentParser(description="Atlas Experiment Surface")
    parser.add_argument("--submit", type=str, metavar="JSON_FILE", help="Submit experiment from JSON file")
    parser.add_argument("--pending", action="store_true", help="List pending experiments")
    parser.add_argument("--vectorbt-data", type=str, metavar="EXP_ID", help="Export vectorbt-ready data")

    args = parser.parse_args()

    if args.submit:
        data = json.loads(Path(args.submit).read_text())
        submit_experiment(
            experiment_type=data.get("type", "custom"),
            hypothesis=data.get("hypothesis", ""),
            parameters=data.get("parameters", {}),
            symbol=data.get("symbol", "NQ"),
        )
    elif args.pending:
        pending = get_pending_experiments()
        print(f"\n=== ATLAS PENDING EXPERIMENTS ({len(pending)}) ===\n")
        for p in pending:
            print(f"  {p['experiment_id']}: [{p['type']}] {p['hypothesis']}")
        print()
    elif args.vectorbt_data:
        data = create_vectorbt_ready_data(args.vectorbt_data)
        if data:
            print(json.dumps(data, indent=2, default=str))
        else:
            print(f"Experiment {args.vectorbt_data} not found")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
