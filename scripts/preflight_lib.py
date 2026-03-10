#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from scripts.bootstrap import ensure_foundation, resolve_repo_root

ROOT = resolve_repo_root(Path(__file__).resolve().parents[1])
WORKSPACE = ROOT / "workspace"

REQUIRED_DIRS = [
    "config",
    "docs",
    "runtime",
    "runtime/core",
    "runtime/dashboard",
    "runtime/executor",
    "runtime/flowstate",
    "runtime/gateway",
    "runtime/controls",
    "runtime/integrations",
    "runtime/researchlab",
    "runtime/evals",
    "runtime/ralph",
    "runtime/memory",
    "scripts",
    "state",
    "state/approvals",
    "state/artifacts",
    "state/events",
    "state/flowstate_sources",
    "state/heartbeat",
    "state/logs",
    "state/memory",
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
    "state/tasks",
    "workspace",
    "workspace/inbox",
    "workspace/out",
    "workspace/work",
]

REQUIRED_FILES = [
    "README.md",
    "docs/deployment.md",
    "docs/operations.md",
    "docs/runtime-regression-runbook.md",
    "config/app.example.yaml",
    "config/channels.example.yaml",
    "config/models.example.yaml",
    "config/policies.example.yaml",
    "scripts/bootstrap.py",
    "scripts/doctor.py",
    "scripts/generate_config.py",
    "scripts/operator_checkpoint_action_pack.py",
    "scripts/operator_action_executor.py",
    "scripts/overnight_operator_run.py",
    "scripts/operator_handoff_pack.py",
    "scripts/smoke_test.py",
    "scripts/validate.py",
    "runtime/core/intake.py",
    "runtime/core/decision_router.py",
    "runtime/core/approval_store.py",
    "runtime/controls/control_store.py",
    "runtime/integrations/hermes_adapter.py",
    "runtime/integrations/autoresearch_adapter.py",
    "runtime/researchlab/runner.py",
    "runtime/evals/trace_store.py",
    "runtime/ralph/consolidator.py",
    "runtime/memory/governance.py",
    "runtime/core/review_store.py",
    "runtime/core/publish_complete.py",
    "runtime/core/run_runtime_regression_pack.py",
    "runtime/gateway/complete_from_artifact.py",
    "runtime/gateway/hermes_execute.py",
    "runtime/gateway/autoresearch_campaign.py",
    "runtime/gateway/replay_eval.py",
    "runtime/gateway/ralph_consolidate.py",
    "runtime/gateway/memory_retrieve.py",
    "runtime/gateway/memory_decision.py",
    "runtime/gateway/discord_intake.py",
    "runtime/dashboard/operator_snapshot.py",
]

KEY_MODULES = [
    "runtime.core.intake",
    "runtime.core.decision_router",
    "runtime.core.review_store",
    "runtime.core.approval_store",
    "runtime.controls.control_store",
    "runtime.integrations.hermes_adapter",
    "runtime.integrations.autoresearch_adapter",
    "runtime.researchlab.runner",
    "runtime.evals.trace_store",
    "runtime.ralph.consolidator",
    "runtime.memory.governance",
    "runtime.core.publish_complete",
    "runtime.core.run_runtime_regression_pack",
    "runtime.gateway.complete_from_artifact",
    "runtime.gateway.hermes_execute",
    "runtime.gateway.autoresearch_campaign",
    "runtime.gateway.replay_eval",
    "runtime.gateway.ralph_consolidate",
    "runtime.gateway.memory_retrieve",
    "runtime.gateway.memory_decision",
    "runtime.dashboard.operator_snapshot",
]

CONFIG_FILES = [
    "config/app.yaml",
    "config/channels.yaml",
    "config/models.yaml",
    "config/policies.yaml",
]

EXAMPLE_CONFIG_FILES = [
    "config/app.example.yaml",
    "config/channels.example.yaml",
    "config/models.example.yaml",
    "config/policies.example.yaml",
]

