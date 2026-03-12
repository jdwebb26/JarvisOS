#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import (
    AuthorityClass,
    BackendAssignmentRecord,
    BackendRuntime,
    ModelFamily,
    ModelTier,
    RoutingDecision,
    RoutingDecisionRecord,
    RoutingReason,
    TaskClass,
    TaskRecord,
    now_iso,
)


DEFAULT_MODEL_POLICY = {
    "schema_version": "v5.2_policy_scaffold",
    "live_runtime_posture": {
        "mode": "qwen_first",
        "rollout_stage": "scaffolding_only",
        "notes": [
            "A2 policy scaffold only. Live routing remains Qwen-first until later routing-core tickets land."
        ],
    },
    "authority_min_tier": {
        AuthorityClass.OBSERVE_ONLY.value: ModelTier.ROUTING.value,
        AuthorityClass.SUGGEST_ONLY.value: ModelTier.GENERAL.value,
        AuthorityClass.REVIEW_REQUIRED.value: ModelTier.HEAVY_REASONING.value,
        AuthorityClass.APPROVAL_REQUIRED.value: ModelTier.HEAVY_REASONING.value,
        AuthorityClass.EXECUTE_BOUNDED.value: ModelTier.GENERAL.value,
    },
    "task_class_policies": {
        TaskClass.GENERAL.value: {
            "allowed_models": [
                {
                    "family": ModelFamily.QWEN.value,
                    "tier": ModelTier.GENERAL.value,
                    "backend_runtime": BackendRuntime.QWEN_EXECUTOR.value,
                    "model_name": "Qwen3.5-35B-A3B",
                    "shadow_eval_eligible": False,
                }
            ],
            "fallback_chain": [
                {
                    "family": ModelFamily.QWEN.value,
                    "tier": ModelTier.ROUTING.value,
                    "backend_runtime": BackendRuntime.QWEN_PLANNER.value,
                    "model_name": "Qwen3.5-9B",
                }
            ],
        }
    },
    "shadow_eval_policy": {
        "enabled": True,
        "requires_explicit_opt_in": True,
        "allowed_families": [ModelFamily.QWEN.value],
    },
    "forbidden_downgrades": {
        AuthorityClass.REVIEW_REQUIRED.value: [ModelTier.ROUTING.value, ModelTier.GENERAL.value],
        AuthorityClass.APPROVAL_REQUIRED.value: [ModelTier.ROUTING.value, ModelTier.GENERAL.value],
        TaskClass.DEPLOY.value: [ModelTier.ROUTING.value, ModelTier.GENERAL.value],
        TaskClass.REVIEW.value: [ModelTier.ROUTING.value, ModelTier.GENERAL.value],
    },
}
_TASK_CLASS_FALLBACK = {
    "deploy": TaskClass.DEPLOY.value,
    "quant": TaskClass.DEPLOY.value,
}
_TIER_FLOOR_ORDER = {
    ModelTier.ROUTING.value: 0,
    ModelTier.GENERAL.value: 1,
    ModelTier.FLOWSTATE.value: 1,
    ModelTier.CODER.value: 2,
    ModelTier.MULTIMODAL.value: 2,
    ModelTier.HEAVY_REASONING.value: 3,
}


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def backend_assignments_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("backend_assignments", root=root)


def model_policy_path(root: Optional[Path] = None) -> Path:
    return Path(root or ROOT).resolve() / "config" / "model_policy.json"


def load_model_policy(root: Optional[Path] = None) -> dict[str, Any]:
    path = model_policy_path(root=root)
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_MODEL_POLICY))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return json.loads(json.dumps(DEFAULT_MODEL_POLICY))
    merged = json.loads(json.dumps(DEFAULT_MODEL_POLICY))
    merged.update({key: value for key, value in payload.items() if key not in {"authority_min_tier", "task_class_policies", "shadow_eval_policy", "forbidden_downgrades"}})
    merged["authority_min_tier"] = {**merged["authority_min_tier"], **dict(payload.get("authority_min_tier") or {})}
    merged["task_class_policies"] = {**merged["task_class_policies"], **dict(payload.get("task_class_policies") or {})}
    merged["shadow_eval_policy"] = {**merged["shadow_eval_policy"], **dict(payload.get("shadow_eval_policy") or {})}
    merged["forbidden_downgrades"] = {**merged["forbidden_downgrades"], **dict(payload.get("forbidden_downgrades") or {})}
    return merged


