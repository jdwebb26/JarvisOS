#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Optional

from runtime.core.risk_tier import evaluate_risk_tier


class PageAgentAnalyzer:
    def __init__(self, config: Optional[dict[str, Any]] = None):
        self.config = dict(config or {})

    def analyze_page(self, url_or_snapshot) -> dict[str, Any]:
        source_ref = str(url_or_snapshot or "")
        summary = "stubbed local page analysis placeholder"
        return {
            "analyzer": "page_agent",
            "status": "stubbed",
            "source_ref": source_ref,
            "page_summary": summary,
            "detected_elements": [
                {"element_type": "link", "target_hint": "primary_navigation", "confidence": "low"},
                {"element_type": "form", "target_hint": "interactive_surface", "confidence": "low"},
            ],
            "recommended_next_step": "review_proposed_browser_actions",
            "reason": "page_agent_not_connected",
        }

    def propose_actions(self, objective, page_analysis) -> list[dict[str, Any]]:
        objective_text = str(objective or "").lower()
        source_ref = str((page_analysis or {}).get("source_ref") or "")

        proposals: list[dict[str, Any]] = [
            {
                "action_type": "inspect_page",
                "target_hint": source_ref or "current_page",
                "rationale": "collect more bounded page detail before any mutation",
                "requires_review": False,
                "proposal_status": "stubbed",
            }
        ]

        high_risk_actions = {
            "send": "send_external_message",
            "message": "send_external_message",
            "credential": "change_credentials",
            "password": "change_credentials",
            "delete": "irreversible_change",
            "push": "send_external_message",
        }
        matched_action = None
        for token, action_type in high_risk_actions.items():
            if token in objective_text:
                matched_action = action_type
                break

        if matched_action is not None:
            risk = evaluate_risk_tier(matched_action, "browser_backend", {})
            proposals.append(
                {
                    "action_type": matched_action,
                    "target_hint": source_ref or "current_page",
                    "rationale": "high-risk objective requires explicit review before any future browser action",
                    "requires_review": risk["tier"] == "high",
                    "proposal_status": "stubbed",
                }
            )
            return proposals

        proposals.append(
            {
                "action_type": "navigate_allowlisted_page",
                "target_hint": source_ref or "current_page",
                "rationale": "bounded navigation proposal from stub page analysis",
                "requires_review": False,
                "proposal_status": "stubbed",
            }
        )
        return proposals
