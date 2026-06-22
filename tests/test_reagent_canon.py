"""
Offline tests for the reagent-canonicalization fixes (review #118):
B27/N2 supplement synonym merge and bare-family ambiguity flagging.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from normalize import canonical_or_none, is_ambiguous_family  # noqa: E402


def test_b27_variants_merge_to_one_canonical():
    assert canonical_or_none("B27") == "B-27 supplement"
    assert canonical_or_none("B27 supplement") == "B-27 supplement"
    assert canonical_or_none("B-27") == "B-27 supplement"   # punctuation-insensitive key


def test_b27_genuine_variant_not_collapsed():
    # a different formulation has a different norm_key -> not merged into plain B-27
    assert canonical_or_none("B27 without vitamin A") != "B-27 supplement"


def test_n2_merge():
    assert canonical_or_none("N2") == "N-2 supplement"
    assert canonical_or_none("N2 supplement") == "N-2 supplement"


def test_bare_family_flagged_ambiguous():
    for fam in ("FGF", "fgf", "FGFs", "Wnt", "BMP", "BMPs", "TGF"):
        assert is_ambiguous_family(fam) is True


def test_specific_members_not_ambiguous():
    for compound in ("FGF2", "Wnt3a", "BMP4", "TGF-β1"):
        assert is_ambiguous_family(compound) is False
