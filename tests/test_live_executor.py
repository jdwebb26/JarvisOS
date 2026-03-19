#!/usr/bin/env python3
"""Tests for the live executor path — proving correct behavior
up to the real broker boundary.

Proves:
  1. Live preflight has full parity with paper preflight
  2. Kill switch blocks live execution
  3. Approval must be live_trade type (paper approval rejected)
  4. Risk limits enforced identically
  5. Broker not-configured produces explicit, actionable error
  6. Config check correctly reports missing env vars
  7. Live adapter health_check returns False when not configured
  8. BrokerNotConfiguredError is raised at the right boundary
  9. execute_live_trade returns broker_error field with clear message
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet, validate_packet
from workspace.quant.shared.packet_store import store_packet
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy,
)
from workspace.quant.shared.registries.approval_registry import (
    create_approval, ApprovedActions,
)
from workspace.quant.executor.paper_adapter import (
    LiveBrokerAdapter, BrokerNotConfiguredError, check_live_broker_config,
    Order, get_adapter,
)
from workspace.quant.executor.executor_lane import (
    execute_paper_trade, execute_live_trade,
)


@pytest.fixture
def clean_root(tmp_path):
    """Provide a clean root directory for each test."""
    (tmp_path / "workspace" / "quant" / "shared" / "latest").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "registries").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "config").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "scheduler").mkdir(parents=True)
    (tmp_path / "state" / "quant" / "executor").mkdir(parents=True)
    for lane in ["atlas", "fish", "hermes", "sigma", "kitt", "tradefloor", "executor"]:
        (tmp_path / "workspace" / "quant" / lane).mkdir(parents=True)

    hosts = {
        "hosts": {
            "NIMO": {"role": "primary", "specs": "128GB", "heavy_job_cap": 2, "ip": "127.0.0.1"},
            "SonLM": {"role": "secondary", "specs": "lighter", "heavy_job_cap": 1, "ip": None},
        },
        "global_heavy_job_cap": 3,
        "lane_placement": {
            "atlas": {"primary": "NIMO", "overflow": "SonLM"},
            "fish": {"primary": "SonLM", "overflow": "cloud"},
            "hermes": {"primary": "mixed", "overflow": "either"},
            "tradefloor": {"primary": "strongest_available", "overflow": "cloud"},
            "kitt": {"primary": "NIMO", "overflow": "cloud"},
            "sigma": {"primary": "NIMO", "overflow": "cloud"},
            "executor": {"primary": "NIMO", "overflow": None},
        },
    }
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "hosts.json").write_text(
        json.dumps(hosts, indent=2), encoding="utf-8")
    gov = {lane: {
        "batch_size": 1, "max_iterations": 5, "cooldown_interval": 0,
        "cloud_burst_allowed": False, "escalation_threshold": 0.6,
        "cadence_multiplier": 1.0, "consecutive_backoff_cycles": 0, "paused": False,
    } for lane in ["atlas", "fish", "hermes", "tradefloor", "kitt", "sigma", "executor"]}
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "governor_state.json").write_text(
        json.dumps(gov, indent=2), encoding="utf-8")
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "kill_switch.json").write_text(
        json.dumps({"engaged": False}), encoding="utf-8")
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "risk_limits.json").write_text(
        json.dumps({
            "portfolio": {"max_total_exposure": 4, "max_correlated_strategies": 3,
                          "max_total_drawdown": 5000, "concentration_threshold": 0.6},
            "per_strategy": {"max_position_size": 2, "max_loss_per_trade": 500,
                             "max_drawdown": 2000},
        }, indent=2), encoding="utf-8")
    return tmp_path


def _setup_live_strategy(root):
    """Create a strategy promoted through to LIVE_QUEUED with live approval."""
    create_strategy(root, "live-001", actor="atlas")
    transition_strategy(root, "live-001", "CANDIDATE", actor="atlas")
    transition_strategy(root, "live-001", "VALIDATING", actor="sigma")
    transition_strategy(root, "live-001", "PROMOTED", actor="sigma")
    transition_strategy(root, "live-001", "PAPER_QUEUED", actor="kitt", approval_ref="apr-paper")
    transition_strategy(root, "live-001", "PAPER_ACTIVE", actor="executor")
    transition_strategy(root, "live-001", "PAPER_REVIEW", actor="sigma")
    transition_strategy(root, "live-001", "LIVE_QUEUED", actor="kitt", approval_ref="apr-live")

    appr = create_approval(
        root, strategy_id="live-001", approval_type="live_trade",
        approved_actions=ApprovedActions(
            execution_mode="live", symbols=["NQ"],
            max_position_size=2, max_loss_per_trade=500,
            max_total_drawdown=2000, slippage_tolerance=0.05,
        ),
    )
    return appr


# ---- Adapter-level tests ----

class TestLiveBrokerAdapter:
    def test_health_check_false_when_not_configured(self):
        adapter = LiveBrokerAdapter()
        assert adapter.health_check() is False

    def test_place_order_raises_not_configured(self):
        adapter = LiveBrokerAdapter()
        order = Order(strategy_id="test", symbol="NQ", side="long", order_type="market")
        with pytest.raises(BrokerNotConfiguredError) as exc:
            adapter.place_order(order)
        assert "Missing env vars" in str(exc.value)

    def test_get_adapter_returns_live(self, tmp_path):
        adapter = get_adapter("live", tmp_path)
        assert isinstance(adapter, LiveBrokerAdapter)

    def test_config_check_reports_missing(self):
        # Ensure env vars are not set
        for var in ["QUANT_BROKER_TYPE", "QUANT_BROKER_API_KEY",
                     "QUANT_BROKER_API_SECRET", "QUANT_BROKER_ENDPOINT"]:
            os.environ.pop(var, None)
        configured, status = check_live_broker_config()
        assert configured is False
        assert all(v == "MISSING" for v in status.values())

    def test_config_check_reports_set(self, monkeypatch):
        monkeypatch.setenv("QUANT_BROKER_TYPE", "alpaca")
        monkeypatch.setenv("QUANT_BROKER_API_KEY", "test-key")
        monkeypatch.setenv("QUANT_BROKER_API_SECRET", "test-secret")
        monkeypatch.setenv("QUANT_BROKER_ENDPOINT", "https://paper.alpaca.markets")
        configured, status = check_live_broker_config()
        assert configured is True
        assert all(v == "set" for v in status.values())

    def test_health_check_true_when_configured(self, monkeypatch):
        monkeypatch.setenv("QUANT_BROKER_TYPE", "alpaca")
        monkeypatch.setenv("QUANT_BROKER_API_KEY", "test-key")
        monkeypatch.setenv("QUANT_BROKER_API_SECRET", "test-secret")
        monkeypatch.setenv("QUANT_BROKER_ENDPOINT", "https://paper.alpaca.markets")
        adapter = LiveBrokerAdapter()
        assert adapter.health_check() is True

    def test_place_order_raises_not_implemented_when_configured(self, monkeypatch):
        """Even with config set, place_order should raise because SDK is not integrated."""
        monkeypatch.setenv("QUANT_BROKER_TYPE", "alpaca")
        monkeypatch.setenv("QUANT_BROKER_API_KEY", "test-key")
        monkeypatch.setenv("QUANT_BROKER_API_SECRET", "test-secret")
        monkeypatch.setenv("QUANT_BROKER_ENDPOINT", "https://paper.alpaca.markets")
        adapter = LiveBrokerAdapter()
        order = Order(strategy_id="test", symbol="NQ", side="long", order_type="market")
        with pytest.raises(BrokerNotConfiguredError) as exc:
            adapter.place_order(order)
        assert "not yet implemented" in str(exc.value)
        assert "final integration point" in str(exc.value)


# ---- execute_live_trade preflight tests ----

class TestExecuteLiveTradePreflights:
    def test_kill_switch_blocks_live(self, clean_root):
        ks = clean_root / "workspace" / "quant" / "shared" / "config" / "kill_switch.json"
        ks.write_text(json.dumps({"engaged": True, "reason": "test"}), encoding="utf-8")
        appr = _setup_live_strategy(clean_root)

        result = execute_live_trade(
            clean_root, "live-001", appr.approval_ref, "NQ", "long",
        )
        assert result["success"] is False
        assert result["rejection_reason"] == "kill_switch_engaged"

    def test_paper_approval_rejected_for_live(self, clean_root):
        """A paper_trade approval must not work for live execution."""
        create_strategy(clean_root, "mode-001", actor="atlas")
        transition_strategy(clean_root, "mode-001", "CANDIDATE", actor="atlas")
        transition_strategy(clean_root, "mode-001", "VALIDATING", actor="sigma")
        transition_strategy(clean_root, "mode-001", "PROMOTED", actor="sigma")
        transition_strategy(clean_root, "mode-001", "PAPER_QUEUED", actor="kitt",
                            approval_ref="apr-paper")

        # Create paper approval, not live
        appr = create_approval(
            clean_root, strategy_id="mode-001", approval_type="paper_trade",
            approved_actions=ApprovedActions(
                execution_mode="paper", symbols=["NQ"],
            ),
        )

        result = execute_live_trade(
            clean_root, "mode-001", appr.approval_ref, "NQ", "long",
        )
        assert result["success"] is False
        assert result["rejection_reason"] == "mode_mismatch"

    def test_risk_limits_enforced_for_live(self, clean_root):
        appr = _setup_live_strategy(clean_root)

        result = execute_live_trade(
            clean_root, "live-001", appr.approval_ref, "NQ", "long",
            quantity=999,  # Way over max_position_size=2
        )
        assert result["success"] is False
        assert result["rejection_reason"] == "strategy_limit_breach"

    def test_wrong_symbol_rejected_for_live(self, clean_root):
        appr = _setup_live_strategy(clean_root)

        result = execute_live_trade(
            clean_root, "live-001", appr.approval_ref, "ES", "long",  # ES not in approved symbols
        )
        assert result["success"] is False
        assert result["rejection_reason"] == "symbol_not_approved"


# ---- Broker boundary tests ----

class TestBrokerBoundary:
    def test_broker_not_configured_produces_explicit_error(self, clean_root):
        """When all preflights pass but broker is not configured, get explicit error."""
        appr = _setup_live_strategy(clean_root)

        result = execute_live_trade(
            clean_root, "live-001", appr.approval_ref, "NQ", "long",
        )
        assert result["success"] is False
        assert result["broker_error"] is not None
        assert "Missing env vars" in result["broker_error"]
        assert "QUANT_BROKER" in result["broker_error"]

    def test_rejection_packet_emitted_when_not_configured(self, clean_root):
        appr = _setup_live_strategy(clean_root)

        result = execute_live_trade(
            clean_root, "live-001", appr.approval_ref, "NQ", "long",
        )
        assert len(result["packets"]) >= 1
        rej_pkt = result["packets"][-1]
        assert rej_pkt["execution_rejection_reason"] == "broker_unhealthy"
        assert "not configured" in rej_pkt["execution_rejection_detail"]

    def test_configured_but_unimplemented_hits_broker_boundary(self, clean_root, monkeypatch):
        """With env vars set, preflights pass and we hit the broker SDK boundary."""
        monkeypatch.setenv("QUANT_BROKER_TYPE", "alpaca")
        monkeypatch.setenv("QUANT_BROKER_API_KEY", "test-key")
        monkeypatch.setenv("QUANT_BROKER_API_SECRET", "test-secret")
        monkeypatch.setenv("QUANT_BROKER_ENDPOINT", "https://paper.alpaca.markets")

        appr = _setup_live_strategy(clean_root)

        result = execute_live_trade(
            clean_root, "live-001", appr.approval_ref, "NQ", "long",
        )
        assert result["success"] is False
        assert result["broker_error"] is not None
        assert "not yet implemented" in result["broker_error"]
        # Intent packet should have been emitted before the broker call failed
        intent_pkts = [p for p in result["packets"]
                       if p.get("packet_type") == "execution_intent_packet"]
        assert len(intent_pkts) == 1
        assert intent_pkts[0]["execution_mode"] == "live"


# ---- Preflight parity ----

class TestPreflightParity:
    def test_paper_and_live_both_check_kill_switch(self, clean_root):
        ks = clean_root / "workspace" / "quant" / "shared" / "config" / "kill_switch.json"
        ks.write_text(json.dumps({"engaged": True}), encoding="utf-8")

        create_strategy(clean_root, "parity-001", actor="atlas")
        paper_result = execute_paper_trade(
            clean_root, "parity-001", "fake-ref", "NQ", "long",
        )
        assert paper_result["rejection_reason"] == "kill_switch_engaged"

        appr = _setup_live_strategy(clean_root)
        live_result = execute_live_trade(
            clean_root, "live-001", appr.approval_ref, "NQ", "long",
        )
        assert live_result["rejection_reason"] == "kill_switch_engaged"

    def test_paper_and_live_both_check_risk_limits(self, clean_root):
        # Paper path
        create_strategy(clean_root, "risk-paper", actor="atlas")
        paper_appr = create_approval(
            clean_root, strategy_id="risk-paper", approval_type="paper_trade",
            approved_actions=ApprovedActions(execution_mode="paper", symbols=["NQ"]),
        )
        paper_result = execute_paper_trade(
            clean_root, "risk-paper", paper_appr.approval_ref, "NQ", "long",
            quantity=999,
        )
        assert paper_result["rejection_reason"] == "strategy_limit_breach"

        # Live path
        appr = _setup_live_strategy(clean_root)
        live_result = execute_live_trade(
            clean_root, "live-001", appr.approval_ref, "NQ", "long",
            quantity=999,
        )
        assert live_result["rejection_reason"] == "strategy_limit_breach"
