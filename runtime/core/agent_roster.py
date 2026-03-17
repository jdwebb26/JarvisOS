#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from runtime.skills.skill_store import list_skills


ROOT = Path(__file__).resolve().parents[2]

SKILL_INVENTORY_PATH = ROOT / "config" / "skill_inventory.json"


def _load_installed_skill_names() -> set[str]:
    try:
        payload = json.loads(SKILL_INVENTORY_PATH.read_text(encoding="utf-8"))
        skills = payload.get("skills") or []
        names = {
            str(item.get("name") or "").strip().lower()
            for item in skills
            if str(item.get("name") or "").strip()
        }
        return names
    except Exception:
        return set()


def _normalize_skill_names(items: list[str]) -> list[str]:
    normalized: list[str] = []
    for item in items:
        text = str(item or "").strip().lower()
        if not text:
            continue
        if INSTALLED_SKILL_NAMES and text not in INSTALLED_SKILL_NAMES:
            continue
        normalized.append(text)
    return normalized


INSTALLED_SKILL_NAMES = _load_installed_skill_names()

COMMON_DENIED_SKILL_NAMES = ["clawhub", "weather", "gog"]

AGENT_SKILL_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "jarvis": ("discord", "session-logs", "voice-call", "sherpa-onnx-tts", "model-usage"),
    "hal": ("coding-agent", "github", "gh-issues", "session-logs", "model-usage"),
    "qwen": ("discord", "session-logs", "voice-call", "sherpa-onnx-tts", "model-usage"),
    "archimedes": ("session-logs", "model-usage"),
    "anton": ("session-logs", "model-usage"),
    "hermes": ("blogwatcher", "summarize", "goplaces", "session-logs", "model-usage"),
    "scout": ("blogwatcher", "summarize", "goplaces", "session-logs", "xurl"),
    "bowser": ("session-logs",),
    "muse": ("summarize", "songsee", "sag", "session-logs"),
    "ralph": ("ordercli", "session-logs"),
    "kitt": ("session-logs", "model-usage"),
}

AGENT_TOOL_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "jarvis": (
        "message",
        "tts",
        "gateway",
        "agents_list",
        "sessions_list",
        "sessions_history",
        "sessions_send",
        "sessions_yield",
        "sessions_spawn",
        "session_status",
        "memory_search",
        "memory_get",
        "read",
    ),
    "hal": (
        "read",
        "edit",
        "write",
        "exec",
        "process",
        "cron",
        "message",
        "gateway",
        "sessions_list",
        "sessions_history",
        "sessions_send",
        "sessions_yield",
        "sessions_spawn",
        "session_status",
        "subagents",
        "memory_search",
        "memory_get",
    ),
    "archimedes": (
        "read",
        "sessions_list",
        "sessions_history",
        "session_status",
        "memory_search",
        "memory_get",
    ),
    "anton": (
        "message",
        "read",
        "sessions_list",
        "sessions_history",
        "session_status",
        "memory_search",
        "memory_get",
    ),
    "hermes": (
        "message",
        "gateway",
        "read",
        "process",
        "sessions_list",
        "sessions_history",
        "sessions_send",
        "sessions_yield",
        "sessions_spawn",
        "session_status",
        "memory_search",
        "memory_get",
    ),
    "qwen": (
        "read",
        "message",
        "tts",
        "gateway",
        "agents_list",
        "sessions_list",
        "sessions_history",
        "sessions_send",
        "sessions_yield",
        "sessions_spawn",
        "session_status",
        "memory_search",
        "memory_get",
    ),
    "scout": (
        "read",
        "process",
        "web_search",
        "web_fetch",
        "image",
        "sessions_list",
        "sessions_history",
        "sessions_send",
        "sessions_yield",
        "sessions_spawn",
        "session_status",
    ),
    "bowser": (
        "browser",
        "process",
        "sessions_list",
        "sessions_history",
        "sessions_send",
        "sessions_yield",
        "sessions_spawn",
        "session_status",
    ),
    "muse": (
        "image",
        "read",
        "tts",
        "message",
    ),
    "ralph": (
        "process",
        "cron",
        "sessions_list",
        "sessions_history",
        "sessions_send",
        "sessions_yield",
        "sessions_spawn",
        "session_status",
        "memory_search",
        "memory_get",
    ),
    "kitt": (
        "read",
        "process",
        "memory_search",
        "memory_get",
        "message",
        "session_status",
        "sessions_list",
        "sessions_history",
    ),
}

