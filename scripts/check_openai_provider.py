#!/usr/bin/env python3
"""Quick status check for OpenAI provider wiring.

Usage:
    python3 scripts/check_openai_provider.py          # status only
    python3 scripts/check_openai_provider.py --ping    # status + live API ping

Exit codes:
    0 — provider is wired and (if --ping) API responded
    1 — provider is wired but OPENAI_API_KEY is not set
    2 — provider is wired but API ping failed
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check OpenAI provider wiring status.")
    parser.add_argument("--ping", action="store_true", help="Send a tiny test request to the API")
    args = parser.parse_args()

    # 1. Check adapter module loads
    try:
        from runtime.integrations.openai_executor import (
            OPENAI_BACKEND_ID,
            load_openai_config,
            openai_chat_completion,
            extract_content,
        )
        print(f"[OK] openai_executor module loaded (backend_id={OPENAI_BACKEND_ID})")
    except ImportError as exc:
        print(f"[FAIL] Cannot import openai_executor: {exc}")
        return 1

    # 2. Check backend dispatch registration
    try:
        from runtime.executor.backend_dispatch import has_backend_adapter
        if has_backend_adapter("openai_executor"):
            print("[OK] openai_executor registered in backend_dispatch")
        else:
            print("[WARN] openai_executor NOT registered in backend_dispatch")
    except ImportError:
        print("[WARN] Could not import backend_dispatch")

    # 3. Check BackendRuntime enum
    try:
        from runtime.core.models import BackendRuntime
        assert hasattr(BackendRuntime, "OPENAI_EXECUTOR")
        print(f"[OK] BackendRuntime.OPENAI_EXECUTOR = {BackendRuntime.OPENAI_EXECUTOR.value}")
    except (ImportError, AssertionError):
        print("[WARN] BackendRuntime.OPENAI_EXECUTOR not found in enum")

    # 4. Check API key presence
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("[INFO] OPENAI_API_KEY is not set — provider is scaffolded but inactive")
        print()
        print("To activate:")
        print("  1. Get an API key at https://platform.openai.com/api-keys")
        print("  2. Add billing at https://platform.openai.com/account/billing")
        print("     (ChatGPT subscription does NOT fund API usage)")
        print("  3. export OPENAI_API_KEY='sk-...'")
        print("  4. Re-run: python3 scripts/check_openai_provider.py --ping")
        return 1 if args.ping else 0

    masked = api_key[:7] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
    print(f"[OK] OPENAI_API_KEY is set ({masked})")

    # 5. Check config builds
    try:
        cfg = load_openai_config()
        print(f"[OK] Config: model={cfg['model']}, base_url={cfg['base_url']}")
    except Exception as exc:
        print(f"[FAIL] Config load error: {exc}")
        return 1

    # 6. Optional live ping
    if args.ping:
        print()
        print("Sending test request...")
        try:
            response = openai_chat_completion(
                [{"role": "user", "content": "Reply with exactly: OPENCLAW_OK"}],
                config=cfg,
                temperature=0.0,
                max_tokens=20,
            )
            content = extract_content(response)
            model_used = response.get("model", "unknown")
            usage = response.get("usage", {})
            print(f"[OK] API responded: model={model_used}, "
                  f"tokens={usage.get('total_tokens', '?')}, "
                  f"content={content!r}")
            return 0
        except Exception as exc:
            print(f"[FAIL] API ping failed: {exc}")
            return 2

    print()
    print("[OK] Provider fully wired. Run with --ping to test live API connectivity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
