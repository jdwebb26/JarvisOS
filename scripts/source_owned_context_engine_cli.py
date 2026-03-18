#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.session_hygiene import pre_context_build_hygiene
from runtime.gateway.source_owned_context_engine import build_context_packet


def _pick(payload: dict, *keys: str, default=None):
    for key in keys:
        if key in payload and payload.get(key) is not None:
            return payload.get(key)
    return default


def _emit_turn_telemetry(
    *,
    agent_id: str,
    session_key: str,
    model_id: str,
    provider_id: str,
    root: Path,
) -> None:
    """Emit per-turn telemetry for any agent's context build.

    Writes to two sinks:
    1. state/acp_telemetry/<agent>.jsonl — durable, operator-queryable
    2. systemd journal via systemd-cat — appears in journalctl under the
       caller's cgroup; when invoked by the gateway subprocess, cgroup is
       openclaw-gateway.service so the entry appears in
       `journalctl --user -u openclaw-gateway.service`.

    Log format: [turn:<agent>] context_build session=<key> path=<acpx|embedded>
                model=<model> provider=<provider> profile=<profile> ts=<iso>
    """
    normalized = str(agent_id or "").strip().lower()
    if not normalized:
        return

    session = str(session_key or "").strip()
    path = "acpx" if ":acp:" in session else "embedded"
    model = str(model_id or "").strip() or "unknown"
    provider = str(provider_id or "").strip() or "unknown"
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Read active profile for visibility
    profile = "unknown"
    try:
        profile_path = root / "state" / "active_profile.json"
        if profile_path.exists():
            profile = json.loads(profile_path.read_text(encoding="utf-8")).get("profile", "local_only")
        else:
            profile = "local_only"
    except Exception:
        pass

    log_line = (
        f"[turn:{normalized}] context_build"
        f" session={session}"
        f" path={path}"
        f" model={model}"
        f" provider={provider}"
        f" profile={profile}"
        f" ts={ts}"
    )

    # --- journal via systemd-cat (inherits cgroup from gateway subprocess) ---
    try:
        subprocess.run(
            ["systemd-cat", "-t", "openclaw-turn", "-p", "info"],
            input=log_line.encode(),
            timeout=2,
            check=False,
        )
    except Exception:
        pass

    # --- durable state file (per-agent JSONL) ---
    try:
        tel_dir = root / "state" / "acp_telemetry"
        tel_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": ts,
            "agent_id": normalized,
            "session_key": session,
            "path": path,
            "model": model,
            "provider": provider,
            "profile": profile,
        }
        # Write to per-agent file
        with open(tel_dir / f"{normalized}.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        # Also maintain the legacy hal_acp.jsonl for backward compatibility
        if normalized == "hal":
            with open(tel_dir / "hal_acp.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def main() -> int:
    payload = json.load(sys.stdin)
    root = Path(_pick(payload, "root", default=ROOT)).resolve()
    agent_id = str(_pick(payload, "agent_id", "agentId", default="") or "")
    session_key = str(_pick(payload, "session_key", "sessionKey", default="") or "")
    model_id = str(_pick(payload, "model_id", "modelId", default="") or "")
    provider_id = str(_pick(payload, "provider_id", "providerId", default="") or "")

    # ── Pre-flight session hygiene for orchestration sessions ──
    # Fires before every context build; only acts on oversized main sessions
    # for jarvis/hal/archimedes.  No-op for Discord-bound or other sessions.
    hygiene_report = pre_context_build_hygiene(
        session_key=session_key,
        openclaw_root=root.parent.parent if root.name == "jarvis-v5" else None,
    )

    result = build_context_packet(
        root=root,
        session_key=session_key,
        system_prompt=str(_pick(payload, "system_prompt", "systemPrompt", default="") or ""),
        current_prompt=str(_pick(payload, "current_prompt", "currentPrompt", default="") or ""),
        messages=list(_pick(payload, "messages", default=[]) or []),
        tools=list(_pick(payload, "tools", default=[]) or []),
        skills_prompt=str(_pick(payload, "skills_prompt", "skillsPrompt", default="") or ""),
        agent_id=agent_id,
        channel=str(_pick(payload, "channel", default="discord") or "discord"),
        provider_id=provider_id,
        model_id=model_id,
        context_window_tokens=int(_pick(payload, "context_window_tokens", "contextWindowTokens", default=200000) or 200000),
        raw_user_turn_window=int(_pick(payload, "raw_user_turn_window", "rawUserTurnWindow", default=6) or 6),
        retrieval_budget_tokens=int(_pick(payload, "retrieval_budget_tokens", "retrievalBudgetTokens", default=1200) or 1200),
        episodic_limit=int(_pick(payload, "episodic_limit", "episodicLimit", default=4) or 4),
        semantic_limit=int(_pick(payload, "semantic_limit", "semanticLimit", default=4) or 4),
        max_session_turns=int(_pick(payload, "max_session_turns", "maxSessionTurns", default=200) or 200),
    )

    if hygiene_report:
        result["sessionHygiene"] = hygiene_report

    _emit_turn_telemetry(
        agent_id=agent_id,
        session_key=session_key,
        model_id=model_id,
        provider_id=provider_id,
        root=root,
    )

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
