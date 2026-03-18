"""test_sync_systemd_units.py — Tests for systemd unit sync logic."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sync_systemd_units import (
    compute_plan,
    discover_repo_units,
    install_units,
)


def _setup(tmpdir: Path) -> tuple[Path, Path]:
    """Create repo and live dirs with test units."""
    repo = tmpdir / "systemd" / "user"
    repo.mkdir(parents=True)
    live = tmpdir / "live"
    live.mkdir(parents=True)
    return repo, live


def test_discover_finds_services_and_timers():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo, _ = _setup(Path(tmpdir))
        (repo / "foo.service").write_text("[Unit]\nDescription=Foo\n")
        (repo / "bar.timer").write_text("[Unit]\nDescription=Bar\n")
        (repo / "readme.md").write_text("not a unit")

        with patch("scripts.sync_systemd_units.REPO_UNITS", repo):
            units = discover_repo_units()
        names = [u.name for u in units]
        assert "foo.service" in names
        assert "bar.timer" in names
        assert "readme.md" not in names


def test_compute_plan_detects_missing_unit():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo, live = _setup(Path(tmpdir))
        repo_file = repo / "test.service"
        repo_file.write_text("[Unit]\nDescription=Test\n")

        with patch("scripts.sync_systemd_units.LIVE_DIR", live):
            plan = compute_plan([repo_file])
        assert len(plan) == 1
        assert plan[0]["action"] == "install"
        assert plan[0]["name"] == "test.service"


def test_compute_plan_detects_drift():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo, live = _setup(Path(tmpdir))
        repo_file = repo / "test.timer"
        repo_file.write_text("[Timer]\nOnUnitActiveSec=60s\n")
        live_file = live / "test.timer"
        live_file.write_text("[Timer]\nOnUnitActiveSec=120s\n")

        with patch("scripts.sync_systemd_units.LIVE_DIR", live):
            plan = compute_plan([repo_file])
        assert len(plan) == 1
        assert plan[0]["action"] == "update"


def test_compute_plan_empty_when_match():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo, live = _setup(Path(tmpdir))
        content = "[Unit]\nDescription=Same\n"
        (repo / "same.service").write_text(content)
        (live / "same.service").write_text(content)

        with patch("scripts.sync_systemd_units.LIVE_DIR", live):
            plan = compute_plan([repo / "same.service"])
        assert plan == []


def test_install_units_copies_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo, live = _setup(Path(tmpdir))
        content = "[Unit]\nDescription=New\n"
        repo_file = repo / "new.service"
        repo_file.write_text(content)

        plan = [{"name": "new.service", "action": "install",
                 "repo": repo_file, "live": live / "new.service"}]

        with patch("scripts.sync_systemd_units.LIVE_DIR", live):
            count = install_units(plan)
        assert count == 1
        assert (live / "new.service").read_text() == content


def test_install_units_dry_run_no_copy():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo, live = _setup(Path(tmpdir))
        repo_file = repo / "dry.service"
        repo_file.write_text("[Unit]\n")

        plan = [{"name": "dry.service", "action": "install",
                 "repo": repo_file, "live": live / "dry.service"}]

        with patch("scripts.sync_systemd_units.LIVE_DIR", live):
            count = install_units(plan, dry_run=True)
        assert count == 1
        assert not (live / "dry.service").exists()
