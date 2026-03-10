from pathlib import Path

from scripts.bootstrap import ensure_foundation, resolve_repo_root


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
    assert (repo / "workspace" / "out").is_dir()
    assert result["copied_configs"]["config/app.yaml"] == "copied"
    assert result["copied_configs"]["config/models.yaml"] == "copied"
