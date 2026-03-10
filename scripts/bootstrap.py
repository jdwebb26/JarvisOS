#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ROOT_MARKERS = [
    "AGENTS.md",
    "scripts/bootstrap.py",
    "docs/spec/01_Jarvis_OS_v5_1_Rebuild_Spec.md",
]

REQUIRED_DIRS = [
    "docs",
    "config",
    "scripts",
    "runtime",
    "runtime/gateway",
    "runtime/core",
    "runtime/auditor",
    "runtime/reporter",
    "runtime/flowstate",
    "runtime/dashboard",
    "runtime/controls",
    "runtime/integrations",
    "runtime/researchlab",
    "runtime/evals",
    "runtime/ralph",
    "runtime/memory",
    "services",
    "services/discord",
    "services/models",
    "services/tools",
    "services/memory",
    "services/approvals",
    "state",
    "state/tasks",
    "state/artifacts",
    "state/approvals",
    "state/logs",
    "state/heartbeat",
    "state/events",
    "state/memory",
    "state/flowstate_sources",
    "state/reviews",
    "state/controls",
    "state/control_actions",
    "state/hermes_requests",
    "state/hermes_results",
    "state/research_campaigns",
    "state/experiment_runs",
    "state/metric_results",
    "state/research_recommendations",
    "state/run_traces",
    "state/eval_cases",
    "state/eval_results",
    "state/consolidation_runs",
    "state/digest_artifact_links",
    "state/memory_candidates",
    "state/memory_retrievals",
    "state/operator_action_executions",
    "workspace",
    "workspace/inbox",
    "workspace/work",
    "workspace/out",
    "systemd",
    "tests",
]

AUTO_CREATE_DIRS = [
    "state",
    "state/tasks",
    "state/artifacts",
    "state/approvals",
    "state/logs",
    "state/heartbeat",
    "state/events",
    "state/memory",
    "state/flowstate_sources",
    "state/reviews",
    "state/controls",
    "state/control_actions",
    "state/hermes_requests",
    "state/hermes_results",
    "state/research_campaigns",
    "state/experiment_runs",
    "state/metric_results",
    "state/research_recommendations",
    "state/run_traces",
    "state/eval_cases",
    "state/eval_results",
    "state/consolidation_runs",
    "state/digest_artifact_links",
    "state/memory_candidates",
    "state/memory_retrievals",
    "state/operator_action_executions",
    "workspace",
    "workspace/inbox",
    "workspace/work",
    "workspace/out",
]

EXAMPLE_CONFIG_MAP = [
    ("config/app.example.yaml", "config/app.yaml"),
    ("config/channels.example.yaml", "config/channels.yaml"),
    ("config/models.example.yaml", "config/models.yaml"),
    ("config/policies.example.yaml", "config/policies.yaml"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def looks_like_repo_root(path: Path) -> bool:
    return all((path / marker).exists() for marker in ROOT_MARKERS)


def resolve_repo_root(path: Path) -> Path:
    candidate = path.expanduser().resolve()
    search_roots = [candidate, *candidate.parents]

    for root in search_roots:
        if looks_like_repo_root(root):
            return root

    for root in search_roots:
        nested = root / "jarvis-v5"
        if looks_like_repo_root(nested):
            return nested

    return candidate


def ensure_dir(path: Path) -> bool:
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True)
    return existed


def ensure_dirs(root: Path, rel_paths: list[str]) -> tuple[list[str], list[str]]:
    created_dirs: list[str] = []
    existing_dirs: list[str] = []

    for rel in rel_paths:
        p = root / rel
        existed = ensure_dir(p)
        if existed:
            existing_dirs.append(rel)
        else:
            created_dirs.append(rel)

    return created_dirs, existing_dirs


def maybe_copy(src: Path, dst: Path, force: bool) -> str:
    if not src.exists():
        return "missing_source"

    if dst.exists() and dst.stat().st_size > 0 and not force:
        return "kept_existing"

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return "copied"


def ensure_config_skeletons(root: Path, *, force: bool = False) -> dict[str, str]:
    copied_configs: dict[str, str] = {}
    for src_rel, dst_rel in EXAMPLE_CONFIG_MAP:
        copied_configs[dst_rel] = maybe_copy(root / src_rel, root / dst_rel, force=force)
    return copied_configs


def ensure_foundation(root: Path, *, force: bool = False) -> dict[str, object]:
    resolved_root = resolve_repo_root(root)
    created_dirs, existing_dirs = ensure_dirs(resolved_root, AUTO_CREATE_DIRS)
    copied_configs = ensure_config_skeletons(resolved_root, force=force)
    return {
        "root": str(resolved_root),
        "created_dirs": created_dirs,
        "existing_dirs_count": len(existing_dirs),
        "copied_configs": copied_configs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap Jarvis v5 scaffold.")
    parser.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        help="Project root path",
    )
    parser.add_argument(
        "--copy-examples",
        action="store_true",
        help="Retained for compatibility; missing live config skeletons are copied by default.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite when used with --copy-examples",
    )
    args = parser.parse_args()

    requested_root = Path(args.root).expanduser().resolve()
    root = resolve_repo_root(requested_root)

    created_dirs, existing_dirs = ensure_dirs(root, REQUIRED_DIRS)
    copied_configs = ensure_config_skeletons(root, force=args.force)

    report = {
        "ok": True,
        "timestamp_utc": now_iso(),
        "root": str(root),
        "requested_root": str(requested_root),
        "created_dirs": created_dirs,
        "existing_dirs_count": len(existing_dirs),
        "copy_examples_enabled": True,
        "copy_examples_requested": args.copy_examples,
        "copied_configs": copied_configs,
    }

    report_path = root / "state" / "logs" / "bootstrap_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
