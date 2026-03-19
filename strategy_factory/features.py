def compute_max_feature_lookback(features_cfg):
    lookbacks = []
    for _, cfg in (features_cfg or {}).items():
        lookbacks.append(int(cfg.get("lookback", 1)))
    return max(lookbacks) if lookbacks else 1


def _ema(values, period):
    """Compute exponential moving average. Returns list same length as values.
    First (period-1) entries use expanding EMA (warmup), not NaN."""
    if not values:
        return []
    alpha = 2.0 / (period + 1)
    result = [values[0]]
    for i in range(1, len(values)):
        result.append(alpha * values[i] + (1 - alpha) * result[-1])
    return result


def _atr(rows, period):
    """Compute Average True Range. Returns list same length as rows.
    Uses EMA-smoothed TR."""
    if not rows:
        return []
    trs = []
    for i, row in enumerate(rows):
        h = row["high"]
        l = row["low"]
        if i == 0:
            tr = h - l
        else:
            prev_c = rows[i - 1]["close"]
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    return _ema(trs, period)


def compute_features(rows, features_cfg):
    """Compute features on bar data and return enriched rows.

    Each row gets additional keys:
        ema_fast, ema_slow, atr, vix_regime

    Args:
        rows: list of dicts with open/high/low/close/volume/vix
        features_cfg: dict like {"ema_fast": {"lookback": 12}, ...}

    Returns:
        list of enriched row dicts (new list, original rows not mutated)
    """
    if not rows:
        return []

    closes = [r["close"] for r in rows]

    ema_fast_period = features_cfg.get("ema_fast", {}).get("lookback", 12)
    ema_slow_period = features_cfg.get("ema_slow", {}).get("lookback", 26)
    atr_period = features_cfg.get("atr", {}).get("lookback", 14)

    ema_fast_vals = _ema(closes, ema_fast_period)
    ema_slow_vals = _ema(closes, ema_slow_period)
    atr_vals = _atr(rows, atr_period)

    enriched = []
    for i, row in enumerate(rows):
        r = dict(row)
        r["ema_fast"] = round(ema_fast_vals[i], 4)
        r["ema_slow"] = round(ema_slow_vals[i], 4)
        r["atr"] = round(atr_vals[i], 4)
        vix = row.get("vix", 20.0)
        if vix < 15:
            r["vix_regime"] = "low_vol"
        elif vix < 25:
            r["vix_regime"] = "mid_vol"
        else:
            r["vix_regime"] = "high_vol"
        enriched.append(r)

    return enriched
