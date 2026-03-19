#!/usr/bin/env python3
"""Tests for quant lanes approval registry."""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.registries.approval_registry import (
    create_approval, get_approval, validate_approval_for_execution,
    revoke_approval, load_all_approvals, ApprovedActions,
)


@pytest.fixture
def approval_root(tmp_path):
    (tmp_path / "workspace" / "quant" / "shared" / "registries").mkdir(parents=True)
    return tmp_path


def _make_actions(**overrides):
    now = datetime.now(timezone.utc)
    defaults = dict(
        execution_mode="paper",
        symbols=["NQ"],
        max_position_size=2,
        max_loss_per_trade=500,
        max_total_drawdown=2000,
        slippage_tolerance=0.05,
        valid_from=now.isoformat(),
        valid_until=(now + timedelta(days=14)).isoformat(),
        broker_target="paper_adapter",
    )
    defaults.update(overrides)
    return ApprovedActions(**defaults)


def test_create_approval(approval_root):
    actions = _make_actions()
    approval = create_approval(approval_root, "test-001", "paper_trade", actions)
    assert approval.approval_ref.startswith("qpt_")
    assert approval.strategy_id == "test-001"
    assert approval.approval_type == "paper_trade"
    assert not approval.revoked


def test_create_approval_invalid_type(approval_root):
    with pytest.raises(ValueError, match="paper_trade or live_trade"):
        create_approval(approval_root, "test-001", "bogus", _make_actions())


def test_get_approval(approval_root):
    actions = _make_actions()
    created = create_approval(approval_root, "test-001", "paper_trade", actions)
    loaded = get_approval(approval_root, created.approval_ref)
    assert loaded is not None
    assert loaded.approval_ref == created.approval_ref
    assert get_approval(approval_root, "nonexistent") is None


def test_validate_for_execution_pass(approval_root):
    actions = _make_actions()
    approval = create_approval(approval_root, "test-001", "paper_trade", actions)
    valid, reason = validate_approval_for_execution(
        approval_root, approval.approval_ref, "test-001", "paper", "NQ")
    assert valid
    assert reason == "approved"


def test_validate_wrong_strategy(approval_root):
    actions = _make_actions()
    approval = create_approval(approval_root, "test-001", "paper_trade", actions)
    valid, reason = validate_approval_for_execution(
        approval_root, approval.approval_ref, "wrong-id", "paper", "NQ")
    assert not valid
    assert "mismatch" in reason


def test_validate_wrong_symbol(approval_root):
    actions = _make_actions()
    approval = create_approval(approval_root, "test-001", "paper_trade", actions)
    valid, reason = validate_approval_for_execution(
        approval_root, approval.approval_ref, "test-001", "paper", "ES")
    assert not valid
    assert "symbol_not_approved" in reason


def test_validate_mode_mismatch(approval_root):
    actions = _make_actions()
    approval = create_approval(approval_root, "test-001", "paper_trade", actions)
    valid, reason = validate_approval_for_execution(
        approval_root, approval.approval_ref, "test-001", "live", "NQ")
    assert not valid
    assert "mode_mismatch" in reason


def test_validate_expired(approval_root):
    past = datetime.now(timezone.utc) - timedelta(days=1)
    actions = _make_actions(
        valid_from=(past - timedelta(days=14)).isoformat(),
        valid_until=past.isoformat(),
    )
    approval = create_approval(approval_root, "test-001", "paper_trade", actions)
    valid, reason = validate_approval_for_execution(
        approval_root, approval.approval_ref, "test-001", "paper", "NQ")
    assert not valid
    assert "expired" in reason


def test_revoke_approval(approval_root):
    actions = _make_actions()
    approval = create_approval(approval_root, "test-001", "paper_trade", actions)
    revoked = revoke_approval(approval_root, approval.approval_ref)
    assert revoked is not None
    assert revoked.revoked

    # Validate should now fail
    valid, reason = validate_approval_for_execution(
        approval_root, approval.approval_ref, "test-001", "paper", "NQ")
    assert not valid
    assert "revoked" in reason
