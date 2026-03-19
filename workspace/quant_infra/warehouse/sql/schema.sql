-- Quant Infrastructure Warehouse Schema
-- Bootstrap: python3 workspace/quant_infra/warehouse/bootstrap.py

-- OHLCV daily bars (loaded from cron CSV)
CREATE TABLE IF NOT EXISTS ohlcv_daily (
    symbol      VARCHAR NOT NULL DEFAULT 'NQ',
    bar_date    DATE NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      BIGINT,
    vix         DOUBLE,
    loaded_at   TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (symbol, bar_date)
);

-- Market environment snapshots (from OpenBB / Hermes)
CREATE TABLE IF NOT EXISTS market_environment_snapshots (
    snapshot_id     VARCHAR PRIMARY KEY,
    captured_at     TIMESTAMP NOT NULL,
    symbol          VARCHAR NOT NULL DEFAULT 'NQ',
    last_close      DOUBLE,
    vix_level       DOUBLE,
    trend_5d        VARCHAR,       -- 'up', 'down', 'flat'
    range_5d_pct    DOUBLE,
    regime          VARCHAR,       -- 'low_vol', 'normal', 'high_vol', 'crisis'
    macro_summary   VARCHAR,
    data_source     VARCHAR,
    freshness_hours DOUBLE,
    raw_json        VARCHAR        -- full OpenBB response if needed
);

-- Market news items (from Scout)
CREATE TABLE IF NOT EXISTS market_news_items (
    item_id         VARCHAR PRIMARY KEY,
    published_at    TIMESTAMP,
    ingested_at     TIMESTAMP DEFAULT current_timestamp,
    source          VARCHAR,
    headline        VARCHAR NOT NULL,
    summary         VARCHAR,
    symbols         VARCHAR,       -- comma-separated
    sentiment       VARCHAR,       -- 'bullish', 'bearish', 'neutral'
    relevance_score DOUBLE,
    url             VARCHAR,
    raw_json        VARCHAR
);

-- Kitt paper positions
CREATE TABLE IF NOT EXISTS kitt_paper_positions (
    position_id     VARCHAR PRIMARY KEY,
    opened_at       TIMESTAMP NOT NULL,
    closed_at       TIMESTAMP,
    symbol          VARCHAR NOT NULL DEFAULT 'NQ',
    direction       VARCHAR NOT NULL,  -- 'long' or 'short'
    quantity        INTEGER NOT NULL DEFAULT 1,
    entry_price     DOUBLE NOT NULL,
    exit_price      DOUBLE,
    stop_loss       DOUBLE,
    take_profit     DOUBLE,
    status          VARCHAR NOT NULL DEFAULT 'open',  -- 'open', 'closed', 'stopped_out', 'expired'
    pnl             DOUBLE,
    pnl_pct         DOUBLE,
    reasoning       VARCHAR,
    upstream_packet VARCHAR,       -- packet_id that triggered this
    mark_price      DOUBLE,        -- latest mark-to-market price
    marked_at       TIMESTAMP
);

-- Kitt trade decisions (audit log)
CREATE TABLE IF NOT EXISTS kitt_trade_decisions (
    decision_id     VARCHAR PRIMARY KEY,
    decided_at      TIMESTAMP NOT NULL,
    action          VARCHAR NOT NULL,  -- 'open_long', 'open_short', 'close', 'hold', 'skip'
    symbol          VARCHAR NOT NULL DEFAULT 'NQ',
    reasoning       VARCHAR NOT NULL,
    confidence      DOUBLE,
    market_context  VARCHAR,       -- summary of market state at decision time
    position_id     VARCHAR,       -- FK to kitt_paper_positions if action created/closed a position
    upstream_packets VARCHAR,      -- comma-separated packet_ids consumed
    outcome         VARCHAR        -- filled after position closed: 'win', 'loss', 'scratch'
);

-- Fish scenarios
CREATE TABLE IF NOT EXISTS fish_scenarios (
    scenario_id     VARCHAR PRIMARY KEY,
    created_at      TIMESTAMP NOT NULL,
    scenario_type   VARCHAR NOT NULL,  -- 'bull_continuation', 'failed_breakout', 'vol_expansion', 'gap_risk', 'stop_out', 'invalidation'
    symbol          VARCHAR NOT NULL DEFAULT 'NQ',
    description     VARCHAR NOT NULL,
    probability     DOUBLE,
    impact          VARCHAR,       -- 'positive', 'negative', 'neutral'
    target_price    DOUBLE,
    invalidation_price DOUBLE,
    timeframe       VARCHAR,       -- '1D', '1W', etc.
    kitt_position_id VARCHAR,      -- FK to the position this scenario evaluates
    upstream_packet VARCHAR,
    status          VARCHAR DEFAULT 'active'  -- 'active', 'realized', 'invalidated', 'expired'
);

-- Sigma validation inputs
CREATE TABLE IF NOT EXISTS sigma_validation_inputs (
    validation_id   VARCHAR PRIMARY KEY,
    submitted_at    TIMESTAMP NOT NULL,
    strategy_id     VARCHAR NOT NULL,
    source_lane     VARCHAR NOT NULL,  -- 'atlas', 'kitt', 'external'
    symbol          VARCHAR NOT NULL DEFAULT 'NQ',
    timeframe       VARCHAR,
    parameters_json VARCHAR,
    backtest_result_json VARCHAR,
    validation_status VARCHAR DEFAULT 'pending',  -- 'pending', 'passed', 'failed', 'deferred'
    notes           VARCHAR
);

-- Atlas experiment inputs
CREATE TABLE IF NOT EXISTS atlas_experiment_inputs (
    experiment_id   VARCHAR PRIMARY KEY,
    submitted_at    TIMESTAMP NOT NULL,
    experiment_type VARCHAR NOT NULL,  -- 'param_sweep', 'walk_forward', 'regime_test', 'custom'
    symbol          VARCHAR NOT NULL DEFAULT 'NQ',
    timeframe       VARCHAR,
    hypothesis      VARCHAR,
    parameters_json VARCHAR,
    data_range_start DATE,
    data_range_end   DATE,
    status          VARCHAR DEFAULT 'pending',  -- 'pending', 'running', 'completed', 'failed'
    result_summary  VARCHAR,
    result_json     VARCHAR
);

-- Token usage tracking (Jarvis observability)
CREATE TABLE IF NOT EXISTS token_usage (
    usage_id        VARCHAR PRIMARY KEY,
    recorded_at     TIMESTAMP NOT NULL,
    lane            VARCHAR NOT NULL,
    model           VARCHAR,
    prompt_tokens   INTEGER,
    completion_tokens INTEGER,
    total_tokens    INTEGER,
    estimated_cost_usd DOUBLE,
    session_id      VARCHAR,
    task_description VARCHAR
);
