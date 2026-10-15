"""Minimal MCP client over streamable HTTP (JSON-RPC 2.0), enough to call remote tools.

``initialize`` stores the ``Mcp-Session-Id`` header; ``call_tool`` posts ``tools/call``
and accepts either an ``application/json`` reply or a ``text/event-stream`` whose last
message with our id carries the result. A 401 asks ``token_supplier`` for a fresh token
once, then raises ``ProviderAuthError``. Tokens never appear in errors or logs.
"""

from __future__ import annotations

import itertools
import json
import threading
from collections.abc import Callable
from typing import Any

import httpx

from cineforge.contracts.providers import ProviderError
from cineforge.providers.http import MAX_ERROR_DETAIL, is_retryable_status

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "cineforge", "version": "0.3"}


class ProviderAuthError(ProviderError):
    """Not signed in, or the token was refused (non-retryable)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class ToolResult:
    """``tools/call`` result: content items plus optional structured content."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.content: list[dict[str, Any]] = list(raw.get("content") or [])
        self.structured: Any = raw.get("structuredContent")
        self.is_error = bool(raw.get("isError"))

    @property
    def text(self) -> str:
        return "\n".join(str(c.get("text", "")) for c in self.content if c.get("type") == "text")

    def links(self) -> list[dict[str, Any]]:
        return [c for c in self.content if c.get("type") == "resource_link" and c.get("uri")]


TokenSupplier = Callable[[bool], str | None]
"""``token_supplier(force_refresh)`` returns a bearer token or None when signed out."""


class McpClient:
    def __init__(self, http: httpx.Client, url: str, token_supplier: TokenSupplier) -> None:
        self.http = http
        self.url = url
        self.token_supplier = token_supplier
        self.session_id: str | None = None
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ public
    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        with self._lock:
            if self.session_id is None:
                self._initialize()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        return ToolResult(result)

    # ------------------------------------------------------------------ protocol
    def _initialize(self) -> None:
        self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = next(self._ids)
        body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        message = self._post(body, expect_reply=True, request_id=request_id)
        if "error" in message:
            err = message["error"] or {}
            detail = str(err.get("message", "unknown error"))[:MAX_ERROR_DETAIL]
            raise ProviderError(f"mcp {method} failed: {detail}", retryable=False)
        return dict(message.get("result") or {})

    def _post(
        self, body: dict[str, Any], *, expect_reply: bool, request_id: int | None = None
    ) -> dict[str, Any]:
        response = self._send(body, force_refresh=False)
        if response.status_code == 401:
            response = self._send(body, force_refresh=True)
            if response.status_code == 401:
                raise ProviderAuthError("higgsfield: sign-in expired or refused; reconnect")
        if response.status_code == 404 and self.session_id and body.get("method") != "initialize":
            self.session_id = None  # session expired server-side: start a new one
            self._initialize()
            response = self._send(body, force_refresh=False)
        if response.status_code >= 400:
            raise ProviderError(
                f"mcp HTTP {response.status_code}: {response.text[:MAX_ERROR_DETAIL]}",
                retryable=is_retryable_status(response.status_code),
            )
        session = response.headers.get("mcp-session-id")
        if session:
            self.session_id = session
        if not expect_reply:
            return {}
        return _parse_reply(response, request_id)

    def _send(self, body: dict[str, Any], *, force_refresh: bool) -> httpx.Response:
        token = self.token_supplier(force_refresh)
        if not token:
            raise ProviderAuthError("higgsfield: not connected; sign in on the Sources page")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        try:
            return self.http.post(self.url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderError(f"mcp timeout: {type(exc).__name__}", retryable=True) from None
        except httpx.HTTPError as exc:
            detail = f"mcp transport error: {type(exc).__name__}"
            raise ProviderError(detail, retryable=True) from None


def _parse_reply(response: httpx.Response, request_id: int | None) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        found: dict[str, Any] | None = None
        for message in _sse_messages(response.text):
            if message.get("id") == request_id and ("result" in message or "error" in message):
                found = message
        if found is None:
            raise ProviderError("mcp: event stream ended without a result", retryable=True)
        return found
    try:
        data = response.json()
    except ValueError:
        raise ProviderError("mcp: reply is not JSON", retryable=False) from None
    if isinstance(data, list):
        data = next((m for m in data if m.get("id") == request_id), {})
    if not isinstance(data, dict):
        raise ProviderError("mcp: unexpected reply shape", retryable=False)
    return data


def _sse_messages(text: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    data_lines: list[str] = []
    for line in [*text.splitlines(), ""]:
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif not line.strip() and data_lines:
            try:
                parsed = json.loads("\n".join(data_lines))
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                messages.append(parsed)
            data_lines = []
    return messages
