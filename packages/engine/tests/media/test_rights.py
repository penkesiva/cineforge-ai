from __future__ import annotations

from typing import Any

import pytest
from cineforge.config import Settings
from cineforge.contracts.media import LicenseInfo, RightsGate, RightsStatus
from cineforge.media.factory import build_rights_gate

A, P, U, B = (
    RightsStatus.APPROVED,
    RightsStatus.PENDING,
    RightsStatus.UNKNOWN,
    RightsStatus.BLOCKED,
)
gate = build_rights_gate(Settings())


def lic(license_type: str, **kw: Any) -> LicenseInfo:
    return LicenseInfo(license_type=license_type, **kw)


CASES: list[tuple[str, LicenseInfo | None, str, RightsStatus]] = [
    # Missing / unknown -> UNKNOWN
    ("no license", None, "commercial", U),
    ("empty type", lic(""), "commercial", U),
    ("unknown type", lic("unknown"), "commercial", U),
    ("unknown despite flags", lic("Unknown", commercial_use_allowed=True), "commercial", U),
    ("unrecognized type", lic("my-custom-license"), "commercial", U),
    ("unrecognized with attribution", lic("weird", attribution_text="x"), "commercial", U),
    # Public domain / CC0 -> APPROVED
    ("cc0", lic("CC0"), "commercial", A),
    ("cc0 versioned", lic("CC0-1.0"), "commercial", A),
    ("public domain", lic("public-domain"), "commercial", A),
    ("public domain spaced", lic("Public Domain"), "commercial", A),
    # Own output -> APPROVED
    ("generated", lic("generated"), "commercial", A),
    ("rendered", lic("rendered"), "commercial", A),
    # CC-BY needs attribution text
    ("cc-by without attribution", lic("CC-BY-4.0"), "commercial", P),
    ("cc-by with attribution", lic("CC-BY-4.0", attribution_text="Photo: Jane"), "commercial", A),
    ("cc-by unversioned", lic("cc-by", attribution_text="Photo: Jane"), "commercial", A),
    ("cc-by-sa needs review", lic("CC-BY-SA-4.0", attribution_text="x"), "commercial", P),
    # NC / commercial not allowed -> BLOCKED for commercial use
    ("cc-by-nc", lic("CC-BY-NC-4.0", attribution_text="x"), "commercial", B),
    ("cc-by-nc-sa", lic("CC-BY-NC-SA-4.0", attribution_text="x"), "commercial", B),
    ("commercial flag false", lic("stock", commercial_use_allowed=False), "commercial", B),
    ("cc0 but commercial false", lic("CC0", commercial_use_allowed=False), "commercial", B),
    ("editorial only", lic("editorial"), "commercial", B),
    ("nc for non-commercial use", lic("CC-BY-NC-4.0", attribution_text="x"), "internal", A),
    # ND / modifications not allowed -> BLOCKED (we transform media)
    ("cc-by-nd", lic("CC-BY-ND-4.0", attribution_text="x"), "commercial", B),
    ("cc-by-nc-nd", lic("CC-BY-NC-ND-4.0", attribution_text="x"), "internal", B),
    ("modifications false", lic("CC0", modifications_allowed=False), "commercial", B),
    ("stock no modifications",
     lic("stock", commercial_use_allowed=True, modifications_allowed=False), "commercial", B),
    # Licensed / stock
    ("stock commercial unknown", lic("stock"), "commercial", P),
    ("licensed commercial unknown", lic("licensed"), "commercial", P),
    ("stock commercial ok", lic("stock", commercial_use_allowed=True), "commercial", A),
    ("royalty free ok", lic("royalty_free", commercial_use_allowed=True), "commercial", A),
    ("stock attribution missing",
     lic("stock", commercial_use_allowed=True, attribution_required=True), "commercial", P),
    ("stock restrictions",
     lic("stock", commercial_use_allowed=True, restrictions=["no-ai-training"]), "commercial", P),
    # Customer uploads need an attestation
    ("customer upload no attestation", lic("customer-upload"), "commercial", P),
    ("customer upload attested",
     lic("customer-upload", commercial_use_allowed=True), "commercial", A),
    ("customer upload denied",
     lic("customer-upload", commercial_use_allowed=False), "commercial", B),
]  # fmt: skip


@pytest.mark.parametrize(
    ("name", "license", "intended_use", "expected"), CASES, ids=[c[0] for c in CASES]
)
def test_rights_rules(
    name: str, license: LicenseInfo | None, intended_use: str, expected: RightsStatus
) -> None:
    decision = gate.evaluate(license, intended_use=intended_use)
    assert decision.status == expected, decision.reasons
    assert decision.reasons, "every decision must explain itself"
    assert decision.policy_version == "v1"
    assert decision.decided_by == "rights_gate"


def test_protocol() -> None:
    assert isinstance(gate, RightsGate)


@pytest.mark.parametrize(
    "license_type", ["", "unknown", "UNKNOWN", "none", "who-knows", "cc-by-zz", "copyright"]
)
@pytest.mark.parametrize("commercial", [None, True, False])
@pytest.mark.parametrize("modifications", [None, True])
def test_unknown_is_never_approved(
    license_type: str, commercial: bool | None, modifications: bool | None
) -> None:
    decision = gate.evaluate(
        lic(
            license_type,
            commercial_use_allowed=commercial,
            modifications_allowed=modifications,
            attribution_text="credit",
        )
    )
    assert decision.status != RightsStatus.APPROVED
