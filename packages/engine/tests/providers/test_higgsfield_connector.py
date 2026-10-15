"""Higgsfield connector: MCP client, OAuth sign-in and the provider, against a fake
server (httpx.MockTransport). No network, no spend."""

from __future__ import annotations

import json
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cineforge.config import Settings
from cineforge.contracts.providers import (
    PriceUnit,
    ProviderCapability,
    ProviderError,
    ProviderRequest,
)
from cineforge.providers.higgsfield import (
    HiggsfieldProvider,
    find_job_id,
    parse_credits,
    result_link,
)
from cineforge.providers.mcp import McpClient, ProviderAuthError, ToolResult
from cineforge.providers.oauth import McpOAuth, OAuthError
from cineforge.providers.settings_store import MemorySecretStore

MCP = "https://mcp.higgsfield.ai/mcp"
JOB = "11111111-2222-4333-8444-555555555555"
STILL = "99999999-2222-4333-8444-555555555555"
CDN = f"https://d8j0ntlcm91z4.cloudfront.net/user_x/hf_{JOB}.mp4"


class FakeMcp:
    """Records tool calls; answers like the real server (text + resource links)."""

    def __init__(self, *, sse: bool = False, status_sequence: list[str] | None = None) -> None:
        self.sse = sse
        self.calls: list[tuple[str, dict]] = []
        self.tokens: list[str] = []
        self.status_sequence = list(status_sequence or ["completed"])
        self.reject_token: str | None = None
        self.submit_reply: str | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        self.tokens.append(auth)
        if self.reject_token and auth == f"Bearer {self.reject_token}":
            return httpx.Response(401, json={"error": "invalid_token"})
        body = json.loads(request.content)
        if "id" not in body:
            return httpx.Response(202)
        if body["method"] == "initialize":
            return self._reply(body["id"], {"protocolVersion": "2025-06-18"}, session="sess-1")
        assert request.headers.get("mcp-session-id") == "sess-1"
        name, args = body["params"]["name"], body["params"]["arguments"]
        self.calls.append((name, args))
        return self._reply(body["id"], self._tool(name, args))

    def _tool(self, name: str, args: dict) -> dict:
        if name == "balance":
            return _text("Credits: 2305.26 | Plan: ultra")
        if name == "media_import_url":
            return _text("Imported media_id: aaaaaaaa-2222-4333-8444-555555555555")
        if name.startswith("generate_"):
            params = args["params"]
            if params.get("get_cost"):
                return _text(f"Cost preflight for {params['model']}: 20 credits (20 exact).")
            if self.submit_reply is not None:
                reply, self.submit_reply = self.submit_reply, None
                return _text(reply)
            return _text(f"Submitted. job_id: {JOB}")
        if name == "job_status":
            state = self.status_sequence.pop(0) if self.status_sequence else "completed"
            if state != "completed":
                return _text(f"Job {JOB} — {state}")
            link = {"type": "resource_link", "uri": CDN, "mimeType": "video/mp4", "name": "x"}
            return {"content": [{"type": "text", "text": f"Job {JOB} — completed\n{CDN}"}, link]}
        raise AssertionError(name)

    def _reply(self, rid: int, result: dict, session: str | None = None) -> httpx.Response:
        message = {"jsonrpc": "2.0", "id": rid, "result": result}
        headers = {"mcp-session-id": session} if session else {}
        if self.sse:
            text = f"event: message\ndata: {json.dumps(message)}\n\n"
            return httpx.Response(
                200, text=text, headers={**headers, "content-type": "text/event-stream"}
            )
        return httpx.Response(200, json=message, headers=headers)


