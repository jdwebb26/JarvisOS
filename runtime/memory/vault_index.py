#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]


def vault_root(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "workspace" / "vault"
    path.mkdir(parents=True, exist_ok=True)
    return path


def vault_artifacts_dir(root: Optional[Path] = None) -> Path:
    path = vault_root(root) / "artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def vault_briefs_dir(root: Optional[Path] = None) -> Path:
    path = vault_root(root) / "briefs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def vault_index_path(root: Optional[Path] = None) -> Path:
    return vault_root(root) / "index.json"


def _default_index(root: Optional[Path] = None) -> dict[str, Any]:
    return {
        "index_version": "1",
        "non_authoritative": True,
        "notes": [
            "Vault content is a governed export sidecar.",
            "Runtime truth remains in Jarvis state and provenance records.",
        ],
        "workspace_vault_path": str(vault_root(root)),
        "items": [],
    }


def ensure_vault_index(root: Optional[Path] = None) -> dict[str, Any]:
    payload = _default_index(root)
    path = vault_index_path(root)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                payload.update(existing)
                payload["workspace_vault_path"] = str(vault_root(root))
                payload["non_authoritative"] = True
                payload.setdefault("items", [])
        except Exception:
            pass
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_vault_index(root: Optional[Path] = None) -> dict[str, Any]:
    path = vault_index_path(root)
    if not path.exists():
        return ensure_vault_index(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ensure_vault_index(root)
    if not isinstance(payload, dict):
        return ensure_vault_index(root)
    payload.setdefault("items", [])
    payload["workspace_vault_path"] = str(vault_root(root))
    payload["non_authoritative"] = True
    return payload


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    row = dict(item or {})
    row["non_authoritative"] = True
    row.setdefault("export_kind", "unknown")
    row.setdefault("title", "")
    row.setdefault("summary", "")
    row.setdefault("exported_at", "")
    row.setdefault("source_refs", {})
    return row


def update_vault_index(item: dict[str, Any], *, root: Optional[Path] = None) -> dict[str, Any]:
    payload = load_vault_index(root)
    rows = [_normalize_item(row) for row in payload.get("items", [])]
    normalized = _normalize_item(item)
    export_id = normalized.get("export_id")
    rows = [row for row in rows if row.get("export_id") != export_id]
    rows.append(normalized)
    rows.sort(key=lambda row: (str(row.get("exported_at") or ""), str(row.get("export_id") or "")), reverse=True)
    payload["items"] = rows
    vault_index_path(root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def rebuild_vault_index(root: Optional[Path] = None) -> dict[str, Any]:
    ensure_vault_index(root)
    items: list[dict[str, Any]] = []
    for folder in (vault_artifacts_dir(root), vault_briefs_dir(root)):
        for path in sorted(folder.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict) or not payload.get("export_id"):
                continue
            items.append(_normalize_item(payload))
    items.sort(key=lambda row: (str(row.get("exported_at") or ""), str(row.get("export_id") or "")), reverse=True)
    payload = load_vault_index(root)
    payload["items"] = items
    vault_index_path(root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def list_vault_items(*, root: Optional[Path] = None, export_kind: Optional[str] = None) -> list[dict[str, Any]]:
    rows = [_normalize_item(row) for row in load_vault_index(root).get("items", [])]
    if export_kind:
        rows = [row for row in rows if row.get("export_kind") == export_kind]
    return rows


def search_vault_items(query: str, *, root: Optional[Path] = None, export_kind: Optional[str] = None) -> list[dict[str, Any]]:
    terms = [term.lower() for term in str(query or "").split() if term.strip()]
    rows = list_vault_items(root=root, export_kind=export_kind)
    if not terms:
        return rows
    matches: list[dict[str, Any]] = []
    for row in rows:
        haystack = " ".join(
            [
                str(row.get("title") or ""),
                str(row.get("summary") or ""),
                json.dumps(row.get("source_refs") or {}, sort_keys=True),
            ]
        ).lower()
        if all(term in haystack for term in terms):
            matches.append(row)
    return matches


def build_vault_index_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    rows = list_vault_items(root=root)
    artifact_rows = [row for row in rows if row.get("export_kind") == "approved_artifact"]
    brief_rows = [row for row in rows if row.get("export_kind") == "derived_brief"]
    return {
        "vault_enabled": True,
        "non_authoritative": True,
        "workspace_vault_path": str(vault_root(root)),
        "index_path": str(vault_index_path(root)),
        "export_count": len(rows),
        "approved_artifact_export_count": len(artifact_rows),
        "brief_export_count": len(brief_rows),
        "latest_export": rows[0] if rows else None,
        "searchable_item_count": len(rows),
    }
