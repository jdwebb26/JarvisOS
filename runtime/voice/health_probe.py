#!/usr/bin/env python3
"""health_probe.py — Health and readiness checks for the Cadence voice stack.

Usage
-----
    # All components
    python3 runtime/voice/health_probe.py

    # Specific component
    python3 runtime/voice/health_probe.py --wake
    python3 runtime/voice/health_probe.py --vad
    python3 runtime/voice/health_probe.py --stt
    python3 runtime/voice/health_probe.py --piper
    python3 runtime/voice/health_probe.py --coqui

    # JSON output
    python3 runtime/voice/health_probe.py --json

Component status values
-----------------------
    ok        — component is ready
    error     — component failed / not installed
    warn      — component available but degraded or missing optional dep
    skip      — probe skipped (dependency not present)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Individual probes
# ---------------------------------------------------------------------------

def probe_parecord() -> dict:
    """Check parecord (PulseAudio capture) availability."""
    if shutil.which("parecord"):
        return {"status": "ok", "note": "parecord found in PATH"}
    return {"status": "error", "note": "parecord not found — install pulseaudio-utils"}


def probe_pulse_sources() -> dict:
    """Check available PulseAudio sources."""
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources", "short"], text=True, timeout=5
        )
        names = [ln.split("\t")[1] for ln in out.strip().splitlines() if "\t" in ln]
        has_rdp = any(n.lower() == "rdpsource" for n in names)
        return {
            "status": "ok",
            "sources": names,
            "rdpsource": has_rdp,
            "note": "RDPSource present" if has_rdp else "RDPSource NOT found (WSL mic passthrough unavailable)",
        }
    except FileNotFoundError:
        return {"status": "error", "note": "pactl not found"}
    except Exception as exc:
        return {"status": "error", "note": str(exc)}


def probe_wake_stack() -> dict:
    """Probe openWakeWord via .venv-voice subprocess."""
    from runtime.voice.voice_config import VENV_VOICE
    py = VENV_VOICE / "bin" / "python"
    if not py.exists():
        return {"status": "error", "note": f"venv-voice not found: {VENV_VOICE}"}

    script = ROOT / "runtime" / "voice" / "live_listener.py"
    try:
        result = subprocess.run(
            [str(py), str(script), "--probe"],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT),
        )
        if result.returncode != 0:
            return {"status": "error", "note": result.stderr[:300]}
        try:
            data = json.loads(result.stdout)
        except Exception:
            data = {"raw": result.stdout[:200]}

        oww_ok = "error" not in data.get("openwakeword", "error")
        model_ok = "ok" in data.get("oww_model", "")
        return {
            "status": "ok" if (oww_ok and model_ok) else "warn",
            "detail": data,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "note": "probe timed out"}
    except Exception as exc:
        return {"status": "error", "note": str(exc)}


def probe_vad() -> dict:
    """Probe Silero VAD via .venv-voice subprocess."""
    from runtime.voice.voice_config import VENV_VOICE
    py = VENV_VOICE / "bin" / "python"
    if not py.exists():
        return {"status": "error", "note": f"venv-voice not found: {VENV_VOICE}"}

    script = ROOT / "runtime" / "voice" / "live_listener.py"
    try:
        result = subprocess.run(
            [str(py), str(script), "--probe"],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT),
        )
        if result.returncode != 0:
            return {"status": "error", "note": result.stderr[:300]}
        try:
            data = json.loads(result.stdout)
        except Exception:
            return {"status": "warn", "note": "could not parse probe output"}
        vad_val = data.get("silero_vad", "")
        ok = "ok" in vad_val
        return {
            "status": "ok" if ok else "warn",
            "silero_vad": vad_val,
        }
    except Exception as exc:
        return {"status": "error", "note": str(exc)}


def probe_stt() -> dict:
    """Probe faster-whisper via .venv-voice subprocess."""
    from runtime.voice.voice_config import VENV_VOICE, FASTER_WHISPER_MODEL
    py = VENV_VOICE / "bin" / "python"
    if not py.exists():
        return {"status": "error", "note": f"venv-voice not found: {VENV_VOICE}"}

    script = ROOT / "runtime" / "voice" / "live_listener.py"
    try:
        result = subprocess.run(
            [str(py), str(script), "--probe"],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT),
        )
        if result.returncode != 0:
            return {"status": "error", "note": result.stderr[:300]}
        try:
            data = json.loads(result.stdout)
        except Exception:
            return {"status": "warn", "note": "could not parse probe output"}
        fw_val = data.get("faster_whisper", "")
        ok = "ok" in fw_val
        return {
            "status": "ok" if ok else "error",
            "faster_whisper": fw_val,
            "model": FASTER_WHISPER_MODEL,
        }
    except Exception as exc:
        return {"status": "error", "note": str(exc)}


def probe_piper() -> dict:
    """Probe Piper TTS via .venv-voice subprocess."""
    from runtime.voice.voice_config import VENV_VOICE
    py = VENV_VOICE / "bin" / "python"
    if not py.exists():
        return {"status": "error", "note": f"venv-voice not found: {VENV_VOICE}"}

    script = ROOT / "runtime" / "voice" / "tts_piper.py"
    try:
        result = subprocess.run(
            [str(py), str(script), "--probe"],
            capture_output=True, text=True, timeout=20, cwd=str(ROOT),
        )
        if result.returncode != 0:
            return {"status": "error", "note": result.stderr[:300]}
        try:
            data = json.loads(result.stdout)
            return data
        except Exception:
            return {"status": "warn", "raw": result.stdout[:200]}
    except subprocess.TimeoutExpired:
        return {"status": "error", "note": "probe timed out"}
    except Exception as exc:
        return {"status": "error", "note": str(exc)}


def probe_coqui() -> dict:
    """Probe Coqui TTS via .venv-coqui subprocess."""
    from runtime.voice.voice_config import VENV_COQUI
    py = VENV_COQUI / "bin" / "python"
    if not py.exists():
        return {"status": "error", "note": f"venv-coqui not found: {VENV_COQUI}"}

    script = ROOT / "runtime" / "voice" / "tts_coqui_render.py"
    try:
        result = subprocess.run(
            [str(py), str(script), "--probe"],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT),
        )
        if result.returncode != 0:
            return {"status": "error", "note": result.stderr[:300]}
        try:
            data = json.loads(result.stdout)
            return data
        except Exception:
            return {"status": "warn", "raw": result.stdout[:200]}
    except subprocess.TimeoutExpired:
        return {"status": "error", "note": "probe timed out"}
    except Exception as exc:
        return {"status": "error", "note": str(exc)}


def probe_all() -> dict:
    """Run all probes and return combined status."""
    from runtime.voice.voice_config import DEFAULT_TTS_ENGINE, LISTENER_MODE

    results = {
        "parecord":        probe_parecord(),
        "pulse_sources":   probe_pulse_sources(),
        "wake_stack":      probe_wake_stack(),
        "vad":             probe_vad(),
        "stt":             probe_stt(),
        "piper":           probe_piper(),
        "coqui":           probe_coqui(),
        "config": {
            "listener_mode":    LISTENER_MODE,
            "default_tts":      DEFAULT_TTS_ENGINE,
        },
    }

    failed = [k for k, v in results.items() if isinstance(v, dict) and v.get("status") == "error"]
    warned = [k for k, v in results.items() if isinstance(v, dict) and v.get("status") == "warn"]

    results["summary"] = {
        "failed":  failed,
        "warned":  warned,
        "overall": "error" if failed else ("warn" if warned else "ok"),
    }
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cadence voice stack health probe"
    )
    parser.add_argument("--wake",   action="store_true", help="Probe wake stack only")
    parser.add_argument("--vad",    action="store_true", help="Probe VAD only")
    parser.add_argument("--stt",    action="store_true", help="Probe STT only")
    parser.add_argument("--piper",  action="store_true", help="Probe Piper only")
    parser.add_argument("--coqui",  action="store_true", help="Probe Coqui only")
    parser.add_argument("--pulse",  action="store_true", help="Probe PulseAudio only")
    parser.add_argument("--json",   action="store_true", dest="json_out",
                        help="JSON output")
    args = parser.parse_args()

    if args.wake:
        result = probe_wake_stack()
    elif args.vad:
        result = probe_vad()
    elif args.stt:
        result = probe_stt()
    elif args.piper:
        result = probe_piper()
    elif args.coqui:
        result = probe_coqui()
    elif args.pulse:
        result = probe_pulse_sources()
    else:
        result = probe_all()

    if args.json_out:
        print(json.dumps(result, indent=2))
    else:
        _print_result(result)

    if isinstance(result, dict):
        summary = result.get("summary", result)
        overall = summary.get("overall", summary.get("status", "ok"))
        return 0 if overall in ("ok", "warn") else 1
    return 0


def _print_result(result: dict, indent: int = 0) -> None:
    pad = "  " * indent
    for k, v in result.items():
        if isinstance(v, dict):
            status = v.get("status", "")
            icon = {"ok": "✓", "error": "✗", "warn": "⚠", "skip": "·"}.get(status, " ")
            note = v.get("note", v.get("reason", ""))
            print(f"{pad}{icon} {k}: {status}  {note}")
            # Print sub-details at deeper indent
            for sk, sv in v.items():
                if sk not in ("status", "note", "reason") and not isinstance(sv, dict):
                    print(f"{pad}    {sk}: {sv}")
        else:
            print(f"{pad}  {k}: {v}")


if __name__ == "__main__":
    raise SystemExit(main())
