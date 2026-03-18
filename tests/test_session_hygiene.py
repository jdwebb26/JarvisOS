"""Tests for runtime.core.session_hygiene — orchestration session auto-rotation."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.session_hygiene import (
    ORCHESTRATION_AGENTS,
    TRANSCRIPT_LINE_THRESHOLD,
    TRANSCRIPT_SIZE_THRESHOLD_BYTES,
    check_and_rotate_orchestration_session,
    pre_context_build_hygiene,
    run_orchestration_hygiene,
)


def _setup_agent_session(
    openclaw_root: Path,
    agent: str,
    *,
    transcript_content: str = "",
    tokens: int | None = 200000,
    extra_sessions: dict | None = None,
) -> tuple[Path, Path]:
    """Create a minimal agent session structure.

    Returns (sessions_json_path, transcript_path).
    """
    sessions_dir = openclaw_root / "agents" / agent / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_id = f"test-{agent}-session-001"
    transcript_path = sessions_dir / f"{session_id}.jsonl"
    transcript_path.write_text(transcript_content, encoding="utf-8")

    main_key = f"agent:{agent}:main"
    sessions_data = {
        main_key: {
            "sessionId": session_id,
            "sessionFile": str(transcript_path),
            "contextTokens": tokens,
            "tokens": None,
            "model": "qwen3.5-35b-a3b",
        }
    }
    if extra_sessions:
        sessions_data.update(extra_sessions)

    sessions_json = sessions_dir / "sessions.json"
    sessions_json.write_text(json.dumps(sessions_data, indent=2), encoding="utf-8")
    return sessions_json, transcript_path


def _make_large_transcript(lines: int = 100) -> str:
    """Generate a transcript with the given number of lines."""
    rows = []
    for i in range(lines):
        entry = {
            "type": "message",
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"Turn {i}: " + ("x" * 200),
            "timestamp": f"2026-03-18T{i:05d}",
        }
        rows.append(json.dumps(entry))
    return "\n".join(rows) + "\n"


# ── Test: oversized orchestration session rotates ──


def test_oversized_session_rotates():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        large_transcript = _make_large_transcript(lines=200)
        sessions_json, transcript_path = _setup_agent_session(
            root, "hal", transcript_content=large_transcript
        )
        original_size = transcript_path.stat().st_size
        assert original_size > TRANSCRIPT_SIZE_THRESHOLD_BYTES

        report = check_and_rotate_orchestration_session(
            agent_id="hal", openclaw_root=root
        )

        assert report["action"] == "rotated"
        assert report["transcript_bytes"] == original_size
        assert report["archive_path"] is not None
        assert Path(report["archive_path"]).exists()
        # Transcript should be truncated.
        assert transcript_path.stat().st_size == 0
        # sessions.json should have tokens reset.
        updated = json.loads(sessions_json.read_text())
        assert updated["agent:hal:main"]["contextTokens"] is None
        assert updated["agent:hal:main"]["tokens"] is None
        assert updated["agent:hal:main"]["model"] is None
        # Archive should contain the original content.
        archive_content = Path(report["archive_path"]).read_text()
        assert len(archive_content) == len(large_transcript)


def test_line_count_threshold_triggers_rotation():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Create small lines but many of them.
        lines = TRANSCRIPT_LINE_THRESHOLD + 10
        transcript = "\n".join(f'{{"t":{i}}}' for i in range(lines)) + "\n"
        _setup_agent_session(root, "jarvis", transcript_content=transcript)

        report = check_and_rotate_orchestration_session(
            agent_id="jarvis", openclaw_root=root
        )
        assert report["action"] == "rotated"
        assert report["transcript_lines"] >= TRANSCRIPT_LINE_THRESHOLD


# ── Test: healthy session stays untouched ──


def test_healthy_session_untouched():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        small_transcript = _make_large_transcript(lines=5)
        sessions_json, transcript_path = _setup_agent_session(
            root, "archimedes", transcript_content=small_transcript
        )
        original_content = transcript_path.read_text()

        report = check_and_rotate_orchestration_session(
            agent_id="archimedes", openclaw_root=root
        )

        assert report["action"] == "ok"
        assert report["reason"] == "within_thresholds"
        # Transcript should be unchanged.
        assert transcript_path.read_text() == original_content
        # sessions.json should be unchanged.
        data = json.loads(sessions_json.read_text())
        assert data["agent:archimedes:main"]["contextTokens"] == 200000


# ── Test: repeated runs don't inherit stale oversized history ──


def test_repeated_runs_clean_after_rotation():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        large_transcript = _make_large_transcript(lines=120)
        _setup_agent_session(root, "hal", transcript_content=large_transcript)

        # Run 1: should rotate.
        r1 = check_and_rotate_orchestration_session(
            agent_id="hal", openclaw_root=root
        )
        assert r1["action"] == "rotated"

        # Run 2: session is now clean, should be ok.
        r2 = check_and_rotate_orchestration_session(
            agent_id="hal", openclaw_root=root
        )
        assert r2["action"] == "ok"
        assert r2["transcript_bytes"] == 0
        assert r2["transcript_lines"] == 0

        # Run 3: still clean.
        r3 = check_and_rotate_orchestration_session(
            agent_id="hal", openclaw_root=root
        )
        assert r3["action"] == "ok"


# ── Test: unrelated sessions are not wiped ──


def test_unrelated_sessions_preserved():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        large_transcript = _make_large_transcript(lines=120)
        discord_session = {
            "agent:hal:discord:channel:123456": {
                "sessionId": "discord-session-001",
                "sessionFile": str(
                    root / "agents" / "hal" / "sessions" / "discord-session-001.jsonl"
                ),
                "contextTokens": 50000,
                "tokens": None,
                "model": "qwen3.5-35b-a3b",
            }
        }
        sessions_json, _ = _setup_agent_session(
            root,
            "hal",
            transcript_content=large_transcript,
            extra_sessions=discord_session,
        )
        # Create the Discord session transcript.
        discord_transcript = root / "agents" / "hal" / "sessions" / "discord-session-001.jsonl"
        discord_content = '{"type":"message","role":"user","content":"hello"}\n'
        discord_transcript.write_text(discord_content, encoding="utf-8")

        report = check_and_rotate_orchestration_session(
            agent_id="hal", openclaw_root=root
        )

        assert report["action"] == "rotated"
        # Discord session transcript must be untouched.
        assert discord_transcript.read_text() == discord_content
        # Discord session metadata must be preserved.
        data = json.loads(sessions_json.read_text())
        assert "agent:hal:discord:channel:123456" in data
        assert data["agent:hal:discord:channel:123456"]["contextTokens"] == 50000


def test_non_orchestration_agent_ignored():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _setup_agent_session(
            root,
            "scout",
            transcript_content=_make_large_transcript(lines=200),
        )

        report = check_and_rotate_orchestration_session(
            agent_id="scout", openclaw_root=root
        )
        # scout is not in ORCHESTRATION_AGENTS — but check_and_rotate operates
        # on whatever agent_id is passed.  The gating is in
        # pre_context_build_hygiene and run_orchestration_hygiene.
        # Here, scout would still get rotated by the raw function.
        # Verify that run_orchestration_hygiene only touches the 3 agents.
        reports = run_orchestration_hygiene(openclaw_root=root)
        agent_ids = [r["agent"] for r in reports]
        assert "scout" not in agent_ids
        assert set(agent_ids) == set(ORCHESTRATION_AGENTS)


# ── Test: pre_context_build_hygiene only fires for orchestration keys ──


def test_pre_context_build_hygiene_only_orchestration():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        large = _make_large_transcript(lines=120)
        _setup_agent_session(root, "hal", transcript_content=large)

        # Orchestration key should fire.
        result = pre_context_build_hygiene(
            session_key="agent:hal:main",
            openclaw_root=root,
        )
        assert result is not None
        assert result["action"] == "rotated"

        # Non-orchestration key should be None.
        result2 = pre_context_build_hygiene(
            session_key="agent:hal:discord:channel:12345",
            openclaw_root=root,
        )
        assert result2 is None

        # Scout key should be None (not in ORCHESTRATION_AGENTS).
        result3 = pre_context_build_hygiene(
            session_key="agent:scout:main",
            openclaw_root=root,
        )
        assert result3 is None


# ── Test: dry run doesn't modify anything ──


def test_dry_run_no_modification():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        large = _make_large_transcript(lines=120)
        sessions_json, transcript_path = _setup_agent_session(
            root, "jarvis", transcript_content=large
        )
        original_content = transcript_path.read_text()
        original_json = sessions_json.read_text()

        report = check_and_rotate_orchestration_session(
            agent_id="jarvis", openclaw_root=root, dry_run=True
        )

        assert report["action"] == "would_rotate"
        assert transcript_path.read_text() == original_content
        assert sessions_json.read_text() == original_json


# ── Test: missing sessions.json handled gracefully ──


def test_missing_sessions_json():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        report = check_and_rotate_orchestration_session(
            agent_id="hal", openclaw_root=root
        )
        assert report["action"] == "skip"
        assert report["reason"] == "no_sessions_json"


# ── Test: run_orchestration_hygiene covers all three agents ──


def test_run_orchestration_hygiene_all_agents():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        large = _make_large_transcript(lines=120)
        for agent in ORCHESTRATION_AGENTS:
            _setup_agent_session(root, agent, transcript_content=large)

        reports = run_orchestration_hygiene(openclaw_root=root)

        assert len(reports) == len(ORCHESTRATION_AGENTS)
        for r in reports:
            assert r["action"] == "rotated"
            assert r["archive_path"] is not None

        # Run again — all should be ok now.
        reports2 = run_orchestration_hygiene(openclaw_root=root)
        for r in reports2:
            assert r["action"] == "ok"


# ── Test: stale lock behavior (sessions.json with stale tokens) ──


def test_stale_tokens_reset_on_rotation():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        large = _make_large_transcript(lines=120)
        sessions_json, _ = _setup_agent_session(
            root, "jarvis", transcript_content=large, tokens=999999
        )

        report = check_and_rotate_orchestration_session(
            agent_id="jarvis", openclaw_root=root
        )
        assert report["action"] == "rotated"

        data = json.loads(sessions_json.read_text())
        assert data["agent:jarvis:main"]["contextTokens"] is None
        assert data["agent:jarvis:main"]["model"] is None

        # Next run sees clean state.
        report2 = check_and_rotate_orchestration_session(
            agent_id="jarvis", openclaw_root=root
        )
        assert report2["action"] == "ok"
