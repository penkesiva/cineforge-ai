"""Opaque cursors for discovery pages. Clients cannot mint the upstream page token."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any


class CursorError(ValueError):
    pass


def sign(payload: dict[str, Any], secret: str) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    digest = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{digest}"


def verify(cursor: str, secret: str) -> dict[str, Any]:
    try:
        body, digest = cursor.split(".", 1)
    except ValueError as exc:
        raise CursorError("cursor is not valid") from exc
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, digest):
        raise CursorError("cursor is not valid")
    pad = "=" * (-len(body) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
    except (ValueError, json.JSONDecodeError) as exc:
        raise CursorError("cursor is not valid") from exc
    if not isinstance(payload, dict) or "run" not in payload:
        raise CursorError("cursor is not valid")
    return payload
