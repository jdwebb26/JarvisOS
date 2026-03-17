#!/usr/bin/env python3
"""
operator_gateway_inbound_server.py
-----------------------------------
Minimal HTTP seam that accepts operator replies via the gateway API and
drops them as valid JSON files into state/operator_gateway_inbound_messages/.

The bridge cycle (operator_bridge_cycle.py --import-from-folder) picks up
any unprocessed file in that directory.

Usage:
    python3 scripts/operator_gateway_inbound_server.py \
        --root ~/.openclaw/workspace/jarvis-v5 \
        --port 18790 \
        --token-file ~/.openclaw/.env   # reads GATEWAY_TOKEN= line
        # or --token <raw-token>

Endpoint:
    POST /operator/inbound
    Authorization: Bearer <token>
    Content-Type: application/json

    Body (all fields except raw_text optional):
    {
        "raw_text":       "X1",           # required: compact reply code
        "source_channel": "api",          # default: "api"
        "source_user":    "operator",     # default: "operator"
        "apply":          true,           # default: true
        "dry_run":        false           # default: false
    }

    Response 200:
    {
        "ok": true,
        "msg_id": "gwapi_<hex>",
        "path":   "/abs/path/to/file.json"
    }
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_token(token: str | None, token_file: str | None) -> str:
    if token:
        return token.strip()
    if token_file:
        p = Path(token_file).expanduser()
        for line in p.read_text().splitlines():
            if line.startswith("GATEWAY_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"')
    # fall back to openclaw.json in parent directories
    for candidate in [
        Path.home() / ".openclaw" / "openclaw.json",
        Path("/home/rollan/.openclaw/openclaw.json"),
    ]:
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text())
                return data["gateway"]["auth"]["token"]
            except (KeyError, json.JSONDecodeError):
                pass
    raise SystemExit("No token found. Pass --token or --token-file.")


def _inbound_dir(root: Path) -> Path:
    d = root / "state" / "operator_gateway_inbound_messages"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# request handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    root: Path
    token: str

    # suppress default request logging; use stderr only on errors
    def log_message(self, fmt, *args):  # type: ignore[override]
        pass

    def _send_json(self, code: int, body: dict) -> None:
        payload = json.dumps(body, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _auth_ok(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return secrets.compare_digest(auth[7:].strip(), self.server.token)
        return False

    def do_POST(self) -> None:  # noqa: N802
        if not self._auth_ok():
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return

        if self.path.rstrip("/") != "/operator/inbound":
            self._send_json(404, {"ok": False, "error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) if length else b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "invalid JSON"})
            return

        raw_text = body.get("raw_text", "").strip()
        if not raw_text:
            self._send_json(400, {"ok": False, "error": "raw_text is required"})
            return

        msg_id = "gwapi_" + uuid.uuid4().hex[:12]
        outdir = _inbound_dir(self.server.root)
        dest = outdir / f"{msg_id}.json"

        payload: dict = {
            "source_kind": "gateway",
            "source_lane": "operator",
            "source_channel": body.get("source_channel", "api"),
            "source_message_id": msg_id,
            "source_user": body.get("source_user", "operator"),
            "raw_text": raw_text,
            "apply": bool(body.get("apply", True)),
            "dry_run": bool(body.get("dry_run", False)),
            "received_at": _now_iso(),
        }
        dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        print(f"[{_now_iso()}] inbound {msg_id} raw_text={raw_text!r} -> {dest}", flush=True)
        self._send_json(200, {"ok": True, "msg_id": msg_id, "path": str(dest)})

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/health":
            self._send_json(200, {"ok": True, "service": "operator_gateway_inbound"})
            return
        self._send_json(404, {"ok": False, "error": "not found"})


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Operator gateway inbound HTTP seam")
    ap.add_argument("--root", default="~/.openclaw/workspace/jarvis-v5",
                    help="Jarvis workspace root")
    ap.add_argument("--port", type=int, default=18790,
                    help="Port to listen on (default 18790)")
    ap.add_argument("--token", default=None, help="Bearer token (raw string)")
    ap.add_argument("--token-file", default=None, help="File containing GATEWAY_TOKEN=<value>")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    token = _load_token(args.token, args.token_file)

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    server.root = root          # type: ignore[attr-defined]
    server.token = token        # type: ignore[attr-defined]

    print(f"operator_gateway_inbound_server listening on 127.0.0.1:{args.port}", flush=True)
    print(f"  root : {root}", flush=True)
    print(f"  inbound dir: {_inbound_dir(root)}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped.")


if __name__ == "__main__":
    main()
