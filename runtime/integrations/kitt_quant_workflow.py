#!/usr/bin/env python3
"""kitt_quant_workflow — Kitt quant cockpit: research + brief generation.

Ties together:
  1. SearXNG web search (optional)  — live search results as evidence
  2. Bowser page fetch (optional)   — real browser DOM text for a target URL
  3. NVIDIA / Kimi K2.5             — Kitt synthesis via nvidia_executor
  4. Brief artifact                  — written to state/kitt_briefs/ + workspace/research/

Entry points:
    run_kitt_quant_brief(...)        — main workflow, returns structured result
    probe_kitt_runtime()             — health check without side effects

CLI:
    python3 runtime/integrations/kitt_quant_workflow.py \
        --task-id proof_001 --query "NQ futures regime" \
        --target-url "https://finance.yahoo.com/quote/NQ=F"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.integrations.nvidia_executor import execute_nvidia_chat, load_nvidia_config
from runtime.integrations.searxng_client import search as searxng_search
from runtime.integrations.bowser_adapter import run_bowser_browser_action
from runtime.core.agent_status_store import update_agent_status
from runtime.core.backend_result_store import save_backend_result
from runtime.core.discord_event_router import emit_event
from runtime.core.models import new_id, now_iso


# ---------------------------------------------------------------------------
# Kitt persona prompt
# ---------------------------------------------------------------------------

KITT_SYSTEM = """\
You are Kitt, the quantitative research specialist for the OpenClaw trading system.

Persona:
- Think like a quant: analytical, numerate, evidence-first, skeptical of weak conclusions.
- Separate observation, hypothesis, evidence, and inference clearly.
- Care about sample quality, bias, leakage, variance, and regime sensitivity.
- Flag weak assumptions. Do not oversell conclusions.
- Be concise and direct. Sound smart, not corporate.

Output format — always produce a structured brief with these sections:
1. MARKET STATE — what the evidence shows right now (price level, trend, vol regime)
2. KEY OBSERVATIONS — 2-4 specific facts extracted from the evidence
3. HYPOTHESIS / RISK — what this suggests about near-term NQ regime or edge conditions
4. CONFIDENCE / CAVEATS — how much to trust this given the data quality and recency
5. RECOMMENDED NEXT STEP — one specific actionable quant follow-up (backtest, parameter sweep, etc.)

