-- Quant Infrastructure Warehouse Views

-- Latest market snapshot
CREATE OR REPLACE VIEW v_latest_market AS
SELECT *
FROM market_environment_snapshots
ORDER BY captured_at DESC
LIMIT 1;

-- NQ daily with technical indicators
CREATE OR REPLACE VIEW v_nq_daily_enriched AS
SELECT
    bar_date,
    open, high, low, close, volume, vix,
    close - LAG(close) OVER (ORDER BY bar_date) AS daily_change,
    ROUND((close - LAG(close) OVER (ORDER BY bar_date)) / LAG(close) OVER (ORDER BY bar_date) * 100, 3) AS daily_change_pct,
    AVG(close) OVER (ORDER BY bar_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS sma_5,
    AVG(close) OVER (ORDER BY bar_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS sma_20,
    MAX(high) OVER (ORDER BY bar_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS high_5d,
    MIN(low) OVER (ORDER BY bar_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS low_5d,
    ROUND((MAX(high) OVER (ORDER BY bar_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)
         - MIN(low) OVER (ORDER BY bar_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW))
         / close * 100, 2) AS range_5d_pct,
    AVG(volume) OVER (ORDER BY bar_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS avg_volume_5d
FROM ohlcv_daily
WHERE symbol = 'NQ'
ORDER BY bar_date;

-- Open paper positions summary
CREATE OR REPLACE VIEW v_open_paper_positions AS
SELECT
    position_id,
    opened_at,
    symbol,
    direction,
    quantity,
    entry_price,
    stop_loss,
    take_profit,
    mark_price,
    marked_at,
    CASE direction
        WHEN 'long'  THEN ROUND((COALESCE(mark_price, entry_price) - entry_price) * quantity * 20, 2)
        WHEN 'short' THEN ROUND((entry_price - COALESCE(mark_price, entry_price)) * quantity * 20, 2)
    END AS unrealized_pnl,
    reasoning
FROM kitt_paper_positions
WHERE status = 'open'
ORDER BY opened_at DESC;

-- Paper trading performance summary
CREATE OR REPLACE VIEW v_paper_performance AS
SELECT
    COUNT(*) AS total_trades,
    COUNT(*) FILTER (WHERE status != 'open') AS closed_trades,
    COUNT(*) FILTER (WHERE status = 'open') AS open_trades,
    COUNT(*) FILTER (WHERE pnl > 0) AS winners,
    COUNT(*) FILTER (WHERE pnl < 0) AS losers,
    COUNT(*) FILTER (WHERE pnl = 0 OR pnl IS NULL) AS scratches,
    ROUND(AVG(pnl) FILTER (WHERE pnl IS NOT NULL), 2) AS avg_pnl,
    ROUND(SUM(pnl) FILTER (WHERE pnl IS NOT NULL), 2) AS total_pnl,
    ROUND(CASE WHEN COUNT(*) FILTER (WHERE pnl IS NOT NULL AND pnl != 0) > 0
        THEN COUNT(*) FILTER (WHERE pnl > 0) * 100.0 / COUNT(*) FILTER (WHERE pnl IS NOT NULL AND pnl != 0)
        ELSE 0 END, 1) AS win_rate_pct
FROM kitt_paper_positions;

-- Active Fish scenarios
CREATE OR REPLACE VIEW v_active_scenarios AS
SELECT
    scenario_id,
    created_at,
    scenario_type,
    symbol,
    description,
    probability,
    impact,
    target_price,
    invalidation_price,
    timeframe,
    kitt_position_id
FROM fish_scenarios
WHERE status = 'active'
ORDER BY created_at DESC;

-- Recent trade decisions
CREATE OR REPLACE VIEW v_recent_decisions AS
SELECT
    decision_id,
    decided_at,
    action,
    symbol,
    reasoning,
    confidence,
    position_id,
    outcome
FROM kitt_trade_decisions
ORDER BY decided_at DESC
LIMIT 50;

-- Token usage by lane (last 7 days)
CREATE OR REPLACE VIEW v_token_usage_7d AS
SELECT
    lane,
    COUNT(*) AS calls,
    SUM(total_tokens) AS total_tokens,
    ROUND(SUM(estimated_cost_usd), 4) AS total_cost_usd,
    ROUND(AVG(total_tokens), 0) AS avg_tokens_per_call
FROM token_usage
WHERE recorded_at >= current_timestamp - INTERVAL 7 DAY
GROUP BY lane
ORDER BY total_tokens DESC;

-- Pending validations
CREATE OR REPLACE VIEW v_pending_validations AS
SELECT *
FROM sigma_validation_inputs
WHERE validation_status = 'pending'
ORDER BY submitted_at DESC;

-- Pending experiments
CREATE OR REPLACE VIEW v_pending_experiments AS
SELECT *
FROM atlas_experiment_inputs
WHERE status = 'pending'
ORDER BY submitted_at DESC;
