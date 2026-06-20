"""
Unit tests for the Tier-3 protocol-by-reference DETECTOR (the router signal).

These exercise the gating logic on synthetic methods text — no network and no
local corpus needed — so they pin the precision rules: external culture-protocol
delegations are flagged; self-references and assay/animal delegations are not.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from tier3_detect import detect_one  # noqa: E402


def _bundle(text):
    return {"pmcid": "PMCTEST", "organoid_type": "intestinal",
            "doi": "10.0/x", "methods_text": text}


def test_external_culture_delegation_is_flagged():
    b = _bundle("Differentiation into definitive endoderm and intestinal organoids "
                "was carried out as previously described (Spence et al., 2011).")
    r = detect_one(b)
    assert r is not None
    assert r["cited"]["kind"] == "named"
    assert r["cited"]["author"] == "Spence" and r["cited"]["year"] == "2011"


def test_numbered_external_delegation_is_flagged():
    b = _bundle("Organoid differentiation was performed as previously described 11. "
                "Briefly, cells were cultured in Matrigel.")
    r = detect_one(b)
    assert r is not None and r["cited"]["kind"] == "numbered"


def test_self_reference_is_not_flagged():
    b = _bundle("Organoids were passaged as described in step 13 above, then "
                "re-embedded in fresh Matrigel as described in the section above.")
    assert detect_one(b) is None


def test_assay_delegation_is_not_flagged():
    b = _bundle("Libraries were sequenced as previously described (Fisher et al., 2011); "
                "immunostaining was performed as previously described.")
    assert detect_one(b) is None


def test_no_delegation_is_not_flagged():
    b = _bundle("Cells were cultured in Matrigel with EGF, Noggin and R-spondin1 "
                "at the concentrations listed in Table 1.")
    assert detect_one(b) is None
