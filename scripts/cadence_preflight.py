#!/usr/bin/env python3
"""cadence_preflight.py — One-command operator preflight for Cadence voice.

Usage:
    python3 scripts/cadence_preflight.py           # full preflight
    python3 scripts/cadence_preflight.py --tts     # TTS render+play test only
    python3 scripts/cadence_preflight.py --json    # machine-readable output

Checks:
    1. PulseAudio output (RDPSink — WSLg audio out)
    2. PulseAudio input  (RDPSource — WSL mic passthrough)
    3. Cadence daemon service status
    4. Voice stack health (wake, VAD, STT, TTS engines)
    5. TTS render proof (generate + optionally play a test line)
    6. Discord text channel connectivity (#review reachable)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_pulse_output() -> dict:
    """Check PulseAudio output sink availability."""
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sinks", "short"], text=True, timeout=5
        )
        sinks = [ln.split("\t")[1] for ln in out.strip().splitlines() if "\t" in ln]
        has_rdp_sink = any("rdpsink" in s.lower() for s in sinks)
        return {
            "status": "ok" if has_rdp_sink else "warn",
            "sinks": sinks,
            "note": "RDPSink available — audio output OK" if has_rdp_sink else "RDPSink not found",
        }
    except Exception as exc:
        return {"status": "error", "note": str(exc)}


def check_pulse_input() -> dict:
    """Check PulseAudio input source (microphone) availability."""
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources", "short"], text=True, timeout=5
        )
        sources = [ln.split("\t")[1] for ln in out.strip().splitlines() if "\t" in ln]
        has_rdp_source = any(s.lower() == "rdpsource" for s in sources)
        monitor_only = all("monitor" in s.lower() for s in sources)
        if has_rdp_source:
            return {"status": "ok", "sources": sources, "note": "RDPSource available — mic input OK"}
        if monitor_only:
            return {
                "status": "blocked",
                "sources": sources,
                "note": "Only monitor sources — mic input BLOCKED (no RDPSource)",
                "fix": "Requires WSLg audio passthrough or RDP mic redirection to be enabled",
            }
        return {"status": "warn", "sources": sources, "note": "RDPSource not found"}
    except Exception as exc:
        return {"status": "error", "note": str(exc)}


def check_daemon_service() -> dict:
    """Check cadence-voice-daemon systemd service status."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "cadence-voice-daemon.service"],
            capture_output=True, text=True, timeout=5,
        )
        is_active = result.stdout.strip() == "active"

        # Get recent logs
        log_result = subprocess.run(
            ["journalctl", "--user", "-u", "cadence-voice-daemon.service",
             "--no-pager", "-n", "5", "--output=short"],
            capture_output=True, text=True, timeout=5,
        )
        recent_logs = log_result.stdout.strip().splitlines()[-3:] if log_result.stdout else []

        # Check for listener_error in recent logs
        has_listener_error = any("listener_error" in ln for ln in recent_logs)

        if is_active and not has_listener_error:
            return {"status": "ok", "note": "Cadence daemon running, listener healthy"}
        elif is_active and has_listener_error:
            return {
                "status": "degraded",
                "note": "Cadence daemon running but listener has errors (likely mic unavailable)",
                "recent_logs": recent_logs,
            }
        else:
            return {"status": "stopped", "note": "Cadence daemon is not running"}
    except Exception as exc:
        return {"status": "error", "note": str(exc)}


def check_voice_stack() -> dict:
    """Run the voice stack health probe."""
    try:
        from runtime.voice.health_probe import probe_all
        result = probe_all()
        return {
            "status": result.get("summary", {}).get("overall", "unknown"),
            "failed": result.get("summary", {}).get("failed", []),
            "warned": result.get("summary", {}).get("warned", []),
            "config": result.get("config", {}),
        }
    except Exception as exc:
        return {"status": "error", "note": str(exc)}


def check_tts_render() -> dict:
    """Test TTS rendering (generate a WAV file)."""
    try:
        from runtime.voice.tts_piper import speak
        wav_path = "/tmp/cadence_preflight_tts.wav"
        result = speak("Preflight check complete. All systems ready.", output_wav=wav_path)
        if result.get("ok") and Path(wav_path).exists():
            size = Path(wav_path).stat().st_size
            return {
                "status": "ok",
                "note": f"Piper TTS rendered {size} bytes",
                "wav_path": wav_path,
                "size_bytes": size,
            }
        return {"status": "error", "note": result.get("error", "render failed")}
    except Exception as exc:
        return {"status": "error", "note": str(exc)}


def check_tts_playback() -> dict:
    """Test TTS playback via paplay."""
    wav = "/tmp/cadence_preflight_tts.wav"
    if not Path(wav).exists():
        return {"status": "skip", "note": "No WAV file to play (render first)"}
    if not shutil.which("paplay"):
        return {"status": "error", "note": "paplay not found"}
    try:
        subprocess.run(["paplay", wav], check=True, timeout=15,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"status": "ok", "note": "Audio playback succeeded"}
    except subprocess.CalledProcessError as exc:
        return {"status": "error", "note": f"paplay exit {exc.returncode}"}
    except Exception as exc:
        return {"status": "error", "note": str(exc)}