CANONICAL_AGENT_ROSTER: dict[str, dict[str, Any]] = {
    "jarvis": {
        "agent_id": "jarvis",
        "display_name": "Jarvis",
        "role": "front door / CEO / orchestrator",
        "status": "wired",
        "kind": "control_plane",
        "responsibilities": [
            "operator-facing coordination and approval routing",
            "session context stewardship",
            "status, summary, and handoff",
            "voice/TTS convenience",
            "delegation and public status visibility",
        ],
        "avoid": [
            "deep research and evidence gathering",
            "browser automation token tasks",
            "repeated maintenance or cleanup chores",
            "pretending to be every specialist",
        ],
        "task_classes": ["general", "docs", "approval", "output"],
        "routing_intent": {
            "preferred_model": "Qwen3.5-9B",
            "fallbacks": ["Qwen3.5-35B", "Qwen3.5-122B"],
            "primary_backend": "qwen_executor",
        },
        "allowed_tool_categories": ["coordination", "voice", "repo_read", "general"],
        "denied_tool_categories": ["research", "browser", "maintenance", "engineering"],
        "denied_tool_name_tokens": ["clawhub", "weather"],
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
            "preferred_model": "Qwen3-Coder-30B",
            "fallbacks": ["Qwen3.5-122B"],
            "primary_backend": "qwen_executor",
        },
        "allowed_tool_categories": ["coordination", "repo_read", "engineering", "general"],
        "denied_tool_categories": ["browser", "research", "maintenance"],
        "denied_tool_name_tokens": ["clawhub", "weather"],
        "preferred_skill_task_classes": ["code", "docs", "deploy"],
        "preferred_skill_backends": ["qwen_executor"],
        "preferred_channels": ["tasks", "code-review"],
    },
    "qwen": {
        "agent_id": "qwen",
        "display_name": "Qwen",
        "role": "autonomous qwen specialist",
        "status": "wired",
        "kind": "specialist",
        "responsibilities": [
            "autonomous coding and repo execution",
            "model-aware job completion",
            "delegation back to HAL when human handoff is required",
        ],
        "avoid": ["browser automation workflows", "public-facing approvals", "creative ideation"],
        "task_classes": ["code", "docs", "deploy"],
        "routing_intent": {
            "preferred_model": "Qwen3.5-9B",
            "fallbacks": ["Qwen3.5-35B"],
            "primary_backend": "qwen_executor",
        },
        "allowed_tool_categories": ["coordination", "repo_read", "engineering", "general"],
        "denied_tool_categories": ["browser", "review", "maintenance"],
        "denied_tool_name_tokens": ["clawhub", "weather"],
        "preferred_skill_task_classes": ["code", "docs", "deploy"],
        "preferred_skill_backends": ["qwen_executor"],
        "preferred_channels": ["qwen"],
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
            "preferred_model": "Qwen3-Coder-Next",
            "fallbacks": ["Qwen3.5-122B"],
            "primary_backend": "qwen_planner",
        },
        "allowed_tool_categories": ["coordination", "repo_read", "engineering", "general"],
        "denied_tool_categories": ["browser", "research", "maintenance"],
        "denied_tool_name_tokens": ["write", "patch", "apply", "edit", "commit", "clawhub", "weather"],
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
        "denied_tool_name_tokens": ["write", "patch", "apply", "edit", "exec", "shell", "bash", "clawhub", "weather"],
        "preferred_skill_task_classes": ["approval", "review", "deploy", "quant"],
        "preferred_skill_backends": ["qwen_planner", "qwen_executor"],
        "preferred_channels": ["audit", "review"],
    },
    "hermes": {
        "agent_id": "hermes",
        "display_name": "Hermes",
        "role": "execution / hermes-agent research integrator",
        "status": "implemented_but_blocked_by_external_runtime",
        "kind": "daemon",
        "responsibilities": [
            "hermes-agent or autoresearch plumbing",
            "execution and orchestration status checks",
            "runtime health/context handoff",
            "structured research/evidence work when invoked",
        ],
        "avoid": [
            "public product identity",
            "direct approval bypass",
            "browser automation loops",
            "unbounded maintenance chores",
        ],
        "task_classes": ["research", "deploy", "flowstate", "general"],
        "routing_intent": {
            "preferred_model": "Qwen3.5-122B",
            "fallbacks": ["Qwen3.5-35B"],
            "primary_backend": "hermes_adapter",
        },
        "allowed_tool_categories": ["coordination", "engineering", "research", "maintenance", "general"],
        "denied_tool_categories": ["browser", "voice"],
        "denied_tool_name_tokens": ["browser", "cleanup", "queue", "voice", "clawhub", "weather"],
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
        "avoid": ["final synthesis", "approvals", "browser automation workflows", "execution/maintenance chores"],
        "task_classes": ["research", "docs", "general"],
        "routing_intent": {
            "preferred_model": "Qwen3.5-35B",
            "fallbacks": ["Qwen3.5-122B"],
            "primary_backend": "qwen_executor",
        },
        "allowed_tool_categories": ["coordination", "research", "browser", "general"],
        "denied_tool_categories": ["maintenance", "review", "creative", "voice", "engineering"],
        "denied_tool_name_tokens": ["clawhub", "weather"],
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
        "denied_tool_categories": ["research", "maintenance", "engineering", "review", "creative", "voice"],
        "denied_tool_name_tokens": ["clawhub", "weather"],
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
        "avoid": ["approvals", "browser workflows", "low-level maintenance", "deep engineering chores"],
        "task_classes": ["docs", "general", "output"],
        "routing_intent": {
            "preferred_model": "Qwen3.5-35B",
            "fallbacks": ["Qwen3.5-9B"],
            "primary_backend": "qwen_executor",
        },
        "allowed_tool_categories": ["coordination", "creative", "repo_read", "general"],
        "denied_tool_categories": ["browser", "research", "maintenance", "engineering", "review", "voice"],
        "denied_tool_name_tokens": ["exec", "shell", "bash", "patch", "write_file", "clawhub", "weather"],
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
        "avoid": ["public-facing chat", "high-stakes final judgment", "forced approvals", "creative production"],
        "task_classes": ["general", "output", "flowstate"],
        "routing_intent": {
            "preferred_model": "Qwen3.5-35B",
            "fallbacks": ["Qwen3.5-122B"],
            "primary_backend": "qwen_executor",
        },
        "allowed_tool_categories": ["coordination", "repo_read", "engineering", "maintenance", "general"],
        "denied_tool_categories": ["browser", "review", "creative", "voice"],
        "denied_tool_name_tokens": ["browser", "approval", "creative", "voice", "clawhub", "weather"],
        "preferred_skill_task_classes": ["general", "output", "flowstate"],
        "preferred_skill_backends": ["qwen_executor", "memory_spine"],
        "preferred_channels": ["tasks"],
    },
    "kitt": {
        "agent_id": "kitt",
        "display_name": "Kitt",
        "role": "quantitative research / analyst specialist",
        "status": "wired",
        "kind": "specialist",
        "responsibilities": [
            "quantitative reasoning and statistical interpretation",
            "hypothesis design and experiment critique",
            "backtest and result critique",
            "strategy diagnostics and robustness analysis",
            "research synthesis for decision support",
        ],
        "avoid": [
            "live execution and approvals",
            "browser automation",
            "engineering chores",
            "pretending confidence that the data does not support",
        ],
        "task_classes": ["research", "quant", "docs"],
        "routing_intent": {
            "preferred_model": "Kimi-K2.5",
            "fallbacks": ["Qwen3.5-35B"],
            "primary_backend": "qwen_planner",
        },
        "allowed_tool_categories": ["coordination", "research", "repo_read", "general"],
        "denied_tool_categories": ["browser", "engineering", "maintenance", "voice"],
        "denied_tool_name_tokens": ["clawhub", "weather"],
        "preferred_skill_task_classes": ["research", "quant", "docs"],
        "preferred_skill_backends": ["qwen_planner", "qwen_executor"],
        "preferred_channels": ["kitt"],
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
    ("creative", ("creative", "copy", "brand", "name", "ideat", "story", "muse", "image", "prompt")),
)

