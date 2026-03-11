#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Optional


class SpeakerGuard:
    def __init__(self, config: dict | None = None):
        self.config = dict(config or {})
        self.low_risk_threshold = float(self.config.get("low_risk_threshold", 0.35))
        self.medium_risk_threshold = float(self.config.get("medium_risk_threshold", 0.7))
        self.high_risk_threshold = float(self.config.get("high_risk_threshold", 0.95))

    def score_speaker(self, audio_features) -> dict:
        del audio_features
        return {
            "status": "stubbed",
            "mode": "speaker_guard_placeholder",
            "speaker_label": "unknown_operator",
            "confidence": float(self.config.get("stub_confidence", 0.5)),
            "reason": "speaker_guard_not_connected",
        }

    def is_known_operator(self, score: dict) -> bool:
        return str(score.get("speaker_label", "")).startswith("known_operator:")

    def confidence_meets_threshold(self, score: dict, risk_tier: str) -> bool:
        confidence = float(score.get("confidence", 0.0))
        tier = (risk_tier or "").strip().lower()
        if tier == "low":
            return confidence >= self.low_risk_threshold
        if tier == "medium":
            return confidence >= self.medium_risk_threshold
        if tier == "high":
            return False
        raise ValueError(f"Unsupported risk tier: {risk_tier}")
