#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from runtime.core.browser_control_allowlist import ensure_default_browser_control_allowlist
from runtime.core.risk_tier import evaluate_risk_tier


def _normalized_url(value: str) -> str:
    return (value or "").strip()


def _host_matches(target_url: str, site_rule: str) -> bool:
    parsed = urlparse(target_url)
    hostname = (parsed.hostname or "").lower()
    candidate = (site_rule or "").strip().lower()
    if not candidate:
        return False
    return hostname == candidate or hostname.endswith(f".{candidate}")


def _url_matches(target_url: str, rule: str) -> bool:
    url = _normalized_url(target_url).lower()
    candidate = (rule or "").strip().lower()
    if not candidate:
        return False
    return url.startswith(candidate)


def _matches_site_list(target_url: str, rules: list[str]) -> bool:
    return any(_host_matches(target_url, rule) or _url_matches(target_url, rule) for rule in rules)


def evaluate_browser_action(
    action_type: str,
    target_url: str,
    action_params: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    allowlist = ensure_default_browser_control_allowlist(root=root)
    url = _normalized_url(target_url)
    params = dict(action_params or {})

    if not url:
        return {
            "allowed": False,
            "risk_tier": "high",
            "review_required": True,
            "allowlist_ref": allowlist.browser_control_allowlist_id,
            "reason": "missing_target_url",
        }

    if _matches_site_list(url, allowlist.blocked_sites):
        return {
            "allowed": False,
            "risk_tier": "high",
            "review_required": True,
            "allowlist_ref": allowlist.browser_control_allowlist_id,
            "reason": "blocked_target_url",
        }

    if not _matches_site_list(url, allowlist.allowed_sites):
        return {
            "allowed": False,
            "risk_tier": "high",
            "review_required": True,
            "allowlist_ref": allowlist.browser_control_allowlist_id,
            "reason": "target_url_not_allowlisted",
        }

    risk = evaluate_risk_tier(action_type, "browser_backend", params)
    return {
        "allowed": True,
        "risk_tier": risk["tier"],
        "review_required": risk["tier"] == "high",
        "allowlist_ref": allowlist.browser_control_allowlist_id,
        "reason": risk["reason"],
    }
