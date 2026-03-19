def ensure_nq_only(instrument):
    if instrument != "NQ":
        raise ValueError(f"Execution instrument must be NQ only. Got: {instrument}")
