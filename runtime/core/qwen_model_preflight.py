#!/usr/bin/env python3
import argparse
import json
import os
from datetime import datetime

try:
    import requests
except Exception:
    requests = None


MODEL_SERVER = os.getenv("QWEN_AGENT_MODEL_SERVER", "http://172.23.64.1:1234/v1").rstrip("/")
MODEL_NAME = os.getenv("QWEN_AGENT_MODEL", "qwen/qwen3.5-9b")
API_KEY = os.getenv("QWEN_AGENT_API_KEY", "lm-studio")


def now_iso() -> str:
    return datetime.now().isoformat()


def sanitize_preview(text: str, limit: int = 240) -> tuple[str, bool]:
    cleaned = (text or "").replace(API_KEY, "[redacted-api-key]") if API_KEY else (text or "")
    cleaned = " ".join(cleaned.split()).strip()
    if not cleaned:
        return "", False
    return cleaned[:limit], len(cleaned) > limit


def detect_contamination(text: str) -> bool:
    lowered = (text or "").strip().lower()
    return (
        lowered.startswith(("the user wants", "here is", "i will", "we need to"))
        or "thinking process:" in lowered
        or "<think>" in lowered
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe Qwen model server reachability and model availability.")
    ap.add_argument("--probe-completion", action="store_true", help="Run a tiny completion probe.")
    ap.add_argument("--timeout-sec", type=float, default=15.0, help="HTTP timeout.")
    ap.add_argument("--json", action="store_true", help="Print JSON.")
    args = ap.parse_args()

    result = {
        "ok": False,
        "timestamp": now_iso(),
        "model_server": MODEL_SERVER,
        "requested_model": MODEL_NAME,
        "requests_installed": requests is not None,
        "server_reachable": False,
        "models_endpoint_ok": False,
        "requested_model_available": False,
        "available_models": [],
        "completion_probe_ran": bool(args.probe_completion),
        "completion_probe_ok": None,
        "completion_probe_contaminated": None,
        "completion_preview": "",
        "completion_preview_truncated": False,
        "error": "",
    }

    if requests is None:
        result["error"] = "requests not installed"
    else:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        }
        try:
            models_resp = requests.get(f"{MODEL_SERVER}/models", headers=headers, timeout=args.timeout_sec)
            models_resp.raise_for_status()
            result["server_reachable"] = True
            result["models_endpoint_ok"] = True
            models_payload = models_resp.json()
            models = [item.get("id", "") for item in models_payload.get("data", []) if item.get("id")]
            result["available_models"] = models
            result["requested_model_available"] = MODEL_NAME in models
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"

        if args.probe_completion and result["models_endpoint_ok"] and result["requested_model_available"]:
            payload = {
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": "/no_think Return only the word pong."},
                    {"role": "user", "content": "Reply with pong only."},
                ],
                "temperature": 0.0,
                "max_tokens": 16,
                "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
            }
            try:
                resp = requests.post(
                    f"{MODEL_SERVER}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=args.timeout_sec,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                preview, truncated = sanitize_preview(content)
                result["completion_preview"] = preview
                result["completion_preview_truncated"] = truncated
                result["completion_probe_contaminated"] = detect_contamination(content)
                result["completion_probe_ok"] = not result["completion_probe_contaminated"]
            except Exception as exc:
                result["completion_probe_ok"] = False
                result["error"] = f"{type(exc).__name__}: {exc}"

    result["ok"] = (
        result["requests_installed"]
        and result["server_reachable"]
        and result["models_endpoint_ok"]
        and result["requested_model_available"]
        and (result["completion_probe_ok"] is not False)
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
