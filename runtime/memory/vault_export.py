#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import ArtifactRecord, RecordLifecycleState, new_id, now_iso
from runtime.memory.vault_index import (
    build_vault_index_summary,
    ensure_vault_index,
    update_vault_index,
    vault_artifacts_dir,
    vault_briefs_dir,
    vault_index_path,
    vault_root,
)


ROOT = Path(__file__).resolve().parents[2]


def _project_root(root: Optional[Path] = None) -> Path:
    return Path(root or ROOT).resolve()


def ensure_vault_scaffold(*, root: Optional[Path] = None) -> dict[str, Any]:
    resolved_root = _project_root(root)
    created: list[str] = []
    for folder in (vault_root(resolved_root), vault_artifacts_dir(resolved_root), vault_briefs_dir(resolved_root)):
        folder.mkdir(parents=True, exist_ok=True)
        created.append(str(folder.relative_to(resolved_root)))
    readme_path = vault_root(resolved_root) / "README.md"
    if not readme_path.exists():
        readme_path.write_text(
            "\n".join(
                [
                    "# Jarvis Vault",
                    "",
                    "This vault is a governed export sidecar.",
                    "",
                    "- Runtime truth remains in `state/` and the Jarvis provenance spine.",
                    "- Vault items are derived/exported support artifacts only.",
                    "- Do not treat this directory as task, review, approval, or execution authority.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    index = ensure_vault_index(resolved_root)
    return {
        "workspace_vault_path": str(vault_root(resolved_root)),
        "index_path": str(vault_index_path(resolved_root)),
        "created_dirs": created,
        "export_count": len(index.get("items", [])),
    }


def _artifact_path(artifact_id: str, *, root: Optional[Path] = None) -> Path:
    return _project_root(root) / "state" / "artifacts" / f"{artifact_id}.json"


def load_exportable_artifact(artifact_id: str, *, root: Optional[Path] = None) -> ArtifactRecord:
    path = _artifact_path(artifact_id, root=root)
    if not path.exists():
        raise FileNotFoundError(f"Artifact not found: {artifact_id}")
    record = ArtifactRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
    if record.lifecycle_state != RecordLifecycleState.PROMOTED.value:
        raise ValueError(f"Artifact {artifact_id} is not promoted and cannot be exported.")
    if record.revoked_at:
        raise ValueError(f"Artifact {artifact_id} is revoked and cannot be exported.")
    return record


def list_exportable_artifacts(*, root: Optional[Path] = None, limit: Optional[int] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    folder = _project_root(root) / "state" / "artifacts"
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            artifact = ArtifactRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if artifact.lifecycle_state != RecordLifecycleState.PROMOTED.value or artifact.revoked_at:
            continue
        rows.append(
            {
                "artifact_id": artifact.artifact_id,
                "task_id": artifact.task_id,
                "title": artifact.title,
                "summary": artifact.summary,
                "artifact_type": artifact.artifact_type,
                "provenance_ref": artifact.provenance_ref,
                "updated_at": artifact.updated_at,
            }
        )
    rows.sort(key=lambda row: (str(row.get("updated_at") or ""), str(row.get("artifact_id") or "")), reverse=True)
    if limit is not None:
        return rows[:limit]
    return rows


def _artifact_export_markdown(record: ArtifactRecord, metadata: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# {record.title}",
            "",
            "_Derived governed vault export. Runtime truth remains in Jarvis state/provenance records._",
            "",
            f"- Export ID: `{metadata['export_id']}`",
            f"- Artifact ID: `{record.artifact_id}`",
            f"- Task ID: `{record.task_id}`",
            f"- Artifact Type: `{record.artifact_type}`",
            f"- Lifecycle State: `{record.lifecycle_state}`",
            f"- Provenance Ref: `{record.provenance_ref or ''}`",
            f"- Exported At: `{metadata['exported_at']}`",
            "",
            "## Summary",
            "",
            record.summary or "_No summary provided._",
            "",
            "## Exported Content",
            "",
            record.content or "_No artifact content._",
            "",
        ]
    )


def export_approved_artifact(artifact_id: str, *, actor: str = "operator", root: Optional[Path] = None) -> dict[str, Any]:
    resolved_root = _project_root(root)
    ensure_vault_scaffold(root=resolved_root)
    record = load_exportable_artifact(artifact_id, root=resolved_root)
    export_id = new_id("vaultexp")
    exported_at = now_iso()
    stem = f"{record.task_id}_{record.artifact_id}"
    markdown_path = vault_artifacts_dir(resolved_root) / f"{stem}.md"
    metadata_path = vault_artifacts_dir(resolved_root) / f"{stem}.json"
    metadata = {
        "export_id": export_id,
        "export_kind": "approved_artifact",
        "title": record.title,
        "summary": record.summary,
        "exported_at": exported_at,
        "actor": actor,
        "non_authoritative": True,
        "markdown_path": str(markdown_path),
        "metadata_path": str(metadata_path),
        "source_refs": {
            "artifact_id": record.artifact_id,
            "task_id": record.task_id,
            "artifact_record_path": str(_artifact_path(record.artifact_id, root=resolved_root)),
            "provenance_ref": record.provenance_ref,
            "execution_backend": record.execution_backend,
            "backend_run_id": record.backend_run_id,
        },
    }
    markdown_path.write_text(_artifact_export_markdown(record, metadata) + "\n", encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    update_vault_index(metadata, root=resolved_root)
    return metadata


def export_brief_markdown(
    *,
    brief_kind: str,
    title: str,
    summary: str,
    markdown: str,
    source_refs: dict[str, Any],
    actor: str = "operator",
    root: Optional[Path] = None,
) -> dict[str, Any]:
    resolved_root = _project_root(root)
    ensure_vault_scaffold(root=resolved_root)
    export_id = new_id("vaultbrief")
    exported_at = now_iso()
    stem = f"{brief_kind}_{export_id}"
    markdown_path = vault_briefs_dir(resolved_root) / f"{stem}.md"
    metadata_path = vault_briefs_dir(resolved_root) / f"{stem}.json"
    metadata = {
        "export_id": export_id,
        "export_kind": "derived_brief",
        "brief_kind": brief_kind,
        "title": title,
        "summary": summary,
        "exported_at": exported_at,
        "actor": actor,
        "non_authoritative": True,
        "markdown_path": str(markdown_path),
        "metadata_path": str(metadata_path),
        "source_refs": dict(source_refs or {}),
    }
    markdown_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    update_vault_index(metadata, root=resolved_root)
    return metadata


def build_vault_export_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    resolved_root = _project_root(root)
    ensure_vault_scaffold(root=resolved_root)
    summary = build_vault_index_summary(root=resolved_root)
    summary["exportable_artifact_count"] = len(list_exportable_artifacts(root=resolved_root))
    summary["governed_export_only"] = True
    summary["runtime_truth_location"] = "state/"
    return summary
