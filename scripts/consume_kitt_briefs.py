#!/usr/bin/env python3
"""consume_kitt_briefs — detect and process factory-origin Kitt briefs exactly once.

Scans state/kitt_briefs/ for briefs with source="strategy_factory" that have
not yet been consumed.  For each:
  1. Renders a markdown research file → workspace/research/
  2. Emits a kitt_brief_completed event → kitt channel + worklog mirror
  3. Writes a consumed marker → state/kitt_briefs_consumed/<brief_id>.json
  4. Writes/updates a quant queue entry → state/quant_queue/<cycle_id>.json

Idempotent: consumed markers prevent double-processing. Quant queue entries
are keyed by cycle_id so multiple briefs per cycle produce one entry.

Usage:
    python3 scripts/consume_kitt_briefs.py           # process pending
    python3 scripts/consume_kitt_briefs.py --dry-run  # preview only
    python3 scripts/consume_kitt_briefs.py --status    # show consumed/pending counts
    python3 scripts/consume_kitt_briefs.py --queue     # show quant queue
    python3 scripts/consume_kitt_briefs.py --queue --cycle <id>  # show one entry
    python3 scripts/consume_kitt_briefs.py --latest    # show current/latest cycle
    python3 scripts/consume_kitt_briefs.py --summary   # show operator summary
    python3 scripts/consume_kitt_briefs.py --rebuild-queue       # rebuild from consumed briefs
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

from runtime.core.discord_event_router import emit_event
from runtime.core.models import new_id, now_iso


# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------

def _briefs_dir(root: Path) -> Path:
    return root / "state" / "kitt_briefs"


def _consumed_dir(root: Path) -> Path:
    d = root / "state" / "kitt_briefs_consumed"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _research_dir() -> Path:
    d = Path.home() / ".openclaw" / "workspace" / "research"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _quant_queue_dir(root: Path) -> Path:
    d = root / "state" / "quant_queue"
    d.mkdir(parents=True, exist_ok=True)
    return d


FACTORY_ARTIFACT_ROOT = Path.home() / ".openclaw" / "workspace" / "artifacts" / "strategy_factory"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _is_factory_origin(brief: dict[str, Any]) -> bool:
    return brief.get("source") == "strategy_factory"


def _is_consumed(brief_id: str, root: Path) -> bool:
    return (_consumed_dir(root) / f"{brief_id}.json").is_file()


def find_pending(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Return (path, data) for factory-origin briefs not yet consumed."""
    bd = _briefs_dir(root)
    if not bd.is_dir():
        return []
    pending = []
    for p in sorted(bd.glob("kitt_brief_*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if _is_factory_origin(data) and not _is_consumed(data.get("brief_id", p.stem), root):
            pending.append((p, data))
    return pending


# ---------------------------------------------------------------------------
# Markdown rendering (factory-origin briefs)
# ---------------------------------------------------------------------------

def _render_factory_markdown(brief: dict[str, Any]) -> str:
    lines = [
        f"# Factory Weekly Brief — {brief.get('cycle_id', '?')}",
        f"**Status**: {brief.get('operator_status', '?')}  ",
        f"**Date**: {brief.get('source_date', '?')}  ",
        f"**Priority family**: {brief.get('priority_family', '?')}  ",
        "",
        "---",
        "",
        f"## Context",
        brief.get("context_summary", ""),
        "",
    ]
    ideas = brief.get("top_idea_lines", [])
    if ideas:
        lines.append("## Top Ideas")
        for idea in ideas:
            lines.append(f"- `{idea}`")
        lines.append("")
    rec = brief.get("action_recommendation", "")
    if rec:
        lines += ["## Recommendation", rec, ""]
    lines.append(f"_source: strategy_factory / {brief.get('brief_id', '?')}_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Quant queue
# ---------------------------------------------------------------------------

def _load_downstream(source_date: str) -> dict[str, Any] | None:
    """Try to load factory_downstream.json for enrichment."""
    p = FACTORY_ARTIFACT_ROOT / source_date / "factory_downstream.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _classify_review_status(brief: dict[str, Any]) -> str:
    """Determine whether this cycle is review_now / monitor / hold."""
    status = brief.get("operator_status", "")
    if status == "review":
        return "review_now"
    if status in ("monitor", "watch"):
        return "monitor"
    return "hold"


def _build_queue_entry(brief: dict[str, Any], *, brief_id: str) -> dict[str, Any]:
    """Build a quant queue entry from a consumed brief + optional downstream enrichment."""
    cycle_id = brief.get("cycle_id", "?")
    source_date = brief.get("source_date", "")
    ds = _load_downstream(source_date) or {}

    ideas = brief.get("top_idea_lines", [])
    # If downstream has structured top_ideas, prefer those
    ds_ideas = ds.get("top_ideas") or []
    if ds_ideas:
        top_ideas = [
            {
                "signature": i.get("signature", "")[:12],
                "family": i.get("family", ""),
                "score": i.get("best_score"),
                "classification": i.get("classification", ""),
            }
            for i in ds_ideas[:5]
        ]
    else:
        top_ideas = [{"line": line} for line in ideas[:5]]

    return {
        "cycle_id": cycle_id,
        "source_brief_id": brief_id,
        "source_date": source_date,
        "created_at": now_iso(),
        "operator_status": brief.get("operator_status"),
        "review_status": _classify_review_status(brief),
        "priority_family": brief.get("priority_family") or ds.get("priority_family"),
        "monitor_family": ds.get("monitor_family"),
        "drop_family": ds.get("drop_family"),
        "strongest_dataset": ds.get("strongest_dataset"),
        "weakest_dataset": ds.get("weakest_dataset"),
        "notable_change": ds.get("notable_change"),
        "degraded_count": ds.get("degraded_count"),
        "action_recommendation": brief.get("action_recommendation"),
        "top_ideas": top_ideas,
        "review_worthy_now": brief.get("operator_status") == "review",
        "enriched_from_downstream": bool(ds),
    }


def _write_queue_entry(brief: dict[str, Any], root: Path, *, brief_id: str) -> Path:
    """Write or update a quant queue entry keyed by cycle_id."""
    entry = _build_queue_entry(brief, brief_id=brief_id)
    cycle_id = entry["cycle_id"]
    qdir = _quant_queue_dir(root)
    entry_path = qdir / f"{cycle_id}.json"

    # If entry already exists for this cycle, merge — keep earliest created_at
    if entry_path.is_file():
        try:
            existing = json.loads(entry_path.read_text(encoding="utf-8"))
            entry["created_at"] = existing.get("created_at", entry["created_at"])
            entry["updated_at"] = now_iso()
        except (json.JSONDecodeError, OSError):
            pass

    entry_path.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    return entry_path


def _recency_key(entry: dict[str, Any]) -> str:
    """Return the best available timestamp for recency sorting."""
    return entry.get("updated_at") or entry.get("created_at") or ""


def queue_list(root: Path) -> list[dict[str, Any]]:
    """Return all quant queue entries, newest first by timestamp."""
    qdir = root / "state" / "quant_queue"
    if not qdir.is_dir():
        return []
    skip = {"LATEST.json"}
    entries = []
    for p in qdir.glob("*.json"):
        if p.name in skip:
            continue
        try:
            entries.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    entries.sort(key=_recency_key, reverse=True)
    return entries


def queue_get(root: Path, cycle_id: str) -> dict[str, Any] | None:
    """Return a single quant queue entry by cycle_id."""
    p = root / "state" / "quant_queue" / f"{cycle_id}.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def queue_latest(root: Path) -> dict[str, Any] | None:
    """Return the most recent queue entry by timestamp."""
    entries = queue_list(root)
    return entries[0] if entries else None


def write_queue_latest(root: Path) -> Path | None:
    """Write state/quant_queue/LATEST.json from the most recent queue entry."""
    latest = queue_latest(root)
    if latest is None:
        return None
    # Write a clean subset — the operator-facing view of the current cycle
    view = {
        "cycle_id": latest.get("cycle_id"),
        "source_date": latest.get("source_date"),
        "review_status": latest.get("review_status"),
        "priority_family": latest.get("priority_family"),
        "monitor_family": latest.get("monitor_family"),
        "drop_family": latest.get("drop_family"),
        "strongest_dataset": latest.get("strongest_dataset"),
        "weakest_dataset": latest.get("weakest_dataset"),
        "notable_change": latest.get("notable_change"),
        "review_worthy_now": latest.get("review_worthy_now"),
        "top_ideas": latest.get("top_ideas", [])[:5],
        "action_recommendation": latest.get("action_recommendation"),
        "source_brief_id": latest.get("source_brief_id"),
        "resolved_from": _recency_key(latest),
    }
    p = _quant_queue_dir(root) / "LATEST.json"
    p.write_text(json.dumps(view, indent=2) + "\n", encoding="utf-8")
    return p


def rebuild_queue(root: Path, *, verbose: bool = False) -> dict[str, Any]:
    """Rebuild quant queue from all consumed factory briefs."""
    bd = _briefs_dir(root)
    cd = _consumed_dir(root)
    rebuilt = 0
    if not bd.is_dir():
        return {"rebuilt": 0}
    for p in sorted(bd.glob("kitt_brief_*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not _is_factory_origin(data):
            continue
        brief_id = data.get("brief_id", p.stem)
        if not (cd / f"{brief_id}.json").is_file():
            continue  # not consumed yet — skip
        _write_queue_entry(data, root, brief_id=brief_id)
        rebuilt += 1
        if verbose:
            print(f"  REBUILT  {data.get('cycle_id', '?')}  ← {brief_id}")
    write_queue_latest(root)
    write_queue_summary(root)
    return {"rebuilt": rebuilt}


# ---------------------------------------------------------------------------
# Operator summary
# ---------------------------------------------------------------------------

def _format_summary(entries: list[dict[str, Any]]) -> str:
    """Render a compact operator-readable summary of the quant queue."""
    if not entries:
        return "# Quant Queue — empty\n\nNo factory cycles consumed yet.\n"

    # entries arrive newest-first by timestamp from queue_list()
    current = entries[0]
    rest = entries[1:]

    lines = ["# Quant Queue Summary", ""]

    # ── Current cycle ──
    cid = current.get("cycle_id", "?")
    sd = current.get("source_date", "?")
    rs = current.get("review_status", "?")
    pf = current.get("priority_family") or "—"
    mf = current.get("monitor_family") or "—"
    df = current.get("drop_family") or "—"

    lines += [
        f"## Current Cycle: {cid}",
        f"- **Date**: {sd}",
        f"- **Status**: {rs}",
        f"- **Priority family**: {pf}",
        f"- **Monitor family**: {mf}",
        f"- **Drop family**: {df}",
    ]
    nc = current.get("notable_change")
    if nc:
        lines.append(f"- **Notable change**: {nc}")
    rec = current.get("action_recommendation")
    if rec:
        lines.append(f"- **Action**: {rec}")
    lines.append("")

    # Actionable?
    if current.get("review_worthy_now"):
        lines.append("**Actionable now**: yes — current cycle needs review")
    else:
        lines.append("**Actionable now**: no — current cycle is monitor/hold")
    lines.append("")

    # Top ideas from current cycle
    ideas = current.get("top_ideas", [])
    if ideas:
        lines.append("### Top Ideas (current)")
        for idea in ideas[:5]:
            sig = idea.get("signature", idea.get("line", "?"))
            fam = idea.get("family", "")
            score = idea.get("score")
            cls_ = idea.get("classification", "")
            score_str = f" score={score}" if score else ""
            cls_str = f" [{cls_}]" if cls_ else ""
            lines.append(f"- `{sig}` {fam}{score_str}{cls_str}")
        lines.append("")

    # ── Historical cycles ──
    if rest:
        lines += ["## Historical Cycles", ""]
        lines.append("| Cycle | Date | Status | Priority | Action |")
        lines.append("|-------|------|--------|----------|--------|")
        for e in rest:
            lines.append(
                f"| {e.get('cycle_id', '?')} "
                f"| {e.get('source_date', '?')} "
                f"| {e.get('review_status', '?')} "
                f"| {e.get('priority_family', '—')} "
                f"| {(e.get('action_recommendation') or '—')[:60]} |"
            )
        lines.append("")

    lines.append(f"_Generated {now_iso()}_")
    return "\n".join(lines) + "\n"


def write_queue_summary(root: Path) -> Path:
    """Write state/quant_queue/SUMMARY.md from current queue entries."""
    entries = queue_list(root)
    summary = _format_summary(entries)
    p = _quant_queue_dir(root) / "SUMMARY.md"
    p.write_text(summary, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Consumption
# ---------------------------------------------------------------------------

def _consume_one(path: Path, brief: dict[str, Any], root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Process one factory-origin brief. Returns a result dict."""
    brief_id = brief.get("brief_id", path.stem)
    cycle_id = brief.get("cycle_id", "?")

    if dry_run:
        return {"brief_id": brief_id, "action": "dry_run", "cycle_id": cycle_id}

    # 1 — Write markdown to workspace/research/
    md_path = _research_dir() / f"{brief_id}.md"
    md_path.write_text(_render_factory_markdown(brief), encoding="utf-8")

    # 2 — Emit kitt_brief_completed event → kitt channel + worklog
    ideas = brief.get("top_idea_lines", [])
    idea_preview = "; ".join(ideas[:2])[:100] if ideas else ""
    detail = (
        f"Factory weekly ({cycle_id}): "
        f"status={brief.get('operator_status', '?')} "
        f"priority={brief.get('priority_family', '?')} "
        f"| {idea_preview}"
    )
    ev = emit_event(
        "kitt_brief_completed",
        "kitt",
        task_id=brief.get("task_id", f"factory_{cycle_id}"),
        detail=detail,
        artifact_id=brief_id,
        extra={
            "source": "strategy_factory",
            "cycle_id": cycle_id,
            "operator_status": brief.get("operator_status"),
            "priority_family": brief.get("priority_family"),
        },
        root=root,
    )

    # 3 — Write consumed marker
    marker = {
        "brief_id": brief_id,
        "consumed_at": now_iso(),
        "cycle_id": cycle_id,
        "event_id": ev.get("event_id"),
        "research_path": str(md_path),
        "outbox_count": len(ev.get("outbox_entries", [])),
    }
    marker_path = _consumed_dir(root) / f"{brief_id}.json"
    marker_path.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")

    # 4 — Write/update quant queue entry (keyed by cycle_id, idempotent)
    queue_path = _write_queue_entry(brief, root, brief_id=brief_id)

    return {
        "brief_id": brief_id,
        "action": "consumed",
        "cycle_id": cycle_id,
        "event_id": ev.get("event_id"),
        "research_path": str(md_path),
        "outbox_entries": len(ev.get("outbox_entries", [])),
        "queue_path": str(queue_path),
    }


def consume_pending(root: Path, *, dry_run: bool = False, verbose: bool = False) -> dict[str, Any]:
    """Process all pending factory-origin briefs. Returns summary."""
    pending = find_pending(root)
    results = []
    for path, brief in pending:
        r = _consume_one(path, brief, root, dry_run=dry_run)
        results.append(r)
        if verbose:
            action = r["action"].upper()
            print(f"  {action}  {r['brief_id']}  cycle={r['cycle_id']}")
    return {
        "pending": len(pending),
        "processed": len(results),
        "dry_run": dry_run,
        "results": results,
    }


def status(root: Path) -> dict[str, Any]:
    """Return counts of factory briefs: total, consumed, pending."""
    bd = _briefs_dir(root)
    total = 0
    consumed = 0
    pending = 0
    if bd.is_dir():
        for p in bd.glob("kitt_brief_*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not _is_factory_origin(data):
                continue
            total += 1
            if _is_consumed(data.get("brief_id", p.stem), root):
                consumed += 1
            else:
                pending += 1
    return {"total_factory": total, "consumed": consumed, "pending": pending}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Consume factory-origin Kitt briefs")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--dry-run", action="store_true", help="Preview without processing")
    parser.add_argument("--status", action="store_true", help="Show counts and exit")
    parser.add_argument("--queue", action="store_true", help="Show quant queue entries")
    parser.add_argument("--cycle", default=None, help="Show a specific cycle (with --queue)")
    parser.add_argument("--rebuild-queue", action="store_true", help="Rebuild quant queue from consumed briefs")
    parser.add_argument("--summary", action="store_true", help="Show operator summary of quant queue")
    parser.add_argument("--latest", action="store_true", help="Show current/latest cycle entry")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    if args.status:
        s = status(root)
        print(json.dumps(s, indent=2))
        return 0

    if args.rebuild_queue:
        r = rebuild_queue(root, verbose=True)
        print(json.dumps(r, indent=2))
        return 0

    if args.queue:
        if args.cycle:
            entry = queue_get(root, args.cycle)
            if entry:
                print(json.dumps(entry, indent=2))
            else:
                print(f"No queue entry for cycle: {args.cycle}")
                return 1
        else:
            entries = queue_list(root)
            if not entries:
                print("Quant queue is empty.")
            else:
                print(json.dumps(entries, indent=2))
        return 0

    if args.latest:
        p = write_queue_latest(root)
        if p:
            print(p.read_text(encoding="utf-8"))
        else:
            print("Quant queue is empty.")
            return 1
        return 0

    if args.summary:
        entries = queue_list(root)
        p = write_queue_summary(root)
        print(_format_summary(entries))
        print(f"Written to {p}")
        return 0

    summary = consume_pending(root, dry_run=args.dry_run, verbose=True)
    if summary["pending"] == 0:
        print("No pending factory-origin briefs.")
    else:
        print(json.dumps(summary, indent=2))
    # Regenerate summary + latest after consuming
    if summary["processed"] > 0 and not args.dry_run:
        write_queue_latest(root)
        write_queue_summary(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