def _text(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _provider(fake: FakeMcp, token: str | None = "tok") -> HiggsfieldProvider:
    settings = Settings(higgsfield_poll_sec=1, higgsfield_job_timeout_sec=30)
    return HiggsfieldProvider(
        settings,
        token_for=lambda tenant, force: token,
        http=httpx.Client(transport=httpx.MockTransport(fake.handler)),
        sleep=lambda s: None,
    )


def _request(**params) -> ProviderRequest:
    return ProviderRequest(
        tenant_id="t1",
        production_id="prod_1",
        shot_id="shot_1",
        capability=ProviderCapability.IMAGE_TO_VIDEO,
        model="wan2_7",
        prompt="Lena talks to camera",
        parameters={"duration_sec": 7.6, "resolution": "1080p", "secret_engine_key": 1, **params},
        idempotency_key="prod_1:GENERATING:visual_production:shot_1:1/clip",
    )


# ------------------------------------------------------------------ MCP client
@pytest.mark.parametrize("sse", [False, True])
def test_mcp_client_initializes_once_and_reads_json_or_sse(sse: bool) -> None:
    fake = FakeMcp(sse=sse)
    client = McpClient(
        httpx.Client(transport=httpx.MockTransport(fake.handler)), MCP, lambda f: "tok"
    )
    assert "2305.26" in client.call_tool("balance", {}).text
    assert "2305.26" in client.call_tool("balance", {}).text
    assert client.session_id == "sess-1"
    assert [c[0] for c in fake.calls] == ["balance", "balance"]


def test_mcp_client_refreshes_once_on_401_then_fails() -> None:
    fake = FakeMcp()
    fake.reject_token = "old"
    asked: list[bool] = []

    def supplier(force: bool) -> str:
        asked.append(force)
        return "new" if force else "old"

    client = McpClient(httpx.Client(transport=httpx.MockTransport(fake.handler)), MCP, supplier)
    client.call_tool("balance", {})
    assert True in asked

    fake.reject_token = "same"
    stuck = McpClient(
        httpx.Client(transport=httpx.MockTransport(fake.handler)), MCP, lambda f: "same"
    )
    with pytest.raises(ProviderAuthError):
        stuck.call_tool("balance", {})


def test_mcp_client_without_token_is_not_connected() -> None:
    client = McpClient(httpx.Client(transport=httpx.MockTransport(FakeMcp().handler)), MCP,
                       lambda f: None)  # fmt: skip
    with pytest.raises(ProviderAuthError, match="not connected"):
        client.call_tool("balance", {})


# ------------------------------------------------------------------ parsing
def test_parsers() -> None:
    assert parse_credits("Cost preflight for x: 24 credits (24 exact).") == Decimal(24)
    assert parse_credits("0.6 credits") == Decimal("0.6")
    assert parse_credits("no price") is None
    result = ToolResult(_text(f"Job {JOB} queued (start image {STILL})"))
    assert find_job_id(result, {STILL}) == JOB
    assert find_job_id(ToolResult(_text(f"uses {STILL}")), {STILL}) is None
    link = ToolResult({"content": [{"type": "resource_link", "uri": CDN, "mimeType": "video/mp4"}]})
    assert result_link(link) == (CDN, "video/mp4")
    foreign = ToolResult(_text("done https://evil.example.com/x.mp4"))
    assert result_link(foreign) is None


# ------------------------------------------------------------------ provider
def test_quote_is_free_and_cached_then_invoke_submits_and_polls() -> None:
    fake = FakeMcp(status_sequence=["in_progress", "completed"])
    provider = _provider(fake)
    request = _request(medias=[{"value": STILL, "role": "start_image"}])
    usage = provider.estimate_usage(request)
    assert (usage.units, usage.unit) == (Decimal(20), PriceUnit.CREDIT)
    response = provider.invoke(request)
    assert response.provider_request_id == JOB
    assert response.output_data["result_url"] == CDN
    assert response.usage.credits == Decimal(20)
    names = [c[0] for c in fake.calls]
    assert names == ["generate_video", "generate_video", "job_status", "job_status"]
    quote, submit = fake.calls[0][1]["params"], fake.calls[1][1]["params"]
    assert quote["get_cost"] is True and "medias" not in quote
    assert "get_cost" not in submit and submit["use_unlim"] is False
    assert submit["duration"] == 8 and submit["resolution"] == "1080p"
    assert submit["medias"] == [{"value": STILL, "role": "start_image"}]
    assert "secret_engine_key" not in submit


def test_voice_line_passes_speech_engine_and_voice() -> None:
    fake = FakeMcp()
    provider = _provider(fake)
    voice = {"variant": "elevenlabs", "voice_type": "preset", "voice_id": "juno-id"}
    request = _request(**voice).model_copy(
        update={"capability": ProviderCapability.VOICE_TTS, "model": "text2speech_v2"}
    )
    provider.invoke(request)
    submit = next(
        a for n, a in fake.calls if n == "generate_audio" and "get_cost" not in a["params"]
    )["params"]
    assert submit["model"] == "text2speech_v2"
    assert {k: submit[k] for k in voice} == voice
    assert "duration" not in submit


def test_context_urls_are_imported_as_reference_media() -> None:
    fake = FakeMcp()
    provider = _provider(fake)
    request = _request(import_urls=[{"url": "https://upload.wikimedia.org/a.jpg"}]).model_copy(
        update={"capability": ProviderCapability.IMAGE_GENERATION, "model": "nano_banana_2"}
    )
    provider.invoke(request)
    submit = next(
        a for n, a in fake.calls if n == "generate_image" and "get_cost" not in a["params"]
    )
    assert submit["params"]["medias"][0]["role"] == "image_references"
    assert submit["params"]["medias"][0]["value"].startswith("aaaaaaaa")


def test_preset_recommendation_retries_once_with_declined_preset() -> None:
    fake = FakeMcp()
    fake.submit_reply = "A preset is recommended (preset_id: cinematic-pov). No job created."
    provider = _provider(fake)
    provider.invoke(_request())
    submits = [a["params"] for n, a in fake.calls if n == "generate_video"][1:]
    assert len(submits) == 2 and submits[1]["declined_preset_id"] == "cinematic-pov"


def test_failed_job_raises_and_timeout_is_not_resubmitted() -> None:
    fake = FakeMcp(status_sequence=["failed"])
    with pytest.raises(ProviderError, match="failed"):
        _provider(fake).invoke(_request())

    slow = FakeMcp(status_sequence=["in_progress"] * 100)
    provider = _provider(slow)
    ticks = iter(range(0, 10_000, 10))
    provider.clock = lambda: float(next(ticks))
    with pytest.raises(ProviderError, match="not resubmitted") as err:
        provider.invoke(_request())
    assert err.value.retryable is False
    submits = [a for n, a in slow.calls if n == "generate_video" and "get_cost" not in a["params"]]
    assert len(submits) == 1


def test_unknown_submission_outcome_is_not_retryable() -> None:
    fake = FakeMcp()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        is_submit = body.get("method") == "tools/call" and "get_cost" not in json.dumps(body)
        if is_submit and body["params"]["name"] == "generate_video":
            raise httpx.ReadTimeout("slow")
        return fake.handler(request)

    provider = _provider(fake)
    provider.http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="outcome unknown") as err:
        provider.invoke(_request())
    assert err.value.retryable is False