QWEN_HINTS = ["family: qwen3.5", "qwen_only: true", "Qwen3.5-"]
EXPECTED_CHANNEL_KEYS = ["jarvis", "tasks", "outputs", "review", "audit", "code_review", "flowstate"]


@dataclass
class Finding:
    status: str
    category: str
    message: str
    remediation: str = ""
    details: str = ""

    def to_dict(self) -> dict[str, str]:
        payload = {
            "status": self.status,
            "category": self.category,
            "message": self.message,
        }
        if self.remediation:
            payload["remediation"] = self.remediation
        if self.details:
            payload["details"] = self.details
        return payload


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _add(finding_list: list[Finding], status: str, category: str, message: str, remediation: str = "", details: str = "") -> None:
    finding_list.append(Finding(status=status, category=category, message=message, remediation=remediation, details=details))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _write_probe(directory: Path) -> str | None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fd, probe_path = tempfile.mkstemp(prefix=".preflight_", dir=str(directory))
        os.close(fd)
        Path(probe_path).unlink(missing_ok=True)
        return None
    except Exception as exc:
        return str(exc)


def _config_text(root: Path, rel: str) -> str:
    path = root / rel
    if not path.exists():
        return ""
    return _read_text(path)


def run_validate(root: Path, *, strict: bool = False) -> dict:
    requested_root = root.expanduser().resolve()
    root = resolve_repo_root(requested_root)
    findings: list[Finding] = []
    foundation = ensure_foundation(root)

    if root.exists():
        _add(findings, "pass", "repo", "Repo root exists.", details=str(root))
    else:
        _add(findings, "fail", "repo", "Repo root does not exist.", "Run from the repo checkout or pass --root to the correct path.", str(root))

    if (root / ".git").exists():
        _add(findings, "pass", "repo", "Git metadata directory is present.")
    else:
        _add(findings, "warn", "repo", "Git metadata directory is missing.", "If this is a source export rather than a git checkout, ignore this warning.")

    if requested_root != root:
        _add(findings, "pass", "repo", "Resolved the requested path to the repo root.", details=f"requested={requested_root}")

    if foundation["created_dirs"]:
        _add(
            findings,
            "pass",
            "foundation",
            "Auto-created managed state/workspace directories.",
            details=", ".join(foundation["created_dirs"]),
        )

    copied_configs = {rel: result for rel, result in foundation["copied_configs"].items() if result == "copied"}
    if copied_configs:
        _add(
            findings,
            "pass",
            "foundation",
            "Created missing live config skeletons from example files.",
            details=", ".join(sorted(copied_configs)),
        )

    for rel in REQUIRED_DIRS:
        path = root / rel
        if not path.exists():
            _add(findings, "fail", "filesystem", f"Missing required directory `{rel}`.", f"Create `{rel}` or rerun `python3 scripts/bootstrap.py --copy-examples`.")
        elif not path.is_dir():
            _add(findings, "fail", "filesystem", f"Required path `{rel}` is not a directory.", f"Replace `{rel}` with a directory.")
        else:
            _add(findings, "pass", "filesystem", f"Directory `{rel}` is present.")

    for rel in REQUIRED_FILES:
        path = root / rel
        if not path.exists():
            _add(findings, "fail", "files", f"Missing required file `{rel}`.", f"Restore `{rel}` from the repo or regenerate the deployment packet.")
        elif not path.is_file():
            _add(findings, "fail", "files", f"Required path `{rel}` is not a file.", f"Replace `{rel}` with the expected file.")
        elif path.stat().st_size == 0:
            _add(findings, "fail", "files", f"Required file `{rel}` is empty.", f"Regenerate or restore `{rel}`.")
        else:
            _add(findings, "pass", "files", f"File `{rel}` is present.")

    qwen_example_files = {
        "config/app.example.yaml",
        "config/models.example.yaml",
        "config/policies.example.yaml",
    }
    for rel in EXAMPLE_CONFIG_FILES:
        text = _config_text(root, rel)
        if not text:
            continue
        if rel in qwen_example_files and not any(hint in text for hint in QWEN_HINTS):
            _add(findings, "fail", "config", f"Example config `{rel}` is missing Qwen-family hints.", "Keep example configs explicitly Qwen-only.")
        else:
            _add(findings, "pass", "config", f"Example config `{rel}` is Qwen-oriented.")

    for rel in CONFIG_FILES:
        path = root / rel
        if not path.exists():
            _add(findings, "warn", "config", f"Live config `{rel}` is missing.", "Run `python3 scripts/generate_config.py` or copy the example config into place.")
            continue
        text = _read_text(path)
        if path.stat().st_size == 0:
            _add(findings, "fail", "config", f"Live config `{rel}` is empty.", f"Regenerate `{rel}` with `python3 scripts/generate_config.py --force`.")
            continue
        if "REPLACE_ME" in text:
            _add(findings, "warn", "config", f"Live config `{rel}` still contains placeholder values.", "Fill in real Discord or environment-specific values before deployment.")
        else:
            _add(findings, "pass", "config", f"Live config `{rel}` has no obvious placeholders.")
        if rel.endswith("models.yaml") and "qwen3.5" not in text.lower():
            _add(findings, "fail", "config", "config/models.yaml is not clearly pinned to Qwen 3.5.", "Keep model config on the Qwen 3.5 family only.")
        elif rel.endswith("models.yaml"):
            _add(findings, "pass", "config", "config/models.yaml is pinned to Qwen 3.5.")
        if rel.endswith("channels.yaml"):
            missing = [key for key in EXPECTED_CHANNEL_KEYS if key not in text]
            if missing:
                _add(findings, "warn", "config", f"config/channels.yaml is missing channel keys: {', '.join(missing)}.", "Add the missing channel mappings before live Discord deployment.")
            else:
                _add(findings, "pass", "config", "config/channels.yaml includes the expected operator channel names.")

    for rel in ["state/logs", "workspace/out"]:
        error = _write_probe(root / rel)
        if error is None:
            _add(findings, "pass", "filesystem", f"Directory `{rel}` is writable.")
        else:
            _add(findings, "fail", "filesystem", f"Directory `{rel}` is not writable.", f"Fix permissions on `{rel}` before deployment.", error)

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    for module_name in KEY_MODULES:
        try:
            importlib.import_module(module_name)
            _add(findings, "pass", "imports", f"Module `{module_name}` imports cleanly.")
        except Exception as exc:
            _add(findings, "fail", "imports", f"Module `{module_name}` failed to import.", f"Fix the import error in `{module_name}` before deployment.", str(exc))

    regression_entry = root / "runtime" / "core" / "run_runtime_regression_pack.py"
    if regression_entry.exists():
        _add(findings, "pass", "runtime", "Runtime regression pack entrypoint is present.")
    else:
        _add(findings, "fail", "runtime", "Runtime regression pack entrypoint is missing.", "Restore `runtime/core/run_runtime_regression_pack.py`.")

    operator_snapshot = root / "state" / "logs" / "operator_snapshot.json"
    if operator_snapshot.exists():
        _add(findings, "pass", "operator", "Operator snapshot log exists.")
    else:
        _add(findings, "warn", "operator", "Operator snapshot log does not exist yet.", "Run a dashboard rebuild or smoke to generate operator-facing logs.")

    pass_count = sum(1 for item in findings if item.status == "pass")
    warn_count = sum(1 for item in findings if item.status == "warn")
    fail_count = sum(1 for item in findings if item.status == "fail")
    ok = fail_count == 0 and (warn_count == 0 or not strict)

    next_actions = [item.remediation for item in findings if item.status == "fail" and item.remediation]
    if not next_actions and warn_count:
        next_actions = [item.remediation for item in findings if item.status == "warn" and item.remediation][:3]

    report = {
        "ok": ok,
        "strict": strict,
        "timestamp_utc": now_iso(),
        "root": str(root),
        "requested_root": str(requested_root),
        "summary": {
            "pass": pass_count,
            "warn": warn_count,
            "fail": fail_count,
        },
        "foundation": foundation,
        "findings": [item.to_dict() for item in findings],
        "next_actions": next_actions,
    }
    return report


