"""
Unit tests for reagent + unit canonicalization (normalize.py).

Pins the entity/unit collapses the consensus & heatmap rely on: synonym mapping,
the two micro-signs unifying, "ng ml -1" notations, and percent kept verbatim.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from normalize import build_canon_map, canon_unit, canonical_or_none  # noqa: E402


def test_canon_unit_unifies_micro_signs():
    # µ (U+00B5) and μ (U+03BC) must collapse to the same canonical unit
    assert canon_unit("µM") == "uM"
    assert canon_unit("μM") == "uM"
    assert canon_unit("uM") == "uM"


def test_canon_unit_per_ml_notations():
    for v in ["ng/mL", "ng ml-1", "ng ml -1", "ng ml −1", "ng/ml"]:
        assert canon_unit(v) == "ng/mL", v
    assert canon_unit("µg/ml") == "ug/mL"


def test_canon_unit_molar_and_percent():
    assert canon_unit("nmol/L") == "nM"
    assert canon_unit("mM") == "mM"
    # percent variants carry meaning (e.g. conditioned medium) — kept verbatim
    assert canon_unit("% v/v") == "% v/v"
    assert canon_unit(None) is None


def test_reagent_synonyms_collapse():
    m = build_canon_map(["bFGF", "FGF2", "RSPO1", "R-spondin1", "Bone morphogenetic protein 4"])
    assert m["bFGF"] == "FGF2" and m["FGF2"] == "FGF2"
    assert m["RSPO1"] == "R-spondin1"
    assert m["Bone morphogenetic protein 4"] == "BMP4"


def test_culture_factor_gate():
    assert canonical_or_none("NOG") == "Noggin"        # figure abbreviation
    assert canonical_or_none("mCherry") is None        # not a culture factor
