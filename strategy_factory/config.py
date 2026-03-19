from copy import deepcopy

TIMEFRAME_GATES = {
    "lt_5m_scalps": {
        "pf_after_costs_2x_slippage": 1.5,
        "max_drawdown_pct": 0.15,
        "min_trades_per_oos_fold": 500,
        "top_1pct_trade_pnl_share": 0.15,
        "profitable_months_pct": 0.75,
        "max_consecutive_losing_months": 1,
        "sharpe_floor": 1.0,
        "sortino_floor": 2.5,
        "n_cap": 500,
        "min_avg_trade_net_points": 1.5,
        "entry_noise_ticks": 1.5,
        "turnover_cap": 5.0,
        "time_weighted_rth_exposure": 0.40,
        "time_to_recovery_days": 10,
    },
    "5_60m_intraday": {
        "pf_after_costs_2x_slippage": 1.3,
        "max_drawdown_pct": 0.20,
        "min_trades_per_oos_fold": 150,
        "top_1pct_trade_pnl_share": 0.20,
        "profitable_months_pct": 0.70,
        "max_consecutive_losing_months": 2,
        "sharpe_floor": 0.8,
        "sortino_floor": 2.0,
        "n_cap": 200,
        "min_avg_trade_net_points": 2.0,
        "entry_noise_ticks": 1.0,
        "turnover_cap": 3.0,
        "time_weighted_rth_exposure": 0.60,
        "time_to_recovery_days": 15,
    },
    "multi_hour_overnight": {
        "pf_after_costs_2x_slippage": 1.2,
        "max_drawdown_pct": 0.15,
        "min_trades_per_oos_fold": 50,
        "top_1pct_trade_pnl_share": 0.25,
        "profitable_months_pct": 0.55,
        "max_consecutive_losing_months": 2,
        "sharpe_floor": 0.8,
        "sortino_floor": 1.5,
        "n_cap": 80,
        "min_avg_trade_net_points": 3.0,
        "entry_noise_ticks": 0.5,
        "turnover_cap": 1.5,
        "time_weighted_rth_exposure": 0.80,
        "time_to_recovery_days": 30,
    },
}

SESSION_SLIPPAGE = {
    "globex_overnight": {"hours": (18.0, 9.5), "multiplier": 1.3},
    "rth_open": {"hours": (9.5, 10.5), "multiplier": 1.5},
    "rth_midday": {"hours": (10.5, 14.0), "multiplier": 1.0},
    "rth_close": {"hours": (14.0, 16.0), "multiplier": 1.2},
}

FILL_MODEL = {
    "touch_only_0_tick": 0.00,
    "trade_through_1_tick": 0.70,
    "trade_through_2plus": 0.95,
    "adverse_selection": 0.25,
}

REGIMES = {
    "low_vol": {"vix_range": (0, 15), "pf_gate": 1.2},
    "mid_vol": {"vix_range": (15, 25), "pf_gate": 1.2},
    "high_vol": {"vix_range": (25, 999), "pf_gate": 1.0},
}

# ---------------------------------------------------------------------------
# Fold profiles — keyed by evidence tier
# ---------------------------------------------------------------------------
# Each evidence tier gets its own fold geometry. The runtime selects the
# profile from the dataset sidecar metadata, not from bar-count heuristics.

