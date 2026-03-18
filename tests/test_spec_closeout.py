"""test_spec_closeout.py — Tests for spec closeout checks."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.spec_closeout import (
    run_closeout,
    render_terminal,
    check_operator_loop,
    check_discord_delivery,
    check_flowstate,
    check_packaging,
)


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n")


# ---------------------------------------------------------------------------
# Individual check tests
# ---------------------------------------------------------------------------

def test_operator_loop_proven_when_all_up():
    with patch("scripts.spec_closeout._unit_active", return_value=True), \
         patch("scripts.spec_closeout._count_files", return_value=10):
        result = check_operator_loop()
    assert result["status"] == "PROVEN"


def test_operator_loop_partial_when_service_down():
    call_count = [0]
    def mock_active(unit):
        call_count[0] += 1
        return call_count[0] > 1  # first call returns False
    with patch("scripts.spec_closeout._unit_active", side_effect=mock_active), \
         patch("scripts.spec_closeout._count_files", return_value=10):
        result = check_operator_loop()
    assert result["status"] in ("PARTIAL", "MISSING")


def test_discord_delivery_proven():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        d = root / "state/discord_outbox"
        d.mkdir(parents=True)
        for i in range(5):
            _write(d / f"outbox_{i}.json", {"status": "delivered"})
        with patch("scripts.spec_closeout.ROOT", root), \
             patch("scripts.spec_closeout._count_files", return_value=5):
            result = check_discord_delivery()
    assert result["status"] == "PROVEN"


def test_discord_delivery_partial_with_failures():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        d = root / "state/discord_outbox"
        d.mkdir(parents=True)
        for i in range(3):
            _write(d / f"outbox_ok_{i}.json", {"status": "delivered"})
        for i in range(10):
            _write(d / f"outbox_fail_{i}.json", {"status": "failed"})
        with patch("scripts.spec_closeout.ROOT", root), \
             patch("scripts.spec_closeout._count_files", return_value=13):
            result = check_discord_delivery()
    assert result["status"] == "PARTIAL"


def test_flowstate_superseded():
    result = check_flowstate()
    assert result["status"] == "SUPERSEDED"


def test_packaging_proven_when_all_present():
    with patch("scripts.spec_closeout._file_exists", return_value=True):
        result = check_packaging()
    assert result["status"] == "PROVEN"


def test_packaging_partial_when_missing():
    def mock_exists(p):
        return "install.sh" in p
    with patch("scripts.spec_closeout._file_exists", side_effect=mock_exists):
        result = check_packaging()
    assert result["status"] == "PARTIAL"


# ---------------------------------------------------------------------------
# Orchestrator / render tests
# ---------------------------------------------------------------------------

def test_run_closeout_returns_counts():
    with patch("scripts.spec_closeout.ALL_CHECKS", [check_flowstate]):
        data = run_closeout()
    assert data["total"] == 1
    assert data["by_status"]["SUPERSEDED"] == 1


def test_render_terminal_shows_status_groups():
    data = {
        "total": 3,
        "by_status": {"PROVEN": 1, "PARTIAL": 1, "BLOCKED": 1},
        "items": [
            {"item": "A", "status": "PROVEN", "evidence": "yes", "fix": ""},
            {"item": "B", "status": "PARTIAL", "evidence": "half", "fix": "do X"},
            {"item": "C", "status": "BLOCKED", "evidence": "no key", "fix": "set key"},
        ],
    }
    text = render_terminal(data)
    assert "1/3 PROVEN" in text
    assert "BLOCKED" in text
    assert "PARTIAL" in text
    assert "fix:" in text