SKILL_BLOCK_RE = re.compile(r"<skill>[\s\S]*?<\/skill>", re.IGNORECASE)
SKILL_NAME_RE = re.compile(r"<name>\s*([^<]+?)\s*<\/name>", re.IGNORECASE)
SKILL_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("browser", ("browser", "tab", "webflow", "navigate", "pinchtab", "playwright")),
    ("research", ("research", "source", "evidence", "collect", "scout", "compare", "synth", "synthesis")),
    ("maintenance", ("cleanup", "janitor", "queue", "drain", "vacuum", "maintenance", "consolidat")),
    ("voice", ("voice", "tts", "audio", "speak", "dictat")),
    ("review", ("review", "approval", "audit", "risk", "critique", "architect")),
    ("engineering", ("code", "patch", "debug", "test", "build", "deploy", "repo", "shell", "exec", "implement")),
    ("creative", ("creative", "copy", "brand", "name", "ideat", "muse", "story")),
    ("coordination", ("session", "handoff", "summary", "status", "task", "route", "message", "operator")),
)

REVIEW_HIERARCHY = {
    "implementation_agent": "hal",
    "technical_reviewer": "archimedes",
    "supreme_reviewer": "anton",
}

DELEGATION_WIRING = [
    # delegation_method values:
    #   "message_tool"    — Jarvis uses the `message` tool to post to the specialist's Discord channel
    #   "decision_router" — internal routing via decision_router.py, which posts to the specialist's channel
    #   "external_adapter"— blocked until external runtime is available
    #   "scaffold_only"   — not implemented
    {"from_agent": "jarvis", "to_agent": "hal", "task_classes": ["code", "deploy"], "status": "policy_backed", "source": "runtime/core/agent_roster.py", "delegation_method": "message_tool", "note": "Use message tool to HAL's #crew channel. sessions_spawn without agentId creates a jarvis subagent, NOT hal."},
    {"from_agent": "hal", "to_agent": "archimedes", "task_classes": ["code", "deploy", "review"], "status": "wired", "source": "runtime/core/decision_router.py", "delegation_method": "decision_router", "note": "decision_router.py posts completed work to Archimedes' #outputs channel for code review."},
    {"from_agent": "archimedes", "to_agent": "anton", "task_classes": ["deploy", "quant", "high_stakes", "approval"], "status": "wired", "source": "runtime/core/decision_router.py", "delegation_method": "decision_router", "note": "decision_router.py escalates high-stakes items to Anton's #review channel."},
    {"from_agent": "jarvis", "to_agent": "scout", "task_classes": ["research", "docs"], "status": "policy_backed", "source": "runtime/core/agent_roster.py", "delegation_method": "message_tool", "note": "Use message tool to Scout's #flowstate channel. Scout has a real live Discord session."},
    {"from_agent": "scout", "to_agent": "hermes", "task_classes": ["research", "quant"], "status": "implemented_but_blocked_by_external_runtime", "source": "runtime/integrations/hermes_adapter.py", "delegation_method": "external_adapter"},
    {"from_agent": "jarvis", "to_agent": "bowser", "task_classes": ["multimodal", "browser"], "status": "scaffold_only", "source": "config/policies.yaml", "delegation_method": "scaffold_only"},
    {"from_agent": "jarvis", "to_agent": "ralph", "task_classes": ["flowstate", "maintenance", "general"], "status": "implemented_but_blocked_by_external_runtime", "source": "runtime/core/agent_roster.py", "delegation_method": "external_adapter"},
]

