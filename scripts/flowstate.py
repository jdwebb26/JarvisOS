#!/usr/bin/env python3
"""flowstate — operator CLI for the Flowstate ingest/distill/promote lifecycle.

Usage:
    python3 scripts/flowstate.py ingest  --title "..." --content "..."
    python3 scripts/flowstate.py distill --source-id fsrc_xxx --summary "..."
    python3 scripts/flowstate.py status
    python3 scripts/flowstate.py inspect --source-id fsrc_xxx
    python3 scripts/flowstate.py inspect --latest
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.flowstate.source_store import create_source, list_sources, load_source
from runtime.flowstate.distill_store import (
    create_distillation_artifact,
    create_extraction_artifact,
    artifact_path,
)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_ingest(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    record = create_source(
        source_type=args.type,
        title=args.title,
        content=args.content,
        source_ref=args.ref or "",
        created_by=args.user,
        root=root,
    )
    if args.json:
        print(json.dumps(record, indent=2))
    else:
        print(f"Ingested: {record['source_id']}")
        print(f"  Title:  {record['title']}")
        print(f"  Type:   {record['source_type']}")
        print(f"  Status: {record['processing_status']}")
    return 0


def cmd_distill(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    source = load_source(args.source_id, root=root)
    if not source:
        print(f"Source not found: {args.source_id}")
        return 1

    extraction = None
    if args.extracted_text:
        extraction = create_extraction_artifact(
            source_id=args.source_id,
            extracted_text=args.extracted_text,
            root=root,
        )

    distillation = create_distillation_artifact(
        source_id=args.source_id,
        summary=args.summary,
        key_claims=args.claim or [],
        key_ideas=args.idea or [],
        candidate_actions=args.action or [],
        notable_sections=args.section or [],
        caveats=args.caveat or [],
        root=root,
    )

    if args.json:
        print(json.dumps({
            "source_id": args.source_id,
            "extraction_id": extraction["artifact_id"] if extraction else None,
            "distillation_id": distillation["artifact_id"],
        }, indent=2))
    else:
        if extraction:
            print(f"Extracted: {extraction['artifact_id']}")
        print(f"Distilled: {distillation['artifact_id']}")
        print(f"  Summary: {distillation['summary'][:80]}")
        print(f"  Claims:  {len(distillation['key_claims'])}")
        print(f"  Ideas:   {len(distillation['key_ideas'])}")
        print(f"  Actions: {len(distillation['candidate_actions'])}")
        print("  Promotion requires explicit approval. Not auto-promoted.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    sources = list_sources(root=root)

    if args.json:
        print(json.dumps(sources, indent=2, default=str))
        return 0

    if not sources:
        print("No Flowstate sources.")
        return 0

    print(f"Flowstate Sources ({len(sources)})")
    print("")
    for s in sorted(sources, key=lambda x: x.get("created_at", ""), reverse=True):
        sid = s["source_id"]
        status = s.get("processing_status", "?")
        title = s.get("title", "")[:45]
        n_dist = len(s.get("distillation_artifact_ids", []))
        n_promo = len(s.get("promotion_request_ids", []))
        print(f"  {sid}  {status:28}  dist={n_dist}  promo={n_promo}  {title}")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()

    if args.latest:
        sources = list_sources(root=root)
        if not sources:
            print("No Flowstate sources.")
            return 1
        sources.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        source = sources[0]
    else:
        source = load_source(args.source_id, root=root)

    if not source:
        print(f"Source not found: {args.source_id}")
        return 1

    if args.json:
        # Include artifacts inline
        result: dict[str, Any] = dict(source)
        result["artifacts"] = []
        for aid in source.get("distillation_artifact_ids", []):
            apath = artifact_path(aid, root=root)
            if apath.exists():
                result["artifacts"].append(json.loads(apath.read_text()))
        ext_id = source.get("extraction_artifact_id")
        if ext_id:
            epath = artifact_path(ext_id, root=root)
            if epath.exists():
                result["extraction_artifact"] = json.loads(epath.read_text())
        print(json.dumps(result, indent=2, default=str))
        return 0

    # Terminal output
    print(f"Source: {source['source_id']}")
    print(f"  Title:    {source.get('title', '')}")
    print(f"  Type:     {source.get('source_type', '')}")
    print(f"  Status:   {source.get('processing_status', '?')}")
    print(f"  Created:  {source.get('created_at', '')[:19]}")
    print(f"  By:       {source.get('created_by', '')}")
    if source.get("source_ref"):
        print(f"  Ref:      {source['source_ref']}")
    print(f"  Content:  {source.get('content', '')[:100]}")
    print("")

    # Extraction
    ext_id = source.get("extraction_artifact_id")
    if ext_id:
        epath = artifact_path(ext_id, root=root)
        if epath.exists():
            ext = json.loads(epath.read_text())
            print(f"  Extraction: {ext_id}")
            print(f"    Text: {ext.get('extracted_text', '')[:80]}")
            print("")

    # Distillations
    for aid in source.get("distillation_artifact_ids", []):
        apath = artifact_path(aid, root=root)
        if apath.exists():
            d = json.loads(apath.read_text())
            latest = " (latest)" if aid == source.get("latest_distillation_artifact_id") else ""
            print(f"  Distillation: {aid}{latest}")
            print(f"    Summary:  {d.get('summary', '')[:80]}")
            if d.get("key_claims"):
                print(f"    Claims:   {d['key_claims']}")
            if d.get("key_ideas"):
                print(f"    Ideas:    {d['key_ideas']}")
            if d.get("candidate_actions"):
                print(f"    Actions:  {d['candidate_actions']}")
            if d.get("caveats"):
                print(f"    Caveats:  {d['caveats']}")
            print("")

    # Promotion requests
    promos = source.get("promotion_request_ids", [])
    if promos:
        print(f"  Promotion requests: {promos}")
        print("  (Check approval status with reconcile_approvals.py)")
    else:
        print("  No promotion requests. Distilled output has not been promoted.")

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Flowstate — ingest, distill, inspect operator lifecycle",
    )
    parser.add_argument("--root", default=str(ROOT), help="Project root")
    parser.add_argument("--json", action="store_true", help="JSON output")
    sub = parser.add_subparsers(dest="command")

    # ingest
    p_ingest = sub.add_parser("ingest", help="Create a Flowstate source record")
    p_ingest.add_argument("--title", required=True)
    p_ingest.add_argument("--content", required=True)
    p_ingest.add_argument("--type", default="note", help="Source type (note, transcript, web_article)")
    p_ingest.add_argument("--ref", default="", help="Source reference")
    p_ingest.add_argument("--user", default="operator")

    # distill
    p_distill = sub.add_parser("distill", help="Distill a source into an artifact")
    p_distill.add_argument("--source-id", required=True)
    p_distill.add_argument("--summary", required=True)
    p_distill.add_argument("--extracted-text", default="")
    p_distill.add_argument("--claim", action="append", help="Key claim (repeatable)")
    p_distill.add_argument("--idea", action="append", help="Key idea (repeatable)")
    p_distill.add_argument("--action", action="append", help="Candidate action (repeatable)")
    p_distill.add_argument("--section", action="append", help="Notable section (repeatable)")
    p_distill.add_argument("--caveat", action="append", help="Caveat (repeatable)")

    # status
    sub.add_parser("status", help="List all Flowstate sources and their lifecycle state")

    # inspect
    p_inspect = sub.add_parser("inspect", help="Full detail for one source")
    p_inspect.add_argument("--source-id", default="")
    p_inspect.add_argument("--latest", action="store_true", help="Inspect most recent source")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    return {
        "ingest": cmd_ingest,
        "distill": cmd_distill,
        "status": cmd_status,
        "inspect": cmd_inspect,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
