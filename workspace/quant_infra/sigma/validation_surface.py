#!/usr/bin/env python3
"""Sigma Validation Surface — validation ingestion and comparison.

Receives validation-ready packets from Atlas/Kitt and compares against
Strategy Factory outputs. Supports optional backtesting.py as secondary
reference harness.

Usage:
    .venv/bin/python3 workspace/quant_infra/sigma/validation_surface.py --submit <json_file>
    .venv/bin/python3 workspace/quant_infra/sigma/validation_surface.py --pending
    .venv/bin/python3 workspace/quant_infra/sigma/validation_surface.py --compare <validation_id>
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from warehouse.loader import get_connection, insert_validation
from packets.writer import write_packet

QUANT_INFRA = Path(__file__).resolve().parent.parent
WAREHOUSE_PATH = QUANT_INFRA / "warehouse" / "quant.duckdb"
EXPERIMENTS_DIR = QUANT_INFRA / "experiments" / "sigma"
STRATEGY_FACTORY = Path.home() / ".openclaw" / "workspace" / "strategy_factory"


def submit_validation(
    strategy_id: str,
    source_lane: str = "atlas",
    parameters: dict | None = None,
    symbol: str = "NQ",
    timeframe: str | None = None,
    notes: str = "",
) -> str:
    """Submit a strategy for validation. Returns validation_id."""
    val_id = f"svl-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    con = get_connection(WAREHOUSE_PATH)
    try:
        insert_validation(con, {
            "validation_id": val_id,
            "submitted_at": now,
            "strategy_id": strategy_id,
            "source_lane": source_lane,
            "symbol": symbol,
            "timeframe": timeframe,
            "parameters": parameters or {},
            "notes": notes,
        })
    finally:
        con.close()

    # Save validation file
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    val_file = EXPERIMENTS_DIR / f"{val_id}.json"
    val_file.write_text(json.dumps({
        "validation_id": val_id,
        "submitted_at": now,
        "strategy_id": strategy_id,
        "source_lane": source_lane,
        "parameters": parameters or {},
        "status": "pending",
        "notes": notes,
    }, indent=2) + "\n")

    _write_sigma_packet(val_id, strategy_id, source_lane)

    print(f"[sigma] Submitted validation {val_id} for strategy {strategy_id}")
    return val_id


def get_pending_validations() -> list[dict]:
    """Get all pending validations."""
    con = get_connection(WAREHOUSE_PATH)
    try:
        rows = con.execute("""
            SELECT validation_id, submitted_at, strategy_id, source_lane, notes
            FROM sigma_validation_inputs WHERE validation_status = 'pending'
            ORDER BY submitted_at DESC
        """).fetchall()
        return [
            {
                "validation_id": r[0], "submitted_at": str(r[1]),
                "strategy_id": r[2], "source_lane": r[3], "notes": r[4],
            }
            for r in rows
        ]
    finally:
        con.close()


def compare_with_factory(validation_id: str) -> dict:
    """Compare a validation against Strategy Factory results.

    Looks for matching strategy outputs in the factory artifacts directory.
    Returns comparison summary.
    """
    con = get_connection(WAREHOUSE_PATH)
    try:
        row = con.execute(
            "SELECT strategy_id, parameters_json FROM sigma_validation_inputs WHERE validation_id = ?",
            [validation_id]
        ).fetchone()
        if not row:
            return {"status": "not_found", "validation_id": validation_id}

        strategy_id = row[0]

        # Check Strategy Factory artifacts
        artifacts_dir = STRATEGY_FACTORY / "artifacts"
        factory_match = None
        if artifacts_dir.exists():
            for artifact_dir in sorted(artifacts_dir.iterdir(), reverse=True):
                candidate = artifact_dir / "candidate_result.json"
                if candidate.exists():
                    try:
                        result = json.loads(candidate.read_text())
                        if result.get("strategy_id") == strategy_id:
                            factory_match = result
                            break
                    except (json.JSONDecodeError, KeyError):
                        continue

        return {
            "status": "compared",
            "validation_id": validation_id,
            "strategy_id": strategy_id,
            "factory_match": factory_match is not None,
            "factory_result": factory_match,
            "note": "Strategy Factory comparison" + (" found" if factory_match else " — no matching artifact"),
        }
    finally:
        con.close()


def _write_sigma_packet(val_id: str, strategy_id: str, source: str) -> None:
    """Write sigma validation packet."""
    pending = get_pending_validations()
    write_packet(
        lane="sigma",
        packet_type="validation",
        summary=f"Sigma: {len(pending)} pending validations | latest: {val_id} ({strategy_id})",
        data={
            "latest_validation": {"id": val_id, "strategy_id": strategy_id, "source": source},
            "pending_count": len(pending),
            "pending_ids": [p["validation_id"] for p in pending[:10]],
        },
        upstream=["atlas_experiment", "kitt_quant"],
        source_module="sigma.validation_surface",
        confidence=0.5,
    )


def main():
    parser = argparse.ArgumentParser(description="Sigma Validation Surface")
    parser.add_argument("--submit", type=str, metavar="JSON_FILE", help="Submit validation from JSON file")
    parser.add_argument("--pending", action="store_true", help="List pending validations")
    parser.add_argument("--compare", type=str, metavar="VAL_ID", help="Compare validation against factory")
    parser.add_argument("--strategy-id", type=str, help="Strategy ID for ad-hoc submission")
    parser.add_argument("--source", type=str, default="atlas", help="Source lane")

    args = parser.parse_args()

    if args.submit:
        data = json.loads(Path(args.submit).read_text())
        submit_validation(
            strategy_id=data.get("strategy_id", "unknown"),
            source_lane=data.get("source_lane", "atlas"),
            parameters=data.get("parameters"),
            notes=data.get("notes", ""),
        )
    elif args.strategy_id:
        submit_validation(strategy_id=args.strategy_id, source_lane=args.source)
    elif args.pending:
        pending = get_pending_validations()
        print(f"\n=== SIGMA PENDING VALIDATIONS ({len(pending)}) ===\n")
        for p in pending:
            print(f"  {p['validation_id']}: strategy={p['strategy_id']} from={p['source_lane']}")
        print()
    elif args.compare:
        result = compare_with_factory(args.compare)
        print(json.dumps(result, indent=2, default=str))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
