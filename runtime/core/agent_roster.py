#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from runtime.skills.skill_store import list_skills


ROOT = Path(__file__).resolve().parents[2]


CANONICAL_AGENT_ROSTER: dict[str, dict[str, Any]] = {
    "jarvis": {
        "agent_id": "jarvis",
        "display_name": "Jarvis",
        "role": "primary user-facing AI OS / CEO / orchestrator",
        "status": "wired",
        "kind": "control_plane",
        "responsibilities": [
            "user interaction",
            "task routing",
            "approvals coordination",
            "session and context handling",
            "summary and handoff",
            "voice and TTS convenience",
            "light operator status visibility",
        ],
        "avoid": [
            "deep research daemon work",
            "browser automation workflows",
            "maintenance and queue-draining chores",
        ],
        "task_classes": ["general", "docs", "approval", "output"],
        "routing_intent": {
            "preferred_model": "Qwen3.5-9B",
            "fallbacks": ["Qwen3.5-35B", "Qwen3.5-122B"],
            "primary_backend": "qwen_executor",
        },
        "allowed_tool_categories": ["coordination", "repo_read", "engineering", "voice", "general"],
        "denied_tool_categories": ["research", "browser", "maintenance"],
        "denied_tool_name_tokens": [],
        "preferred_skill_task_classes": ["general", "docs", "approval", "output"],
        "preferred_skill_backends": ["qwen_executor", "qwen_planner"],
        "preferred_channels": ["jarvis", "discord", "voice"],
    },
    "hal": {
        "agent_id": "hal",
        "display_name": "HAL",
        "role": "primary coding / implementation agent",
        "status": "wired",
        "kind": "specialist",
        "responsibilities": [
            "code changes",
            "patching",
            "local engineering execution",
            "tests and build loops",
        ],
        "avoid": ["deep research synthesis", "browser automation", "general operator chat"],
        "task_classes": ["code", "docs", "deploy"],
        "routing_intent": {
            "preferred_model": "Qwen3.5-35B",
            "fallbacks": ["Qwen3.5-122B"],
            "primary_backend": "qwen_executor",
        },
        "allowed_tool_categories": ["coordination", "repo_read", "engineering", "general"],
        "denied_tool_categories": ["browser", "research"],
        "denied_tool_name_tokens": [],
        "preferred_skill_task_classes": ["code", "docs", "deploy"],
        "preferred_skill_backends": ["qwen_executor"],
        "preferred_channels": ["tasks", "code-review"],
    },
    "archimedes": {
        "agent_id": "archimedes",
        "display_name": "Archimedes",
        "role": "code reviewer / architecture reviewer / technical critic",
        "status": "wired",
        "kind": "reviewer",
        "responsibilities": [
            "code review",
            "architecture review",
            "bug and risk finding",
            "second-pass critique of implementation output",
        ],
        "avoid": ["general-purpose user chat", "broad browsing", "creative ideation"],
        "task_classes": ["review", "code", "deploy"],
        "routing_intent": {
            "preferred_model": "Qwen3.5-122B",
            "fallbacks": ["Qwen3.5-35B"],
            "primary_backend": "qwen_planner",
        },
        "allowed_tool_categories": ["coordination", "repo_read", "engineering", "general"],
        "denied_tool_categories": ["browser", "research", "maintenance"],
        "denied_tool_name_tokens": ["write", "patch", "apply", "edit", "commit"],
        "preferred_skill_task_classes": ["code", "review", "deploy"],
        "preferred_skill_backends": ["qwen_executor", "qwen_planner"],
        "preferred_channels": ["code-review", "review"],
    },
    "anton": {
        "agent_id": "anton",
        "display_name": "Anton",
        "role": "supreme reviewer / high-stakes final brain",
        "status": "wired",
        "kind": "reviewer",
        "responsibilities": [
            "high-stakes review",
            "final judgment",
            "strategic critique",
            "difficult approval and review decisions",
        ],
        "avoid": ["background chores", "routine chat", "browser automation"],
        "task_classes": ["approval", "review", "deploy", "quant"],
        "routing_intent": {
            "preferred_model": "Qwen3.5-122B",
            "fallbacks": ["Qwen3.5-35B"],
            "primary_backend": "qwen_planner",
        },
        "allowed_tool_categories": ["coordination", "repo_read", "general"],
        "denied_tool_categories": ["browser", "research", "maintenance"],
        "denied_tool_name_tokens": ["write", "patch", "apply", "edit", "exec", "shell", "bash"],
        "preferred_skill_task_classes": ["approval", "review", "deploy", "quant"],
        "preferred_skill_backends": ["qwen_planner", "qwen_executor"],
        "preferred_channels": ["audit", "review"],
    },
    "hermes": {
        "agent_id": "hermes",
        "display_name": "Hermes",
        "role": "deep research / structured research daemon",
        "status": "implemented_but_blocked_by_external_runtime",
        "kind": "daemon",
        "responsibilities": [
            "deep research",
            "evidence gathering",
            "research synthesis",
            "candidate-oriented research output",
        ],
        "avoid": ["public product identity", "direct approval bypass", "direct memory promotion"],
        "task_classes": ["research", "docs", "quant"],
        "routing_intent": {
            "preferred_model": "Qwen3.5-122B",
            "fallbacks": ["Qwen3.5-35B"],
            "primary_backend": "hermes_adapter",
        },
        "allowed_tool_categories": ["coordination", "repo_read", "research", "general"],
        "denied_tool_categories": ["browser", "maintenance"],
        "denied_tool_name_tokens": [],
        "preferred_skill_task_classes": ["research", "docs", "quant"],
        "preferred_skill_backends": ["hermes_adapter", "qwen_planner"],
        "preferred_channels": ["tasks", "research"],
    },
    "scout": {
        "agent_id": "scout",
        "display_name": "Scout",
        "role": "web scout / reconnaissance / collection",
        "status": "wired",
        "kind": "specialist",
        "responsibilities": [
            "web browsing",
            "scraping and collection",
            "source gathering",
            "lead generation for research tasks",
        ],
        "avoid": ["final synthesis", "approvals", "browser automation workflows"],
        "task_classes": ["research", "docs", "general"],
        "routing_intent": {
            "preferred_model": "Qwen3.5-35B",
            "fallbacks": ["Qwen3.5-122B"],
            "primary_backend": "qwen_executor",
        },
        "allowed_tool_categories": ["coordination", "research", "general"],
        "denied_tool_categories": ["browser", "maintenance"],
        "denied_tool_name_tokens": [],
        "preferred_skill_task_classes": ["research", "docs"],
        "preferred_skill_backends": ["qwen_executor", "hermes_adapter"],
        "preferred_channels": ["tasks", "research"],
    },
    "bowser": {
        "agent_id": "bowser",
        "display_name": "Bowser",
        "role": "browser automation / tab workflow specialist",
        "status": "scaffold_only",
        "kind": "subsystem",
        "responsibilities": [
            "browser actions",
            "tab and workflow operations",
            "website interaction workflows",
        ],
        "avoid": ["general chat", "deep synthesis", "task authority"],
        "task_classes": ["multimodal", "general"],
        "routing_intent": {
            "preferred_model": "Qwen3.5-35B",
            "fallbacks": ["Qwen3.5-122B"],
            "primary_backend": "browser_bridge",
        },
        "allowed_tool_categories": ["coordination", "browser", "general"],
        "denied_tool_categories": ["research", "maintenance"],
        "denied_tool_name_tokens": [],
        "preferred_skill_task_classes": ["general", "multimodal"],
        "preferred_skill_backends": ["browser_bridge", "qwen_executor"],
        "preferred_channels": ["tasks"],
    },
    "muse": {
        "agent_id": "muse",
        "display_name": "Muse",
        "role": "creative writing / ideation / copy specialist",
        "status": "policy_backed",
        "kind": "specialist",
        "responsibilities": [
            "creative writing",
            "ideation",
            "naming and branding",
            "higher-temperature assistance",
        ],
        "avoid": ["approvals", "browser workflows", "low-level maintenance"],
        "task_classes": ["docs", "general", "output"],
        "routing_intent": {
            "preferred_model": "Qwen3.5-35B",
            "fallbacks": ["Qwen3.5-9B"],
            "primary_backend": "qwen_executor",
        },
        "allowed_tool_categories": ["coordination", "repo_read", "general"],
        "denied_tool_categories": ["browser", "research", "maintenance"],
        "denied_tool_name_tokens": ["exec", "shell", "bash", "patch", "write_file"],
        "preferred_skill_task_classes": ["docs", "general", "output"],
        "preferred_skill_backends": ["qwen_executor"],
        "preferred_channels": ["jarvis"],
    },
    "ralph": {
        "agent_id": "ralph",
        "display_name": "Ralph",
        "role": "overflow / maintenance / consolidation worker",
        "status": "implemented_but_blocked_by_external_runtime",
        "kind": "daemon",
        "responsibilities": [
            "maintenance chores",
            "queue draining",
            "low-priority miscellaneous work",
            "memory consolidation",
        ],
        "avoid": ["public-facing chat", "high-stakes final judgment"],
        "task_classes": ["general", "output", "flowstate"],
        "routing_intent": {
            "preferred_model": "Qwen3.5-35B",
            "fallbacks": ["Qwen3.5-122B"],
            "primary_backend": "qwen_executor",
        },
        "allowed_tool_categories": ["coordination", "repo_read", "engineering", "maintenance", "general"],
        "denied_tool_categories": ["browser"],
        "denied_tool_name_tokens": [],
        "preferred_skill_task_classes": ["general", "output", "flowstate"],
        "preferred_skill_backends": ["qwen_executor", "memory_spine"],
        "preferred_channels": ["tasks"],
    },
}


