"""Fail-closed rights gate (policy v1).

Rules, evaluated in order (first decisive rule wins):

1. No license, or license_type empty/"unknown"                  -> UNKNOWN
2. Non-commercial (NC) license, or commercial_use_allowed False,
   when the intended use is commercial                          -> BLOCKED
3. No-derivatives (ND) license or modifications_allowed False
   (we always transform media)                                  -> BLOCKED
4. Our own output ("generated", "rendered")                      -> APPROVED
5. Unrecognized license type                                     -> UNKNOWN
6. Recognized license but needs a human:
   - CC-BY-* without attribution_text, or attribution_required
     without attribution_text                                   -> PENDING
   - share-alike (SA) licenses                                  -> PENDING
   - licensed/stock with commercial_use_allowed unknown         -> PENDING
   - customer-upload without commercial-use attestation         -> PENDING
   - any listed restrictions                                    -> PENDING
7. Otherwise (CC0, public domain, CC-BY with attribution,
   licensed/stock or attested customer upload)                  -> APPROVED
"""

from __future__ import annotations

import re

from cineforge.contracts.media import LicenseInfo, RightsDecision, RightsStatus

POLICY_VERSION = "v1"

OWN_OUTPUT = frozenset({"generated", "rendered"})
PUBLIC_DOMAIN = frozenset({"cc0", "cc0-1.0", "public-domain", "pd", "pdm", "pdm-1.0"})
LICENSED = frozenset({"commercial", "licensed", "stock", "royalty-free", "rights-managed"})
EDITORIAL = frozenset({"editorial", "editorial-only"})
CUSTOMER_UPLOAD = "customer-upload"
_CC = re.compile(r"^cc-by(?:-(?P<mods>(?:nc|nd|sa)(?:-(?:nc|nd|sa))*))?(?:-\d+(?:\.\d+)?)?$")


def normalize_license_type(value: str | None) -> str:
    return re.sub(r"[\s_]+", "-", (value or "").strip().lower())


class DefaultRightsGate:
    policy_version = POLICY_VERSION

    def evaluate(
        self, license: LicenseInfo | None, *, intended_use: str = "commercial"
    ) -> RightsDecision:
        status, reasons = self._decide(license, intended_use)
        return RightsDecision(status=status, reasons=reasons, policy_version=POLICY_VERSION)

    def _decide(self, lic: LicenseInfo | None, intended_use: str) -> tuple[RightsStatus, list[str]]:
        if lic is None:
            return RightsStatus.UNKNOWN, ["no license information (fail closed)"]
        kind = normalize_license_type(lic.license_type)
        if kind in ("", "unknown", "none"):
            return RightsStatus.UNKNOWN, [f"license type {lic.license_type!r} is unknown"]

        cc = _CC.match(kind)
        mods = set((cc.group("mods") or "").split("-")) - {""} if cc else set()
        commercial = intended_use.strip().lower() == "commercial"

        if commercial and "nc" in mods:
            return RightsStatus.BLOCKED, [f"{lic.license_type} forbids commercial use"]
        if commercial and lic.commercial_use_allowed is False:
            return RightsStatus.BLOCKED, ["license does not allow commercial use"]
        if commercial and kind in EDITORIAL:
            return RightsStatus.BLOCKED, ["editorial-only license cannot be used commercially"]
        if "nd" in mods:
            return RightsStatus.BLOCKED, [f"{lic.license_type} forbids derivatives"]
        if lic.modifications_allowed is False:
            return RightsStatus.BLOCKED, ["license does not allow modifications"]

        if kind in OWN_OUTPUT:
            return RightsStatus.APPROVED, [f"{kind} by CineForge (own output)"]

        recognized = (
            cc is not None
            or kind in PUBLIC_DOMAIN
            or kind in LICENSED
            or kind in EDITORIAL
            or kind == CUSTOMER_UPLOAD
        )
        if not recognized:
            return RightsStatus.UNKNOWN, [f"unrecognized license type {lic.license_type!r}"]

        pending: list[str] = []
        has_attribution = bool((lic.attribution_text or "").strip())
        if cc is not None and not has_attribution:
            pending.append(f"{lic.license_type} requires attribution_text")
        elif lic.attribution_required and not has_attribution:
            pending.append("attribution required but attribution_text is missing")
        if "sa" in mods:
            pending.append("share-alike terms need legal review")
        if kind in LICENSED and lic.commercial_use_allowed is None:
            pending.append("commercial use not confirmed for licensed/stock media")
        if kind == CUSTOMER_UPLOAD and lic.commercial_use_allowed is not True:
            pending.append("customer upload lacks commercial-use attestation")
        if lic.restrictions:
            pending.append(f"license restrictions need review: {', '.join(lic.restrictions)}")
        if pending:
            return RightsStatus.PENDING, pending

        if kind in PUBLIC_DOMAIN:
            return RightsStatus.APPROVED, [f"{lic.license_type}: no rights reserved"]
        if cc is not None:
            return RightsStatus.APPROVED, [f"{lic.license_type} with attribution"]
        if kind == CUSTOMER_UPLOAD:
            return RightsStatus.APPROVED, ["customer attested commercial-use rights"]
        return RightsStatus.APPROVED, [f"{kind} license allows commercial use"]
