#!/usr/bin/env python3
"""Tests proving proof_tracker integration into the live paper execution path.

Acceptance criteria:
  1. execute_paper_trade auto-creates a paper run on first fill
  2. Subsequent fills update proof metrics via record_fill
  3. Proof evaluation runs after every fill
  4. Result dict includes proof tracking state
  5. Proof-ready strategies surface correctly
  6. No live execution without existing live gate rules
  7. Integration does not break existing paper execution behavior
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet, validate_packet
from workspace.quant.shared.packet_store import store_packet, list_lane_packets
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, get_strategy,
)
from workspace.quant.shared.registries.approval_registry import (
    create_approval, load_all_approvals, ApprovedActions,
)
from workspace.quant.sigma.validation_lane import validate_candidate
from workspace.quant.executor.executor_lane import execute_paper_trade
from workspace.quant.executor.proof_tracker import (
    get_active_run, load_paper_run, list_paper_runs, evaluate_proof,
)


@pytest.fixture
def clean_root(tmp_path):
    """Provide a clean root with all required structure."""
    (tmp_path / "workspace" / "quant" / "shared" / "latest").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "registries").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "config").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "scheduler").mkdir(parents=True)
    (tmp_path / "state" / "quant" / "executor").mkdir(parents=True)
    for lane in ["atlas", "fish", "hermes", "sigma", "kitt", "tradefloor", "executor"]:
        (tmp_path / "workspace" / "quant" / lane).mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "executor" / "paper_runs").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "executor" / "promotions").mkdir(parents=True)

    hosts = {
        "hosts": {"NIMO": {"role": "primary", "specs": "128GB", "heavy_job_cap": 2, "ip": "127.0.0.1"}},
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
        json.dumps(hosts, indent=2), encoding="utf-8"
    )
    gov = {lane: {
        "batch_size": 1, "max_iterations": 5, "cooldown_interval": 0,
        "cloud_burst_allowed": False, "escalation_threshold": 0.6,
        "cadence_multiplier": 1.0, "consecutive_backoff_cycles": 0, "paused": False,
    } for lane in ["atlas", "fish", "hermes", "tradefloor", "kitt", "sigma", "executor"]}
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "governor_state.json").write_text(
        json.dumps(gov, indent=2), encoding="utf-8"
    )
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "risk_limits.json").write_text(
        json.dumps({"per_strategy": {"max_position_size": 2},
                     "portfolio": {"max_total_exposure": 4}}),
        encoding="utf-8",
    )
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "review_thresholds.json").write_text(
        json.dumps({
            "validation": {"min_profit_factor": 1.3, "min_sharpe": 0.8,
                           "max_drawdown_pct": 0.15, "min_trades": 20},
            "paper_review": {"min_profit_factor": 1.3, "min_sharpe": 0.8,
                             "max_drawdown_pct": 0.15, "min_fill_rate": 0.90,
                             "max_correlation": 0.70},
        }), encoding="utf-8",
    )
    return tmp_path


def _promote_to_paper_queued(root, sid="int-001"):
    """Push a strategy through validation → PAPER_QUEUED, return approval_ref."""
    create_strategy(root, sid, actor="atlas")
    transition_strategy(root, sid, "CANDIDATE", actor="atlas")
    cpkt = make_packet("candidate_packet", "atlas", f"Test strategy {sid}",
                       strategy_id=sid, confidence=0.5,
                       timeframe_scope="15m", symbol_scope="NQ")
    store_packet(root, cpkt)

    transition_strategy(root, sid, "VALIDATING", actor="sigma")
    validate_candidate(root, cpkt, profit_factor=1.5, sharpe=1.0,
                       max_drawdown_pct=0.10, trade_count=30)
    # Now PROMOTED
    now = datetime.now(timezone.utc)
    actions = ApprovedActions(
        execution_mode="paper", symbols=["NQ"],
        valid_from=now.isoformat(),
        valid_until=(now + timedelta(days=14)).isoformat(),
    )
    appr = create_approval(root, sid, "paper_trade", approved_actions=actions)
    transition_strategy(root, sid, "PAPER_QUEUED", actor="kitt",
                        approval_ref=appr.approval_ref)
    return appr.approval_ref


# ---------------------------------------------------------------------------
# Auto-create paper run on first fill
# ---------------------------------------------------------------------------

class TestPaperRunAutoCreation:
    def test_first_fill_creates_paper_run(self, clean_root):
        """execute_paper_trade auto-creates a paper run on first fill."""
        ref = _promote_to_paper_queued(clean_root, "auto-001")
        result = execute_paper_trade(
            clean_root, "auto-001", ref, symbol="NQ", side="long",
        )
        assert result["success"] is True
        assert "proof" in result
        assert result["proof"].get("paper_run_id") is not None
        # Entry fill opens position — no closed trade yet
        assert result["proof"]["closed_count"] == 0

    def test_paper_run_persists_on_disk(self, clean_root):
        """Paper run state file exists after execution."""
        ref = _promote_to_paper_queued(clean_root, "disk-001")
        result = execute_paper_trade(
            clean_root, "disk-001", ref, symbol="NQ", side="long",
        )
        run_id = result["proof"]["paper_run_id"]
        run = load_paper_run(clean_root, run_id)
        assert run is not None
        assert run.strategy_id == "disk-001"
        # Entry only — no closed trades
        assert run.closed_count == 0

    def test_horizon_inferred_from_candidate(self, clean_root):
        """Horizon class is inferred from the candidate's timeframe_scope."""
        ref = _promote_to_paper_queued(clean_root, "hz-001")
        result = execute_paper_trade(
            clean_root, "hz-001", ref, symbol="NQ", side="long",
        )
        # Candidate was created with timeframe_scope="15m" → "intraday"
        assert result["proof"]["horizon_class"] == "intraday"