Keep the brief under 350 words. Use plain section headers. No bullet nesting beyond one level.
"""


# ---------------------------------------------------------------------------
# State directory for Kitt briefs
# ---------------------------------------------------------------------------

def _briefs_dir(root: Optional[Path] = None) -> Path:
    d = Path(root or ROOT).resolve() / "state" / "kitt_briefs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _workspace_research_dir() -> Path:
    d = Path("/home/rollan/.openclaw/workspace/research")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_brief(brief_id: str, payload: dict[str, Any], *, root: Optional[Path] = None) -> Path:
    p = _briefs_dir(root) / f"{brief_id}.json"
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    # Also write a markdown copy to workspace/research/ for operator visibility
    try:
        md_path = _workspace_research_dir() / f"{brief_id}.md"
        md_path.write_text(_render_markdown(payload), encoding="utf-8")
    except Exception:
        pass
    return p


def _render_markdown(payload: dict[str, Any]) -> str:
    brief = payload.get("brief_text", "")
    lines = [
        f"# Kitt Quant Brief — {payload.get('brief_id', '')}",
        f"**Task**: {payload.get('task_id', '')}  ",
        f"**Created**: {payload.get('created_at', '')}  ",
        f"**Model**: {payload.get('model_used', '')}  ",
        "",
    ]
    if payload.get("query"):
        lines += [f"**Query**: {payload['query']}  ", ""]
    if payload.get("target_url"):
        lines += [f"**Page**: {payload['target_url']}  ", ""]
    lines += ["---", "", brief, ""]
    if payload.get("search_results"):
        lines += ["## Sources", ""]
        for r in payload["search_results"][:5]:
            title = r.get("title", "")
            url = r.get("url", "")
            lines.append(f"- [{title}]({url})" if url else f"- {title}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Health probe
# ---------------------------------------------------------------------------

def probe_kitt_runtime(*, root: Optional[Path] = None) -> dict[str, Any]:
    """Check NVIDIA API and SearXNG availability without side effects."""
    results: dict[str, Any] = {}

    # NVIDIA check
    try:
        load_nvidia_config()
        results["nvidia"] = {"reachable": True, "error": None}
    except Exception as exc:
        results["nvidia"] = {"reachable": False, "error": str(exc)}

    # SearXNG check
    try:
        from runtime.integrations.research_backends import SearXNGBackend
        h = SearXNGBackend().healthcheck()
        results["searxng"] = {"reachable": h.get("healthy", False), "status": h.get("status"), "error": None}
    except Exception as exc:
        results["searxng"] = {"reachable": False, "error": str(exc)}

    # Bowser check
    try:
        from runtime.integrations.bowser_adapter import probe_bowser_runtime
        b = probe_bowser_runtime(root=root)
        results["bowser"] = {"reachable": b.get("reachable", False), "version": b.get("version"), "error": b.get("error")}
    except Exception as exc:
        results["bowser"] = {"reachable": False, "error": str(exc)}

    results["kitt_ready"] = (
        results.get("nvidia", {}).get("reachable", False)
    )
    return results


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------

def run_kitt_quant_brief(
    *,
    task_id: str,
    query: str = "",
    target_url: str = "",
    context: str = "",
    max_search_results: int = 5,
    actor: str = "kitt",
    lane: str = "quant",
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Run a Kitt quant research brief.

    Steps:
      1. SearXNG search if query provided
      2. Bowser page fetch if target_url provided
      3. Kimi K2.5 via nvidia_executor — synthesise brief
      4. Write artifact to state/kitt_briefs/ and workspace/research/
      5. Update agent_status for kitt

    Returns structured result with keys:
      status, brief_text, brief_id, search_results, browser_result,
      nvidia_result, artifact_path, error
    """
    brief_id = new_id("kitt_brief")
    created_at = now_iso()
    error_parts: list[str] = []
    search_results: list[dict[str, Any]] = []
    browser_text = ""
    browser_result: dict[str, Any] = {}

    # -----------------------------------------------------------------------
    # Step 1 — SearXNG search
    # -----------------------------------------------------------------------
    if query.strip():
        try:
            sq = searxng_search(
                query.strip(),
                actor=actor,
                lane=lane,
                root=root,
                max_results=max_search_results,
            )
            search_results = sq.get("results") or []
        except Exception as exc:
            error_parts.append(f"searxng_error: {exc}")

    # -----------------------------------------------------------------------
    # Step 2 — Bowser page fetch
    # -----------------------------------------------------------------------
    if target_url.strip():
        try:
            br = run_bowser_browser_action(
                task_id=task_id,
                actor=actor,
                lane=lane,
                action_type="text",
                target_url=target_url.strip(),
                execute=True,
                root=root,
            )
            browser_result = br
            # Extract text from browser action result.
            # full_text is stored in snapshot.payload.snapshot_refs.full_text (text actions).
            # Fallback: outcome_summary (first 1500 chars).
            bag = br.get("browser_action_result", {})
            snap_payload = bag.get("snapshot", {}).get("payload", {})
            snap_refs_payload = snap_payload.get("snapshot_refs", {}) or {}
            full_text = (
                snap_refs_payload.get("full_text")
                or bag.get("result", {}).get("outcome_summary", "")
            )
            browser_text = str(full_text or "")
        except Exception as exc:
            error_parts.append(f"bowser_error: {exc}")

    # -----------------------------------------------------------------------
    # Step 3 — Build evidence block for Kitt
    # -----------------------------------------------------------------------
    evidence_parts: list[str] = []

    if search_results:
        evidence_parts.append("## Search Results")
        for i, r in enumerate(search_results[:max_search_results], 1):
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = r.get("content", r.get("snippet", ""))
            evidence_parts.append(f"{i}. [{title}]({url})\n   {snippet}")

    if browser_text:
        evidence_parts.append(f"## Live Page Content ({target_url})")
        # Truncate to stay within token budget
        evidence_parts.append(browser_text[:3000])

    if context.strip():
        evidence_parts.append("## Additional Context")
        evidence_parts.append(context.strip())

    if not evidence_parts:
        evidence_parts.append(
            "No live evidence gathered. Provide analysis based on general knowledge "
            "of NQ futures market structure and current regime indicators."
        )

    user_prompt = (
        f"Research task: {query or target_url or 'NQ futures market overview'}\n\n"
        + "\n\n".join(evidence_parts)
        + "\n\nProduce a concise operator brief following your standard format."
    )

    # -----------------------------------------------------------------------
    # Step 4 — NVIDIA / Kimi K2.5 call
    # -----------------------------------------------------------------------
    nvidia_result = execute_nvidia_chat(
        task_id=task_id,
        actor=actor,
        lane=lane,
        messages=[
            {"role": "system", "content": KITT_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=4096,  # Kimi K2.5 uses thinking tokens; 1024 leaves content budget empty
        root=root,
    )

    brief_text = nvidia_result.get("content", "")
    nvidia_ok = nvidia_result.get("status") == "completed" and bool(brief_text)
    nvidia_transient = nvidia_result.get("transient", False) or nvidia_result.get("status") == "transient_error"
    if not nvidia_ok:
        prefix = "nvidia_transient" if nvidia_transient else "nvidia_error"
        error_parts.append(f"{prefix}: {nvidia_result.get('error', 'empty response')}")

    # -----------------------------------------------------------------------
    # Step 5 — Save artifact
    # -----------------------------------------------------------------------
    payload = {
        "brief_id": brief_id,
        "task_id": task_id,
        "created_at": created_at,
        "updated_at": now_iso(),
        "actor": actor,
        "lane": lane,
        "query": query,
        "target_url": target_url,
        "model_used": "moonshotai/kimi-k2.5",
        "brief_text": brief_text,
        "search_result_count": len(search_results),
        "search_results": search_results[:max_search_results],
        "browser_fetched": bool(browser_text),
        "nvidia_request_id": nvidia_result.get("request_id"),
        "nvidia_result_id": nvidia_result.get("result_id"),
        "nvidia_usage": nvidia_result.get("usage", {}),
        "error": "; ".join(error_parts) if error_parts else "",
        "schema_version": "v1",
    }
    artifact_path = ""
    try:
        p = _save_brief(brief_id, payload, root=root)
        artifact_path = str(p)
    except Exception as exc:
        error_parts.append(f"save_error: {exc}")

    # -----------------------------------------------------------------------
    # Step 6 — Update kitt agent_status
    # -----------------------------------------------------------------------
    try:
        headline = (
            f"Kitt brief ready: {(query or target_url or 'quant overview')[:60]}."
            if nvidia_ok
            else f"Kitt brief FAILED: {'; '.join(error_parts)[:80]}"
        )
        update_agent_status(
            "kitt",
            headline,
            state="idle" if nvidia_ok else "error",
            current_task_id=task_id,
            last_result=brief_text[:120] if brief_text else ("; ".join(error_parts) or "no result"),
            root=root,
        )
    except Exception:
        pass

    # -----------------------------------------------------------------------
    # Step 7 — Backend result store + Discord event surfacing
    # -----------------------------------------------------------------------
    try:
        save_backend_result(
            task_id=task_id,
            agent_id="kitt",
            backend="kitt_quant",
            status="ok" if nvidia_ok else "error",
            summary=f"Kitt brief {brief_id}: {(query or target_url or 'quant overview')[:80]}",
            artifact_refs={"brief_path": artifact_path, "brief_id": brief_id} if artifact_path else {},
            error="; ".join(error_parts) if error_parts else "",
            extra={"model_used": "moonshotai/kimi-k2.5", "search_count": len(search_results)},
            root=root,
        )
    except Exception:
        pass

    try:
        preview = brief_text[:100].replace("\n", " ") if brief_text else "no content"
        emit_event(
            "kitt_brief_completed" if nvidia_ok else "kitt_brief_failed",
            "kitt",
            task_id=task_id,
            detail=f"{brief_id}: {preview}" if nvidia_ok else f"FAILED: {'; '.join(error_parts)[:100]}",
            artifact_id=brief_id,
            extra={"artifact_path": artifact_path, "model_used": "moonshotai/kimi-k2.5"},
            root=root,
        )
    except Exception:
        pass

    return {
        "status": "completed" if nvidia_ok else "failed",
        "brief_id": brief_id,
        "brief_text": brief_text,
        "artifact_path": artifact_path,
        "search_results": search_results,
        "browser_result": browser_result,
        "nvidia_result": nvidia_result,
        "model_used": "moonshotai/kimi-k2.5",
        "error": "; ".join(error_parts) if error_parts else "",
        "transient": nvidia_transient,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Kitt quant workflow — live research brief.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", default="", help="Task ID (generated if omitted)")
    parser.add_argument("--actor", default="kitt", help="Actor name")
    parser.add_argument("--lane", default="quant", help="Lane name")
    parser.add_argument("--query", default="", help="SearXNG search query")
    parser.add_argument("--target-url", default="", help="URL to fetch via Bowser")
    parser.add_argument("--context", default="", help="Extra context text")
    parser.add_argument("--probe", action="store_true", help="Health probe and exit")
    parser.add_argument("--brief-only", action="store_true", help="Print only the brief text")
    args = parser.parse_args()

    resolved_root = Path(args.root).resolve()

    if args.probe:
        print(json.dumps(probe_kitt_runtime(root=resolved_root), indent=2))
        return 0

    if not args.query and not args.target_url:
        parser.error("--query or --target-url (or both) required unless --probe")

    task_id = args.task_id or new_id("kitt_task")
    result = run_kitt_quant_brief(
        task_id=task_id,
        query=args.query,
        target_url=args.target_url,
        context=args.context,
        actor=args.actor,
        lane=args.lane,
        root=resolved_root,
    )

    if args.brief_only:
        print(result.get("brief_text", ""))
        return 0 if result.get("status") == "completed" else 1

    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
