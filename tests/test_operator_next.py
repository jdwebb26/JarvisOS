"""test_operator_next.py — Tests for operator_next priority policy."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_next import (
    compute_actions,
    no_action_item,
    render_compact,
    render_default,
    render_json,
)


def _make_infra(summary="Gateway is down"):
    return [{"priority": 1, "category": "infra", "summary": summary,
             "command": "systemctl --user start x", "detail": ""}]

def _make_stale():
    return [{"priority": 2, "category": "cleanup", "summary": "3 stale approvals",
             "command": "python3 scripts/reconcile_approvals.py --apply", "detail": ""}]

def _make_approval(tid="task_aaa"):
    return [{"priority": 3, "category": "approval", "summary": f"approve {tid} — test",
             "command": f"python3 scripts/run_ralph_v1.py --approve {tid}", "detail": "",
             "task_id": tid, "approval_id": "apr_001"}]

def _make_transient(tid="task_bbb"):
    return [{"priority": 4, "category": "transient_failure",
             "summary": f"retry {tid} — timeout", "command": f"--retry {tid}",
             "detail": "timeout", "task_id": tid}]

def _make_permanent(tid="task_ccc"):
    return [{"priority": 5, "category": "permanent_failure",
             "summary": f"investigate {tid}", "command": f"--explain {tid}",
             "detail": "", "task_id": tid}]

def _make_blocked():
    return [{"priority": 6, "category": "blocked", "summary": "5 blocked",
             "command": "triage", "detail": ""}]

def _make_queue():
    return [{"priority": 7, "category": "queue", "summary": "3 queued",
             "command": "ralph --status", "detail": ""}]


def _patch_all(**overrides):
    """Return a context manager that patches all check functions."""
    defaults = {
        "_check_infra": [],
        "_check_stale_state": [],
        "_check_approvals": [],
        "_check_failed_tasks": [],
        "_check_blocked": [],
        "_check_queue": [],
    }
    defaults.update(overrides)
    patches = [
        patch(f"scripts.operator_next.{fn}", return_value=val)
        for fn, val in defaults.items()
    ]
    from contextlib import ExitStack
    stack = ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


# ---------------------------------------------------------------------------
# Priority ordering tests
# ---------------------------------------------------------------------------

def test_infra_beats_approvals():
    with _patch_all(
        _check_infra=_make_infra(),
        _check_approvals=_make_approval(),
    ):
        actions = compute_actions()
    assert actions[0]["category"] == "infra"


def test_stale_beats_approvals():
    with _patch_all(
        _check_stale_state=_make_stale(),
        _check_approvals=_make_approval(),
    ):
        actions = compute_actions()
    assert actions[0]["category"] == "cleanup"


def test_approval_beats_transient():
    with _patch_all(
        _check_approvals=_make_approval(),
        _check_failed_tasks=_make_transient(),
    ):
        actions = compute_actions()
    assert actions[0]["category"] == "approval"


def test_transient_beats_permanent():
    with _patch_all(
        _check_failed_tasks=_make_transient() + _make_permanent(),
    ):
        actions = compute_actions()
    assert actions[0]["category"] == "transient_failure"


def test_no_action_when_clear():
    with _patch_all():
        actions = compute_actions()
    assert len(actions) == 0


def test_queue_is_lowest_priority():
    with _patch_all(
        _check_approvals=_make_approval(),
        _check_queue=_make_queue(),
    ):
        actions = compute_actions()
    assert actions[0]["category"] == "approval"
    assert actions[-1]["category"] == "queue"


# ---------------------------------------------------------------------------
# Render tests
# ---------------------------------------------------------------------------

def test_render_default_single():
    text = render_default(_make_approval())
    assert "NEXT:" in text
    assert "--approve" in text


def test_render_default_empty():
    text = render_default([])
    assert "no operator action needed" in text


def test_render_compact():
    text = render_compact(_make_approval())
    assert text.startswith("NEXT:")
    assert "\n" not in text


def test_render_compact_empty():
    text = render_compact([])
    assert "clear" in text


def test_render_json_structure():
    import json as _json
    text = render_json(_make_approval() + _make_transient(), top=2)
    data = _json.loads(text)
    assert "actions" in data
    assert len(data["actions"]) == 2
    assert data["total_candidates"] == 2
