import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_json(cmd: list[str]) -> dict:
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        raise AssertionError(
            f"Command failed ({completed.returncode}): {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def test_enqueue_reply_message_writes_inbound_row(tmp_path: Path):
    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_enqueue_reply_message.py"),
            "--root",
            str(tmp_path),
            "--raw-text",
            "A1",
            "--source-message-id",
            "msg_enqueue_1",
            "--apply",
            "--dry-run",
        ]
    )

    path = Path(payload["path"])
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert path.exists()
    assert stored["source_message_id"] == "msg_enqueue_1"
    assert stored["raw_text"] == "A1"
    assert stored["apply"] is True
    assert stored["dry_run"] is True