def write_report(root: Path, name: str, payload: dict) -> Path:
    path = root / "state" / "logs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def render_validate_report(report: dict) -> str:
    lines = [
        f"validate: {'PASS' if report['ok'] else 'FAIL'}",
        f"root: {report['root']}",
        (
            "summary: "
            f"pass={report['summary']['pass']} "
            f"warn={report['summary']['warn']} "
            f"fail={report['summary']['fail']}"
        ),
    ]
    for item in report["findings"]:
        if item["status"] == "pass":
            continue
        lines.append(f"- {item['status'].upper()} [{item['category']}] {item['message']}")
        if item.get("remediation"):
            lines.append(f"  next: {item['remediation']}")
    if report["ok"]:
        lines.append("next: run `python3 scripts/smoke_test.py` for a runtime-local deployment smoke.")
    return "\n".join(lines)


def build_doctor_report(root: Path) -> dict:
    validation = run_validate(root, strict=False)
    findings: list[Finding] = []

    for item in validation["findings"]:
        findings.append(Finding(**item))

    tasks_count = len(list((root / "state" / "tasks").glob("*.json")))
    outputs_count = len(list((root / "workspace" / "out").glob("*.json")))
    approvals_count = len(list((root / "state" / "approvals").glob("*.json")))
    controls_count = len(list((root / "state" / "controls").glob("*.json")))
    research_campaigns_count = len(list((root / "state" / "research_campaigns").glob("*.json")))
    run_traces_count = len(list((root / "state" / "run_traces").glob("*.json")))
    eval_results_count = len(list((root / "state" / "eval_results").glob("*.json")))
    consolidation_runs_count = len(list((root / "state" / "consolidation_runs").glob("*.json")))
    memory_retrievals_count = len(list((root / "state" / "memory_retrievals").glob("*.json")))
    reviews_count = len(list((root / "state" / "reviews").glob("*.json")))

    _add(findings, "pass", "runtime_state", "State directories are readable.", details=f"tasks={tasks_count} approvals={approvals_count} reviews={reviews_count} outputs={outputs_count} controls={controls_count} research_campaigns={research_campaigns_count} run_traces={run_traces_count} eval_results={eval_results_count} consolidation_runs={consolidation_runs_count} memory_retrievals={memory_retrievals_count}")

    state_export = root / "state" / "logs" / "state_export.json"
    if state_export.exists():
        _add(findings, "pass", "operator", "state_export.json is present for operator/dashboard visibility.")
    else:
        _add(findings, "warn", "operator", "state_export.json is missing.", "Run a dashboard rebuild or smoke before operator handoff.")

    regression = _run_python_json(root, [sys.executable, str(root / "runtime" / "core" / "run_runtime_regression_pack.py")])
    if regression["ok"]:
        pack = regression["payload"]
        _add(findings, "pass", "runtime", f"Runtime regression pack is green ({pack.get('passed')}/{pack.get('total')} passed).")
    else:
        _add(findings, "fail", "runtime", "Runtime regression pack is not green.", "Fix the failing smoke(s) before deployment.", regression["message"])

    fail_count = sum(1 for item in findings if item.status == "fail")
    warn_count = sum(1 for item in findings if item.status == "warn")
    if fail_count:
        verdict = "blocked"
    elif warn_count:
        verdict = "healthy_with_warnings"
    else:
        verdict = "healthy"

    grouped: dict[str, list[dict]] = {}
    for item in findings:
        grouped.setdefault(item.category, []).append(item.to_dict())

    next_actions = [item.remediation for item in findings if item.status == "fail" and item.remediation]
    if not next_actions:
        next_actions = [item.remediation for item in findings if item.status == "warn" and item.remediation][:5]
    if regression["ok"]:
        next_actions.append("After a green baseline, use operator snapshot / dashboard outputs to work the next ready_to_ship or publish-complete handoff.")

    return {
        "ok": fail_count == 0,
        "verdict": verdict,
        "timestamp_utc": now_iso(),
        "root": str(root),
        "summary": {
            "pass": sum(1 for item in findings if item.status == "pass"),
            "warn": warn_count,
            "fail": fail_count,
            "tasks": tasks_count,
            "approvals": approvals_count,
            "controls": controls_count,
            "research_campaigns": research_campaigns_count,
            "run_traces": run_traces_count,
            "eval_results": eval_results_count,
            "consolidation_runs": consolidation_runs_count,
            "memory_retrievals": memory_retrievals_count,
            "reviews": reviews_count,
            "outputs": outputs_count,
        },
        "groups": grouped,
        "next_actions": next_actions,
        "regression_pack": regression["payload"] if regression["ok"] else None,
    }


