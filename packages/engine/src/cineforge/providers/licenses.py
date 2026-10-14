"""Map open-license labels from media sources onto the rights-gate vocabulary.

Recognized labels become ``CC0``, ``public-domain`` or ``CC-BY[-<mods>][-<version>]``
(mods: ``SA``, ``NC``, ``ND``, ``NC-SA``, ``NC-ND``). Anything else, including ported
licenses such as "CC BY-SA 2.0 de", keeps its raw label so ``DefaultRightsGate``
returns UNKNOWN (fail closed). Never guess a more permissive license.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime

from cineforge.contracts.common import utcnow
from cineforge.contracts.media import LicenseInfo

_CC0 = frozenset({"cc0", "cc-0", "cc0-1.0", "cc-zero", "cc-zero-1.0"})
_PUBLIC_DOMAIN = frozenset(
    {"pd", "pdm", "pdm-1.0", "public-domain", "publicdomain", "public-domain-mark"}
)
_CC_BY = re.compile(
    r"^(?:cc-)?by(?:-(?P<mods>sa|nc|nd|nc-sa|sa-nc|nc-nd|nd-nc))?(?:-(?P<version>\d+(?:\.\d+)?))?$"
)
_MODS = {"sa": "SA", "nc": "NC", "nd": "ND", "nc-sa": "NC-SA", "sa-nc": "NC-SA",
         "nc-nd": "NC-ND", "nd-nc": "NC-ND"}  # fmt: skip
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class OpenLicense:
    license_type: str
    recognized: bool
    family: str  # "cc0" | "public-domain" | "cc-by" | "unknown"
    mods: frozenset[str] = frozenset()

    @property
    def commercial_use_allowed(self) -> bool | None:
        if not self.recognized:
            return None
        if "NC" in self.mods:
            return False
        if "ND" in self.mods:
            return None
        return True

    @property
    def modifications_allowed(self) -> bool | None:
        if not self.recognized:
            return None
        return "ND" not in self.mods

    @property
    def attribution_required_default(self) -> bool:
        return self.family not in ("cc0", "public-domain")


def _slug(value: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[\s_]+", "-", value.strip().lower())).strip("-")


def normalize_open_license(raw: str | None, version: str | None = None) -> OpenLicense:
    """``raw`` is a code (``cc-by-sa-4.0``, ``by``, ``pdm``) or a short name
    (``CC BY-SA 4.0``, ``Public domain``); ``version`` fills in a missing CC version."""
    label = (raw or "").strip()
    slug = _slug(label)
    if not slug:
        return OpenLicense("unknown", False, "unknown")
    if slug in _CC0:
        return OpenLicense("CC0", True, "cc0")
    if slug in _PUBLIC_DOMAIN or slug.startswith("pd-"):
        return OpenLicense("public-domain", True, "public-domain")
    match = _CC_BY.match(slug)
    if match:
        mods = _MODS.get(match.group("mods") or "", "")
        ver = match.group("version") or (version or "").strip()
        if ver and not re.fullmatch(r"\d+(?:\.\d+)?", ver):
            return OpenLicense(label, False, "unknown")
        parts = ["CC-BY"] + ([mods] if mods else []) + ([ver] if ver else [])
        return OpenLicense("-".join(parts), True, "cc-by", frozenset(mods.split("-")) - {""})
    return OpenLicense(label, False, "unknown")


def strip_html(value: str | None, *, limit: int | None = None) -> str:
    text = _SPACE.sub(" ", html.unescape(_TAG.sub(" ", value or ""))).strip()
    if limit is not None and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def build_license_info(
    lic: OpenLicense,
    *,
    source_provider: str,
    source_url: str | None,
    license_url: str | None = None,
    author: str | None = None,
    attribution_text: str | None = None,
    attribution_required: bool | None = None,
    restrictions: list[str] | None = None,
    retrieved_at: datetime | None = None,
) -> LicenseInfo:
    if attribution_required is None:
        attribution_required = lic.attribution_required_default
    return LicenseInfo(
        license_type=lic.license_type,
        license_url=license_url or None,
        author=author or None,
        attribution_text=attribution_text or None,
        attribution_required=attribution_required,
        commercial_use_allowed=lic.commercial_use_allowed,
        modifications_allowed=lic.modifications_allowed,
        restrictions=list(restrictions or []),
        source_provider=source_provider,
        source_url=source_url,
        retrieved_at=retrieved_at or utcnow(),
    )
