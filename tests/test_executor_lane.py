#!/usr/bin/env python3
"""Tests for quant lanes executor and paper adapter."""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.executor.paper_adapter import (
    PaperBrokerAdapter, LiveBrokerAdapter, Order, get_adapter,
)
from workspace.quant.executor.executor_lane import execute_paper_trade
from workspace.quant.shared.registries.strategy_registry import create_strategy, transition_strategy
from workspace.quant.shared.registries.approval_registry import create_approval, ApprovedActions


@pytest.fixture
def exec_root(tmp_path):
    """Create a temp root with quant directory structure."""
    for d in ["workspace/quant/shared/registries",
              "workspace/quant/shared/config",
              "workspace/quant/shared/latest",
              "workspace/quant/executor",
              "state/quant/executor"]:
        (tmp_path / d).mkdir(parents=True)
    # Write kill switch (not engaged)
    (tmp_path / "workspace/quant/shared/config/kill_switch.json").write_text(
        '{"engaged": false}')
    (tmp_path / "workspace/quant/shared/config/risk_limits.json").write_text(
        '{"per_strategy": {"max_position_size": 2}, "portfolio": {}}')
    return tmp_path


def _setup_strategy_and_approval(root, strategy_id="test-001"):
    create_strategy(root, strategy_id, actor="atlas")
    transition_strategy(root, strategy_id, "CANDIDATE", actor="atlas")
    transition_strategy(root, strategy_id, "VALIDATING", actor="sigma")
    transition_strategy(root, strategy_id, "PROMOTED", actor="sigma")
    now = datetime.now(timezone.utc)
    actions = ApprovedActions(
        execution_mode="paper", symbols=["NQ"],
        valid_from=now.isoformat(),
        valid_until=(now + timedelta(days=14)).isoformat(),
    )
    approval = create_approval(root, strategy_id, "paper_trade", actions)
    transition_strategy(root, strategy_id, "PAPER_QUEUED", actor="kitt",
                        approval_ref=approval.approval_ref)
    return approval


# --- Paper Adapter Tests ---

def test_paper_adapter_place_order(tmp_path):
    adapter = PaperBrokerAdapter(tmp_path)
    order = Order("test-001", "NQ", "long", "market", 1)
    fill = adapter.place_order(order, simulated_price=18250.0)
    assert fill.status == "filled"
    assert fill.symbol == "NQ"
    assert fill.fill_price > 0


def test_paper_adapter_health(tmp_path):
    adapter = PaperBrokerAdapter(tmp_path)
    assert adapter.health_check() is True


def test_paper_adapter_positions(tmp_path):
    adapter = PaperBrokerAdapter(tmp_path)
    order = Order("test-001", "NQ", "long", "market", 1)
    adapter.place_order(order)
    positions = adapter.get_positions("test-001")
    assert len(positions) == 1
    assert positions[0].symbol == "NQ"


def test_live_adapter_raises(tmp_path):
    from workspace.quant.executor.paper_adapter import BrokerNotConfiguredError
    adapter = LiveBrokerAdapter()
    with pytest.raises(BrokerNotConfiguredError):
        adapter.place_order(Order("test", "NQ", "long", "market"))
    assert adapter.health_check() is False


def test_get_adapter(tmp_path):
    paper = get_adapter("paper", tmp_path)
    assert isinstance(paper, PaperBrokerAdapter)
    live = get_adapter("live", tmp_path)
    assert isinstance(live, LiveBrokerAdapter)


# --- Executor Lane Tests ---

def test_execute_paper_trade_success(exec_root):
    approval = _setup_strategy_and_approval(exec_root)
    result = execute_paper_trade(
        exec_root, "test-001", approval.approval_ref,
        symbol="NQ", side="long", quantity=1,
    )
    assert result["success"] is True
    assert result["fill"]["status"] == "filled"


def test_execute_rejects_wrong_symbol(exec_root):
    approval = _setup_strategy_and_approval(exec_root)
    result = execute_paper_trade(
        exec_root, "test-001", approval.approval_ref,
        symbol="ES", side="long",
    )
    assert result["success"] is False
    assert result["rejection_reason"] == "symbol_not_approved"


def test_execute_rejects_bad_approval(exec_root):
    _setup_strategy_and_approval(exec_root)
    result = execute_paper_trade(
        exec_root, "test-001", "fake-ref",
        symbol="NQ", side="long",
    )
    assert result["success"] is False
    assert result["rejection_reason"] == "invalid_approval"


def test_execute_rejects_kill_switch(exec_root):
    approval = _setup_strategy_and_approval(exec_root)
    # Engage kill switch
    (exec_root / "workspace/quant/shared/config/kill_switch.json").write_text(
        '{"engaged": true}')
    result = execute_paper_trade(
        exec_root, "test-001", approval.approval_ref,
        symbol="NQ", side="long",
    )
    assert result["success"] is False
    assert result["rejection_reason"] == "kill_switch_engaged"


def test_execute_rejects_position_breach(exec_root):
    approval = _setup_strategy_and_approval(exec_root)
    result = execute_paper_trade(
        exec_root, "test-001", approval.approval_ref,
        symbol="NQ", side="long", quantity=10,  # exceeds max_position_size=2
    )
    assert result["success"] is False
    assert result["rejection_reason"] == "strategy_limit_breach"