TOOL_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("browser", ("browser", "tab", "page", "navigate", "click", "form", "pinchtab")),
    ("research", ("search", "web", "scrape", "crawl", "source", "searx", "collect")),
    ("maintenance", ("cleanup", "janitor", "queue", "drain", "vacuum", "maintenance")),
    ("voice", ("voice", "tts", "audio", "speak", "spotify")),
    ("coordination", ("task", "review", "approval", "session", "handoff", "status", "notify", "summary")),
    ("engineering", ("exec", "shell", "bash", "command", "terminal", "git", "patch", "write", "edit", "diff", "test", "build", "pytest", "npm", "pnpm")),
    ("repo_read", ("read", "open", "inspect", "grep", "rg", "cat", "sed", "ls", "file", "repo", "workspace")),
)


def list_agent_ids() -> list[str]:
    return list(CANONICAL_AGENT_ROSTER.keys())


def get_agent_profile(agent_id: str) -> dict[str, Any]:
    normalized = str(agent_id or "").strip().lower()
    if normalized not in CANONICAL_AGENT_ROSTER:
        normalized = "jarvis"
    return dict(CANONICAL_AGENT_ROSTER[normalized])


def infer_agent_id(*, agent_id: str = "", session_key: str = "", lane: str = "") -> str:
    normalized = str(agent_id or "").strip().lower()
    if normalized in CANONICAL_AGENT_ROSTER:
        return normalized
    session = str(session_key or "").strip()
    if session.startswith("agent:"):
        parts = session.split(":")
        if len(parts) > 1 and parts[1].strip().lower() in CANONICAL_AGENT_ROSTER:
            return parts[1].strip().lower()
    lane_value = str(lane or "").strip().lower()
    if lane_value in CANONICAL_AGENT_ROSTER:
        return lane_value
    return "jarvis"


