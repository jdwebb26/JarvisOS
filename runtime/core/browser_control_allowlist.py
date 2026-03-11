#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import BrowserControlAllowlistRecord, new_id, now_iso


def browser_control_allowlists_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "browser_control_allowlists"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(browser_control_allowlist_id: str, *, root: Optional[Path] = None) -> Path:
    return browser_control_allowlists_dir(root) / f"{browser_control_allowlist_id}.json"


def save_browser_control_allowlist(
    record: BrowserControlAllowlistRecord,
    *,
    root: Optional[Path] = None,
) -> BrowserControlAllowlistRecord:
    record.updated_at = now_iso()
    _path(record.browser_control_allowlist_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def list_browser_control_allowlists(*, root: Optional[Path] = None) -> list[BrowserControlAllowlistRecord]:
    rows: list[BrowserControlAllowlistRecord] = []
    for path in browser_control_allowlists_dir(root).glob("*.json"):
        try:
            rows.append(BrowserControlAllowlistRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: (row.updated_at, row.created_at), reverse=True)
    return rows


def ensure_default_browser_control_allowlist(*, root: Optional[Path] = None) -> BrowserControlAllowlistRecord:
    rows = list_browser_control_allowlists(root=root)
    if rows:
        return rows[0]
    record = BrowserControlAllowlistRecord(
        browser_control_allowlist_id=new_id("browserallow"),
        created_at=now_iso(),
        updated_at=now_iso(),
        actor="system",
        lane="browser_policy",
        allowed_apps=[],
        allowed_sites=[],
        allowed_paths=[],
        blocked_apps=[],
        blocked_sites=[],
        blocked_paths=[],
        destructive_actions_require_confirmation=True,
        secret_entry_requires_manual_control=True,
    )
    return save_browser_control_allowlist(record, root=root)


def build_browser_control_allowlist_summary(*, root: Optional[Path] = None) -> dict:
    latest = ensure_default_browser_control_allowlist(root=root)
    rows = list_browser_control_allowlists(root=root)
    return {
        "browser_control_allowlist_count": len(rows),
        "latest_browser_control_allowlist": latest.to_dict(),
        "allowed_app_count": len(latest.allowed_apps),
        "allowed_site_count": len(latest.allowed_sites),
        "allowed_path_count": len(latest.allowed_paths),
        "blocked_app_count": len(latest.blocked_apps),
        "blocked_site_count": len(latest.blocked_sites),
        "blocked_path_count": len(latest.blocked_paths),
        "destructive_actions_require_confirmation": latest.destructive_actions_require_confirmation,
        "secret_entry_requires_manual_control": latest.secret_entry_requires_manual_control,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current BrowserControlAllowlist summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_browser_control_allowlist_summary(root=Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
