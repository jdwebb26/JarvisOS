#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from runtime.flowstate.source_store import load_source, save_source


ROOT = Path(__file__).resolve().parents[2]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_artifact_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def artifacts_dir(root: Optional[Path] = None) -> Path:
    base = root or ROOT
    path = base / "state" / "flowstate_sources" / "artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def artifact_path(artifact_id: str, root: Optional[Path] = None) -> Path:
    return artifacts_dir(root) / f"{artifact_id}.json"


def _preserve_or_advance_status(current_status: str, target_status: str) -> str:
    if current_status == "awaiting_promotion_approval":
        return "awaiting_promotion_approval"
    return target_status


def create_extraction_artifact(
    *,
    source_id: str,
    extracted_text: str,
    extraction_kind: str = "text_extraction",
    root: Optional[Path] = None,
) -> dict:
    source = load_source(source_id, root=root)
    if source is None:
        raise ValueError(f"Flowstate source not found: {source_id}")

    artifact = {
        "artifact_id": new_artifact_id("fext"),
        "artifact_type": "flowstate_extraction",
        "source_id": source_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "title": source["title"],
        "source_type": source["source_type"],
        "extraction_kind": extraction_kind,
        "extracted_text": extracted_text,
        "version": "v1",
    }

    artifact_path(artifact["artifact_id"], root=root).write_text(
        json.dumps(artifact, indent=2) + "\n",
        encoding="utf-8",
    )

    source["extraction_artifact_id"] = artifact["artifact_id"]
    source["processing_status"] = _preserve_or_advance_status(
        source.get("processing_status", "ingested"),
        "extracted",
    )
    save_source(source, root=root)

    return artifact


def create_distillation_artifact(
    *,
    source_id: str,
    summary: str,
    key_claims: list[str],
    key_ideas: list[str],
    candidate_actions: list[str],
    notable_sections: list[str],
    caveats: list[str],
    root: Optional[Path] = None,
) -> dict:
    source = load_source(source_id, root=root)
    if source is None:
        raise ValueError(f"Flowstate source not found: {source_id}")

    artifact = {
        "artifact_id": new_artifact_id("fdist"),
        "artifact_type": "flowstate_distillation",
        "source_id": source_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "title": source["title"],
        "source_type": source["source_type"],
        "summary": summary,
        "key_claims": key_claims,
        "key_ideas": key_ideas,
        "candidate_actions": candidate_actions,
        "notable_sections": notable_sections,
        "caveats": caveats,
        "version": "v1",
    }

    artifact_path(artifact["artifact_id"], root=root).write_text(
        json.dumps(artifact, indent=2) + "\n",
        encoding="utf-8",
    )

    source.setdefault("distillation_artifact_ids", [])
    source["distillation_artifact_ids"].append(artifact["artifact_id"])
    source["latest_distillation_artifact_id"] = artifact["artifact_id"]
    source["processing_status"] = _preserve_or_advance_status(
        source.get("processing_status", "ingested"),
        "distilled",
    )
    save_source(source, root=root)

    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Flowstate extraction and distillation artifacts.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--source-id", required=True, help="Flowstate source id")
    parser.add_argument("--extracted-text", default="", help="Optional extracted/transcribed text")
    parser.add_argument("--summary", required=True, help="Concise summary")
    parser.add_argument("--claim", action="append", default=[], help="Key claim (repeatable)")
    parser.add_argument("--idea", action="append", default=[], help="Key idea (repeatable)")
    parser.add_argument("--action", action="append", default=[], help="Candidate action (repeatable)")
    parser.add_argument("--section", action="append", default=[], help="Notable section/timestamp (repeatable)")
    parser.add_argument("--caveat", action="append", default=[], help="Caveat/uncertainty (repeatable)")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    extraction = None
    if args.extracted_text.strip():
        extraction = create_extraction_artifact(
            source_id=args.source_id,
            extracted_text=args.extracted_text.strip(),
            root=root,
        )

    distillation = create_distillation_artifact(
        source_id=args.source_id,
        summary=args.summary.strip(),
        key_claims=args.claim,
        key_ideas=args.idea,
        candidate_actions=args.action,
        notable_sections=args.section,
        caveats=args.caveat,
        root=root,
    )

    result = {
        "ok": True,
        "source_id": args.source_id,
        "extraction_artifact_id": extraction["artifact_id"] if extraction else None,
        "distillation_artifact_id": distillation["artifact_id"],
    }

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
