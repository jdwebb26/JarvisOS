from pathlib import Path

from scripts.bootstrap import ensure_foundation, resolve_repo_root
from scripts import preflight_lib


ROOT = Path(__file__).resolve().parents[1]


def test_resolve_repo_root_from_workspace_parent():
    assert resolve_repo_root(ROOT.parent) == ROOT


def test_resolve_repo_root_from_repo_subdir():
    assert resolve_repo_root(ROOT / "scripts") == ROOT


def test_ensure_foundation_creates_managed_dirs_and_live_configs(tmp_path):
    repo = tmp_path / "jarvis-v5"
    repo.mkdir(parents=True)
    (repo / "AGENTS.md").write_text("test\n", encoding="utf-8")
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "bootstrap.py").write_text("# marker\n", encoding="utf-8")
    (repo / "docs" / "spec").mkdir(parents=True)
    (repo / "docs" / "spec" / "01_Jarvis_OS_v5_1_Rebuild_Spec.md").write_text("# spec\n", encoding="utf-8")
    (repo / "config").mkdir(parents=True)

    for name in ("app", "channels", "models", "policies"):
        (repo / "config" / f"{name}.example.yaml").write_text(f"{name}: example\n", encoding="utf-8")

    result = ensure_foundation(repo)

    assert (repo / "state" / "logs").is_dir()
    assert (repo / "state" / "control_events").is_dir()
    assert (repo / "state" / "control_blocked_actions").is_dir()
    assert (repo / "state" / "memory_validations").is_dir()
    assert (repo / "state" / "memory_promotion_decisions").is_dir()
    assert (repo / "state" / "memory_rejection_decisions").is_dir()
    assert (repo / "state" / "memory_revocation_decisions").is_dir()
    assert (repo / "workspace" / "out").is_dir()
    assert result["copied_configs"]["config/app.yaml"] == "copied"
    assert result["copied_configs"]["config/models.yaml"] == "copied"


def test_run_smoke_rebuilds_dashboard_outputs(monkeypatch, tmp_path: Path):
    root = tmp_path
    (root / "state" / "logs").mkdir(parents=True)

    monkeypatch.setattr(
        preflight_lib,
        "run_validate",
        lambda _root, strict=False: {"ok": True, "summary": {"pass": 1, "warn": 0, "fail": 0}, "findings": []},
    )
    monkeypatch.setattr(
        preflight_lib,
        "_run_python_json",
        lambda _root, _cmd: {"ok": True, "payload": {"ok": True, "passed": 5, "total": 5}},
    )

    import runtime.dashboard.rebuild_all as rebuild_module

    def fake_rebuild_all(*, root: Path) -> dict:
        (root / "state" / "logs" / "operator_snapshot.json").write_text("{}", encoding="utf-8")
        (root / "state" / "logs" / "state_export.json").write_text("{}", encoding="utf-8")
        return {"ok": True, "written_files": ["operator_snapshot.json", "state_export.json"], "errors": []}

    monkeypatch.setattr(rebuild_module, "rebuild_all", fake_rebuild_all)

    report = preflight_lib.run_smoke(root)

    assert report["ok"] is True
    assert [step["step"] for step in report["steps"]] == ["validate", "runtime_regression_pack", "dashboard_rebuild"]
    assert report["steps"][-1]["ok"] is True
    assert (root / "state" / "logs" / "operator_snapshot.json").exists()
    assert (root / "state" / "logs" / "state_export.json").exists()