def _normalize_task_class(task_class: Any = "", *, task_type: Any = "") -> str:
    raw = str(task_class or task_type or TaskClass.GENERAL.value).strip().lower()
    raw = _TASK_CLASS_FALLBACK.get(raw, raw)
    return TaskClass.coerce(raw, default=TaskClass.GENERAL).value


def _normalize_authority_class(authority_class: Any = "", *, review_required: bool = False, approval_required: bool = False) -> str:
    if approval_required:
        return AuthorityClass.APPROVAL_REQUIRED.value
    if review_required:
        return AuthorityClass.REVIEW_REQUIRED.value
    raw = str(authority_class or AuthorityClass.SUGGEST_ONLY.value).strip().lower()
    return AuthorityClass.coerce(raw, default=AuthorityClass.SUGGEST_ONLY).value


def _normalize_tier(value: Any) -> str:
    return ModelTier.coerce(str(value or ModelTier.GENERAL.value).strip().lower(), default=ModelTier.GENERAL).value


def _tier_meets_floor(candidate_tier: Any, minimum_tier: Any) -> bool:
    candidate = _normalize_tier(candidate_tier)
    minimum = _normalize_tier(minimum_tier)
    return _TIER_FLOOR_ORDER.get(candidate, 0) >= _TIER_FLOOR_ORDER.get(minimum, 0)


def _extract_route_candidate(route: Any) -> dict[str, Any]:
    if isinstance(route, RoutingDecision):
        payload = route.to_dict()
        return {
            "family": payload.get("selected_family", ModelFamily.UNASSIGNED.value),
            "tier": payload.get("selected_tier", ModelTier.GENERAL.value),
            "backend_runtime": payload.get("selected_backend_runtime", BackendRuntime.UNASSIGNED.value),
            "model_name": payload.get("metadata", {}).get("model_name", ""),
            "routing_reason": payload.get("routing_reason", RoutingReason.POLICY_DEFAULT.value),
        }
    if isinstance(route, RoutingDecisionRecord):
        return {
            "family": str((route.policy_constraints or {}).get("family") or ModelFamily.UNASSIGNED.value),
            "tier": str((route.policy_constraints or {}).get("tier") or ModelTier.GENERAL.value),
            "backend_runtime": str(route.selected_execution_backend or BackendRuntime.UNASSIGNED.value),
            "model_name": str(route.selected_model_name or ""),
            "routing_reason": str(route.selection_reason or RoutingReason.POLICY_DEFAULT.value),
        }
    payload = dict(route or {})
    return {
        "family": str(payload.get("family") or payload.get("selected_family") or ModelFamily.UNASSIGNED.value),
        "tier": str(payload.get("tier") or payload.get("selected_tier") or ModelTier.GENERAL.value),
        "backend_runtime": str(payload.get("backend_runtime") or payload.get("selected_backend_runtime") or payload.get("selected_execution_backend") or BackendRuntime.UNASSIGNED.value),
        "model_name": str(payload.get("model_name") or payload.get("selected_model_name") or ""),
        "routing_reason": str(payload.get("routing_reason") or payload.get("selection_reason") or RoutingReason.POLICY_DEFAULT.value),
    }


def _task_context_from_record(task: Optional[TaskRecord]) -> dict[str, Any]:
    if task is None:
        return {
            "task_class": TaskClass.GENERAL.value,
            "authority_class": AuthorityClass.SUGGEST_ONLY.value,
            "review_required": False,
            "approval_required": False,
        }
    return {
        "task_class": _normalize_task_class(task.task_type),
        "authority_class": _normalize_authority_class(
            review_required=bool(task.review_required),
            approval_required=bool(task.approval_required),
        ),
        "review_required": bool(task.review_required),
        "approval_required": bool(task.approval_required),
    }


def allowed_models_by_task_class(task_class: Any, *, root: Optional[Path] = None) -> list[dict[str, Any]]:
    policy = load_model_policy(root=root)
    task_key = _normalize_task_class(task_class)
    task_policy = dict((policy.get("task_class_policies") or {}).get(task_key) or {})
    return [dict(item) for item in task_policy.get("allowed_models", [])]


def get_allowed_models_for_task(task_class: Any, *, root: Optional[Path] = None) -> list[dict[str, Any]]:
    return allowed_models_by_task_class(task_class, root=root)


