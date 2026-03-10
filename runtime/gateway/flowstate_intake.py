#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.flowstate.source_store import create_source


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway intake for Flowstate source creation.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--source-type", default="note", help="Source type")
    parser.add_argument("--title", required=True, help="Title")
    parser.add_argument("--content", required=True, help="Content")
    parser.add_argument("--source-ref", default="", help="Source reference")
    parser.add_argument("--created-by", default="operator", help="Creator")
    args = parser.parse_args()

    record = create_source(
        source_type=args.source_type,
        title=args.title,
        content=args.content,
        source_ref=args.source_ref,
        created_by=args.created_by,
        root=Path(args.root).resolve(),
    )

    reply = {
        "kind": "flowstate_source_created",
        "reply": (
            f"Flowstate source `{record['source_id']}` created. "
            "It is stored as source material only and will not be promoted without approval."
        ),
        "source": record,
    }

    print(json.dumps(reply, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