FOLD_PROFILES = {
    "research_only": {  # synthetic
        "mode": "rolling",
        "train_len": 5000,
        "test_len": 2000,
        "purge_len": 50,
        "retrain_cadence": 2000,
        "n_folds": 8,
        "minimum_any_fold_trades": 50,
    },
    "research": {  # daily real
        # 375-bar OOS (~18 months) gives 6-16 trades/fold for daily
        # strategies, enough for sharpe/sortino to be statistically
        # meaningful.  Previous 125-bar windows produced 1-6 trades
        # where ratio metrics were dominated by single-trade noise.
        # Non-overlapping cadence keeps folds independent.
        # 8 folds * (500+30+375) = 7240 bars needed; with 6438 bars
        # the builder produces as many folds as data allows.
        "mode": "rolling",
        "train_len": 500,
        "test_len": 375,
        "purge_len": 30,
        "retrain_cadence": 375,
        "n_folds": 8,
        "minimum_any_fold_trades": 1,
    },
    "exploratory": {  # hourly real
        "mode": "rolling",
        "train_len": 800,
        "test_len": 200,
        "purge_len": 30,
        "retrain_cadence": 200,
        "n_folds": 8,
        "minimum_any_fold_trades": 5,
    },
    "exploratory_4h": {  # 4h real — sparse bars (~300 from 60d hourly)
        # 100 bars train, 50 bars test, purge >= max_feature_lookback (26)
        # With cadence=50: fold0 train [0:100], purge [100:130], test [130:180]
        # fold1 starts at 50, etc.  3 folds needs ~280 bars.
        "mode": "rolling",
        "train_len": 100,
        "test_len": 50,
        "purge_len": 30,
        "retrain_cadence": 50,
        "n_folds": 3,
        "minimum_any_fold_trades": 1,
    },
    "exploratory_15m": {  # 15m real — ~1500 bars from 60d fetch
        "mode": "rolling",
        "train_len": 600,
        "test_len": 200,
        "purge_len": 30,
        "retrain_cadence": 200,
        "n_folds": 4,
        "minimum_any_fold_trades": 5,
    },
    "execution_grade": {  # intraday real
        "mode": "rolling",
        "train_len": 5000,
        "test_len": 2000,
        "purge_len": 50,
        "retrain_cadence": 2000,
        "n_folds": 8,
        "minimum_any_fold_trades": 50,
    },
}

# ---------------------------------------------------------------------------
# Gate profiles — keyed by evidence tier
# ---------------------------------------------------------------------------
# Each evidence tier has its own gate thresholds. Daily research cannot
# accidentally pass execution-grade gates.  The thresholds are honest for
# the data granularity: daily data produces fewer, noisier trades so
# min_trades and ratio floors are adjusted downward — but PF floor stays
# high to avoid promoting noise.

GATE_PROFILES = {
    "research_only": {  # synthetic — same as execution to catch regressions
        "pf_floor": 1.2,
        "min_trades_per_oos_fold": 50,
        "max_drawdown_proxy": 1000.0,
        "sharpe_floor": 0.8,
        "sortino_floor": 1.5,
    },
    "research": {  # daily real
        "pf_floor": 1.2,
        "min_trades_per_oos_fold": 1,
        "max_drawdown_proxy": 2000.0,
        "sharpe_floor": 0.3,
        "sortino_floor": 0.5,
    },
    "exploratory": {  # hourly real
        "pf_floor": 1.2,
        "min_trades_per_oos_fold": 5,
        "max_drawdown_proxy": 1500.0,
        "sharpe_floor": 0.5,
        "sortino_floor": 1.0,
    },
    "exploratory_4h": {  # 4h real — sparse data, relaxed like research
        "pf_floor": 1.2,
        "min_trades_per_oos_fold": 1,
        "max_drawdown_proxy": 2000.0,
        "sharpe_floor": 0.3,
        "sortino_floor": 0.5,
    },
    "exploratory_15m": {  # 15m real — decent bar count, moderate gates
        "pf_floor": 1.2,
        "min_trades_per_oos_fold": 5,
        "max_drawdown_proxy": 1500.0,
        "sharpe_floor": 0.5,
        "sortino_floor": 1.0,
    },
    "execution_grade": {  # intraday real — strictest
        "pf_floor": 1.2,
        "min_trades_per_oos_fold": 50,
        "max_drawdown_proxy": 1000.0,
        "sharpe_floor": 0.8,
        "sortino_floor": 1.5,
    },
}


# ---------------------------------------------------------------------------
# Family / dataset compatibility
# ---------------------------------------------------------------------------
# Not every strategy family makes sense on every data granularity.
# mean_reversion needs intraday signals; running it on daily bars produces
# NO_TRADES rejections that waste compute and clutter history.