# ---------------------------------------------------------------------------
# Fill recording updates metrics
# ---------------------------------------------------------------------------

class TestFillRecording:
    def test_round_trips_accumulate(self, clean_root):
        """Entry/exit round trips accumulate closed trades in the same run."""
        ref = _promote_to_paper_queued(clean_root, "multi-001")

        # Round trip 1: entry + exit
        execute_paper_trade(clean_root, "multi-001", ref, symbol="NQ", side="long",
                            simulated_price=18000.0)
        r1 = execute_paper_trade(clean_root, "multi-001", ref, symbol="NQ", side="short",
                                  simulated_price=18050.0)
        assert r1["proof"]["closed_count"] == 1

        # Round trip 2
        execute_paper_trade(clean_root, "multi-001", ref, symbol="NQ", side="long",
                            simulated_price=18050.0)
        r2 = execute_paper_trade(clean_root, "multi-001", ref, symbol="NQ", side="short",
                                  simulated_price=18100.0)
        assert r2["proof"]["closed_count"] == 2

    def test_run_reused_across_fills(self, clean_root):
        """Same paper_run_id is used across multiple fills."""
        ref = _promote_to_paper_queued(clean_root, "reuse-001")

        r1 = execute_paper_trade(
            clean_root, "reuse-001", ref, symbol="NQ", side="long",
        )
        r2 = execute_paper_trade(
            clean_root, "reuse-001", ref, symbol="NQ", side="long",
        )
        assert r1["proof"]["paper_run_id"] == r2["proof"]["paper_run_id"]


# ---------------------------------------------------------------------------
# Proof evaluation runs automatically
# ---------------------------------------------------------------------------

class TestProofEvaluation:
    def test_proof_status_starts_accumulating(self, clean_root):
        """After first fill, proof status is 'accumulating'."""
        ref = _promote_to_paper_queued(clean_root, "eval-001")
        result = execute_paper_trade(
            clean_root, "eval-001", ref, symbol="NQ", side="long",
        )
        assert result["proof"]["proof_status"] == "accumulating"
        assert result["proof"]["sufficient"] is False

    def test_proof_evaluation_checked_every_close(self, clean_root):
        """Proof evaluation runs after each closed trade."""
        ref = _promote_to_paper_queued(clean_root, "evalcheck-001")
        for _ in range(3):
            execute_paper_trade(clean_root, "evalcheck-001", ref, symbol="NQ",
                                side="long", simulated_price=18000.0)
            result = execute_paper_trade(clean_root, "evalcheck-001", ref, symbol="NQ",
                                          side="short", simulated_price=18050.0)
        # Still accumulating (intraday needs 30 trades minimum)
        assert result["proof"]["sufficient"] is False
        assert result["proof"]["closed_count"] == 3


# ---------------------------------------------------------------------------
# Existing behavior preserved
# ---------------------------------------------------------------------------

class TestExistingBehavior:
    def test_fill_still_returned(self, clean_root):
        """execute_paper_trade still returns fill data as before."""
        ref = _promote_to_paper_queued(clean_root, "compat-001")
        result = execute_paper_trade(
            clean_root, "compat-001", ref, symbol="NQ", side="long",
        )
        assert result["success"] is True
        assert result["fill"] is not None
        assert "fill_price" in result["fill"]
        assert "slippage" in result["fill"]

    def test_packets_still_emitted(self, clean_root):
        """Intent and status packets still emitted."""
        ref = _promote_to_paper_queued(clean_root, "pkt-001")
        result = execute_paper_trade(
            clean_root, "pkt-001", ref, symbol="NQ", side="long",
        )
        types = [p["packet_type"] for p in result["packets"]]
        assert "execution_intent_packet" in types
        assert "execution_status_packet" in types

    def test_strategy_transitions_to_paper_active(self, clean_root):
        """Strategy still transitions from PAPER_QUEUED to PAPER_ACTIVE."""
        ref = _promote_to_paper_queued(clean_root, "trans-001")
        execute_paper_trade(
            clean_root, "trans-001", ref, symbol="NQ", side="long",
        )
        s = get_strategy(clean_root, "trans-001")
        assert s.lifecycle_state == "PAPER_ACTIVE"

    def test_rejection_still_works(self, clean_root):
        """Pre-flight rejection still works without proof tracking."""
        # Strategy with no approval → rejected
        create_strategy(clean_root, "noapp-001", actor="atlas")
        transition_strategy(clean_root, "noapp-001", "CANDIDATE", actor="atlas")
        result = execute_paper_trade(
            clean_root, "noapp-001", "fake_ref", symbol="NQ", side="long",
        )
        assert result["success"] is False
        assert "proof" not in result or result.get("proof") is None

    def test_proof_tracking_failure_does_not_break_execution(self, clean_root):
        """Even if proof tracking fails, the fill succeeds."""
        ref = _promote_to_paper_queued(clean_root, "safe-001")
        # Sabotage the paper_runs directory to make proof tracking fail
        runs_dir = clean_root / "workspace" / "quant" / "executor" / "paper_runs"
        runs_dir.rmdir()  # Remove it
        (runs_dir.parent / "paper_runs").write_text("not a directory")  # Create a file instead

        result = execute_paper_trade(
            clean_root, "safe-001", ref, symbol="NQ", side="long",
        )
        # Execution still succeeds
        assert result["success"] is True
        assert result["fill"] is not None
        # Proof info will have an error
        assert "error" in result.get("proof", {})
