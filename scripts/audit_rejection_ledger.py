#!/usr/bin/env python3
"""Audit the rejection ledger — ingest from live sources, rebuild index, show summary.

Usage:
    python3 scripts/audit_rejection_ledger.py [--ingest] [--rebuild-index] [--summary]

Flags:
    --ingest         Scan live sources and normalize new rejections into the ledger
    --rebuild-index  Rebuild index.jsonl from individual record files
    --summary        Print ledger summary stats

Without flags, runs --summary.
"""

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.quant.rejection_normalizer import (
    normalize_any,
    normalize_factory_candidate,
)
from runtime.quant.rejection_ledger import RejectionLedger

# Default source paths (relative to workspace)
WORKSPACE = Path(__file__).resolve().parents[1]
OPENCLAW_WS = Path.home() / ".openclaw" / "workspace"

FACTORY_ARTIFACTS = OPENCLAW_WS / "artifacts" / "strategy_factory"
STRATEGIES_JSONL = OPENCLAW_WS / "STRATEGIES.jsonl"
SIGMA_DIR = WORKSPACE / "workspace" / "quant" / "sigma"
EXECUTOR_DIR = WORKSPACE / "workspace" / "quant" / "executor"


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def ingest_all(ledger: RejectionLedger) -> int:
    """Scan all live sources and ingest new rejections."""
    new_count = 0

    # 1. Strategy Factory candidate results
    for result_path in sorted(FACTORY_ARTIFACTS.rglob("candidate_result.json")):
        raw = _load_json(result_path)
        if raw:
            rec = normalize_factory_candidate(raw)
            if rec and not ledger.exists(rec.rejection_id):
                ledger.write(rec)
                new_count += 1

    # 2. STRATEGIES.jsonl (gate_overall == FAIL)
    if STRATEGIES_JSONL.exists():
        for line in STRATEGIES_JSONL.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if raw.get("gate_overall") == "FAIL":
                rec = normalize_factory_candidate(raw)
                if rec and not ledger.exists(rec.rejection_id):
                    ledger.write(rec)
                    new_count += 1

    # 3. Sigma rejection packets
    for path in sorted(SIGMA_DIR.glob("sigma-strategy-rejection-*.json")):
        raw = _load_json(path)
        if raw:
            rec = normalize_any(raw)
            if rec and not ledger.exists(rec.rejection_id):
                ledger.write(rec)
                new_count += 1

    # 4. Executor rejection packets
    for path in sorted(EXECUTOR_DIR.glob("executor-execution-rejection-*.json")):
        raw = _load_json(path)
        if raw:
            rec = normalize_any(raw)
            if rec and not ledger.exists(rec.rejection_id):
                ledger.write(rec)
                new_count += 1

    return new_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit rejection ledger")
    parser.add_argument("--ingest", action="store_true", help="Ingest from live sources")
    parser.add_argument("--rebuild-index", action="store_true", help="Rebuild index.jsonl")
    parser.add_argument("--summary", action="store_true", help="Print summary stats")
    parser.add_argument("--state-dir", type=Path, default=None)
    args = parser.parse_args()

    # Default to --summary if no flags
    if not (args.ingest or args.rebuild_index or args.summary):
        args.summary = True

    ledger = RejectionLedger(args.state_dir) if args.state_dir else RejectionLedger()

    if args.ingest:
        new = ingest_all(ledger)
        print(f"Ingested {new} new rejection records (total: {ledger.count()})")

    if args.rebuild_index:
        count = ledger.rebuild_index()
        print(f"Rebuilt index with {count} entries")

    if args.summary:
        s = ledger.summary()
        print(f"\nRejection Ledger Summary ({s['total']} records)")
        print("=" * 50)
        if s["by_reason"]:
            print("\nBy reason:")
            for r, c in s["by_reason"].items():
                print(f"  {r}: {c}")
        if s["by_family"]:
            print("\nBy family:")
            for f, c in s["by_family"].items():
                print(f"  {f}: {c}")
        if s["by_lane"]:
            print("\nBy source lane:")
            for l, c in s["by_lane"].items():
                print(f"  {l}: {c}")


if __name__ == "__main__":
    main()