FAMILY_DATASET_COMPAT = {
    "ema_crossover":    {"daily", "1h", "4h", "15m", "1min_bar", "5m", "synthetic"},
    "ema_crossover_cd": {"daily", "1h", "4h", "15m", "1min_bar", "5m", "synthetic"},
    "breakout":         {"daily", "1h", "4h", "15m", "1min_bar", "5m", "synthetic"},
    "mean_reversion":   {"1h", "4h", "15m", "1min_bar", "5m", "synthetic"},
}


def check_family_compat(family_id, data_granularity):
    """Check if a strategy family is compatible with the data granularity.

    Returns (is_compatible, reason_if_not).
    """
    compat_set = FAMILY_DATASET_COMPAT.get(family_id)
    if compat_set is None:
        return True, None  # unknown family — allow

    gran = data_granularity.lower()
    if gran in compat_set:
        return True, None

    return False, f"family:{family_id} incompatible with granularity:{gran}"


# ---------------------------------------------------------------------------
# Known dataset identities
# ---------------------------------------------------------------------------
KNOWN_DATASETS = {
    "NQ_daily": {
        "file_stem": "NQ_daily",
        "granularity": "daily",
        "instrument": "NQ",
        "description": "NQ=F daily OHLCV + VIX",
    },
    "NQ_hourly": {
        "file_stem": "NQ_hourly",
        "granularity": "1h",
        "instrument": "NQ",
        "description": "NQ=F hourly OHLCV + VIX (accumulated)",
    },
    "NQ_4h": {
        "file_stem": "NQ_4h",
        "granularity": "4h",
        "instrument": "NQ",
        "description": "NQ=F 4-hour OHLCV + VIX (resampled from hourly)",
    },
    "NQ_15m": {
        "file_stem": "NQ_15m",
        "granularity": "15m",
        "instrument": "NQ",
        "description": "NQ=F 15-minute OHLCV + VIX (accumulated)",
    },
}


def select_fold_profile(evidence_tier):
    """Select fold profile by evidence tier.

    Returns (fold_spec_dict, profile_name).
    Falls back to research_only if tier unknown.
    """
    if evidence_tier in FOLD_PROFILES:
        return deepcopy(FOLD_PROFILES[evidence_tier]), evidence_tier
    return deepcopy(FOLD_PROFILES["research_only"]), "research_only"


def select_gate_profile(evidence_tier):
    """Select gate profile by evidence tier.

    Returns (gate_dict, profile_name).
    Falls back to research_only if tier unknown.
    """
    if evidence_tier in GATE_PROFILES:
        return deepcopy(GATE_PROFILES[evidence_tier]), evidence_tier
    return deepcopy(GATE_PROFILES["research_only"]), "research_only"


DEFAULT_CONFIG = {
    "instrument": "NQ",
    "timeframe_bucket": "5_60m_intraday",
    "data_granularity": "1min_bar",
    "fold_spec": {
        "mode": "rolling",
        "train_len": 5000,
        "test_len": 2000,
        "purge_len": 50,
        "retrain_cadence": 2000,
        "n_folds": 8,
    },
    "features": {
        "ema_fast": {"lookback": 12},
        "ema_slow": {"lookback": 26},
        "atr": {"lookback": 14},
        "vix_regime": {"lookback": 20},
    },
    "reward_lambda": 0.05,
    "score_lambda": 0.30,
    "minimum_any_fold_trades": 50,
    "max_leverage": 4.0,
    "stop_floor_points": 2.0,
    "concentration_limit": 0.30,
    "optimizer_n_trials": 15,
    "optimizer_seed": 42,
    # Fold spec for daily granularity (used when bar count < 10000)
    # ~500 trading days train ≈ 2 years, ~125 days test ≈ 6 months
    "fold_spec_daily": {
        "mode": "rolling",
        "train_len": 500,
        "test_len": 125,
        "purge_len": 30,
        "retrain_cadence": 125,
        "n_folds": 8,
        # Daily bars produce far fewer trades than intraday.
        # 125 test days ≈ 6 months. A multi-hour/overnight strategy
        # might produce 1-10 trades per fold on daily bars.
        "minimum_any_fold_trades": 1,
    },
    # Transaction cost model (NQ futures)
    # NQ: 1 point = $20, 1 tick = 0.25 points = $5
    # commission_per_side_points: broker commission per side in NQ points
    #   (e.g., $2.50/side ÷ $20/point = 0.125 points)
    # slippage_per_side_points: expected slippage per side in NQ points
    #   (e.g., 1 tick = 0.25 points)
    # cost_per_trade = 2 * (commission_per_side + slippage_per_side)
    "cost_model": {
        "commission_per_side_points": 0.125,
        "slippage_per_side_points": 0.25,
    },
}

