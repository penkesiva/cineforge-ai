"""Higgsfield through its MCP server, billed to the tenant's plan credits.

Used two ways: the operator-run external generations (Phase 2) share the constants, and
``HiggsfieldProvider`` lets agents generate inside the engine (stills, talking clips,
b-roll, voice lines). Every call goes through ``PaidCallGuard``: ``estimate_usage`` asks
for a free quote (``get_cost``), the guard reserves it, then ``invoke`` submits with
``use_unlim: false``, polls the job and returns the CDN URL. The orchestrator downloads
results from ``RESULT_HOSTS`` only. A submission whose outcome is unknown (transport
timeout) is never resubmitted.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from cineforge.config import Settings
from cineforge.contracts.media import AssetKind
from cineforge.contracts.providers import (
    PriceUnit,
    ProviderCapability,
    ProviderError,
    ProviderInfo,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
)
from cineforge.providers.mcp import McpClient, ProviderAuthError, ToolResult

log = logging.getLogger(__name__)

NAME = "higgsfield"
MCP_URL = "https://mcp.higgsfield.ai/mcp"

# Generation results (video and audio) are served from this CloudFront distribution.
RESULT_HOSTS: tuple[str, ...] = ("d8j0ntlcm91z4.cloudfront.net", ".higgsfield.ai")
MAX_RESULT_BYTES = 200 * 1024 * 1024

OUTPUT_KINDS: dict[ProviderCapability, AssetKind] = {
    ProviderCapability.IMAGE_TO_VIDEO: AssetKind.VIDEO,
    ProviderCapability.VIDEO_GENERATION: AssetKind.VIDEO,
    ProviderCapability.VOICE_TTS: AssetKind.AUDIO,
    ProviderCapability.IMAGE_GENERATION: AssetKind.IMAGE,
}

C = ProviderCapability
TOOLS: dict[ProviderCapability, str] = {
    C.IMAGE_GENERATION: "generate_image",
    C.IMAGE_TO_VIDEO: "generate_video",
    C.VIDEO_GENERATION: "generate_video",
    C.VOICE_TTS: "generate_audio",
}
MODELS = (
    "nano_banana_2",
    "wan2_7",
    "kling3_0",
    "seedance_2_0",
    "kling2_6",
    "seed_audio",
    "text2speech_v2",
)
# Request parameters forwarded to the tool (everything else stays engine-side).
PASSTHROUGH = frozenset(
    {
        "resolution",
        "aspect_ratio",
        "mode",
        "variant",
        "sound",
        "generate_audio",
        "voice_type",
        "voice_id",
        "speech_rate",
        "genre",
        "bitrate_mode",
        "declined_preset_id",
    }
)
TERMINAL_OK = ("completed", "succeeded", "success")
TERMINAL_FAILED = ("failed", "nsfw", "cancelled", "canceled", "error", "rejected")
CONTEXT = "CineForge production asset generated under an approved budget"

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_JOB_RE = re.compile(rf"(?:job[_ ]?id|jobId|job)[\"'\s:=#]*({_UUID})", re.IGNORECASE)
_UUID_RE = re.compile(_UUID)
_CREDITS_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*credits?", re.IGNORECASE)
_PRESET_RE = re.compile(r"(?:declined_)?preset_id[\"'\s:=]*([A-Za-z0-9_-]{3,64})")
_URL_RE = re.compile(r"https://[^\s\"'<>{}]+")


def parse_credits(text: str) -> Decimal | None:
    match = _CREDITS_RE.search(text)
    if not match:
        return None
    try:
        return Decimal(match.group(1))
    except InvalidOperation:
        return None


def find_job_id(result: ToolResult, exclude: set[str]) -> str | None:
    found = _job_from_structured(result.structured, exclude)
    if found:
        return found
    for match in _JOB_RE.finditer(result.text):
        if match.group(1) not in exclude:
            return match.group(1)
    for link in result.links():
        for candidate in _UUID_RE.findall(str(link.get("uri", ""))):
            if candidate not in exclude:
                return candidate
    return None


def _job_from_structured(node: Any, exclude: set[str], depth: int = 0) -> str | None:
    if depth > 6 or node is None:
        return None
    if isinstance(node, dict):
        for key in ("job_id", "jobId", "job_ids", "jobs", "id"):
            value = node.get(key)
            if isinstance(value, str) and _UUID_RE.fullmatch(value) and value not in exclude:
                return value
            if isinstance(value, list):
                for item in value:
                    found = _job_from_structured(
                        {"id": item} if isinstance(item, str) else item, exclude, depth + 1
                    )
                    if found:
                        return found
        for value in node.values():
            found = _job_from_structured(value, exclude, depth + 1)
            if found:
                return found
    if isinstance(node, list):
        for item in node:
            found = _job_from_structured(item, exclude, depth + 1)
            if found:
                return found
    return None


def result_link(result: ToolResult) -> tuple[str, str | None] | None:
    """(url, mime type) of the finished output, preferring resource links."""
    for link in result.links():
        return str(link["uri"]), link.get("mimeType")
    for url in _URL_RE.findall(result.text):
        host = url.split("/", 3)[2]
        if any(host == h or (h.startswith(".") and host.endswith(h)) for h in RESULT_HOSTS):
            return url, None
    return None


UPLOAD_HOST = "upload.higgsfield.ai"


def _upload_host(url: str) -> bool:
    return url.split("/", 3)[2] == UPLOAD_HOST


def _first_upload_url(node: Any, depth: int = 0) -> str | None:
    if depth > 6:
        return None
    if isinstance(node, dict):
        value = node.get("upload_url")
        if isinstance(value, str) and value.startswith("https://") and _upload_host(value):
            return value
        node = list(node.values())
    if isinstance(node, list):
        for item in node:
            found = _first_upload_url(item, depth + 1)
            if found:
                return found
    return None


def job_state(result: ToolResult) -> str:
    text = result.text.lower()
    head = text.splitlines()[0] if text else ""
    for word in (*TERMINAL_FAILED, *TERMINAL_OK):
        if word in head:
            return word
    structured = result.structured if isinstance(result.structured, dict) else {}
    status = structured.get("status")
    return str(status or "").lower() or "pending"


class HiggsfieldProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        token_for: Callable[[str, bool], str | None],
        http: httpx.Client,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.token_for = token_for
        self.http = http
        self.sleep = sleep
        self.clock = clock
        self._clients: dict[str, McpClient] = {}
        self._quotes: dict[str, Decimal] = {}
        self._lock = threading.Lock()
        self.info = ProviderInfo(
            name=NAME,
            display_name="Higgsfield",
            capabilities=[C.IMAGE_GENERATION, C.IMAGE_TO_VIDEO, C.VOICE_TTS],
            models=list(MODELS),
            is_mock=False,
            is_paid=True,
            requires_key=True,
            auth_method="oauth",
            description="Images, talking and b-roll video, voices on your Higgsfield plan "
            "credits (MCP). Sign in once; every call is quoted and reserved first.",
            docs_url="https://higgsfield.ai",
        )

    # ------------------------------------------------------------------ plumbing
    def client(self, tenant_id: str) -> McpClient:
        with self._lock:
            existing = self._clients.get(tenant_id)
            if existing is None:
                existing = McpClient(
                    self.http,
                    self.settings.higgsfield_mcp_url,
                    lambda force: self.token_for(tenant_id, force),
                )
                self._clients[tenant_id] = existing
            return existing

    def call(self, tenant_id: str, tool: str, arguments: dict[str, Any]) -> ToolResult:
        result = self.client(tenant_id).call_tool(tool, arguments)
        if result.is_error:
            raise ProviderError(f"higgsfield {tool}: {result.text[:300]}", retryable=False)
        return result

    def upload_media(self, tenant_id: str, *, filename: str, data: bytes, content_type: str) -> str:
        """Upload an owned reference image (free) and return its Higgsfield media id."""
        result = self.call(
            tenant_id, "media_upload", {"filename": filename, "content_type": content_type}
        )
        media_id = _job_from_structured(result.structured, set()) or next(
            iter(_UUID_RE.findall(result.text)), None
        )
        url = next((u for u in _URL_RE.findall(result.text) if _upload_host(u)), None)
        if isinstance(result.structured, dict):
            url = _first_upload_url(result.structured) or url
        if media_id is None or url is None:
            raise ProviderError("higgsfield media_upload: no media id or upload URL")
        put = self.http.put(
            url,
            content=data,
            headers={"Content-Type": content_type, "If-None-Match": "*"},
            timeout=120,
        )
        if put.status_code >= 300:
            raise ProviderError(f"higgsfield upload failed: HTTP {put.status_code}")
        self.call(tenant_id, "media_confirm", {"type": "image", "media_id": media_id})
        return media_id

    def balance(self, tenant_id: str) -> Decimal | None:
        return parse_credits(self.call(tenant_id, "balance", {}).text)

    # ------------------------------------------------------------------ params
    def _params(self, request: ProviderRequest, *, get_cost: bool) -> dict[str, Any]:
        tool = TOOLS.get(request.capability)
        if tool is None:
            raise ProviderError(f"higgsfield does not support {request.capability}")
        src = request.parameters
        params: dict[str, Any] = {
            "model": request.model,
            "prompt": request.prompt or "",
            "use_unlim": False,
        }
        params |= {k: v for k, v in src.items() if k in PASSTHROUGH and v is not None}
        if tool == "generate_video" and src.get("duration_sec") is not None:
            params["duration"] = max(2, round(float(src["duration_sec"])))
        medias = [dict(m) for m in src.get("medias") or []]
        if medias:
            params["medias"] = medias
        if get_cost:
            params["get_cost"] = True
        return params

    def _resolve_imports(self, request: ProviderRequest) -> ProviderRequest:
        """Import context URLs (``parameters['import_urls']``) as media ids. Free."""
        imports = request.parameters.get("import_urls") or []
        if not imports:
            return request
        medias = list(request.parameters.get("medias") or [])
        for item in imports:
            result = self.call(
                request.tenant_id, "media_import_url", {"url": item["url"], "type": "image"}
            )
            media_id = _job_from_structured(result.structured, set()) or next(
                iter(_UUID_RE.findall(result.text)), None
            )
            if media_id is None:
                log.warning("higgsfield: could not import context reference; skipped")
                continue
            medias.append({"value": media_id, "role": item.get("role", "image_references")})
        params = {k: v for k, v in request.parameters.items() if k != "import_urls"}
        return request.model_copy(update={"parameters": {**params, "medias": medias}})

    # ------------------------------------------------------------------ Provider
    def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        cached = self._quotes.get(request.idempotency_key)
        if cached is None:
            tool = TOOLS.get(request.capability)
            if tool is None:
                raise ProviderError(f"higgsfield does not support {request.capability}")
            # Price depends on model, duration and resolution, not on the media ids.
            params = self._params(request, get_cost=True)
            params.pop("medias", None)
            params.pop("declined_preset_id", None)
            result = self.call(request.tenant_id, tool, {"params": params, "context": CONTEXT})
            cached = parse_credits(result.text)
            if cached is None:
                raise ProviderError("higgsfield: quote returned no credit amount")
            self._quotes[request.idempotency_key] = cached
        return ProviderUsage(units=cached, unit=PriceUnit.CREDIT, credits=cached)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        started = self.clock()
        quote = self.estimate_usage(request).units
        request = self._resolve_imports(request)
        tool = TOOLS[request.capability]
        exclude = {str(m.get("value")) for m in request.parameters.get("medias") or []}
        job_id = self._submit(request, tool, exclude)
        url, mime = self._wait(request.tenant_id, job_id)
        self._quotes.pop(request.idempotency_key, None)
        return ProviderResponse(
            provider=NAME,
            model=request.model,
            capability=request.capability,
            provider_request_id=job_id,
            output_data={"result_url": url, "content_type": mime, "job_id": job_id},
            usage=ProviderUsage(units=quote, unit=PriceUnit.CREDIT, credits=quote),
            latency_ms=int((self.clock() - started) * 1000),
        )

    def _submit(self, request: ProviderRequest, tool: str, exclude: set[str]) -> str:
        params = self._params(request, get_cost=False)
        for _ in range(2):
            try:
                result = self.call(request.tenant_id, tool, {"params": params, "context": CONTEXT})
            except ProviderAuthError:
                raise
            except ProviderError as exc:
                if exc.retryable:
                    raise ProviderError(
                        f"higgsfield {tool}: submission outcome unknown ({exc}); "
                        "not resubmitted, check the Higgsfield history",
                        retryable=False,
                    ) from None
                raise
            job_id = find_job_id(result, exclude)
            if job_id:
                return job_id
            preset = _PRESET_RE.search(result.text)
            if preset and "declined_preset_id" not in params:
                params["declined_preset_id"] = preset.group(1)
                continue
            break
        raise ProviderError(f"higgsfield {tool}: no job created ({result.text[:200]})")

    def _wait(self, tenant_id: str, job_id: str) -> tuple[str, str | None]:
        deadline = self.clock() + self.settings.higgsfield_job_timeout_sec
        while True:
            result = self.call(tenant_id, "job_status", {"jobId": job_id, "sync": True})
            state = job_state(result)
            if state in TERMINAL_FAILED:
                raise ProviderError(f"higgsfield job {job_id} {state}: {result.text[:200]}")
            link = result_link(result)
            if link and (state in TERMINAL_OK or state == "pending"):
                return link
            if self.clock() >= deadline:
                raise ProviderError(
                    f"higgsfield job {job_id} not finished after "
                    f"{self.settings.higgsfield_job_timeout_sec:.0f}s; not resubmitted"
                )
            self.sleep(self.settings.higgsfield_poll_sec)