def minimum_tier_by_authority_class(authority_class: Any, *, root: Optional[Path] = None) -> str:
    policy = load_model_policy(root=root)
    authority_key = _normalize_authority_class(authority_class)
    configured = (policy.get("authority_min_tier") or {}).get(authority_key, ModelTier.GENERAL.value)
    return _normalize_tier(configured)


def get_min_tier_for_authority(authority_class: Any, *, root: Optional[Path] = None) -> str:
    return minimum_tier_by_authority_class(authority_class, root=root)


def fallback_chain_lookup(
    task_class: Any,
    *,
    authority_class: Any = "",
    root: Optional[Path] = None,
) -> list[dict[str, Any]]:
    policy = load_model_policy(root=root)
    task_key = _normalize_task_class(task_class)
    task_policy = dict((policy.get("task_class_policies") or {}).get(task_key) or {})
    minimum_tier = minimum_tier_by_authority_class(authority_class or AuthorityClass.SUGGEST_ONLY.value, root=root)
    return [
        dict(item)
        for item in task_policy.get("fallback_chain", [])
        if _tier_meets_floor(item.get("tier"), minimum_tier)
    ]


def get_fallback_chain(
    task_class: Any,
    *,
    authority_class: Any = "",
    root: Optional[Path] = None,
) -> list[dict[str, Any]]:
    return fallback_chain_lookup(task_class, authority_class=authority_class, root=root)


def shadow_eval_eligibility(
    *,
    task_class: Any,
    authority_class: Any = "",
    family: Any = "",
    backend_runtime: Any = "",
    root: Optional[Path] = None,
    explicit_opt_in: bool = False,
) -> dict[str, Any]:
    policy = load_model_policy(root=root)
    family_value = ModelFamily.coerce(str(family or ModelFamily.UNASSIGNED.value).strip().lower(), default=ModelFamily.UNASSIGNED).value
    backend_value = str(backend_runtime or BackendRuntime.UNASSIGNED.value)
    task_key = _normalize_task_class(task_class)
    authority_key = _normalize_authority_class(authority_class)
    task_allowed = allowed_models_by_task_class(task_key, root=root)
    matched = next(
        (
            row
            for row in task_allowed
            if row.get("family") == family_value and row.get("backend_runtime") == backend_value
        ),
        None,
    )
    shadow_policy = dict(policy.get("shadow_eval_policy") or {})
    allowed = bool(shadow_policy.get("enabled", False))
    if allowed and shadow_policy.get("requires_explicit_opt_in", False) and not explicit_opt_in:
        allowed = False
    if allowed and shadow_policy.get("allowed_families") and family_value not in shadow_policy.get("allowed_families", []):
        allowed = False
    if matched is not None and not bool(matched.get("shadow_eval_eligible", False)):
        allowed = False
    return {
        "allowed": allowed,
        "task_class": task_key,
        "authority_class": authority_key,
        "family": family_value,
        "backend_runtime": backend_value,
        "requires_explicit_opt_in": bool(shadow_policy.get("requires_explicit_opt_in", False)),
        "reason": "shadow_eval_eligible" if allowed else "shadow_eval_not_eligible",
    }


def route_legality_checks(
    *,
    task_class: Any,
    authority_class: Any = "",
    family: Any = "",
    tier: Any = "",
    backend_runtime: Any = "",
    model_name: str = "",
    root: Optional[Path] = None,
) -> dict[str, Any]:
    task_key = _normalize_task_class(task_class)
    authority_key = _normalize_authority_class(authority_class)
    family_value = ModelFamily.coerce(str(family or ModelFamily.UNASSIGNED.value).strip().lower(), default=ModelFamily.UNASSIGNED).value
    tier_value = _normalize_tier(tier)
    backend_value = str(backend_runtime or BackendRuntime.UNASSIGNED.value)
    allowed_specs = allowed_models_by_task_class(task_key, root=root)
    minimum_tier = minimum_tier_by_authority_class(authority_key, root=root)
    findings: list[str] = []

    if not allowed_specs:
        findings.append("no_allowed_models_for_task_class")

    allowed_match = next(
        (
            row
            for row in allowed_specs
            if row.get("family") == family_value
            and row.get("backend_runtime") == backend_value
            and (not row.get("model_name") or row.get("model_name") == model_name)
        ),
        None,
    )
    if allowed_specs and allowed_match is None:
        findings.append("model_not_allowed_for_task_class")

    if not _tier_meets_floor(tier_value, minimum_tier):
        findings.append("below_minimum_tier_for_authority_class")

    return {
        "allowed": not findings,
        "task_class": task_key,
        "authority_class": authority_key,
        "family": family_value,
        "tier": tier_value,
        "backend_runtime": backend_value,
        "model_name": model_name,
        "minimum_tier": minimum_tier,
        "findings": findings,
        "reason": "route_legal" if not findings else "route_illegal",
    }


