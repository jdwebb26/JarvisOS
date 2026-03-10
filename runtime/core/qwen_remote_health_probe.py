#!/usr/bin/env python3
import json, os, socket, time
from urllib.parse import urlparse

try:
    import requests
except Exception as e:
    print(json.dumps({"ok": False, "stage": "import_requests", "error": str(e)}, indent=2))
    raise SystemExit(1)

BASE = os.getenv("QWEN_AGENT_MODEL_SERVER", "http://172.23.64.1:1234/v1").rstrip("/")
MODEL = os.getenv("QWEN_AGENT_MODEL", "qwen/qwen3.5-9b")
API_KEY = os.getenv("QWEN_AGENT_API_KEY", "lm-studio")

parsed = urlparse(BASE)
host = parsed.hostname or ""
port = parsed.port or (443 if parsed.scheme == "https" else 80)

out = {
    "ok": False,
    "base": BASE,
    "model": MODEL,
    "host": host,
    "port": port,
}

t0 = time.time()
try:
    sock = socket.create_connection((host, port), timeout=5)
    sock.close()
    out["tcp_connect"] = "ok"
except Exception as e:
    out["stage"] = "tcp_connect"
    out["error"] = str(e)
    print(json.dumps(out, indent=2))
    raise SystemExit(1)

headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

try:
    r = requests.get(f"{BASE}/models", headers=headers, timeout=10)
    out["models_status_code"] = r.status_code
    out["models_ok"] = r.ok
    out["models_head"] = r.text[:500]
except Exception as e:
    out["stage"] = "http_models"
    out["error"] = str(e)
    print(json.dumps(out, indent=2))
    raise SystemExit(1)

payload = {
    "model": MODEL,
    "messages": [
        {"role": "system", "content": "/no_think reply with exactly: ok"},
        {"role": "user", "content": "Reply with exactly: ok"},
    ],
    "temperature": 0,
    "max_tokens": 8,
    "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
}

try:
    r2 = requests.post(
        f"{BASE}/chat/completions",
        headers=headers,
        json=payload,
        timeout=(5, 25),
    )
    out["chat_status_code"] = r2.status_code
    out["chat_http_ok"] = r2.ok
    out["chat_head"] = r2.text[:800]

    content = ""
    finish_reason = None
    try:
        data = r2.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = str(msg.get("content") or "")
        finish_reason = choice.get("finish_reason")
    except Exception as e:
        out["chat_json_parse_error"] = str(e)

    content_l = content.lower()
    thinking_detected = ("thinking process:" in content_l) or content_l.startswith("thinking process")
    exact_ok = content.strip() == "ok"

    out["assistant_content"] = content[:300]
    out["finish_reason"] = finish_reason
    out["thinking_detected"] = thinking_detected
    out["exact_ok"] = exact_ok
    out["usable_no_think"] = bool(r2.ok and exact_ok and not thinking_detected)
    out["transport_healthy"] = bool(out.get("tcp_connect") == "ok" and out.get("models_ok") and r2.ok)
    out["ok"] = out["usable_no_think"]
    out["elapsed_sec"] = round(time.time() - t0, 3)
except Exception as e:
    out["stage"] = "chat_completions"
    out["elapsed_sec"] = round(time.time() - t0, 3)
    out["error"] = str(e)

print(json.dumps(out, indent=2))
