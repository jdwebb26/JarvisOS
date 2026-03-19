#!/usr/bin/env python3
"""Pulse TradingView Webhook Receiver.

Small, boring HTTP receiver that accepts TradingView webhook POSTs
and normalizes them into Pulse alert ingestion.

Auth: shared secret in PULSE_WEBHOOK_SECRET env var or secrets.env.
TradingView sends it as ?secret=<value> query param or X-Pulse-Secret header.

Usage:
    python3 scripts/pulse_webhook.py                  # default port 18795
    python3 scripts/pulse_webhook.py --port 18795
    PULSE_WEBHOOK_SECRET=mysecret python3 scripts/pulse_webhook.py

TradingView alert message format (any of these work):
    - Plain text: "18450"
    - Text with note: "18450 liquidity sweep"
    - JSON: {"level": 18450, "note": "liquidity sweep", "symbol": "NQ"}
    - JSON with tags: {"text": "NQ reclaim at 18500", "direction": "bullish"}
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_secret() -> str:
    """Load webhook secret from env or secrets.env. Returns '' if not set."""
    secret = os.environ.get("PULSE_WEBHOOK_SECRET", "")
    if secret:
        return secret
    secrets_path = Path.home() / ".openclaw" / "secrets.env"
    if secrets_path.exists():
        for line in secrets_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("PULSE_WEBHOOK_SECRET="):
                return line.split("=", 1)[1].strip()
    return ""


def _raw_log_dir() -> Path:
    d = ROOT / "state" / "pulse_raw"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_raw(payload: bytes, source_ip: str):
    """Persist raw webhook payload for audit."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = _raw_log_dir() / f"tv_{ts}.json"
    try:
        body = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        body = {"raw_text": payload.decode("utf-8", errors="replace")}
    record = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "source_ip": source_ip,
        "payload": body,
    }
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def normalize_tv_payload(body: bytes) -> dict:
    """Normalize a TradingView webhook payload into Pulse alert kwargs.

    Accepts:
      - Plain text: "18450" or "18450 liquidity sweep"
      - JSON: {"level": 18450, "note": "...", "symbol": "NQ", "direction": "bullish"}
      - JSON with "text" field: {"text": "NQ reclaim at 18500"}

    Returns dict suitable for ingest_alert(): {text, symbol, level, direction}
    """
    text_str = body.decode("utf-8", errors="replace").strip()

    # Try JSON first
    try:
        data = json.loads(text_str)
        if isinstance(data, dict):
            return {
                "text": data.get("text", data.get("note", data.get("message", ""))),
                "symbol": data.get("symbol", data.get("ticker", "NQ")),
                "level": data.get("level", data.get("price", None)),
                "direction": data.get("direction", data.get("bias", None)),
            }
    except (json.JSONDecodeError, ValueError):
        pass

    # Plain text
    return {
        "text": text_str,
        "symbol": "NQ",
        "level": None,
        "direction": None,
    }


class PulseWebhookHandler(BaseHTTPRequestHandler):
    """Handle TradingView webhook POSTs."""

    def do_POST(self):
        # Read body
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 10_000:
            self._respond(413, {"error": "payload too large"})
            return
        body = self.rfile.read(content_length) if content_length > 0 else b""

        # Auth check
        secret = _load_secret()
        if secret:
            # Check query param or header
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            provided = (
                qs.get("secret", [None])[0]
                or self.headers.get("X-Pulse-Secret", "")
            )
            if provided != secret:
                self._respond(401, {"error": "invalid secret"})
                return

        # Save raw for audit
        source_ip = self.client_address[0] if self.client_address else "unknown"
        _save_raw(body, source_ip)

        # Normalize and ingest
        try:
            from workspace.quant.pulse.alert_lane import ingest_alert
            kwargs = normalize_tv_payload(body)
            pkt, parsed = ingest_alert(
                ROOT,
                text=kwargs.get("text", ""),
                symbol=kwargs.get("symbol", "NQ"),
                level=kwargs.get("level"),
                direction=kwargs.get("direction"),
                source="tradingview",
            )
            self._respond(200, {
                "status": "ok",
                "packet_id": pkt.packet_id,
                "level": parsed.get("level"),
                "tags": parsed.get("tags", []),
            })
        except Exception as e:
            self._respond(500, {"error": str(e)})

    def do_GET(self):
        self._respond(200, {"status": "pulse_webhook_alive"})

    def _respond(self, code: int, data: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, fmt, *args):
        # Quieter logging
        pass


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Pulse TradingView Webhook Receiver")
    parser.add_argument("--port", type=int, default=18795)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    secret = _load_secret()
    print(f"Pulse webhook receiver starting on {args.host}:{args.port}")
    print(f"  Auth: {'shared secret configured' if secret else 'NO SECRET (open)'}")
    print(f"  Raw log: {_raw_log_dir()}")

    server = HTTPServer((args.host, args.port), PulseWebhookHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