def is_route_allowed(
    *,
    task_class: Any,
    authority_class: Any = "",
    family: Any = "",
    tier: Any = "",
    backend_runtime: Any = "",
    model_name: str = "",
    root: Optional[Path] = None,
) -> bool:
    return bool(
        route_legality_checks(
            task_class=task_class,
            authority_class=authority_class,
            family=family,
            tier=tier,
            backend_runtime=backend_runtime,
            model_name=model_name,
            root=root,
        )["allowed"]
    )


def assert_forbidden_downgrade(
    *,
    task_class: Any,
    authority_class: Any = "",
    candidate_tier: Any,
    root: Optional[Path] = None,
) -> None:
    policy = load_model_policy(root=root)
    task_key = _normalize_task_class(task_class)
    authority_key = _normalize_authority_class(authority_class)
    candidate = _normalize_tier(candidate_tier)
    forbidden = list((policy.get("forbidden_downgrades") or {}).get(authority_key, []))
    forbidden.extend((policy.get("forbidden_downgrades") or {}).get(task_key, []))
    forbidden_values = {_normalize_tier(item) for item in forbidden}
    if candidate in forbidden_values:
        raise ValueError(
            f"Forbidden downgrade: task_class={task_key} authority_class={authority_key} candidate_tier={candidate}"
        )


def route_legality_for_task(
    *,
    task: Optional[TaskRecord],
    route: Any,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    context = _task_context_from_record(task)
    candidate = _extract_route_candidate(route)
    legality = route_legality_checks(
        task_class=context["task_class"],
        authority_class=context["authority_class"],
        family=candidate["family"],
        tier=candidate["tier"],
        backend_runtime=candidate["backend_runtime"],
        model_name=candidate["model_name"],
        root=root,
    )
    try:
        assert_forbidden_downgrade(
            task_class=context["task_class"],
            authority_class=context["authority_class"],
            candidate_tier=candidate["tier"],
            root=root,
        )
    except ValueError as exc:
        legality = dict(legality)
        legality["allowed"] = False
        legality.setdefault("findings", []).append("forbidden_downgrade")
        legality["reason"] = "route_illegal"
        legality["forbidden_downgrade_error"] = str(exc)
    return legality


def _path(record_id: str, root: Optional[Path] = None) -> Path:
    return backend_assignments_dir(root=root) / f"{record_id}.json"


def save_backend_assignment(record: BackendAssignmentRecord, *, root: Optional[Path] = None) -> BackendAssignmentRecord:
    record.updated_at = now_iso()
    _path(record.backend_assignment_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_backend_assignment(backend_assignment_id: str, *, root: Optional[Path] = None) -> Optional[BackendAssignmentRecord]:
    path = _path(backend_assignment_id, root=root)
    if not path.exists():
        return None
    return BackendAssignmentRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_backend_assignments(root: Optional[Path] = None) -> list[BackendAssignmentRecord]:
    rows: list[BackendAssignmentRecord] = []
    for path in sorted(backend_assignments_dir(root=root).glob("*.json")):
        try:
            rows.append(BackendAssignmentRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def latest_backend_assignment(root: Optional[Path] = None) -> Optional[BackendAssignmentRecord]:
    rows = list_backend_assignments(root=root)
    return rows[0] if rows else None


def build_backend_assignment_summary(root: Optional[Path] = None) -> dict:
    rows = list_backend_assignments(root=root)
    provider_counts: dict[str, int] = {}
    backend_counts: dict[str, int] = {}
    policy = load_model_policy(root=root)
    for row in rows:
        provider_counts[row.provider_id] = provider_counts.get(row.provider_id, 0) + 1
        backend_counts[row.execution_backend] = backend_counts.get(row.execution_backend, 0) + 1
    return {
        "backend_assignment_count": len(rows),
        "provider_counts": provider_counts,
        "execution_backend_counts": backend_counts,
        "model_policy_path": str(model_policy_path(root=root)),
        "live_runtime_posture": dict(policy.get("live_runtime_posture") or {}),
        "latest_backend_assignment": rows[0].to_dict() if rows else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current backend assignment summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_backend_assignment_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
