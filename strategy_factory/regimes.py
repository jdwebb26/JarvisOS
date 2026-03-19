def label_regime(vix_value):
    if vix_value < 15:
        return "low_vol"
    if vix_value < 25:
        return "mid_vol"
    return "high_vol"


def regime_gate(bucket_trades, bucket_pf, bucket_pnl, fold_equity, pf_threshold):
    if bucket_trades >= 15:
        return bool(bucket_pf is not None and bucket_pf >= pf_threshold)
    return bucket_pnl >= (-0.05 * fold_equity)
