"""OAuth sign-in for MCP providers (Higgsfield) and the connected status on the Sources
page. The callback lands on the local API (127.0.0.1) and redirects to the dashboard;
tokens go straight into the tenant's secret store and never reach the browser."""

from __future__ import annotations

from urllib.parse import urlencode

from cineforge.contracts.api import ConnectorStatus, OAuthStartResponse
from cineforge.contracts.providers import ProviderError
from cineforge.providers.factory import build_higgsfield_auth
from cineforge.providers.higgsfield import NAME as HIGGSFIELD
from cineforge.providers.higgsfield import HiggsfieldProvider
from cineforge.providers.oauth import McpOAuth, OAuthError
from cineforge.runtime import Runtime
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from cineforge_api.deps import RuntimeDep, TenantDep

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])
OAUTH_PROVIDERS = frozenset({HIGGSFIELD})


def _auth(rt: Runtime, name: str) -> McpOAuth:
    if name not in OAUTH_PROVIDERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"provider {name!r} has no sign-in")
    return build_higgsfield_auth(rt.settings, rt.secrets)


def _status(rt: Runtime, name: str, tenant_id: str, *, with_balance: bool) -> ConnectorStatus:
    auth = _auth(rt, name)
    if not auth.connected(tenant_id):
        return ConnectorStatus(provider=name, connected=False, detail="Not signed in")
    balance, detail = None, "Signed in"
    try:
        provider = rt.providers.get(name)
    except LookupError:
        provider = None
    if with_balance and isinstance(provider, HiggsfieldProvider):
        try:
            balance = provider.balance(tenant_id)
        except ProviderError as exc:
            detail = f"Signed in; balance unavailable ({exc})"[:300]
    return ConnectorStatus(provider=name, connected=True, balance_credits=balance, detail=detail)


@router.post("/{name}/oauth/start", response_model=OAuthStartResponse)
def oauth_start(name: str, rt: RuntimeDep, tenant_id: TenantDep) -> OAuthStartResponse:
    try:
        url = _auth(rt, name).start(tenant_id)
    except OAuthError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"sign-in unavailable: {exc}") from None
    return OAuthStartResponse(provider=name, authorize_url=url)


@router.get("/{name}/oauth/callback", include_in_schema=False)
def oauth_callback(
    name: str,
    rt: RuntimeDep,
    code: str | None = Query(default=None, max_length=2000),
    state: str | None = Query(default=None, max_length=200),
    error: str | None = Query(default=None, max_length=200),
) -> RedirectResponse:
    tenant_id = rt.settings.default_tenant_id
    result = {"connected": name}
    if error or not code or not state:
        result = {"connect_error": error or "missing code"}
    else:
        try:
            _auth(rt, name).callback(tenant_id, code, state)
        except OAuthError as exc:
            result = {"connect_error": str(exc)[:200]}
    target = f"{rt.settings.dashboard_url.rstrip('/')}/sources?{urlencode(result)}"
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/{name}/oauth", response_model=ConnectorStatus)
def oauth_disconnect(name: str, rt: RuntimeDep, tenant_id: TenantDep) -> ConnectorStatus:
    _auth(rt, name).disconnect(tenant_id)
    return _status(rt, name, tenant_id, with_balance=False)


@router.get("/{name}/connection", response_model=ConnectorStatus)
def connection(
    name: str, rt: RuntimeDep, tenant_id: TenantDep, balance: bool = False
) -> ConnectorStatus:
    """``balance=true`` asks the provider for the plan balance (a free call)."""
    return _status(rt, name, tenant_id, with_balance=balance)
