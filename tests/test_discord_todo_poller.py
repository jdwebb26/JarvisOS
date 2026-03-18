"""Tests for discord_todo_poller — message filtering, first-run safety, idempotency."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.discord_todo_poller import (
    is_eligible_message,
    poll_once,
    _load_state,
    _save_state,
    _state_path,
)


# ---------------------------------------------------------------------------
# is_eligible_message
# ---------------------------------------------------------------------------

class TestIsEligibleMessage:
    def test_normal_user_message(self):
        msg = {"type": 0, "author": {"id": "123", "bot": False}, "content": "Fix the bug"}
        ok, reason = is_eligible_message(msg)
        assert ok is True
        assert reason == "ok"

    def test_reply_message(self):
        msg = {"type": 19, "author": {"id": "123"}, "content": "task: do this"}
        ok, _ = is_eligible_message(msg)
        assert ok is True

    def test_bot_message(self):
        msg = {"type": 0, "author": {"id": "999", "bot": True}, "content": "hello"}
        ok, reason = is_eligible_message(msg)
        assert ok is False
        assert reason == "bot"

    def test_webhook_message(self):
        msg = {"type": 0, "author": {"id": "999"}, "content": "hello", "webhook_id": "888"}
        ok, reason = is_eligible_message(msg)
        assert ok is False
        assert reason == "webhook"

    def test_jarvis_bot_id(self):
        msg = {"type": 0, "author": {"id": "1469920721378480192"}, "content": "hi"}
        ok, reason = is_eligible_message(msg)
        assert ok is False
        assert reason == "jarvis_bot"

    def test_system_message_type_7(self):
        """Type 7 = member join."""
        msg = {"type": 7, "author": {"id": "123"}, "content": "Welcome!"}
        ok, reason = is_eligible_message(msg)
        assert ok is False
        assert "system_message_type" in reason

    def test_empty_content(self):
        msg = {"type": 0, "author": {"id": "123"}, "content": "  "}
        ok, reason = is_eligible_message(msg)
        assert ok is False
        assert reason == "empty"

    def test_slash_command(self):
        msg = {"type": 0, "author": {"id": "123"}, "content": "/status"}
        ok, reason = is_eligible_message(msg)
        assert ok is False
        assert reason == "noise"

    def test_bare_url(self):
        msg = {"type": 0, "author": {"id": "123"}, "content": "https://example.com/path"}
        ok, reason = is_eligible_message(msg)
        assert ok is False
        assert reason == "noise"

    def test_single_emoji(self):
        msg = {"type": 0, "author": {"id": "123"}, "content": "<:thumbsup:123456>"}
        ok, reason = is_eligible_message(msg)
        assert ok is False
        assert reason == "noise"

    def test_punctuation_only(self):
        msg = {"type": 0, "author": {"id": "123"}, "content": "..."}
        ok, reason = is_eligible_message(msg)
        assert ok is False
        assert reason == "noise"

    def test_url_with_text_is_eligible(self):
        msg = {"type": 0, "author": {"id": "123"}, "content": "Check this out https://example.com"}
        ok, _ = is_eligible_message(msg)
        assert ok is True

    def test_no_content_key(self):
        msg = {"type": 0, "author": {"id": "123"}}
        ok, reason = is_eligible_message(msg)
        assert ok is False
        assert reason == "empty"


# ---------------------------------------------------------------------------
# First-run safety
# ---------------------------------------------------------------------------

class TestFirstRunSafety:
    def test_first_run_seeds_without_processing(self, tmp_path):
        """First run with no state should seed cursor, not process messages."""
        state_dir = tmp_path / "state" / "discord_todo_poller"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "poller_state.json"

        newest_msg = [{"id": "999999", "type": 0, "author": {"id": "1"}, "content": "old"}]

        with patch("scripts.discord_todo_poller._state_path", return_value=state_file), \
             patch("scripts.discord_todo_poller.fetch_recent_messages", return_value=newest_msg) as mock_fetch:
            result = poll_once("fake_token")

        assert result.get("seeded") is True
        assert result["processed"] == 0

        # State file should now have last_message_id set
        saved = json.loads(state_file.read_text())
        assert saved["last_message_id"] == "999999"

        # fetch was called with limit=1 (seed call), not with after=None
        calls = mock_fetch.call_args_list
        assert any(call.kwargs.get("limit") == 1 or (len(call.args) > 1 and call.args[1] == 1)
                    for call in calls) or calls[0][1].get("limit") == 1


class TestIdempotency:
    def test_same_message_not_processed_twice(self, tmp_path):
        """A message in processed_message_ids should be skipped."""
        state_dir = tmp_path / "state" / "discord_todo_poller"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "poller_state.json"

        state = {"last_message_id": "100", "processed_message_ids": ["200"]}
        state_file.write_text(json.dumps(state))

        messages = [{"id": "200", "type": 0, "author": {"id": "1"}, "content": "do thing"}]

        with patch("scripts.discord_todo_poller._state_path", return_value=state_file), \
             patch("scripts.discord_todo_poller.fetch_recent_messages", return_value=messages), \
             patch("scripts.discord_todo_poller._task_exists_for_message_id", return_value=False):
            result = poll_once("fake_token")

        assert result["processed"] == 0

    def test_task_level_dedup(self, tmp_path):
        """If a task already exists for this source_message_id, skip."""
        state_dir = tmp_path / "state" / "discord_todo_poller"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "poller_state.json"

        state = {"last_message_id": "100", "processed_message_ids": []}
        state_file.write_text(json.dumps(state))

        messages = [{"id": "200", "type": 0, "author": {"id": "1"}, "content": "do thing"}]

        with patch("scripts.discord_todo_poller._state_path", return_value=state_file), \
             patch("scripts.discord_todo_poller.fetch_recent_messages", return_value=messages), \
             patch("scripts.discord_todo_poller._task_exists_for_message_id", return_value=True):
            result = poll_once("fake_token", verbose=True)

        assert result["processed"] == 0


class TestDryRun:
    def test_dry_run_does_not_save_state(self, tmp_path):
        """Dry run should not update the state file."""
        state_dir = tmp_path / "state" / "discord_todo_poller"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "poller_state.json"

        state = {"last_message_id": "100", "processed_message_ids": []}
        state_file.write_text(json.dumps(state))

        messages = [{"id": "200", "type": 0, "author": {"id": "1"}, "content": "test task"}]

        with patch("scripts.discord_todo_poller._state_path", return_value=state_file), \
             patch("scripts.discord_todo_poller.fetch_recent_messages", return_value=messages), \
             patch("scripts.discord_todo_poller._task_exists_for_message_id", return_value=False):
            result = poll_once("fake_token", dry_run=True)

        assert result["processed"] == 1
        assert result["results"][0]["dry_run"] is True

        # State should be unchanged
        saved = json.loads(state_file.read_text())
        assert saved["last_message_id"] == "100"
        assert saved["processed_message_ids"] == []
