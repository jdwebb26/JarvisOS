#!/usr/bin/env python3
"""Tests for the backend dependency health preflight check."""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.preflight_lib import (
    Finding,
    _BACKEND_REQUIRED_PACKAGES,
    check_backend_dependency_health,
)


def test_reports_python_interpreter(tmp_path: Path) -> None:
    findings = check_backend_dependency_health(tmp_path)
    interpreter_finding = [f for f in findings if "Validating backend dependencies" in f.message]
    assert len(interpreter_finding) == 1
    assert interpreter_finding[0].status == "pass"
    assert sys.executable in interpreter_finding[0].details


def test_pass_when_package_importable(tmp_path: Path) -> None:
    findings = check_backend_dependency_health(tmp_path)
    # requests is in _BACKEND_REQUIRED_PACKAGES for nvidia_executor.
    # Whether it passes or warns depends on the environment, but the check must run.
    nvidia_findings = [f for f in findings if "nvidia_executor" in f.message]
    assert len(nvidia_findings) >= 1
    # Each finding should be either pass or warn, never fail.
    for f in nvidia_findings:
        assert f.status in ("pass", "warn")


def test_warn_when_package_missing(tmp_path: Path) -> None:
    """Simulate a missing package by patching importlib.import_module to fail for 'requests'."""
    original_import = importlib.import_module

    def _mock_import(name: str, *args, **kwargs):
        if name == "requests":
            raise ImportError(f"No module named '{name}'")
        return original_import(name, *args, **kwargs)

    with patch("scripts.preflight_lib.importlib.import_module", side_effect=_mock_import):
        findings = check_backend_dependency_health(tmp_path)

    warn_findings = [f for f in findings if f.status == "warn" and "requests" in f.message]
    assert len(warn_findings) == 1
    assert "nvidia_executor" in warn_findings[0].message
    assert "NOT importable" in warn_findings[0].message
    assert warn_findings[0].remediation
    assert "pip install" in warn_findings[0].remediation


def test_pass_when_package_present(tmp_path: Path) -> None:
    """Simulate a present package by patching importlib.import_module to succeed."""
    original_import = importlib.import_module

    def _mock_import(name: str, *args, **kwargs):
        if name == "requests":
            return types.ModuleType("requests")
        return original_import(name, *args, **kwargs)

    with patch("scripts.preflight_lib.importlib.import_module", side_effect=_mock_import):
        findings = check_backend_dependency_health(tmp_path)

    pass_findings = [f for f in findings if f.status == "pass" and "nvidia_executor" in f.message]
    assert len(pass_findings) == 1
    assert "importable" in pass_findings[0].message


def test_backend_required_packages_registry() -> None:
    """Verify the registry has the expected structure."""
    assert "nvidia_executor" in _BACKEND_REQUIRED_PACKAGES
    assert "requests" in _BACKEND_REQUIRED_PACKAGES["nvidia_executor"]


def test_no_fail_level_findings(tmp_path: Path) -> None:
    """Dependency health checks must always be advisory (pass/warn), never fail."""
    findings = check_backend_dependency_health(tmp_path)
    fail_findings = [f for f in findings if f.status == "fail"]
    assert fail_findings == []
