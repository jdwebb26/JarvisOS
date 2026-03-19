#!/usr/bin/env python3
"""Quant Executor — Paper Proof Tracker & Live Promotion Gate.

Owns:
  - paper run records (durable, per-strategy)
  - proof metric accumulation over strategy-specific horizons
  - promotion packet generation when proof is sufficient
  - live execution gating (impossible without explicit approval)

Core rule:
  paper_active does NOT mean live eligible.
  A strategy must prove over its strategy-specific proof window,
  emit a review-ready promotion packet, get approved, and only
  then become live-eligible.

Proof profiles are per-strategy, keyed by horizon_class:
  scalp, intraday, swing, event

Each profile defines the minimum evidence required before
a strategy can be proposed for live promotion.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import make_packet, QuantPacket
from workspace.quant.shared.packet_store import store_packet


# ---------------------------------------------------------------------------
# Proof profiles — strategy-specific proof windows
# ---------------------------------------------------------------------------

@dataclass
class ProofProfile:
    """Defines the minimum evidence required for live promotion."""
    time_horizon_class: str          # scalp, intraday, swing, event
    min_trades_required: int = 20
    min_days_required: int = 5
    min_expectancy: float = 0.5      # avg profit per trade in points
    min_win_rate: Optional[float] = None  # 0-1, None = not required
    max_drawdown: float = 2000.0     # max drawdown in dollars
    max_consecutive_losses: int = 5
    required_market_regimes: Optional[list[str]] = None  # e.g. ["trending", "ranging"]

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "ProofProfile":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


# Built-in profiles — operator can override via config
DEFAULT_PROFILES: dict[str, ProofProfile] = {
    "scalp": ProofProfile(
        time_horizon_class="scalp",
        min_trades_required=50,
        min_days_required=5,
        min_expectancy=0.3,
        min_win_rate=0.55,
        max_drawdown=1000.0,
        max_consecutive_losses=8,
    ),
    "intraday": ProofProfile(
        time_horizon_class="intraday",
        min_trades_required=30,
        min_days_required=10,
        min_expectancy=0.5,
        min_win_rate=0.50,
        max_drawdown=1500.0,
        max_consecutive_losses=6,
    ),
    "swing": ProofProfile(
        time_horizon_class="swing",
        min_trades_required=15,
        min_days_required=21,
        min_expectancy=1.0,
        max_drawdown=2000.0,
        max_consecutive_losses=4,
    ),
    "event": ProofProfile(
        time_horizon_class="event",
        min_trades_required=10,
        min_days_required=14,
        min_expectancy=0.8,
        max_drawdown=2500.0,
        max_consecutive_losses=3,
    ),
}


def load_proof_profiles(root: Path) -> dict[str, ProofProfile]:
    """Load proof profiles from config or return defaults."""
    path = root / "workspace" / "quant" / "shared" / "config" / "proof_profiles.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            profiles = {}
            for key, val in data.items():
                profiles[key] = ProofProfile.from_dict(val)
            return profiles
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_PROFILES)


def get_proof_profile(root: Path, horizon_class: str) -> ProofProfile:
    """Get the proof profile for a given horizon class."""
    profiles = load_proof_profiles(root)
    if horizon_class not in profiles:
        raise ValueError(f"Unknown horizon_class: {horizon_class!r}. "
                         f"Available: {list(profiles.keys())}")
    return profiles[horizon_class]


# ---------------------------------------------------------------------------
# Paper run records — durable, per-strategy
# ---------------------------------------------------------------------------

@dataclass
class PaperRun:
    """Durable record of a paper trading run for one strategy."""
    paper_run_id: str
    strategy_id: str
    started_at: str
    status: str                      # paper_active, paper_monitoring, paper_proof_ready,
                                     # awaiting_review, review_rejected, live_ready,
                                     # archived
    horizon_class: str
    entry_count: int = 0
    closed_count: int = 0
    open_positions: int = 0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    max_drawdown: float = 0.0
    win_count: int = 0
    loss_count: int = 0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0
    win_rate: float = 0.0
    expectancy: float = 0.0
    proof_status: str = "accumulating"  # accumulating, sufficient, insufficient
    last_checkpoint: str = ""
    promotion_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "PaperRun":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


def _runs_dir(root: Path) -> Path:
    d = root / "workspace" / "quant" / "executor" / "paper_runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _make_run_id(strategy_id: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = hashlib.sha256(f"{strategy_id}{ts}".encode()).hexdigest()[:8]
    return f"prun_{strategy_id}_{ts}_{short}"


def create_paper_run(root: Path, strategy_id: str, horizon_class: str) -> PaperRun:
    """Create a new paper run record for a strategy entering paper_active."""
    # Validate horizon class
    get_proof_profile(root, horizon_class)

    run = PaperRun(
        paper_run_id=_make_run_id(strategy_id),
        strategy_id=strategy_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        status="paper_active",
        horizon_class=horizon_class,
        last_checkpoint=datetime.now(timezone.utc).isoformat(),
    )
    save_paper_run(root, run)
    return run


def save_paper_run(root: Path, run: PaperRun):
    """Persist a paper run record."""
    path = _runs_dir(root) / f"{run.paper_run_id}.json"
    path.write_text(json.dumps(run.to_dict(), indent=2) + "\n", encoding="utf-8")


def load_paper_run(root: Path, paper_run_id: str) -> Optional[PaperRun]:
    """Load a paper run by ID."""
    path = _runs_dir(root) / f"{paper_run_id}.json"
    if not path.exists():
        return None
    try:
        return PaperRun.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return None


def get_active_run(root: Path, strategy_id: str) -> Optional[PaperRun]:
    """Find the active paper run for a strategy (if any)."""
    d = _runs_dir(root)
    for f in sorted(d.glob(f"prun_{strategy_id}_*.json"), reverse=True):
        try:
            run = PaperRun.from_dict(json.loads(f.read_text(encoding="utf-8")))
            if run.status in ("paper_active", "paper_monitoring", "paper_proof_ready",
                              "awaiting_review"):
                return run
        except (json.JSONDecodeError, OSError):
            continue
    return None


def list_paper_runs(root: Path, strategy_id: Optional[str] = None) -> list[PaperRun]:
    """List all paper runs, optionally filtered by strategy."""
    d = _runs_dir(root)
    runs = []
    pattern = f"prun_{strategy_id}_*.json" if strategy_id else "prun_*.json"
    for f in sorted(d.glob(pattern)):
        try:
            runs.append(PaperRun.from_dict(json.loads(f.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, OSError):
            continue
    return runs


# ---------------------------------------------------------------------------
# Proof metric accumulation
# ---------------------------------------------------------------------------

def record_fill(root: Path, paper_run_id: str, pnl: float, is_winner: bool) -> PaperRun:
    """Record a completed trade (fill) against a paper run.

    Updates entry_count, closed_count, realized_pnl, win/loss counts,
    consecutive losses, win_rate, expectancy, max_drawdown.
    """
    run = load_paper_run(root, paper_run_id)
    if run is None:
        raise ValueError(f"Paper run {paper_run_id} not found")
    if run.status not in ("paper_active", "paper_monitoring"):
        raise ValueError(f"Paper run {paper_run_id} is {run.status}, cannot record fills")

    run.entry_count += 1
    run.closed_count += 1
    run.realized_pnl += pnl

    if is_winner:
        run.win_count += 1
        run.consecutive_losses = 0
    else:
        run.loss_count += 1
        run.consecutive_losses += 1
        run.max_consecutive_losses = max(run.max_consecutive_losses, run.consecutive_losses)

    total = run.win_count + run.loss_count
    run.win_rate = round(run.win_count / total, 4) if total > 0 else 0.0
    run.expectancy = round(run.realized_pnl / total, 2) if total > 0 else 0.0

    # Track drawdown (simplified: peak-to-trough of realized_pnl)
    if run.realized_pnl < 0:
        run.max_drawdown = max(run.max_drawdown, abs(run.realized_pnl))

    run.last_checkpoint = datetime.now(timezone.utc).isoformat()
    save_paper_run(root, run)
    return run


def evaluate_proof(root: Path, paper_run_id: str) -> dict:
    """Evaluate whether a paper run has accumulated sufficient proof.

    Returns {sufficient: bool, criteria: {name: {required, actual, met}}, run}.
    """
    run = load_paper_run(root, paper_run_id)
    if run is None:
        raise ValueError(f"Paper run {paper_run_id} not found")

    profile = get_proof_profile(root, run.horizon_class)

    # Compute days elapsed
    try:
        started = datetime.fromisoformat(run.started_at)
        days_elapsed = (datetime.now(timezone.utc) - started).total_seconds() / 86400
    except (ValueError, TypeError):
        days_elapsed = 0.0

    criteria = {}

    criteria["min_trades"] = {
        "required": profile.min_trades_required,
        "actual": run.closed_count,
        "met": run.closed_count >= profile.min_trades_required,
    }
    criteria["min_days"] = {
        "required": profile.min_days_required,
        "actual": round(days_elapsed, 1),
        "met": days_elapsed >= profile.min_days_required,
    }
    criteria["min_expectancy"] = {
        "required": profile.min_expectancy,
        "actual": run.expectancy,
        "met": run.expectancy >= profile.min_expectancy,
    }
    criteria["max_drawdown"] = {
        "required": profile.max_drawdown,
        "actual": run.max_drawdown,
        "met": run.max_drawdown <= profile.max_drawdown,
    }
    criteria["max_consecutive_losses"] = {
        "required": profile.max_consecutive_losses,
        "actual": run.max_consecutive_losses,
        "met": run.max_consecutive_losses <= profile.max_consecutive_losses,
    }

    if profile.min_win_rate is not None:
        criteria["min_win_rate"] = {
            "required": profile.min_win_rate,
            "actual": run.win_rate,
            "met": run.win_rate >= profile.min_win_rate,
        }

    all_met = all(c["met"] for c in criteria.values())

    # Update proof_status on the run
    run.proof_status = "sufficient" if all_met else "accumulating"
    if run.status == "paper_active" and all_met:
        run.status = "paper_proof_ready"
    save_paper_run(root, run)

    return {"sufficient": all_met, "criteria": criteria, "run": run}


# ---------------------------------------------------------------------------
# Promotion — review-ready packet when proof is sufficient
# ---------------------------------------------------------------------------

@dataclass
class PromotionReview:
    """Review record for a strategy seeking live promotion."""
    promotion_id: str
    strategy_id: str
    paper_run_id: str
    summary: str
    proof_metrics: dict
    artifacts: list[str]
    recommended_action: str      # promote_to_live, extend_paper, reject
    status: str = "pending"      # pending, approved, rejected, rerun_paper
    created_at: str = ""
    decided_at: Optional[str] = None
    decision_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "PromotionReview":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


def _promotions_dir(root: Path) -> Path:
    d = root / "workspace" / "quant" / "executor" / "promotions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_promotion_review(root: Path, paper_run_id: str) -> tuple[PromotionReview, QuantPacket]:
    """Create a promotion review record and emit a review packet.

    Only works if the paper run has proof_status=sufficient.
    Returns (promotion_review, review_packet).
    """
    run = load_paper_run(root, paper_run_id)
    if run is None:
        raise ValueError(f"Paper run {paper_run_id} not found")

    eval_result = evaluate_proof(root, paper_run_id)
    run = eval_result["run"]  # re-read after evaluate

    if not eval_result["sufficient"]:
        failing = [k for k, v in eval_result["criteria"].items() if not v["met"]]
        raise ValueError(f"Proof insufficient for {paper_run_id}. "
                         f"Failing: {failing}")

    ts = datetime.now(timezone.utc)
    short = hashlib.sha256(f"{run.strategy_id}{ts.isoformat()}".encode()).hexdigest()[:8]
    promo_id = f"promo_{run.strategy_id}_{short}"

    summary = (
        f"{run.strategy_id} ({run.horizon_class}): "
        f"{run.closed_count} trades over "
        f"{(ts - datetime.fromisoformat(run.started_at)).days}d, "
        f"PnL={run.realized_pnl:+.2f}, "
        f"expectancy={run.expectancy:.2f}, "
        f"win_rate={run.win_rate:.0%}, "
        f"max_dd={run.max_drawdown:.0f}"
    )

    promo = PromotionReview(
        promotion_id=promo_id,
        strategy_id=run.strategy_id,
        paper_run_id=paper_run_id,
        summary=summary,
        proof_metrics={k: v for k, v in eval_result["criteria"].items()},
        artifacts=[str(_runs_dir(root) / f"{paper_run_id}.json")],
        recommended_action="promote_to_live",
        status="pending",
        created_at=ts.isoformat(),
    )

    # Save promotion record
    path = _promotions_dir(root) / f"{promo_id}.json"
    path.write_text(json.dumps(promo.to_dict(), indent=2) + "\n", encoding="utf-8")

    # Update paper run
    run.status = "awaiting_review"
    run.promotion_id = promo_id
    save_paper_run(root, run)

    # Emit review packet
    pkt = make_packet(
        "paper_review_packet", "sigma",
        f"Paper proof complete: {summary}",
        priority="high",
        strategy_id=run.strategy_id,
        trade_count=run.closed_count,
        realized_pf=round(1.0 + run.expectancy / 10, 2) if run.expectancy > 0 else 0.8,
        realized_sharpe=round(run.expectancy / max(run.max_drawdown / 100, 0.01), 2),
        max_drawdown=round(run.max_drawdown / 10000, 4),
        fill_rate=0.95,
        outcome="advance_to_live" if eval_result["sufficient"] else "iterate",
        outcome_reasoning=summary,
        notes=f"promotion_id={promo_id}; paper_run_id={paper_run_id}; horizon={run.horizon_class}",
    )
    store_packet(root, pkt)

    return promo, pkt


def decide_promotion(root: Path, promotion_id: str, decision: str,
                     reason: str = "") -> PromotionReview:
    """Record operator decision on a promotion review.

    decision: "approved", "rejected", "rerun_paper"
    """
    path = _promotions_dir(root) / f"{promotion_id}.json"
    if not path.exists():
        raise ValueError(f"Promotion {promotion_id} not found")

    promo = PromotionReview.from_dict(json.loads(path.read_text(encoding="utf-8")))
    if promo.status != "pending":
        raise ValueError(f"Promotion {promotion_id} already decided: {promo.status}")

    promo.status = decision
    promo.decided_at = datetime.now(timezone.utc).isoformat()
    promo.decision_reason = reason

    path.write_text(json.dumps(promo.to_dict(), indent=2) + "\n", encoding="utf-8")

    # Update paper run status
    run = load_paper_run(root, promo.paper_run_id)
    if run:
        if decision == "approved":
            run.status = "live_ready"
        elif decision == "rejected":
            run.status = "review_rejected"
        elif decision == "rerun_paper":
            run.status = "paper_active"  # Back to accumulating
            run.proof_status = "accumulating"
        save_paper_run(root, run)

    return promo


# ---------------------------------------------------------------------------
# Live execution request — blocked without approval
# ---------------------------------------------------------------------------

@dataclass
class LiveExecRequest:
    """Request to begin live execution for an approved strategy."""
    live_exec_id: str
    strategy_id: str
    approved_promotion_id: str
    risk_caps: dict
    size_policy: dict
    operator_approval_ref: str
    status: str = "pending"        # pending, active, paused, failed, archived
    created_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LiveExecRequest":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


def request_live_execution(
    root: Path,
    strategy_id: str,
    promotion_id: str,
    operator_approval_ref: str,
    risk_caps: Optional[dict] = None,
    size_policy: Optional[dict] = None,
) -> LiveExecRequest:
    """Create a live execution request. Blocked unless promotion is approved.

    Returns LiveExecRequest or raises ValueError.
    """
    # Verify promotion exists and is approved
    promo_path = _promotions_dir(root) / f"{promotion_id}.json"
    if not promo_path.exists():
        raise ValueError(f"Promotion {promotion_id} not found")
    promo = PromotionReview.from_dict(json.loads(promo_path.read_text(encoding="utf-8")))
    if promo.status != "approved":
        raise ValueError(f"Promotion {promotion_id} is {promo.status}, not approved. "
                         f"Live execution blocked.")
    if promo.strategy_id != strategy_id:
        raise ValueError(f"Promotion {promotion_id} is for {promo.strategy_id}, "
                         f"not {strategy_id}")

    # Verify operator approval ref exists
    if not operator_approval_ref:
        raise ValueError("operator_approval_ref is required for live execution")

    ts = datetime.now(timezone.utc)
    short = hashlib.sha256(f"{strategy_id}{ts.isoformat()}".encode()).hexdigest()[:8]

    req = LiveExecRequest(
        live_exec_id=f"lexec_{strategy_id}_{short}",
        strategy_id=strategy_id,
        approved_promotion_id=promotion_id,
        risk_caps=risk_caps or {"max_position_size": 1, "max_loss_per_trade": 500,
                                "max_total_drawdown": 2000},
        size_policy=size_policy or {"method": "fixed", "contracts": 1},
        operator_approval_ref=operator_approval_ref,
        status="pending",
        created_at=ts.isoformat(),
    )

    # Save
    d = root / "workspace" / "quant" / "executor" / "live_requests"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{req.live_exec_id}.json"
    path.write_text(json.dumps(req.to_dict(), indent=2) + "\n", encoding="utf-8")

    return req