def test_provider_info_is_paid_oauth() -> None:
    info = _provider(FakeMcp()).info
    assert info.is_paid and info.requires_key and info.auth_method == "oauth"
    assert {ProviderCapability.IMAGE_GENERATION, ProviderCapability.IMAGE_TO_VIDEO,
            ProviderCapability.VOICE_TTS} <= set(info.capabilities)  # fmt: skip


# ------------------------------------------------------------------ OAuth
class FakeAuthServer:
    def __init__(self) -> None:
        self.registered = 0
        self.token_forms: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known/oauth-protected-resource/mcp"):
            return httpx.Response(200, json={"authorization_servers": ["https://auth.example"]})
        if url == "https://auth.example/.well-known/oauth-authorization-server":
            return httpx.Response(200, json={
                "authorization_endpoint": "https://auth.example/authorize",
                "token_endpoint": "https://auth.example/token",
                "registration_endpoint": "https://auth.example/register",
            })  # fmt: skip
        if url == "https://auth.example/register":
            self.registered += 1
            return httpx.Response(201, json={"client_id": "client-123"})
        if url == "https://auth.example/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_forms.append(form)
            n = len(self.token_forms)
            return httpx.Response(200, json={
                "access_token": f"access-{n}", "refresh_token": f"refresh-{n}", "expires_in": 3600,
            })  # fmt: skip
        return httpx.Response(404)


def _auth(server: FakeAuthServer, clock) -> tuple[McpOAuth, MemorySecretStore]:
    secrets = MemorySecretStore()
    auth = McpOAuth(
        provider="higgsfield",
        resource_url=MCP,
        redirect_uri="http://127.0.0.1:8000/api/v1/providers/higgsfield/oauth/callback",
        secrets=secrets,
        http=httpx.Client(transport=httpx.MockTransport(server.handler)),
        clock=clock,
    )
    return auth, secrets


def test_oauth_sign_in_with_pkce_then_refresh() -> None:
    now = [1000.0]
    server = FakeAuthServer()
    auth, secrets = _auth(server, lambda: now[0])
    assert not auth.connected("t1") and auth.token("t1") is None

    url = auth.start("t1")
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert url.startswith("https://auth.example/authorize?")
    assert query["client_id"] == "client-123" and query["code_challenge_method"] == "S256"
    assert query["resource"] == MCP and "offline_access" in query["scope"]

    auth.callback("t1", "code-xyz", query["state"])
    form = server.token_forms[0]
    assert form["grant_type"] == "authorization_code" and form["code_verifier"]
    assert auth.connected("t1") and auth.token("t1") == "access-1"
    assert "access-1" not in url

    with pytest.raises(OAuthError):
        auth.callback("t1", "code-xyz", query["state"])  # state is single-use

    now[0] += 3600
    assert auth.token("t1") == "access-2"
    assert server.token_forms[1] == {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-1",
        "resource": MCP,
        "client_id": "client-123",
    }
    auth.start("t1")
    assert server.registered == 1  # client registration is reused

    auth.disconnect("t1")
    assert not auth.connected("t1")
    assert secrets.get("t1", "higgsfield_client")


def test_oauth_rejects_wrong_or_stale_state() -> None:
    now = [0.0]
    auth, _ = _auth(FakeAuthServer(), lambda: now[0])
    auth.start("t1")
    with pytest.raises(OAuthError):
        auth.callback("t1", "code", "forged")
    url = auth.start("t1")
    state = parse_qs(urlsplit(url).query)["state"][0]
    now[0] += 3600
    with pytest.raises(OAuthError, match="too long"):
        auth.callback("t1", "code", state)
