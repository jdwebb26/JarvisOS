#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.gateway.source_owned_context_engine import build_context_packet


def _pick(payload: dict, *keys: str, default=None):
    for key in keys:
        if key in payload and payload.get(key) is not None:
            return payload.get(key)
    return default


def main() -> int:
    payload = json.load(sys.stdin)
    root = Path(_pick(payload, "root", default=ROOT)).resolve()
    result = build_context_packet(
        root=root,
        session_key=str(_pick(payload, "session_key", "sessionKey", default="") or ""),
        system_prompt=str(_pick(payload, "system_prompt", "systemPrompt", default="") or ""),
        current_prompt=str(_pick(payload, "current_prompt", "currentPrompt", default="") or ""),
        messages=list(_pick(payload, "messages", default=[]) or []),
        tools=list(_pick(payload, "tools", default=[]) or []),
        skills_prompt=str(_pick(payload, "skills_prompt", "skillsPrompt", default="") or ""),
        agent_id=str(_pick(payload, "agent_id", "agentId", default="") or ""),
        channel=str(_pick(payload, "channel", default="discord") or "discord"),
        provider_id=str(_pick(payload, "provider_id", "providerId", default="") or ""),
        model_id=str(_pick(payload, "model_id", "modelId", default="") or ""),
        context_window_tokens=int(_pick(payload, "context_window_tokens", "contextWindowTokens", default=200000) or 200000),
        raw_user_turn_window=int(_pick(payload, "raw_user_turn_window", "rawUserTurnWindow", default=6) or 6),
        retrieval_budget_tokens=int(_pick(payload, "retrieval_budget_tokens", "retrievalBudgetTokens", default=1200) or 1200),
        episodic_limit=int(_pick(payload, "episodic_limit", "episodicLimit", default=4) or 4),
        semantic_limit=int(_pick(payload, "semantic_limit", "semanticLimit", default=4) or 4),
        max_session_turns=int(_pick(payload, "max_session_turns", "maxSessionTurns", default=200) or 200),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
