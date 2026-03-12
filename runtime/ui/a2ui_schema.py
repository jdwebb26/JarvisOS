#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


def new_component(component_type: str, *, component_id: str, props: dict[str, Any]) -> dict[str, Any]:
    return {
        "component_id": component_id,
        "component_type": component_type,
        "props": dict(props or {}),
    }


def new_view(
    view_id: str,
    *,
    title: str,
    view_type: str,
    components: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "view_id": view_id,
        "title": title,
        "view_type": view_type,
        "components": list(components or []),
        "metadata": dict(metadata or {}),
    }


def validate_component_payload(component: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(component, dict):
        return ["component_not_dict"]
    if not str(component.get("component_id") or "").strip():
        errors.append("missing_component_id")
    if not str(component.get("component_type") or "").strip():
        errors.append("missing_component_type")
    if not isinstance(component.get("props"), dict):
        errors.append("component_props_not_dict")
    return errors


def validate_view_payload(view: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(view, dict):
        return ["view_not_dict"]
    if not str(view.get("view_id") or "").strip():
        errors.append("missing_view_id")
    if not str(view.get("title") or "").strip():
        errors.append("missing_title")
    if not str(view.get("view_type") or "").strip():
        errors.append("missing_view_type")
    components = view.get("components")
    if not isinstance(components, list):
        errors.append("components_not_list")
        return errors
    for component in components:
        errors.extend(validate_component_payload(component))
    metadata = view.get("metadata", {})
    if not isinstance(metadata, dict):
        errors.append("metadata_not_dict")
    return errors

