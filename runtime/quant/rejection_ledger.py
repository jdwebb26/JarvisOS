"""Durable rejection ledger — writes canonical RejectionRecords to state/quant/rejections/.

Storage layout:
  state/quant/rejections/rej_<id>.json   — individual record
  state/quant/rejections/index.jsonl      — append-only index for fast scan
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from runtime.quant.rejection_types import RejectionRecord

DEFAULT_STATE_DIR = Path(__file__).resolve().parents[2] / "state" / "quant" / "rejections"


class RejectionLedger:
    def __init__(self, state_dir: Path | str | None = None):
        self.state_dir = Path(state_dir) if state_dir else DEFAULT_STATE_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)

    @property
    def index_path(self) -> Path:
        return self.state_dir / "index.jsonl"

    def _record_path(self, rejection_id: str) -> Path:
        return self.state_dir / f"{rejection_id}.json"

    def exists(self, rejection_id: str) -> bool:
        return self._record_path(rejection_id).exists()

    def write(self, record: RejectionRecord, *, overwrite: bool = False) -> Path:
        """Write a rejection record. Returns the path written."""
        path = self._record_path(record.rejection_id)
        if path.exists() and not overwrite:
            return path

        data = record.to_dict()
        path.write_text(json.dumps(data, indent=2, default=str) + "\n")

        # Append to index
        index_entry = {
            "rejection_id": record.rejection_id,
            "created_at": record.created_at,
            "strategy_id": record.strategy_id,
            "family": record.family,
            "source_lane": record.source_lane,
            "primary_reason": record.primary_reason,
            "next_action_hint": record.next_action_hint,
        }
        with open(self.index_path, "a") as f:
            f.write(json.dumps(index_entry, default=str) + "\n")

        return path

    def write_many(self, records: list[RejectionRecord], *, overwrite: bool = False) -> int:
        """Write multiple records. Returns count of new records written."""
        count = 0
        for rec in records:
            if not self.exists(rec.rejection_id) or overwrite:
                self.write(rec, overwrite=overwrite)
                count += 1
        return count

    def read(self, rejection_id: str) -> RejectionRecord | None:
        path = self._record_path(rejection_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return RejectionRecord.from_dict(data)

    def read_all(self) -> list[RejectionRecord]:
        """Read all rejection records from individual JSON files."""
        records: list[RejectionRecord] = []
        for path in sorted(self.state_dir.glob("rej_*.json")):
            try:
                data = json.loads(path.read_text())
                records.append(RejectionRecord.from_dict(data))
            except (json.JSONDecodeError, TypeError):
                continue
        return records

    def read_index(self) -> list[dict[str, Any]]:
        """Read the append-only index for fast scanning."""
        if not self.index_path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for line in self.index_path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    def rebuild_index(self) -> int:
        """Rebuild index.jsonl from individual record files. Returns entry count."""
        records = self.read_all()
        with open(self.index_path, "w") as f:
            for rec in records:
                entry = {
                    "rejection_id": rec.rejection_id,
                    "created_at": rec.created_at,
                    "strategy_id": rec.strategy_id,
                    "family": rec.family,
                    "source_lane": rec.source_lane,
                    "primary_reason": rec.primary_reason,
                    "next_action_hint": rec.next_action_hint,
                }
                f.write(json.dumps(entry, default=str) + "\n")
        return len(records)

    def count(self) -> int:
        return len(list(self.state_dir.glob("rej_*.json")))

    def summary(self) -> dict[str, Any]:
        """Quick summary stats from the index."""
        entries = self.read_index()
        reasons: dict[str, int] = {}
        families: dict[str, int] = {}
        lanes: dict[str, int] = {}
        for e in entries:
            r = e.get("primary_reason", "unknown")
            reasons[r] = reasons.get(r, 0) + 1
            f = e.get("family", "")
            if f:
                families[f] = families.get(f, 0) + 1
            lane = e.get("source_lane", "")
            if lane:
                lanes[lane] = lanes.get(lane, 0) + 1
        return {
            "total": len(entries),
            "by_reason": dict(sorted(reasons.items(), key=lambda x: -x[1])),
            "by_family": dict(sorted(families.items(), key=lambda x: -x[1])),
            "by_lane": dict(sorted(lanes.items(), key=lambda x: -x[1])),
        }