REVIEW_LANE_SUMMARY = {
    "primary_review_channel": "review",
    "technical_review_channel": "code_review",
    "high_stakes_review_channel": "audit",
    "source_files": [
        "config/channels.yaml",
        "config/policies.yaml",
        "runtime/core/decision_router.py",
    ],
    "notes": [
        "#review remains the primary concise review/approval lane.",
        "#code_review is the explicit Archimedes technical review lane.",
        "#audit is the explicit Anton high-stakes review lane.",
    ],
}

# Runtime type per agent.
# "embedded"  = runs inline inside the OpenClaw process (current live path for all Discord turns).
# "acp_ready" = this agent is designated as an ACP harness candidate; activation requires
#               acp.enabled=true in openclaw.json AND per-agent runtime.type="acp" to be set.
# "acp"       = ACP is activated for this agent.  The gateway will spawn autonomous coding
#               sessions via the configured ACP backend when this agent receives work.
#               Requires the ACP backend dependency (qwen-agent) to be installed.
AGENT_RUNTIME_TYPES: dict[str, str] = {
    "jarvis":     "embedded",    # must stay embedded — front door and control plane
    "hal":        "acp",         # ACP activated — task lifecycle proven; bridge needs qwen-agent installed
    "archimedes": "embedded",
    "anton":      "embedded",
    "hermes":     "embedded",    # second ACP candidate; not flipped until HAL is validated
    "scout":      "embedded",
    "bowser":     "embedded",
    "muse":       "embedded",
    "ralph":      "embedded",
    "qwen":       "embedded",
    "kitt":       "embedded",
}


