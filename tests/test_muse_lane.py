"""Tests for the Muse creative lane — classification, routing, and safety."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.intake import infer_task_type, infer_risk, review_required, approval_required


# ---------------------------------------------------------------------------
# 1. Channel-aware classification: #muse channel → creative
# ---------------------------------------------------------------------------

class TestMuseChannelOverride:
    """Messages from #muse channel should always be creative, regardless of content."""

    def test_muse_channel_plain_creative(self):
        assert infer_task_type("Design a logo for the project", channel="muse") == "creative"

    def test_muse_channel_with_trading_language(self):
        """The core misrouting bug: trading terms in a creative prompt."""
        assert infer_task_type(
            "Design a brand identity for our NQ trading dashboard",
            channel="muse",
        ) == "creative"

    def test_muse_channel_with_strategy_term(self):
        assert infer_task_type(
            "Write marketing copy for our prop account strategy product",
            channel="muse",
        ) == "creative"

    def test_muse_channel_with_backtest_term(self):
        assert infer_task_type(
            "Create a visual report template for backtest results",
            channel="muse",
        ) == "creative"

    def test_muse_channel_with_code_terms(self):
        """Even code-sounding requests in #muse stay creative."""
        assert infer_task_type(
            "Write a creative python-themed poem",
            channel="muse",
        ) == "creative"

    def test_muse_channel_with_deploy_terms(self):
        assert infer_task_type(
            "Draft a release announcement for our new service",
            channel="muse",
        ) == "creative"

    def test_creative_channel_alias(self):
        assert infer_task_type("Brainstorm ideas", channel="creative") == "creative"


# ---------------------------------------------------------------------------
# 2. Keyword-based creative detection (non-muse channels)
# ---------------------------------------------------------------------------

class TestCreativeKeywordDetection:
    """Creative keywords should trigger creative type even without channel hint."""

    def test_brainstorm(self):
        assert infer_task_type("brainstorm ideas for a new product") == "creative"

    def test_tagline(self):
        assert infer_task_type("write a tagline for OpenClaw") == "creative"

    def test_slogan(self):
        assert infer_task_type("create a slogan for the trading desk") == "creative"

    def test_marketing_copy(self):
        assert infer_task_type("write marketing copy for the website") == "creative"

    def test_brand(self):
        assert infer_task_type("develop the brand guidelines") == "creative"

    def test_logo(self):
        assert infer_task_type("design a logo for the team") == "creative"

    def test_poem(self):
        assert infer_task_type("write a poem about algorithmic trading") == "creative"


# ---------------------------------------------------------------------------
# 3. Non-muse channels still classify correctly
# ---------------------------------------------------------------------------

class TestNonMuseClassification:
    """Tasks in non-muse channels should still get their correct type."""

    def test_quant_in_todo(self):
        assert infer_task_type("Analyze NQ trading regime shifts", channel="todo") == "quant"

    def test_code_in_todo(self):
        assert infer_task_type("Fix the python script bug", channel="todo") == "code"

    def test_deploy_in_todo(self):
        assert infer_task_type("Deploy the new systemd service", channel="todo") == "deploy"

    def test_browser_in_todo(self):
        assert infer_task_type("Browse the NVIDIA documentation website", channel="todo") == "browser"

    def test_general_in_todo(self):
        assert infer_task_type("Summarize today's work", channel="todo") == "general"

    def test_no_channel(self):
        """Default channel='' should not trigger muse override."""
        assert infer_task_type("Design a new feature") == "general"  # no creative keyword
        assert infer_task_type("Design a logo") == "creative"  # "logo" is creative keyword
        assert infer_task_type("Do something general") == "general"


# ---------------------------------------------------------------------------
# 4. Risk/review/approval: creative stays safe
# ---------------------------------------------------------------------------

class TestCreativeRiskAndGating:
    """Creative tasks should have normal risk and no review/approval gates."""

    def test_creative_risk_is_normal(self):
        assert infer_risk("creative", "design a trading dashboard logo") == "normal"

    def test_creative_no_review_required(self):
        assert review_required("creative", "normal") is False

    def test_creative_no_approval_required(self):
        assert approval_required("creative", "normal") is False

    def test_quant_still_high_stakes(self):
        """Quant tasks must remain high_stakes — creative fix must not weaken this."""
        assert infer_risk("quant", "backtest the NQ strategy") == "high_stakes"

    def test_deploy_still_high_stakes(self):
        assert infer_risk("deploy", "deploy the service") == "high_stakes"

    def test_quant_still_needs_approval(self):
        assert approval_required("quant", "high_stakes") is True

    def test_deploy_still_needs_approval(self):
        assert approval_required("deploy", "high_stakes") is True

    def test_code_still_needs_review(self):
        assert review_required("code", "risky") is True


# ---------------------------------------------------------------------------
# 5. Backend selection: creative → muse_creative
# ---------------------------------------------------------------------------

class TestMuseBackendSelection:

    def test_creative_type_routes_to_muse(self):
        from runtime.ralph.agent_loop import select_backend_for_task
        task = SimpleNamespace(
            task_type="creative",
            execution_backend="ralph_adapter",
            normalized_request="design a logo for the NQ trading dashboard",
            raw_request="",
        )
        assert select_backend_for_task(task) == "muse_creative"

    def test_creative_type_beats_trading_keywords(self):
        """task_type=creative must win over keyword 'trading' → kitt_quant."""
        from runtime.ralph.agent_loop import select_backend_for_task
        task = SimpleNamespace(
            task_type="creative",
            execution_backend="ralph_adapter",
            normalized_request="write a story about NQ trading strategies and backtest results",
            raw_request="",
        )
        assert select_backend_for_task(task) == "muse_creative"

    def test_quant_type_still_routes_to_kitt(self):
        """Quant tasks must still go to kitt_quant — not broken by creative fix."""
        from runtime.ralph.agent_loop import select_backend_for_task
        task = SimpleNamespace(
            task_type="quant",
            execution_backend="ralph_adapter",
            normalized_request="analyze NQ regime shifts",
            raw_request="",
        )
        # quant is not in the lane-locked set, so keyword scoring may apply,
        # but _TYPE_DEFAULTS["quant"] = "kitt_quant" is the fallback.
        result = select_backend_for_task(task)
        assert result == "kitt_quant"

    def test_general_type_with_trading_keywords_routes_to_kitt(self):
        """A general task mentioning trading should still route to kitt_quant via keywords."""
        from runtime.ralph.agent_loop import select_backend_for_task
        task = SimpleNamespace(
            task_type="general",
            execution_backend="ralph_adapter",
            normalized_request="what is the current NQ trading regime",
            raw_request="",
        )
        # 'trading' keyword should score for kitt_quant
        result = select_backend_for_task(task)
        assert result in {"kitt_quant", "hal"}  # kitt_quant via keyword or hal via general default
