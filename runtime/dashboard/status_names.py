from __future__ import annotations


_STATUS_ALIASES = {
    "waiting_on_review": "waiting_review",
    "waiting_on_approval": "waiting_approval",
}


def normalize_status_name(status: str | None) -> str | None:
    if status is None:
        return None
    return _STATUS_ALIASES.get(status, status)


def normalize_status_counts(counts: dict[str, int] | None) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for status, count in (counts or {}).items():
        key = normalize_status_name(status) or "unknown"
        normalized[key] = normalized.get(key, 0) + count
    return normalized


def normalize_status_summary(summary: dict) -> dict:
    normalized = dict(summary)
    if "waiting_on_review" in normalized:
        normalized["waiting_review"] = normalized.pop("waiting_on_review")
    if "waiting_on_approval" in normalized:
        normalized["waiting_approval"] = normalized.pop("waiting_on_approval")
    if "counts" in normalized:
        normalized["counts"] = normalize_status_counts(normalized.get("counts"))
    return normalized
