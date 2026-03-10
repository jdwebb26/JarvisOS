#!/usr/bin/env python3
import json, os, time

try:
    import requests
except Exception as e:
    print(json.dumps({"ok": False, "stage": "import_requests", "error": str(e)}, indent=2))
    raise SystemExit(1)

BASE = os.getenv("QWEN_AGENT_MODEL_SERVER", "http://172.23.64.1:1234/v1").rstrip("/")
MODEL = os.getenv("QWEN_AGENT_MODEL", "qwen/qwen3.5-9b")
API_KEY = os.getenv("QWEN_AGENT_API_KEY", "lm-studio")

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

out = {
    "ok": False,
    "base": BASE,
    "model": MODEL,
}

t0 = time.time()
try:
    r = requests.post(
        f"{BASE}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=(5, 25),
    )
    out["elapsed_sec"] = round(time.time() - t0, 3)
    out["status_code"] = r.status_code
    out["http_ok"] = r.ok
    out["head"] = r.text[:1200]

    content = ""
    finish_reason = None
    try:
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = str(msg.get("content") or "")
        finish_reason = choice.get("finish_reason")
    except Exception as e:
        out["json_parse_error"] = str(e)

    content_l = content.lower()
    thinking_detected = ("thinking process:" in content_l) or content_l.startswith("thinking process")
    exact_ok = content.strip() == "ok"

    out["assistant_content"] = content[:400]
    out["finish_reason"] = finish_reason
    out["thinking_detected"] = thinking_detected
    out["exact_ok"] = exact_ok
    out["usable_no_think"] = bool(r.ok and exact_ok and not thinking_detected)
    out["ok"] = out["usable_no_think"]
except Exception as e:
    out["elapsed_sec"] = round(time.time() - t0, 3)
    out["stage"] = "chat_completions"
    out["error"] = str(e)

print(json.dumps(out, indent=2))
