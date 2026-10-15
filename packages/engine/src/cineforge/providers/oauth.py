"""OAuth 2.1 sign-in for MCP providers (Higgsfield): discovery, dynamic client
registration, PKCE (S256), refresh. Everything lives in the tenant's ``SecretStore``:

- ``<provider>``          token set ``{access_token, refresh_token, expires_at, ...}``;
                          its presence makes the provider READY (registry key lookup)
- ``<provider>_client``   registered client ``{client_id, token_endpoint, ...}``
- ``<provider>_pending``  one in-flight sign-in ``{state, verifier, created_at}``

Tokens are never logged or returned by the API.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets as pysecrets
import threading
import time
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from cineforge.contracts.providers import SecretStore

log = logging.getLogger(__name__)

PENDING_TTL_SEC = 600
REFRESH_MARGIN_SEC = 60
SCOPES = "openid email offline_access"


class OAuthError(RuntimeError):
    """Sign-in failed or is not possible (bad state, discovery or token error)."""


def pkce_pair() -> tuple[str, str]:
    verifier = pysecrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class McpOAuth:
    def __init__(
        self,
        *,
        provider: str,
        resource_url: str,
        redirect_uri: str,
        secrets: SecretStore,
        http: httpx.Client,
        client_name: str = "CineForge AI (local)",
        clock=time.time,
    ) -> None:
        self.provider = provider
        self.resource_url = resource_url
        self.redirect_uri = redirect_uri
        self.secrets = secrets
        self.http = http
        self.client_name = client_name
        self.clock = clock
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ storage
    def _get(self, tenant_id: str, suffix: str = "") -> dict[str, Any] | None:
        raw = self.secrets.get(tenant_id, self.provider + suffix)
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def _put(self, tenant_id: str, suffix: str, value: dict[str, Any]) -> None:
        self.secrets.put(tenant_id, self.provider + suffix, json.dumps(value))

    def connected(self, tenant_id: str) -> bool:
        tokens = self._get(tenant_id)
        return bool(tokens and tokens.get("access_token"))

    # ------------------------------------------------------------------ discovery
    def _metadata(self) -> dict[str, Any]:
        parts = urlsplit(self.resource_url)
        base = f"{parts.scheme}://{parts.netloc}"
        resource = self._get_json(f"{base}/.well-known/oauth-protected-resource{parts.path}")
        servers = resource.get("authorization_servers") or []
        if not servers:
            raise OAuthError("resource metadata lists no authorization server")
        for server in servers:
            try:
                base_url = server.rstrip("/")
                meta = self._get_json(f"{base_url}/.well-known/oauth-authorization-server")
            except OAuthError:
                continue
            if meta.get("authorization_endpoint") and meta.get("token_endpoint"):
                return meta
        raise OAuthError("no authorization server supports the authorization-code flow")

    def _get_json(self, url: str) -> dict[str, Any]:
        try:
            response = self.http.get(url)
        except httpx.HTTPError as exc:
            raise OAuthError(f"discovery failed: {type(exc).__name__}") from None
        if response.status_code != 200:
            raise OAuthError(f"discovery {url} returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise OAuthError(f"discovery {url} is not JSON") from None
        if not isinstance(data, dict):
            raise OAuthError(f"discovery {url} is not an object")
        return data

    def _client(self, tenant_id: str, meta: dict[str, Any]) -> dict[str, Any]:
        stored = self._get(tenant_id, "_client")
        if stored and stored.get("redirect_uri") == self.redirect_uri:
            return stored
        endpoint = meta.get("registration_endpoint")
        if not endpoint:
            raise OAuthError("authorization server does not support client registration")
        body = {
            "client_name": self.client_name,
            "redirect_uris": [self.redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": SCOPES,
        }
        try:
            response = self.http.post(endpoint, json=body)
        except httpx.HTTPError as exc:
            raise OAuthError(f"client registration failed: {type(exc).__name__}") from None
        if response.status_code not in (200, 201):
            raise OAuthError(f"client registration returned HTTP {response.status_code}")
        data = response.json()
        client = {
            "client_id": data["client_id"],
            "client_secret": data.get("client_secret"),
            "redirect_uri": self.redirect_uri,
            "authorization_endpoint": meta["authorization_endpoint"],
            "token_endpoint": meta["token_endpoint"],
        }
        self._put(tenant_id, "_client", client)
        return client

    # ------------------------------------------------------------------ flow
    def start(self, tenant_id: str) -> str:
        meta = self._metadata()
        client = self._client(tenant_id, meta)
        verifier, challenge = pkce_pair()
        state = pysecrets.token_urlsafe(24)
        self._put(tenant_id, "_pending", {"state": state, "verifier": verifier, "at": self.clock()})
        query = {
            "response_type": "code",
            "client_id": client["client_id"],
            "redirect_uri": self.redirect_uri,
            "scope": SCOPES,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": self.resource_url,
            "prompt": "consent",
        }
        return f"{client['authorization_endpoint']}?{urlencode(query)}"

    def callback(self, tenant_id: str, code: str, state: str) -> None:
        pending = self._get(tenant_id, "_pending")
        if not pending or not pysecrets.compare_digest(str(pending.get("state", "")), state):
            raise OAuthError("unknown or reused sign-in state; start again")
        if self.clock() - float(pending.get("at", 0)) > PENDING_TTL_SEC:
            self.secrets.delete(tenant_id, self.provider + "_pending")
            raise OAuthError("sign-in took too long; start again")
        client = self._get(tenant_id, "_client")
        if not client:
            raise OAuthError("client registration missing; start again")
        tokens = self._token_request(
            client,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": pending["verifier"],
                "resource": self.resource_url,
            },
        )
        self._store_tokens(tenant_id, tokens, previous=None)
        self.secrets.delete(tenant_id, self.provider + "_pending")

    def token(self, tenant_id: str, force_refresh: bool = False) -> str | None:
        with self._lock:
            tokens = self._get(tenant_id)
            if not tokens or not tokens.get("access_token"):
                return None
            fresh = float(tokens.get("expires_at") or 0) - self.clock() > REFRESH_MARGIN_SEC
            if fresh and not force_refresh:
                return str(tokens["access_token"])
            refresh = tokens.get("refresh_token")
            client = self._get(tenant_id, "_client")
            if not refresh or not client:
                return None if force_refresh else str(tokens["access_token"])
            try:
                new = self._token_request(
                    client,
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": refresh,
                        "resource": self.resource_url,
                    },
                )
            except OAuthError as exc:
                log.warning("%s token refresh failed: %s", self.provider, exc)
                return None
            return self._store_tokens(tenant_id, new, previous=tokens)

    def disconnect(self, tenant_id: str) -> None:
        for suffix in ("", "_pending"):
            self.secrets.delete(tenant_id, self.provider + suffix)

    # ------------------------------------------------------------------ helpers
    def _token_request(self, client: dict[str, Any], form: dict[str, str]) -> dict[str, Any]:
        data = {**form, "client_id": client["client_id"]}
        if client.get("client_secret"):
            data["client_secret"] = client["client_secret"]
        try:
            response = self.http.post(
                client["token_endpoint"], data=data, headers={"Accept": "application/json"}
            )
        except httpx.HTTPError as exc:
            raise OAuthError(f"token request failed: {type(exc).__name__}") from None
        if response.status_code != 200:
            try:
                err = response.json().get("error", "")
            except ValueError:
                err = ""
            raise OAuthError(f"token endpoint returned HTTP {response.status_code} {err}".strip())
        payload = response.json()
        if not payload.get("access_token"):
            raise OAuthError("token response has no access_token")
        return payload

    def _store_tokens(
        self, tenant_id: str, payload: dict[str, Any], *, previous: dict[str, Any] | None
    ) -> str:
        expires_in = float(payload.get("expires_in") or 3600)
        tokens = {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token") or (previous or {}).get("refresh_token"),
            "expires_at": self.clock() + expires_in,
            "token_type": payload.get("token_type", "Bearer"),
        }
        self._put(tenant_id, "", tokens)
        return str(tokens["access_token"])
