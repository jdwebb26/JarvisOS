from __future__ import annotations

import json
from pathlib import Path

from runtime.integrations.shadowbroker_adapter import validate_shadowbroker_runtime
from scripts.preflight_lib import (
    build_doctor_report,
    smoke_shadowbroker_bad_payload,
    smoke_shadowbroker_missing_config,
    smoke_shadowbroker_mocked_success,
)


def test_shadowbroker_invalid_config_is_classified_explicitly():
    result = validate_shadowbroker_runtime(metadata_override={"base_url": "notaurl", "timeout_seconds": 5})
    assert result["status"] == "blocked_shadowbroker_invalid_config"


def test_shadowbroker_stale_snapshot_is_reported_honestly(tmp_path: Path):
    health_dir = tmp_path / "state" / "shadowbroker_backend_health"
    snapshot_dir = tmp_path / "state" / "shadowbroker_snapshots"
    health_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (health_dir / "latest.json").write_text(
        json.dumps(
            {
                "backend_id": "shadowbroker",
                "created_at": "2026-03-12T00:00:00+00:00",
                "updated_at": "2026-03-12T00:00:00+00:00",
                "configured": True,
                "status": "healthy",
                "healthy": True,
                "base_url": "https://shadowbroker.invalid",
                "degraded_reason": "",
                "timeout_seconds": 5,
                "latency_ms": 12,
            }
        ),
        encoding="utf-8",
    )
    (snapshot_dir / "old.json").write_text(
        json.dumps(
            {
                "snapshot_id": "old",
                "created_at": "2020-01-01T00:00:00+00:00",
                "updated_at": "2020-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    report = build_doctor_report(root=tmp_path)
    shadowbroker_items = report["groups"]["shadowbroker"]
    assert any("stale" in item["message"].lower() for item in shadowbroker_items)


def test_shadowbroker_smoke_missing_config():
    result = smoke_shadowbroker_missing_config(Path("."))
    assert result["ok"] is True
    assert result["summary"]["backend_status"] == "blocked_shadowbroker_not_configured"


def test_shadowbroker_smoke_mocked_success(tmp_path: Path):
    result = smoke_shadowbroker_mocked_success(tmp_path)
    assert result["ok"] is True
    assert result["summary"]["backend_status"] == "healthy"


def test_shadowbroker_smoke_bad_payload(tmp_path: Path):
    result = smoke_shadowbroker_bad_payload(tmp_path)
    assert result["ok"] is True
    assert result["summary"]["backend_status"] == "degraded_shadowbroker_bad_payload"
