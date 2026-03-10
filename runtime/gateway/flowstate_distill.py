#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.flowstate.distill_store import (
    create_distillation_artifact,
    create_extraction_artifact,
)
from runtime.flowstate.source_store import load_source


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway wrapper for Flowstate distillation.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--source-id", required=True, help="Flowstate source id")
    parser.add_argument("--extracted-text", default="", help="Optional extracted text")
    parser.add_argument("--summary", required=True, help="Concise summary")
    parser.add_argument("--claim", action="append", default=[], help="Key claim (repeatable)")
    parser.add_argument("--idea", action="append", default=[], help="Key idea (repeatable)")
    parser.add_argument("--action", action="append", default=[], help="Candidate action (repeatable)")
    parser.add_argument("--section", action="append", default=[], help="Notable section (repeatable)")
    parser.add_argument("--caveat", action="append", default=[], help="Caveat (repeatable)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    source = load_source(args.source_id, root=root)
    if source is None:
        raise ValueError(f"Flowstate source not found: {args.source_id}")

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

    reply = {
        "kind": "flowstate_distilled",
        "reply": (
            f"Flowstate source `{args.source_id}` distilled. "
            f"Distillation artifact: `{distillation['artifact_id']}`. "
            "Promotion still requires explicit approval."
        ),
        "source_id": args.source_id,
        "extraction_artifact_id": extraction["artifact_id"] if extraction else None,
        "distillation_artifact_id": distillation["artifact_id"],
    }

    print(json.dumps(reply, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
