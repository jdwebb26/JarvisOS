from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.spoken_approval import (
    create_spoken_approval_challenge,
    set_spoken_approval_code,
    spoken_approval_challenges_dir,
    spoken_approval_config_dir,
    verify_spoken_approval_code,
)
from runtime.voice.approval_prompt import (
    acknowledge_spoken_approval_result,
    create_voice_confirmation_prompt,
)


def test_setting_and_changing_approval_code_stores_hash_only() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = set_spoken_approval_code("alpha bravo", actor="tester", lane="tests", root=root)
        second = set_spoken_approval_code("charlie delta", actor="tester", lane="tests", root=root)
        assert first["code_hash"] != second["code_hash"]
        config = json.loads((spoken_approval_config_dir(root) / "active_code.json").read_text(encoding="utf-8"))
        assert "alpha bravo" not in json.dumps(config)
        assert "charlie delta" not in json.dumps(config)


def test_creating_spoken_approval_challenge() -> None:
    with TemporaryDirectory() as tmp:
        challenge = create_spoken_approval_challenge(
            action_id="act_1",
            actor="tester",
            lane="tests",
            risk_tier="high",
            root=Path(tmp),
        )
        assert challenge["action_id"] == "act_1"
        assert challenge["status"] == "pending"
        assert challenge["used"] is False


def test_correct_code_succeeds() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        set_spoken_approval_code("alpha bravo", actor="tester", lane="tests", root=root)
        challenge = create_spoken_approval_challenge(
            action_id="act_2",
            actor="tester",
            lane="tests",
            risk_tier="medium",
            root=root,
        )
        result = verify_spoken_approval_code(
            " Alpha   Bravo ",
            challenge_id=challenge["challenge_id"],
            actor="tester",
            lane="tests",
            root=root,
        )
        assert result["approved"] is True
        assert result["status"] == "approved"


def test_wrong_code_fails() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        set_spoken_approval_code("alpha bravo", actor="tester", lane="tests", root=root)
        challenge = create_spoken_approval_challenge(
            action_id="act_3",
            actor="tester",
            lane="tests",
            risk_tier="high",
            root=root,
        )
        result = verify_spoken_approval_code(
            "wrong code",
            challenge_id=challenge["challenge_id"],
            actor="tester",
            lane="tests",
            root=root,
        )
        assert result["approved"] is False
        assert result["status"] == "invalid_code"


def test_reused_challenge_fails() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        set_spoken_approval_code("alpha bravo", actor="tester", lane="tests", root=root)
        challenge = create_spoken_approval_challenge(
            action_id="act_4",
            actor="tester",
            lane="tests",
            risk_tier="high",
            root=root,
        )
        first = verify_spoken_approval_code(
            "alpha bravo",
            challenge_id=challenge["challenge_id"],
            actor="tester",
            lane="tests",
            root=root,
        )
        second = verify_spoken_approval_code(
            "alpha bravo",
            challenge_id=challenge["challenge_id"],
            actor="tester",
            lane="tests",
            root=root,
        )
        assert first["status"] == "approved"
        assert second["status"] == "reused"


def test_expired_challenge_fails() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        set_spoken_approval_code("alpha bravo", actor="tester", lane="tests", root=root)
        challenge = create_spoken_approval_challenge(
            action_id="act_5",
            actor="tester",
            lane="tests",
            risk_tier="high",
            root=root,
            ttl_seconds=0,
        )
        challenge_path = spoken_approval_challenges_dir(root) / f"{challenge['challenge_id']}.json"
        stored = json.loads(challenge_path.read_text(encoding="utf-8"))
        stored["expires_at"] = "2000-01-01T00:00:00+00:00"
        challenge_path.write_text(json.dumps(stored, indent=2) + "\n", encoding="utf-8")
        result = verify_spoken_approval_code(
            "alpha bravo",
            challenge_id=challenge["challenge_id"],
            actor="tester",
            lane="tests",
            root=root,
        )
        assert result["approved"] is False
        assert result["status"] == "expired"


def test_voice_prompt_and_ack_are_stubbed_and_durable() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        challenge = create_spoken_approval_challenge(
            action_id="act_6",
            actor="tester",
            lane="tests",
            risk_tier="medium",
            root=root,
        )
        prompt = create_voice_confirmation_prompt(
            challenge_id=challenge["challenge_id"],
            action_id=challenge["action_id"],
            actor="tester",
            lane="tests",
            root=root,
        )
        ack = acknowledge_spoken_approval_result(
            "approved",
            actor="tester",
            lane="tests",
            root=root,
        )
        assert prompt["status"] == "prompted"
        assert ack["status"] == "approved"


if __name__ == "__main__":
    test_setting_and_changing_approval_code_stores_hash_only()
    test_creating_spoken_approval_challenge()
    test_correct_code_succeeds()
    test_wrong_code_fails()
    test_reused_challenge_fails()
    test_expired_challenge_fails()
    test_voice_prompt_and_ack_are_stubbed_and_durable()
