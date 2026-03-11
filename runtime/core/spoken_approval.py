#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from runtime.core.models import new_id, now_iso


ROOT = Path(__file__).resolve().parents[2]


def spoken_approval_config_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "spoken_approval_config"
    path.mkdir(parents=True, exist_ok=True)
    return path


def spoken_approval_challenges_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "spoken_approval_challenges"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _config_path(root: Optional[Path] = None) -> Path:
    return spoken_approval_config_dir(root) / "active_code.json"


def _challenge_path(challenge_id: str, *, root: Optional[Path] = None) -> Path:
    return spoken_approval_challenges_dir(root) / f"{challenge_id}.json"


def _normalize_code_phrase(value: str) -> str:
    normalized = " ".join(str(value or "").strip().lower().split())
    return normalized


def _hash_code_phrase(value: str) -> str:
    return hashlib.sha256(_normalize_code_phrase(value).encode("utf-8")).hexdigest()


def _load_active_code(root: Optional[Path] = None) -> Optional[dict]:
    path = _config_path(root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_active_code(record: dict, *, root: Optional[Path] = None) -> dict:
    _config_path(root).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def _load_challenge(challenge_id: str, *, root: Optional[Path] = None) -> Optional[dict]:
    path = _challenge_path(challenge_id, root=root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_challenge(record: dict, *, root: Optional[Path] = None) -> dict:
    record["updated_at"] = now_iso()
    _challenge_path(record["challenge_id"], root=root).write_text(
        json.dumps(record, indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def _is_expired(expires_at: str) -> bool:
    return now_iso() > expires_at


def set_spoken_approval_code(
    code_phrase: str,
    *,
    actor: str = "operator",
    lane: str = "voice",
    root=None,
) -> dict:
    record = {
        "config_id": new_id("spkcfg"),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "actor": actor,
        "lane": lane,
        "status": "active",
        "code_hash": _hash_code_phrase(code_phrase),
        "reason": "spoken_approval_code_set",
    }
    return _save_active_code(record, root=root)


def create_spoken_approval_challenge(
    *,
    action_id: str,
    actor: str,
    lane: str,
    risk_tier: str,
    root=None,
    ttl_seconds: int = 120,
) -> dict:
    now = now_iso()
    expires_at = (
        __import__("datetime").datetime.fromisoformat(now.replace("Z", "+00:00"))
        + __import__("datetime").timedelta(seconds=ttl_seconds)
    ).isoformat()
    record = {
        "challenge_id": new_id("spkchl"),
        "action_id": action_id,
        "actor": actor,
        "lane": lane,
        "risk_tier": risk_tier,
        "created_at": now,
        "updated_at": now,
        "expires_at": expires_at,
        "status": "pending",
        "used": False,
        "used_at": None,
        "used_by": None,
        "verification_result": "pending",
    }
    return _save_challenge(record, root=root)


def verify_spoken_approval_code(
    spoken_code: str,
    *,
    challenge_id: str,
    actor: str,
    lane: str,
    root=None,
) -> dict:
    challenge = _load_challenge(challenge_id, root=root)
    if challenge is None:
        return {
            "challenge_id": challenge_id,
            "action_id": "",
            "actor": actor,
            "lane": lane,
            "status": "invalid_code",
            "reason": "unknown_challenge",
            "approved": False,
        }

    if challenge.get("used"):
        challenge["status"] = "reused"
        challenge["verification_result"] = "reused"
        _save_challenge(challenge, root=root)
        return {
            "challenge_id": challenge_id,
            "action_id": challenge["action_id"],
            "actor": actor,
            "lane": lane,
            "status": "reused",
            "reason": "challenge_already_used",
            "approved": False,
        }

    if _is_expired(challenge["expires_at"]):
        challenge["status"] = "expired"
        challenge["verification_result"] = "expired"
        _save_challenge(challenge, root=root)
        return {
            "challenge_id": challenge_id,
            "action_id": challenge["action_id"],
            "actor": actor,
            "lane": lane,
            "status": "expired",
            "reason": "challenge_expired",
            "approved": False,
        }

    active_code = _load_active_code(root=root)
    if active_code is None:
        challenge["status"] = "no_active_code"
        challenge["verification_result"] = "no_active_code"
        _save_challenge(challenge, root=root)
        return {
            "challenge_id": challenge_id,
            "action_id": challenge["action_id"],
            "actor": actor,
            "lane": lane,
            "status": "no_active_code",
            "reason": "no_active_spoken_approval_code",
            "approved": False,
        }

    if _hash_code_phrase(spoken_code) != active_code["code_hash"]:
        challenge["status"] = "invalid_code"
        challenge["verification_result"] = "invalid_code"
        _save_challenge(challenge, root=root)
        return {
            "challenge_id": challenge_id,
            "action_id": challenge["action_id"],
            "actor": actor,
            "lane": lane,
            "status": "invalid_code",
            "reason": "spoken_code_mismatch",
            "approved": False,
        }

    challenge["status"] = "approved"
    challenge["used"] = True
    challenge["used_at"] = now_iso()
    challenge["used_by"] = actor
    challenge["verification_result"] = "approved"
    _save_challenge(challenge, root=root)
    return {
        "challenge_id": challenge_id,
        "action_id": challenge["action_id"],
        "actor": actor,
        "lane": lane,
        "status": "approved",
        "reason": "spoken_code_verified",
        "approved": True,
    }