def list_agent_ids() -> list[str]:
    return list(CANONICAL_AGENT_ROSTER.keys())


def _allowed_skill_names_for_agent(agent_id: str) -> list[str]:
    # Fail-closed: check CANONICAL_AGENT_ROSTER directly — do NOT delegate to
    # infer_agent_id() which falls back to "jarvis" for unknowns.
    normalized = str(agent_id or "").strip().lower()
    if normalized not in CANONICAL_AGENT_ROSTER:
        return []
    allowlist = AGENT_SKILL_ALLOWLIST.get(normalized) or []
    return _normalize_skill_names(list(allowlist))


def _allowed_tool_names_for_agent(agent_id: str) -> list[str]:
    # Fail-closed: check CANONICAL_AGENT_ROSTER directly — do NOT delegate to
    # infer_agent_id() which falls back to "jarvis" for unknowns.
    normalized = str(agent_id or "").strip().lower()
    if normalized not in CANONICAL_AGENT_ROSTER:
        return []
    allowlist = AGENT_TOOL_ALLOWLIST.get(normalized) or []
    return [str(item).strip().lower() for item in allowlist if str(item).strip()]


def get_agent_profile(agent_id: str) -> dict[str, Any]:
    normalized = str(agent_id or "").strip().lower()
    if normalized not in CANONICAL_AGENT_ROSTER:
        normalized = "jarvis"
    return dict(CANONICAL_AGENT_ROSTER[normalized])


def get_agent_runtime_type(agent_id: str) -> str:
    """Return "embedded", "acp_ready", or "acp" for the agent.  Falls back to "embedded" for unknowns."""
    normalized = infer_agent_id(agent_id=agent_id)
    return AGENT_RUNTIME_TYPES.get(normalized, "embedded")


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


def _skill_policy_for_agent(agent_id: str) -> dict[str, Any]:
    normalized = infer_agent_id(agent_id=agent_id)
    return {
        "allowed_categories": [],
        "denied_categories": [],
        "allow_name_tokens": [],
        "deny_name_tokens": [],
        "allowed_skill_names": _allowed_skill_names_for_agent(normalized),
        "denied_skill_names": COMMON_DENIED_SKILL_NAMES,
        "allow_general_by_default": False,
    }


