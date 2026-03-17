#!/usr/bin/env python3
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import BrowserActionRequestRecord, BrowserActionResultRecord, new_id, now_iso

_DEFAULT_BASE_URL = "http://127.0.0.1:9867"
_CONFIG_PATH = Path.home() / ".pinchtab" / "config.json"


def _load_token() -> str:
    if _CONFIG_PATH.exists():
        try:
            cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            token = cfg.get("server", {}).get("token", "")
            if token:
                return token
        except Exception:
            pass
    return ""


def _api(
    method: str,
    path: str,
    *,
    body: Optional[dict[str, Any]] = None,
    token: str = "",
    base_url: str = _DEFAULT_BASE_URL,
    timeout: int = 30,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace") if exc.fp else ""
        return {"_http_error": exc.code, "_body": raw}
    except Exception as exc:
        return {"_error": str(exc)}


_NAVIGATE_ACTIONS = {"navigate", "navigate_allowlisted_page", "open_tab", "goto"}
_SNAPSHOT_ACTIONS = {"snapshot", "inspect_page", "accessibility_tree"}
_TEXT_ACTIONS = {"text", "extract_text", "read_page"}
_SCREENSHOT_ACTIONS = {"screenshot", "capture"}
_CLICK_ACTIONS = {"click", "tap"}
_FILL_ACTIONS = {"fill", "type_into", "input"}


class PinchTabBackend:
    def __init__(self, config: Optional[dict[str, Any]] = None):
        cfg = dict(config or {})
        self.base_url: str = cfg.get("base_url") or _DEFAULT_BASE_URL
        self._token: str = cfg.get("token") or _load_token()

    def health_check(self) -> dict[str, Any]:
        result = _api("GET", "/health", token=self._token, base_url=self.base_url, timeout=5)
        ok = result.get("status") == "ok" and "_error" not in result and "_http_error" not in result
        return {
            "backend": "pinchtab",
            "connected": ok,
            "ok": ok,
            "status": result.get("status", "unreachable"),
            "version": result.get("version"),
            "uptime": result.get("uptime"),
            "instances": result.get("instances"),
            "default_instance": result.get("defaultInstance"),
            "reason": None if ok else result.get("_error") or result.get("_body") or "health_check_failed",
            "config": {"base_url": self.base_url},
        }

    def execute_action(self, request: BrowserActionRequestRecord) -> BrowserActionResultRecord:
        action_type = (request.action_type or "snapshot").lower()
        target_url = request.target_url or ""
        target_selector = request.target_selector or ""
        params = dict(request.action_params or {})

        try:
            outcome, snapshot_refs, error = self._dispatch(action_type, target_url, target_selector, params)
            status = "error" if error else "ok"
        except Exception as exc:
            outcome = f"PinchTab backend exception: {exc}"
            snapshot_refs = {}
            error = str(exc)
            status = "error"

        return BrowserActionResultRecord(
            result_id=new_id("bres"),
            request_id=request.request_id,
            task_id=request.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=request.actor,
            lane=request.lane,
            status=status,
            outcome_summary=outcome,
            snapshot_refs=snapshot_refs,
            trace_refs={},
            error=error,
        )

    def _get_default_instance(self) -> Optional[str]:
        result = _api("GET", "/health", token=self._token, base_url=self.base_url, timeout=5)
        inst = result.get("defaultInstance", {})
        return inst.get("id") if isinstance(inst, dict) else None

    def _open_tab(self, inst_id: str, url: str) -> dict[str, Any]:
        return _api(
            "POST",
            f"/instances/{inst_id}/tabs/open",
            body={"url": url},
            token=self._token,
            base_url=self.base_url,
        )

    def _snap(self, tab_id: str) -> dict[str, Any]:
        result = _api("GET", f"/tabs/{tab_id}/snapshot", token=self._token, base_url=self.base_url)
        return result if isinstance(result, dict) else {"count": 0, "nodes": []}

    def _dispatch(
        self,
        action_type: str,
        target_url: str,
        target_selector: str,
        params: dict[str, Any],
    ) -> tuple[str, dict[str, Any], Optional[str]]:
        inst_id = params.get("instance_id") or self._get_default_instance()
        if not inst_id:
            return "no PinchTab instance available", {}, "no_instance"

        if action_type in _NAVIGATE_ACTIONS:
            if not target_url:
                return "navigate action requires a target_url", {}, "missing_target_url"
            tab = self._open_tab(inst_id, target_url)
            if "_error" in tab or "_http_error" in tab:
                return f"tab open failed: {tab}", {}, "tab_open_failed"
            tab_id = tab.get("tabId", "")
            time.sleep(1)
            snapshot = self._snap(tab_id)
            refs = {"tab_id": tab_id, "snapshot_node_count": snapshot.get("count", 0)}
            summary = f"Navigated to {target_url}; tab {tab_id}; snapshot nodes={snapshot.get('count', 0)}"
            return summary, refs, None

        if action_type in _SNAPSHOT_ACTIONS:
            tab_id = params.get("tab_id", "")
            if not tab_id and target_url:
                tab = self._open_tab(inst_id, target_url)
                if "_error" in tab or "_http_error" in tab:
                    return f"tab open failed: {tab}", {}, "tab_open_failed"
                tab_id = tab.get("tabId", "")
                time.sleep(1)
            if not tab_id:
                tabs_result = _api("GET", f"/instances/{inst_id}/tabs", token=self._token, base_url=self.base_url)
                tabs = tabs_result if isinstance(tabs_result, list) else tabs_result.get("tabs", [])
                if tabs:
                    tab_id = tabs[0].get("id") or tabs[0].get("tabId", "")
            if not tab_id:
                return "no tab available for snapshot", {}, "no_tab"
            snapshot = self._snap(tab_id)
            node_count = snapshot.get("count", 0)
            nodes_preview = json.dumps(snapshot.get("nodes", [])[:5])
            summary = f"Snapshot of tab {tab_id}: {node_count} nodes. Preview: {nodes_preview[:300]}"
            return summary, {"tab_id": tab_id, "node_count": node_count}, None

        if action_type in _TEXT_ACTIONS:
            tab_id = params.get("tab_id", "")
            if not tab_id and target_url:
                tab = self._open_tab(inst_id, target_url)
                tab_id = tab.get("tabId", "")
                time.sleep(1)
            if not tab_id:
                return "no tab available for text extraction", {}, "no_tab"
            text_result = _api("GET", f"/tabs/{tab_id}/text", token=self._token, base_url=self.base_url)
            if "_error" in text_result or "_http_error" in text_result:
                return f"text extraction failed: {text_result}", {}, "text_extract_failed"
            text = str(text_result.get("text", ""))[:2000]
            summary = f"Extracted {len(text)} chars from tab {tab_id}: {text[:200]}"
            return summary, {"tab_id": tab_id, "chars": len(text)}, None

        if action_type in _SCREENSHOT_ACTIONS:
            tab_id = params.get("tab_id", "")
            if not tab_id and target_url:
                tab = self._open_tab(inst_id, target_url)
                tab_id = tab.get("tabId", "")
                time.sleep(1)
            if not tab_id:
                return "no tab available for screenshot", {}, "no_tab"
            shot_result = _api("GET", f"/tabs/{tab_id}/screenshot", token=self._token, base_url=self.base_url)
            if "_error" in shot_result or "_http_error" in shot_result:
                return f"screenshot failed: {shot_result}", {}, "screenshot_failed"
            summary = f"Screenshot taken for tab {tab_id}"
            return summary, {"tab_id": tab_id}, None

        if action_type in _CLICK_ACTIONS:
            tab_id = params.get("tab_id", "")
            if not tab_id:
                return "click action requires tab_id in action_params", {}, "missing_tab_id"
            selector = target_selector or params.get("selector", "")
            if not selector:
                return "click action requires target_selector", {}, "missing_selector"
            click_result = _api(
                "POST",
                f"/tabs/{tab_id}/action",
                body={"action": "click", "selector": selector},
                token=self._token,
                base_url=self.base_url,
            )
            if "_error" in click_result or "_http_error" in click_result:
                return f"click failed: {click_result}", {}, "click_failed"
            return f"Clicked '{selector}' on tab {tab_id}", {"tab_id": tab_id, "selector": selector}, None

        if action_type in _FILL_ACTIONS:
            tab_id = params.get("tab_id", "")
            if not tab_id:
                return "fill action requires tab_id in action_params", {}, "missing_tab_id"
            selector = target_selector or params.get("selector", "")
            value = params.get("value", "")
            if not selector:
                return "fill action requires target_selector", {}, "missing_selector"
            fill_result = _api(
                "POST",
                f"/tabs/{tab_id}/action",
                body={"action": "fill", "selector": selector, "value": value},
                token=self._token,
                base_url=self.base_url,
            )
            if "_error" in fill_result or "_http_error" in fill_result:
                return f"fill failed: {fill_result}", {}, "fill_failed"
            return f"Filled '{selector}' on tab {tab_id}", {"tab_id": tab_id, "selector": selector}, None

        # fallback: snapshot whatever is open
        tabs_result = _api("GET", f"/instances/{inst_id}/tabs", token=self._token, base_url=self.base_url)
        tabs = tabs_result if isinstance(tabs_result, list) else tabs_result.get("tabs", [])
        if tabs:
            tab_id = tabs[0].get("id") or tabs[0].get("tabId", "")
            snapshot = self._snap(tab_id)
            summary = (
                f"Action type '{action_type}' not directly mapped; "
                f"returned snapshot of tab {tab_id} ({snapshot.get('count', 0)} nodes)"
            )
            return summary, {"tab_id": tab_id, "action_type_received": action_type}, None

        return f"action_type '{action_type}' not handled and no tabs available", {}, "unhandled_action"