# ---------------------------------------------------------------------------
# Evidence classification system
# ---------------------------------------------------------------------------
# Determines what a backtest result can be used for based on the data
# that produced it.  This is a hard policy — not a suggestion.

EVIDENCE_TIERS = {
    "synthetic": {
        "source_class": "synthetic",
        "evidence_tier": "research_only",
        "promotion_eligible": False,
        "max_stage": "CANDIDATE",
        "description": "Synthetic data — development and research only",
    },
    "daily_real": {
        "source_class": "market_data",
        "evidence_tier": "research",
        "promotion_eligible": False,
        "max_stage": "CANDIDATE",
        "description": "Real daily bars — research grade, not execution-ready",
    },
    "hourly_real": {
        "source_class": "market_data",
        "evidence_tier": "exploratory",
        "promotion_eligible": False,
        "max_stage": "CANDIDATE",
        "description": "Real hourly bars — exploratory, pre-candidate",
    },
    "4h_real": {
        "source_class": "market_data",
        "evidence_tier": "exploratory_4h",
        "promotion_eligible": False,
        "max_stage": "CANDIDATE",
        "description": "Real 4-hour bars — exploratory, sparse data",
    },
    "15m_real": {
        "source_class": "market_data",
        "evidence_tier": "exploratory_15m",
        "promotion_eligible": False,
        "max_stage": "CANDIDATE",
        "description": "Real 15-minute bars — exploratory, pre-candidate",
    },
    "intraday_real": {
        "source_class": "market_data",
        "evidence_tier": "execution_grade",
        "promotion_eligible": True,
        "max_stage": "BACKTESTED",
        "description": "Real intraday bars (≤5m) — execution-grade evidence",
    },
}


def classify_evidence(data_source, data_granularity):
    """Classify evidence tier from data source and granularity.

    Args:
        data_source: "real" or "synthetic"
        data_granularity: "daily", "1h", "5m", "1m", "1min_bar", etc.

    Returns:
        dict with source_class, evidence_tier, promotion_eligible, max_stage,
        description.
    """
    if data_source == "synthetic":
        return dict(EVIDENCE_TIERS["synthetic"])

    gran = str(data_granularity).lower()

    if gran in ("daily", "1d", "day"):
        return dict(EVIDENCE_TIERS["daily_real"])

    if gran in ("4h", "4hr", "240m", "240min"):
        return dict(EVIDENCE_TIERS["4h_real"])

    if gran in ("1h", "hourly", "60m", "60min"):
        return dict(EVIDENCE_TIERS["hourly_real"])

    if gran in ("15m", "15min"):
        return dict(EVIDENCE_TIERS["15m_real"])

    # Anything ≤ 5 minutes is execution-grade
    if gran in ("1m", "1min", "1min_bar", "5m", "5min", "3m", "3min"):
        return dict(EVIDENCE_TIERS["intraday_real"])

    # Unknown granularity with real data — conservative: treat as daily
    return dict(EVIDENCE_TIERS["daily_real"])


def get_config():
    return deepcopy(DEFAULT_CONFIG)
