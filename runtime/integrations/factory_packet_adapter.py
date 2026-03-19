#!/usr/bin/env python3
"""Strategy Factory operator_packet.json reader/adapter.

Discovers the newest weekly operator packet from the Strategy Factory
artifact tree and produces a compact downstream payload for Jarvis,
Kitt, and worklog consumers.

CLI:
    python3 runtime/integrations/factory_packet_adapter.py
    python3 runtime/integrations/factory_packet_adapter.py --root /path/to/artifacts
    python3 runtime/integrations/factory_packet_adapter.py --format discord
    python3 runtime/integrations/factory_packet_adapter.py --write-artifact
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

FACTORY_ARTIFACT_ROOT = Path.home() / ".openclaw" / "workspace" / "artifacts" / "strategy_factory"

DOWNSTREAM_FIELDS = (
    "cycle_id",
    "operator_status",
    "priority_family",
    "monitor_family",
    "drop_family",
    "strongest_dataset",
    "weakest_dataset",
    "notable_change",
    "degraded_count",
    "honest_failures",
    "top_ideas",
    "action_recommendation",
)


class FactoryPacketError(Exception):
    """Raised when the operator packet cannot be loaded."""


# ── discovery ────────────────────────────────────────────────────────

def _discover_newest_packet(root: Path | None = None) -> Path:
    """Return the path to the newest operator_packet.json.

    Date-folders are named YYYY-MM-DD. We sort lexicographically
    (which equals chronological for ISO dates) and pick the latest
    folder that actually contains an operator_packet.json.
    """
    base = root or FACTORY_ARTIFACT_ROOT
    if not base.is_dir():
        raise FactoryPacketError(f"artifact root does not exist: {base}")

    date_dirs = sorted(
        (d for d in base.iterdir() if d.is_dir()),
        key=lambda d: d.name,
        reverse=True,
    )
    for d in date_dirs:
        packet = d / "operator_packet.json"
        if packet.is_file():
            return packet

    raise FactoryPacketError(f"no operator_packet.json found under {base}")


# ── loader ───────────────────────────────────────────────────────────

def load_operator_packet(
    path: Optional[Path] = None,
    *,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Load and validate a raw operator packet.

    Parameters
    ----------
    path : explicit packet file path (takes priority)
    root : artifact root to auto-discover from
    """
    target = path or _discover_newest_packet(root)
    try:
        raw = json.loads(target.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise FactoryPacketError(f"failed to read {target}: {exc}") from exc

    if not isinstance(raw, dict) or "cycle_id" not in raw:
        raise FactoryPacketError(f"invalid operator packet at {target}: missing cycle_id")

    raw["_source_path"] = str(target)
    return raw


# ── downstream payload ───────────────────────────────────────────────

def build_downstream_payload(packet: dict[str, Any]) -> dict[str, Any]:
    """Extract a compact downstream payload from a raw operator packet."""
    payload: dict[str, Any] = {}
    for field in DOWNSTREAM_FIELDS:
        payload[field] = packet.get(field)

    # Trim top_ideas to top 3 and flatten for readability
    raw_ideas = payload.get("top_ideas") or []
    payload["top_ideas"] = [
        {
            "signature": idea.get("signature", ""),
            "family": idea.get("family", ""),
            "best_score": idea.get("best_score"),
            "classification": idea.get("classification", ""),
        }
        for idea in raw_ideas[:3]
    ]

    payload["source_date"] = _extract_date(packet)
    payload["generated_at"] = packet.get("generated_at")
    return payload


def _extract_date(packet: dict[str, Any]) -> str | None:
    """Pull the date-folder name from _source_path, or from generated_at."""
    src = packet.get("_source_path", "")
    parts = Path(src).parts
    # look for YYYY-MM-DD part
    for p in reversed(parts):
        if len(p) == 10 and p[4] == "-" and p[7] == "-":
            return p
    gen = packet.get("generated_at", "")
    if gen:
        try:
            return datetime.fromisoformat(gen).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass
    return None


# ── Discord message rendering ────────────────────────────────────────

def render_discord_message(payload: dict[str, Any]) -> str:
    """Render a compact Discord-ready message from the downstream payload."""
    lines: list[str] = []
    status = (payload.get("operator_status") or "unknown").upper()
    lines.append(f"**Strategy Factory Weekly** | `{payload.get('cycle_id', '?')}` | status: **{status}**")
    lines.append("")

    pf = payload.get("priority_family") or "none"
    mf = payload.get("monitor_family") or "none"
    df = payload.get("drop_family") or "none"
    lines.append(f"Priority: `{pf}` | Monitor: `{mf}` | Drop: `{df}`")

    sd = payload.get("strongest_dataset") or "?"
    wd = payload.get("weakest_dataset") or "?"
    lines.append(f"Strongest: `{sd}` | Weakest: `{wd}`")

    nc = payload.get("notable_change")
    if nc:
        lines.append(f"Change: {nc}")

    deg = payload.get("degraded_count", 0)
    fails = payload.get("honest_failures") or []
    lines.append(f"Degraded: {deg} | Failures: {len(fails)}")

    ideas = payload.get("top_ideas") or []
    if ideas:
        lines.append("")
        lines.append("**Top ideas:**")
        for i, idea in enumerate(ideas, 1):
            sig = idea.get("signature", "?")[:8]
            fam = idea.get("family", "?")
            score = idea.get("best_score")
            score_s = f"{score:.4f}" if score is not None else "?"
            lines.append(f"  {i}. `{sig}` ({fam}) score={score_s}")

    rec = payload.get("action_recommendation")
    if rec:
        lines.append("")
        lines.append(f"> {rec}")

    date = payload.get("source_date") or "?"
    lines.append(f"\n_source: {date}_")
    return "\n".join(lines)


# ── worklog rendering ────────────────────────────────────────────────

def render_worklog_entry(payload: dict[str, Any]) -> str:
    """One-line worklog entry for operator logs."""
    cid = payload.get("cycle_id", "?")
    status = payload.get("operator_status", "?")
    pf = payload.get("priority_family") or "none"
    deg = payload.get("degraded_count", 0)
    rec = payload.get("action_recommendation") or ""
    date = payload.get("source_date") or "?"
    return f"[{date}] factory:{cid} status={status} priority={pf} degraded={deg} | {rec}"


# ── Kitt handoff rendering ──────────────────────────────────────────

def render_kitt_handoff(payload: dict[str, Any]) -> dict[str, Any]:
    """Structured handoff for the Kitt quant workflow.

    Returns a flat dict that kitt_quant_workflow can consume directly
    as additional context when generating research briefs.
    """
    ideas = payload.get("top_ideas") or []
    idea_lines = []
    for idea in ideas:
        sig = idea.get("signature", "?")[:8]
        fam = idea.get("family", "?")
        score = idea.get("best_score")
        cls = idea.get("classification", "")
        score_s = f"{score:.4f}" if score is not None else "?"
        idea_lines.append(f"{sig} ({fam}) score={score_s} [{cls}]")

    return {
        "source": "strategy_factory",
        "cycle_id": payload.get("cycle_id"),
        "operator_status": payload.get("operator_status"),
        "source_date": payload.get("source_date"),
        "priority_family": payload.get("priority_family"),
        "action_recommendation": payload.get("action_recommendation"),
        "context_summary": (
            f"Factory status={payload.get('operator_status', '?')}. "
            f"Priority family: {payload.get('priority_family') or 'none'}. "
            f"Degraded: {payload.get('degraded_count', 0)}. "
            f"Strongest data: {payload.get('strongest_dataset') or '?'}. "
            f"Weakest data: {payload.get('weakest_dataset') or '?'}."
        ),
        "top_idea_lines": idea_lines,
    }


# ── artifact writer ─────────────────────────────────────────────────

def write_downstream_artifact(
    result: dict[str, Any],
    *,
    root: Optional[Path] = None,
) -> Path:
    """Write the downstream payload JSON next to the source operator_packet.

    Writes to <date_dir>/factory_downstream.json.
    Returns the path written.
    """
    payload = result["payload"]
    source_date = payload.get("source_date")
    if not source_date:
        raise FactoryPacketError("cannot write artifact: no source_date in payload")

    base = root or FACTORY_ARTIFACT_ROOT
    out_dir = base / source_date
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "factory_downstream.json"
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out_path


# ── convenience entry point ──────────────────────────────────────────

def consume_factory_packet(
    *,
    path: Optional[Path] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Full pipeline: discover -> load -> build payload -> render.

    Returns a dict with keys:
        payload, discord_message, worklog_entry, kitt_handoff.
    """
    packet = load_operator_packet(path=path, root=root)
    payload = build_downstream_payload(packet)
    return {
        "payload": payload,
        "discord_message": render_discord_message(payload),
        "worklog_entry": render_worklog_entry(payload),
        "kitt_handoff": render_kitt_handoff(payload),
    }


# ── runtime emission ────────────────────────────────────────────────

def emit_factory_weekly(
    *,
    path: Optional[Path] = None,
    artifact_root: Optional[Path] = None,
    runtime_root: Optional[Path] = None,
) -> dict[str, Any]:
    """Wire the factory adapter into the live runtime emission path.

    1. Consume the newest operator_packet via the existing adapter.
    2. Emit a ``factory_weekly_summary`` event through the Discord event
       router (→ Sigma owner channel, worklog mirror, Jarvis forward).
    3. Write a Kitt brief to ``state/kitt_briefs/``.
    4. Write the downstream artifact JSON.

    Parameters
    ----------
    path : explicit operator_packet.json path (skips discovery)
    artifact_root : strategy factory artifact root (for packet discovery)
    runtime_root : jarvis-v5 runtime root (for emit_event / kitt briefs)

    Returns
    -------
    dict with keys: payload, discord_message, worklog_entry, kitt_handoff,
                    event_result, kitt_brief_path, artifact_path
    """
    _rt_root = Path(__file__).resolve().parents[2]
    if str(_rt_root) not in sys.path:
        sys.path.insert(0, str(_rt_root))

    from runtime.core.discord_event_router import emit_event  # noqa: E402
    from runtime.core.models import new_id, now_iso  # noqa: E402

    # 1 — consume
    result = consume_factory_packet(path=path, root=artifact_root)
    payload = result["payload"]

    # 2 — emit through the standard event router
    cycle_id = payload.get("cycle_id", "unknown")
    event_result = emit_event(
        kind="factory_weekly_summary",
        agent_id="sigma",
        task_id=f"factory_{cycle_id}",
        detail=result["discord_message"],
        artifact_id=f"factory_{cycle_id}",
        extra={
            "cycle_id": cycle_id,
            "operator_status": payload.get("operator_status"),
            "priority_family": payload.get("priority_family"),
            "source_date": payload.get("source_date"),
        },
        root=runtime_root,
    )

    # 3 — write kitt brief
    rt = Path(runtime_root or Path(__file__).resolve().parents[2])
    briefs_dir = rt / "state" / "kitt_briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    brief_id = new_id("kitt_brief")
    brief_record: dict[str, Any] = {
        "brief_id": brief_id,
        "task_id": f"factory_{cycle_id}",
        "created_at": now_iso(),
        "actor": "factory_adapter",
        "lane": "quant",
        "source": "strategy_factory",
        **result["kitt_handoff"],
    }
    brief_path = briefs_dir / f"{brief_id}.json"
    brief_path.write_text(json.dumps(brief_record, indent=2) + "\n", encoding="utf-8")

    # 4 — write downstream artifact
    artifact_path = write_downstream_artifact(result, root=artifact_root)

    return {
        **result,
        "event_result": event_result,
        "kitt_brief_path": str(brief_path),
        "artifact_path": str(artifact_path),
    }


# ── CLI ─────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Consume Strategy Factory operator_packet and produce downstream artifacts.",
    )
    parser.add_argument("--root", default=None, help="Artifact root (default: ~/.openclaw/...)")
    parser.add_argument("--path", default=None, help="Explicit packet path (skips discovery)")
    parser.add_argument(
        "--format",
        choices=["json", "discord", "worklog", "kitt", "all"],
        default="all",
        help="Output format (default: all)",
    )
    parser.add_argument("--write-artifact", action="store_true", help="Write factory_downstream.json to artifact dir")
    parser.add_argument("--emit", action="store_true", help="Emit through runtime (event router + kitt brief + artifact)")
    parser.add_argument("--runtime-root", default=None, help="Jarvis runtime root (default: auto-detect)")
    args = parser.parse_args()

    root = Path(args.root) if args.root else None
    path = Path(args.path) if args.path else None

    # ── full emission mode ──
    if args.emit:
        rt_root = Path(args.runtime_root) if args.runtime_root else None
        try:
            result = emit_factory_weekly(path=path, artifact_root=root, runtime_root=rt_root)
        except FactoryPacketError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print("=== Emitted ===")
        print(f"Event:    {result['event_result']['event_id']}")
        print(f"Kind:     {result['event_result']['kind']}")
        print(f"Outbox:   {len(result['event_result'].get('outbox_entries', []))} entries")
        print(f"Worklog:  {'yes' if result['event_result'].get('worklog_mirrored') else 'no'}")
        print(f"Jarvis:   {'yes' if result['event_result'].get('jarvis_forwarded') else 'no'}")
        print(f"Brief:    {result['kitt_brief_path']}")
        print(f"Artifact: {result['artifact_path']}")
        print(f"\n=== Discord Message ===\n{result['discord_message']}")
        print(f"\n=== Worklog Entry ===\n{result['worklog_entry']}")
        return 0

    try:
        result = consume_factory_packet(path=path, root=root)
    except FactoryPacketError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    fmt = args.format
    if fmt == "json":
        print(json.dumps(result["payload"], indent=2))
    elif fmt == "discord":
        print(result["discord_message"])
    elif fmt == "worklog":
        print(result["worklog_entry"])
    elif fmt == "kitt":
        print(json.dumps(result["kitt_handoff"], indent=2))
    else:
        print("=== Downstream Payload ===")
        print(json.dumps(result["payload"], indent=2))
        print("\n=== Discord Message ===")
        print(result["discord_message"])
        print("\n=== Worklog Entry ===")
        print(result["worklog_entry"])
        print("\n=== Kitt Handoff ===")
        print(json.dumps(result["kitt_handoff"], indent=2))

    if args.write_artifact:
        try:
            out = write_downstream_artifact(result, root=root)
            print(f"\nArtifact written: {out}", file=sys.stderr)
        except FactoryPacketError as exc:
            print(f"Artifact write failed: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
