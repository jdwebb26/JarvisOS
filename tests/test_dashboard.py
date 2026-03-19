"""Tests for dashboard data aggregation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dashboard import collect_dashboard_data, DASHBOARD_HTML


def test_collect_returns_required_keys():
    data = collect_dashboard_data()
    assert "generated_at" in data
    assert "health" in data
    assert "next_actions" in data
    assert "approvals" in data
    assert "failed" in data
    assert "blocked" in data
    assert "queued" in data
    assert "promotable_outputs" in data
    assert "quant_live_queued" in data


def test_quant_live_queued_is_list():
    data = collect_dashboard_data()
    assert isinstance(data["quant_live_queued"], list)


def test_health_has_verdict():
    data = collect_dashboard_data()
    assert data["health"]["verdict"] in ("PASS", "WARN", "FAIL", "ERROR", "UNKNOWN")


def test_next_actions_is_list():
    data = collect_dashboard_data()
    assert isinstance(data["next_actions"], list)


def test_task_lists_are_lists():
    data = collect_dashboard_data()
    assert isinstance(data["approvals"], list)
    assert isinstance(data["failed"], list)
    assert isinstance(data["blocked"], list)
    assert isinstance(data["queued"], list)


def test_html_template_is_valid():
    assert "<!DOCTYPE html>" in DASHBOARD_HTML
    assert "OpenClaw" in DASHBOARD_HTML
    assert "/api/data" in DASHBOARD_HTML