def classify_tool_category(tool: dict[str, Any]) -> str:
    name = " ".join(
        [
            str(tool.get("name") or ""),
            str(tool.get("toolName") or ""),
            str(tool.get("description") or ""),
        ]
    ).lower()
    for category, tokens in TOOL_CATEGORY_RULES:
        if any(token in name for token in tokens):
            return category
    return "general"


def filter_tools_for_agent(
    agent_id: str,
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    profile = get_agent_profile(agent_id)
    allowed_categories = set(profile.get("allowed_tool_categories") or [])
    denied_categories = set(profile.get("denied_tool_categories") or [])
    denied_name_tokens = [str(token).lower() for token in profile.get("denied_tool_name_tokens") or []]
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    drop_reasons: dict[str, int] = {}
    for tool in tools:
        name = str(tool.get("name") or tool.get("toolName") or "tool")
        category = classify_tool_category(tool)
        lowered_name = name.lower()
        denied_by_name = next((token for token in denied_name_tokens if token and token in lowered_name), "")
        if denied_by_name:
            dropped.append(tool)
            reason = f"name_token:{denied_by_name}"
            drop_reasons[reason] = drop_reasons.get(reason, 0) + 1
            continue
        if category in denied_categories:
            dropped.append(tool)
            reason = f"category:{category}"
            drop_reasons[reason] = drop_reasons.get(reason, 0) + 1
            continue
        if allowed_categories and category not in allowed_categories and category != "general":
            dropped.append(tool)
            reason = f"not_allowed:{category}"
            drop_reasons[reason] = drop_reasons.get(reason, 0) + 1
            continue
        kept.append(tool)
    return {
        "agentId": profile["agent_id"],
        "beforeCount": len(tools),
        "afterCount": len(kept),
        "droppedCount": len(dropped),
        "dropReasons": drop_reasons,
        "tools": kept,
    }


def _skill_matches_agent(*, agent: dict[str, Any], skill: Any) -> bool:
    task_classes = set(str(item).lower() for item in getattr(skill, "task_classes", []) or [])
    allowed_backends = set(str(item) for item in getattr(skill, "allowed_backends", []) or [])
    preferred_task_classes = set(str(item).lower() for item in agent.get("preferred_skill_task_classes") or [])
    preferred_skill_backends = set(str(item) for item in agent.get("preferred_skill_backends") or [])
    if task_classes and preferred_task_classes.intersection(task_classes):
        return True
    if allowed_backends and preferred_skill_backends.intersection(allowed_backends):
        return True
    tags = set(str(item).lower() for item in (getattr(skill, "metadata", {}) or {}).get("tags", []) or [])
    identity_tokens = {
        agent["agent_id"],
        agent["display_name"].lower(),
        str(agent.get("kind") or "").lower(),
    }
    return bool(tags.intersection(identity_tokens))


def build_agent_roster_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    resolved_root = Path(root or ROOT).resolve()
    runtime_policy_path = resolved_root / "config" / "runtime_routing_policy.json"
    runtime_policy: dict[str, Any] = {}
    if runtime_policy_path.exists():
        try:
            runtime_policy = json.loads(runtime_policy_path.read_text(encoding="utf-8"))
        except Exception:
            runtime_policy = {}
    configured_agent_policies = dict(runtime_policy.get("agent_policies") or {})
    skills = list_skills(root=resolved_root)
    rows: list[dict[str, Any]] = []
    wired = 0
    partial = 0
    blocked = 0
    for agent_id in list_agent_ids():
        profile = get_agent_profile(agent_id)
        routing_policy = dict(configured_agent_policies.get(agent_id) or {})
        matched_skills = [skill.skill_name for skill in skills if _skill_matches_agent(agent=profile, skill=skill)]
        row = {
            "agent_id": agent_id,
            "display_name": profile["display_name"],
            "role": profile["role"],
            "status": profile["status"],
            "kind": profile["kind"],
            "responsibilities": list(profile.get("responsibilities") or []),
            "avoid": list(profile.get("avoid") or []),
            "task_classes": list(profile.get("task_classes") or []),
            "routing_intent": dict(profile.get("routing_intent") or {}),
            "configured_routing_policy": routing_policy,
            "tool_policy": {
                "allowed_categories": list(profile.get("allowed_tool_categories") or []),
                "denied_categories": list(profile.get("denied_tool_categories") or []),
                "denied_name_tokens": list(profile.get("denied_tool_name_tokens") or []),
            },
            "preferred_channels": list(profile.get("preferred_channels") or []),
            "matched_skill_names": matched_skills[:10],
            "matched_skill_count": len(matched_skills),
            "routing_policy_present": bool(routing_policy),
        }
        rows.append(row)
        if profile["status"] == "wired":
            wired += 1
        elif profile["status"] == "policy_backed":
            partial += 1
        else:
            blocked += 1
    return {
        "schema_version": "v5.2_agent_roster_v1",
        "agent_count": len(rows),
        "wired_agent_count": wired,
        "partial_agent_count": partial,
        "blocked_or_scaffold_agent_count": blocked,
        "configured_agent_policy_count": len(configured_agent_policies),
        "rows": rows,
        "review_hierarchy": {
            "implementation_agent": "hal",
            "technical_reviewer": "archimedes",
            "supreme_reviewer": "anton",
        },
        "notes": [
            "Jarvis remains the public face and control plane.",
            "Hermes and Ralph are real subsystem lanes, but current live availability remains external-runtime dependent.",
            "Bowser is policy-mapped to bounded browser automation, but the browser bridge itself remains scaffold-only.",
            "The current repo does not implement a second autonomous orchestration mesh; specialization is policy-backed through routing, context prep, review roles, and subsystem adapters.",
        ],
    }
