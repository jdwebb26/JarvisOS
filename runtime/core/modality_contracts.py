#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import ModalityContractRecord, new_id, now_iso


DEFAULT_MODALITY_CONTRACTS = [
    {
        "contract_name": "qwen_text_core",
        "provider_id": "qwen",
        "model_family": "qwen3.5",
        "input_modalities": ["text"],
        "output_modalities": ["text", "json"],
        "enabled": True,
        "policy_tags": ["qwen_only", "text_primary", "approved"],
        "control_flags": ["operator_only_mode_respected"],
        "bounded_rules": {"files": "metadata_only", "images": "disabled", "audio": "disabled"},
    },
    {
        "contract_name": "qwen_file_scaffold",
        "provider_id": "qwen",
        "model_family": "qwen3.5",
        "input_modalities": ["file_ref"],
        "output_modalities": ["text", "json"],
        "enabled": False,
        "policy_tags": ["bounded_multimodal_scaffold", "file_review_only"],
        "control_flags": ["operator_only_mode_required", "execution_freeze_respected"],
        "bounded_rules": {"files": "explicit_ref_only", "images": "disabled", "audio": "disabled"},
    },
    {
        "contract_name": "qwen_image_audio_scaffold",
        "provider_id": "qwen",
        "model_family": "qwen3.5",
        "input_modalities": ["image_ref", "audio_ref"],
        "output_modalities": ["text"],
        "enabled": False,
        "policy_tags": ["bounded_multimodal_scaffold", "disabled_by_default"],
        "control_flags": ["operator_only_mode_required", "execution_freeze_respected"],
        "bounded_rules": {"images": "reference_only", "audio": "reference_only", "execution": "forbidden"},
    },
]


def modality_contracts_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "modality_contracts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(folder: Path, record_id: str) -> Path:
    return folder / f"{record_id}.json"


def save_modality_contract(record: ModalityContractRecord, *, root: Optional[Path] = None) -> ModalityContractRecord:
    record.updated_at = now_iso()
    _path(modality_contracts_dir(root), record.modality_contract_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def list_modality_contracts(root: Optional[Path] = None) -> list[ModalityContractRecord]:
    rows: list[ModalityContractRecord] = []
    for path in modality_contracts_dir(root).glob("*.json"):
        try:
            rows.append(ModalityContractRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def ensure_default_modality_contracts(root: Optional[Path] = None) -> list[ModalityContractRecord]:
    root_path = Path(root or ROOT).resolve()
    existing = {row.contract_name: row for row in list_modality_contracts(root_path)}
    for item in DEFAULT_MODALITY_CONTRACTS:
        if item["contract_name"] in existing:
            continue
        save_modality_contract(
            ModalityContractRecord(
                modality_contract_id=new_id("mod"),
                created_at=now_iso(),
                updated_at=now_iso(),
                **item,
            ),
            root=root_path,
        )
    return list_modality_contracts(root_path)


def build_modality_summary(root: Optional[Path] = None) -> dict:
    rows = ensure_default_modality_contracts(root)
    enabled_input_modalities = sorted({mod for row in rows if row.enabled for mod in row.input_modalities})
    return {
        "modality_contract_count": len(rows),
        "enabled_modality_contract_count": sum(1 for row in rows if row.enabled),
        "enabled_input_modalities": enabled_input_modalities,
        "runtime_modality_mode": "text_only_qwen",
        "multimodal_runtime_enabled": any(mod in {"image_ref", "audio_ref", "file_ref"} for mod in enabled_input_modalities),
        "latest_modality_contract": rows[0].to_dict() if rows else None,
        "policy_tags": sorted({tag for row in rows for tag in row.policy_tags}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show bounded multimodal contract scaffolding.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_modality_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