def render_doctor_report(report: dict) -> str:
    lines = [
        f"doctor: {report['verdict']}",
        f"root: {report['root']}",
        (
            "summary: "
            f"pass={report['summary']['pass']} "
            f"warn={report['summary']['warn']} "
            f"fail={report['summary']['fail']} "
            f"tasks={report['summary']['tasks']} "
            f"outputs={report['summary']['outputs']}"
        ),
    ]
    for category, items in report["groups"].items():
        noteworthy = [item for item in items if item["status"] != "pass"]
        if not noteworthy:
            continue
        lines.append(f"{category}:")
        for item in noteworthy:
            lines.append(f"- {item['status'].upper()} {item['message']}")
            if item.get("remediation"):
                lines.append(f"  next: {item['remediation']}")
    if report["next_actions"]:
        lines.append("next actions:")
        for action in report["next_actions"][:5]:
            lines.append(f"- {action}")
    return "\n".join(lines)


def _run_python_json(root: Path, cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return {"ok": False, "message": stderr or stdout or f"exit {proc.returncode}"}
    try:
        return {"ok": True, "payload": json.loads(stdout) if stdout else {}}
    except Exception:
        return {"ok": False, "message": f"non-JSON output: {stdout[:800]}"}


def run_smoke(root: Path) -> dict:
    root = root.resolve()
    steps: list[dict] = []

    validation = run_validate(root, strict=False)
    steps.append(
        {
            "step": "validate",
            "ok": validation["ok"],
            "summary": validation["summary"],
            "message": "validate passed" if validation["ok"] else "validate found blocking failures",
        }
    )
    if not validation["ok"]:
        return {
            "ok": False,
            "timestamp_utc": now_iso(),
            "root": str(root),
            "steps": steps,
            "message": "Smoke stopped at validate.",
        }

    pack = _run_python_json(root, [sys.executable, str(root / "runtime" / "core" / "run_runtime_regression_pack.py")])
    steps.append(
        {
            "step": "runtime_regression_pack",
            "ok": pack["ok"] and bool(pack["payload"].get("ok")),
            "summary": pack.get("payload", {}),
            "message": (
                f"regression pack green ({pack['payload'].get('passed')}/{pack['payload'].get('total')} passed)"
                if pack["ok"] and pack["payload"].get("ok")
                else pack.get("message", "runtime regression pack failed")
            ),
        }
    )
    if not (pack["ok"] and pack["payload"].get("ok")):
        return {
            "ok": False,
            "timestamp_utc": now_iso(),
            "root": str(root),
            "steps": steps,
            "message": "Smoke stopped at runtime_regression_pack.",
        }

    return {
        "ok": True,
        "timestamp_utc": now_iso(),
        "root": str(root),
        "steps": steps,
        "message": "Repo-local deployment smoke is green. Next operator move: work candidate-ready or shipped tasks through apply/publish-complete.",
    }


def render_smoke_report(report: dict) -> str:
    status = "PASS" if report["ok"] else "FAIL"
    lines = [f"smoke: {status}", f"root: {report['root']}"]
    for step in report["steps"]:
        lines.append(f"- {step['step']}: {'ok' if step['ok'] else 'fail'} :: {step['message']}")
    lines.append(f"next: {report['message']}")
    return "\n".join(lines)
