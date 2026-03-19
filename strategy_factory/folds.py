def validate_purge_gap(purge_len, max_feature_lookback, sentinel_mode=False):
    if sentinel_mode:
        return
    if int(purge_len) < int(max_feature_lookback):
        raise ValueError(
            f"Purge gap {purge_len} < max lookback {max_feature_lookback}. DATA LEAKAGE."
        )


def build_folds(n_rows, fold_spec, max_feature_lookback, sentinel_mode=False):
    mode = fold_spec["mode"]
    train_len = int(fold_spec["train_len"])
    test_len = int(fold_spec["test_len"])
    purge_len = int(fold_spec["purge_len"])
    retrain_cadence = int(fold_spec["retrain_cadence"])
    n_folds = int(fold_spec["n_folds"])

    validate_purge_gap(purge_len, max_feature_lookback, sentinel_mode=sentinel_mode)

    if sentinel_mode:
        return [{
            "fold_id": 0,
            "mode": mode,
            "train_start": 0,
            "train_end": min(train_len, n_rows),
            "purge_start": min(train_len, n_rows),
            "purge_end": min(train_len, n_rows),
            "test_start": min(train_len, n_rows),
            "test_end": min(train_len + test_len, n_rows),
            "purge_len": 0,
            "retrain_cadence": retrain_cadence,
            "invalid_for_selection": True,
        }]

    folds = []
    cursor = 0
    for i in range(n_folds):
        train_start = cursor if mode == "rolling" else 0
        if mode not in {"rolling", "anchored"}:
            raise ValueError(f"Unsupported fold mode: {mode}")

        train_end = train_start + train_len
        purge_start = train_end
        purge_end = purge_start + purge_len
        test_start = purge_end
        test_end = test_start + test_len

        if test_end > n_rows:
            break

        folds.append({
            "fold_id": i,
            "mode": mode,
            "train_start": train_start,
            "train_end": train_end,
            "purge_start": purge_start,
            "purge_end": purge_end,
            "test_start": test_start,
            "test_end": test_end,
            "purge_len": purge_len,
            "retrain_cadence": retrain_cadence,
            "invalid_for_selection": False,
        })

        cursor += retrain_cadence

    if not folds:
        raise ValueError("No folds produced. Check data length and fold_spec.")

    return folds