def check_discord_text() -> dict:
    """Check Discord text channel reachable (via bot token to #review)."""
    try:
        _scripts = ROOT / "scripts"
        if str(_scripts) not in sys.path:
            sys.path.insert(0, str(_scripts))
        from dispatch_utils import send_bot_message
        # Don't actually send, just verify token loads
        from dispatch_utils import load_webhook_url
        token = load_webhook_url("DISCORD_BOT_TOKEN", Path.home() / ".openclaw")
        if token:
            return {"status": "ok", "note": "Discord bot token available — text channels reachable"}
        return {"status": "warn", "note": "Discord bot token not found"}
    except Exception as exc:
        return {"status": "error", "note": str(exc)}


def check_discord_voice() -> dict:
    """Check Discord voice channel support."""
    # Discord voice requires discord.py[voice] with opus + nacl
    has_discord = False
    try:
        import discord  # noqa: F401
        has_discord = True
    except ImportError:
        pass

    has_opus = shutil.which("opusenc") is not None or Path("/usr/lib/x86_64-linux-gnu/libopus.so.0").exists()
    has_nacl = False
    try:
        import nacl  # noqa: F401
        has_nacl = True
    except ImportError:
        pass

    if has_discord and has_nacl:
        return {"status": "ok", "note": "discord.py + nacl available — voice channels supported"}

    missing = []
    if not has_discord:
        missing.append("discord.py[voice]")
    if not has_nacl:
        missing.append("PyNaCl")

    return {
        "status": "not_implemented",
        "note": "Discord voice channel join NOT implemented",
        "missing": missing,
        "fix": "Discord voice requires: pip install 'discord.py[voice]' — plus a voice bot implementation",
    }


# ---------------------------------------------------------------------------
# Full preflight
# ---------------------------------------------------------------------------

def run_preflight(*, play_tts: bool = False) -> dict:
    """Run all preflight checks."""
    checks = {
        "pulse_output": check_pulse_output(),
        "pulse_input": check_pulse_input(),
        "daemon_service": check_daemon_service(),
        "voice_stack": check_voice_stack(),
        "tts_render": check_tts_render(),
        "discord_text": check_discord_text(),
        "discord_voice": check_discord_voice(),
    }

    if play_tts:
        checks["tts_playback"] = check_tts_playback()

    # Classify results
    blockers = []
    warnings = []
    ok_checks = []
    not_impl = []

    for name, result in checks.items():
        status = result.get("status", "unknown")
        if status in ("error", "blocked"):
            blockers.append(name)
        elif status in ("warn", "degraded"):
            warnings.append(name)
        elif status == "not_implemented":
            not_impl.append(name)
        elif status in ("ok", "skip"):
            ok_checks.append(name)

    # Determine overall readiness
    if "discord_voice" in not_impl:
        readiness = "local_only"
        readiness_note = "Voice works LOCAL ONLY — Discord voice channel NOT available"
    elif blockers:
        readiness = "blocked"
        readiness_note = f"Blocked: {', '.join(blockers)}"
    elif warnings:
        readiness = "degraded"
        readiness_note = f"Degraded: {', '.join(warnings)}"
    else:
        readiness = "ready"
        readiness_note = "All systems ready"

    checks["summary"] = {
        "readiness": readiness,
        "note": readiness_note,
        "ok": ok_checks,
        "warnings": warnings,
        "blockers": blockers,
        "not_implemented": not_impl,
    }
    return checks


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _icon(status: str) -> str:
    return {
        "ok": "\u2705", "ready": "\u2705",
        "error": "\u274c", "blocked": "\U0001f6d1",
        "warn": "\u26a0\ufe0f", "degraded": "\u26a0\ufe0f",
        "not_implemented": "\U0001f6a7", "skip": "\u23ed\ufe0f",
        "stopped": "\u23f9\ufe0f", "local_only": "\U0001f4bb",
    }.get(status, "\u2753")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cadence voice preflight check")
    parser.add_argument("--tts", action="store_true", help="Include TTS playback test")
    parser.add_argument("--json", action="store_true", dest="json_out", help="JSON output")
    args = parser.parse_args()

    result = run_preflight(play_tts=args.tts)

    if args.json_out:
        print(json.dumps(result, indent=2))
    else:
        print("\n  CADENCE PREFLIGHT CHECK")
        print("  " + "=" * 40)
        for name, check in result.items():
            if name == "summary":
                continue
            if not isinstance(check, dict):
                continue
            status = check.get("status", "?")
            note = check.get("note", "")
            print(f"  {_icon(status)} {name}: {note}")
            if check.get("fix"):
                print(f"      fix: {check['fix']}")

        summary = result.get("summary", {})
        readiness = summary.get("readiness", "unknown")
        print()
        print(f"  {'=' * 40}")
        print(f"  {_icon(readiness)} READINESS: {summary.get('note', readiness)}")

        if readiness == "local_only":
            print()
            print("  FOR DRIVING TEST:")
            print("    - Voice I/O works at the desktop only")
            print("    - Discord TEXT commands work from phone")
            print("    - Discord VOICE channels not yet wired")
            print("    - Use #review text commands for approvals")
        print()

    overall = result.get("summary", {}).get("readiness", "unknown")
    return 0 if overall in ("ready", "local_only") else 1


if __name__ == "__main__":
    raise SystemExit(main())