def classify_skill_category(skill_name: str, skill: Any = None) -> str:
    lowered = str(skill_name or "").strip().lower()
    task_classes = set(str(item).lower() for item in getattr(skill, "task_classes", []) or [])
    metadata = getattr(skill, "metadata", {}) or {}
    tags = set(str(item).lower() for item in metadata.get("tags", []) or [])
    for category, tokens in SKILL_CATEGORY_RULES:
        if task_classes.intersection(tokens):
            return category
        if tags.intersection(tokens):
            return category
        if any(token in lowered for token in tokens):
            return category
    if task_classes.intersection({"docs", "general", "output"}):
        return "general"
    return "general"


def parse_skill_prompt_entries(skills_prompt: str) -> list[dict[str, Any]]:
    prompt = str(skills_prompt or "").strip()
    if not prompt:
        return []
    rows: list[dict[str, Any]] = []
    for match in SKILL_BLOCK_RE.finditer(prompt):
        block = match.group(0) or ""
        name = SKILL_NAME_RE.search(block)
        rows.append(
            {
                "name": str(name.group(1) if name else "(unknown)").strip(),
                "block": block,
                "blockChars": len(block),
            }
        )
    return rows


def filter_skills_prompt_for_agent(
    agent_id: str,
    skills_prompt: str,
    *,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    # Fail-closed: unknown agents get no skills — do NOT fall through to jarvis profile.
    _norm = str(agent_id or "").strip().lower()
    if _norm not in CANONICAL_AGENT_ROSTER:
        return {
            "agentId": _norm or "unknown",
            "beforeCount": 0,
            "afterCount": 0,
            "dropReasons": {"unknown_agent": 1},
            "skillsPrompt": "",
            "loadedSkillNames": [],
            "loadedSkillCategories": [],
            "policy": {},
        }
    profile = get_agent_profile(agent_id)
    policy = _skill_policy_for_agent(profile["agent_id"])
    prompt = str(skills_prompt or "").strip()
    entries = parse_skill_prompt_entries(prompt)
    if not prompt or not entries:
        return {
            "agentId": profile["agent_id"],
            "beforeCount": 0,
            "afterCount": 0,
            "dropReasons": {},
            "skillsPrompt": "",
            "loadedSkillNames": [],
            "loadedSkillCategories": [],
            "policy": policy,
        }
    skill_records = {row.skill_name.lower(): row for row in list_skills(root=root)}
    deny_name_tokens = [str(item).lower() for item in policy.get("deny_name_tokens") or []]
    allowed_skill_names = set(str(item).lower() for item in policy.get("allowed_skill_names") or [])
    denied_skill_names = set(str(item).lower() for item in policy.get("denied_skill_names") or [])
    allow_general_by_default = bool(policy.get("allow_general_by_default"))
    kept_blocks: list[str] = []
    loaded_skill_names: list[str] = []
    loaded_skill_categories: list[str] = []
    drop_reasons: dict[str, int] = {}
    for entry in entries:
        name = str(entry.get("name") or "(unknown)").strip()
        lowered = name.lower()
        matched_skill = skill_records.get(lowered)
        category = classify_skill_category(name, matched_skill)
        if denied_skill_names and lowered in denied_skill_names:
            reason = f"skill_name:{lowered}"
            drop_reasons[reason] = drop_reasons.get(reason, 0) + 1
            continue
        deny_token = next((token for token in deny_name_tokens if token and token in lowered), "")
        if deny_token:
            reason = f"name_token:{deny_token}"
            drop_reasons[reason] = drop_reasons.get(reason, 0) + 1
            continue
        if allowed_skill_names:
            if lowered not in allowed_skill_names:
                reason = "skill_not_in_allowlist"
                drop_reasons[reason] = drop_reasons.get(reason, 0) + 1
                continue
        elif not allow_general_by_default:
            reason = "no_allowlist"
            drop_reasons[reason] = drop_reasons.get(reason, 0) + 1
            continue
        kept_blocks.append(str(entry.get("block") or ""))
        loaded_skill_names.append(name)
        loaded_skill_categories.append(category)
    filtered_prompt = ""
    if kept_blocks:
        filtered_prompt = "<available_skills>\n" + "\n".join(kept_blocks) + "\n</available_skills>"
    return {
        "agentId": profile["agent_id"],
        "beforeCount": len(entries),
        "afterCount": len(loaded_skill_names),
        "dropReasons": drop_reasons,
        "skillsPrompt": filtered_prompt,
        "loadedSkillNames": loaded_skill_names,
        "loadedSkillCategories": sorted(set(loaded_skill_categories)),
        "policy": policy,
    }


def summarize_visible_tools(tools: list[dict[str, Any]], *, agent_id: str) -> dict[str, Any]:
    names: list[str] = []
    categories: list[str] = []
    for tool in tools:
        name = str(tool.get("name") or tool.get("toolName") or "tool")
        names.append(name)
        categories.append(classify_tool_category(tool))
    return {
        "agentId": infer_agent_id(agent_id=agent_id),
        "visibleToolCount": len(tools),
        "visibleToolNames": names,
        "visibleToolCategories": sorted(set(categories)),
    }


def build_agent_runtime_loadout(
    *,
    agent_id: str,
    skills_prompt: str,
    tools: list[dict[str, Any]],
    provider_id: str = "",
    model_id: str = "",
    root: Optional[Path] = None,
) -> dict[str, Any]:
    profile = get_agent_profile(agent_id)
    loaded_skills = filter_skills_prompt_for_agent(profile["agent_id"], skills_prompt, root=root)
    filtered_tools_result = filter_tools_for_agent(profile["agent_id"], tools)
    filtered_tool_list = list(filtered_tools_result.get("tools") or [])
    tool_summary = summarize_visible_tools(filtered_tool_list, agent_id=profile["agent_id"])
    loaded_tools = {
        **tool_summary,
        "beforeCount": int(filtered_tools_result.get("beforeCount") or 0),
        "loadedToolCount": int(filtered_tools_result.get("afterCount") or 0),
        "dropReasons": dict(filtered_tools_result.get("dropReasons") or {}),
    }
    return {
        "agentId": profile["agent_id"],
        "displayName": profile["display_name"],
        "role": profile["role"],
        "status": profile["status"],
        "runtimeType": get_agent_runtime_type(profile["agent_id"]),
        "providerId": str(provider_id or ""),
        "modelId": str(model_id or profile.get("routing_intent", {}).get("preferred_model") or ""),
        "loadedSkills": {
            "beforeCount": int(loaded_skills.get("beforeCount") or 0),
            "loadedSkillCount": int(loaded_skills.get("afterCount") or 0),
            "loadedSkillNames": list(loaded_skills.get("loadedSkillNames") or []),
            "loadedSkillCategories": list(loaded_skills.get("loadedSkillCategories") or []),
            "dropReasons": dict(loaded_skills.get("dropReasons") or {}),
        },
        "loadedTools": loaded_tools,
        "reviewHierarchy": dict(REVIEW_HIERARCHY),
        "delegationTargets": [row["to_agent"] for row in DELEGATION_WIRING if row["from_agent"] == profile["agent_id"]],
    }


def build_delegation_receipt(
    *,
    from_agent: str,
    to_agent: str,
    method: str,
    session_key: str = "",
    session_id: str = "",
    model_id: str = "",
    provider_id: str = "",
    visible_tools: Optional[list[str]] = None,
    evidence_summary: str = "",
) -> dict[str, Any]:
    """Return a structured delegation receipt.

    ``verified`` is True only when ``session_key`` starts with ``agent:<to_agent>:`` — meaning
    a real specialist session was observed, not a generic subagent created by ``sessions_spawn``
    without an ``agentId``.

    ``method`` should be one of: ``message_tool``, ``decision_router``, ``sessions_spawn_agentId``,
    ``direct_discord_channel``, ``unknown``.
    """
    to_agent_norm = str(to_agent or "").strip().lower()
    session_key_str = str(session_key or "").strip()
    verified = bool(session_key_str) and session_key_str.startswith(f"agent:{to_agent_norm}:")
    unverified_reason = ""
    if not verified:
        if not session_key_str:
            unverified_reason = "no session_key provided — delegation not confirmed"
        elif not session_key_str.startswith(f"agent:{to_agent_norm}:"):
            unverified_reason = (
                f"session_key '{session_key_str}' does not match agent:{to_agent_norm}:* "
                f"— likely a generic subagent, not a real specialist session"
            )
    return {
        "fromAgent": str(from_agent or "").strip().lower(),
        "toAgent": to_agent_norm,
        "method": str(method or "unknown"),
        "sessionKey": session_key_str,
        "sessionId": str(session_id or ""),
        "modelId": str(model_id or ""),
        "providerId": str(provider_id or ""),
        "visibleTools": list(visible_tools or []),
        "evidenceSummary": str(evidence_summary or ""),
        "verified": verified,
        "verifiedReason": f"session_key confirms agent:{to_agent_norm}:* session" if verified else unverified_reason,
    }


def filter_tools_for_agent(
    agent_id: str,
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    # Fail-closed: unknown agents get no tools — do NOT fall through to jarvis profile.
    _norm = str(agent_id or "").strip().lower()
    if _norm not in CANONICAL_AGENT_ROSTER:
        return {
            "agentId": _norm or "unknown",
            "beforeCount": len(tools),
            "afterCount": 0,
            "droppedCount": len(tools),
            "dropReasons": {"unknown_agent": len(tools)} if tools else {},
            "tools": [],
        }
    profile = get_agent_profile(agent_id)
    allowed_names = set(_allowed_tool_names_for_agent(profile["agent_id"]))
    denied_name_tokens = [str(token).lower() for token in profile.get("denied_tool_name_tokens") or []]
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    drop_reasons: dict[str, int] = {}
    for tool in tools:
        name = str(tool.get("name") or tool.get("toolName") or "tool")
        lowered_name = name.lower()
        denied_by_name = next((token for token in denied_name_tokens if token and token in lowered_name), "")
        if denied_by_name:
            dropped.append(tool)
            reason = f"name_token:{denied_by_name}"
            drop_reasons[reason] = drop_reasons.get(reason, 0) + 1
            continue
        if allowed_names and lowered_name not in allowed_names:
            dropped.append(tool)
            reason = "not_in_allowlist"
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
            "skill_policy": _skill_policy_for_agent(agent_id),
            "preferred_channels": list(profile.get("preferred_channels") or []),
            "matched_skill_names": matched_skills[:10],
            "matched_skill_count": len(matched_skills),
            "routing_policy_present": bool(routing_policy),
            "runtime_type": get_agent_runtime_type(agent_id),
            "delegation_targets": [row["to_agent"] for row in DELEGATION_WIRING if row["from_agent"] == agent_id],
        }
        rows.append(row)
        if profile["status"] == "wired":
            wired += 1
        elif profile["status"] == "policy_backed":
            partial += 1
        else:
            blocked += 1
    acp_ready_count = sum(1 for r in rows if r["runtime_type"] == "acp_ready")
    acp_active_count = sum(1 for r in rows if r["runtime_type"] == "acp")
    return {
        "schema_version": "v5.2_agent_roster_v2",
        "agent_count": len(rows),
        "wired_agent_count": wired,
        "partial_agent_count": partial,
        "blocked_or_scaffold_agent_count": blocked,
        "configured_agent_policy_count": len(configured_agent_policies),
        "embedded_agent_count": len(rows) - acp_ready_count - acp_active_count,
        "acp_ready_agent_count": acp_ready_count,
        "acp_active_agent_count": acp_active_count,
        "rows": rows,
        "review_hierarchy": dict(REVIEW_HIERARCHY),
        "delegation_wiring": list(DELEGATION_WIRING),
        "review_lane_summary": dict(REVIEW_LANE_SUMMARY),
        "notes": [
            "Jarvis remains the public face and control plane.",
            "Hermes and Ralph are real subsystem lanes, but current live availability remains external-runtime dependent.",
            "Bowser is policy-mapped to bounded browser automation, but the browser bridge itself remains scaffold-only.",
            "The current repo does not implement a second autonomous orchestration mesh; specialization is policy-backed through routing, context prep, review roles, and subsystem adapters.",
        ],
    }
