"""
Tests for ucum_unit() added to normalize.py.
No network — pure unit mapping, fully offline.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import normalize as nz


# --------------------------------------------------------------------------- #
# ucum_unit — canonical mapping
# --------------------------------------------------------------------------- #

def test_ucum_none_returns_none():
    assert nz.ucum_unit(None) is None

def test_ucum_empty_returns_none():
    assert nz.ucum_unit("") is None

def test_ucum_ngml():
    assert nz.ucum_unit("ng/mL") == "ng.mL-1"

def test_ucum_ugml():
    assert nz.ucum_unit("ug/mL") == "ug.mL-1"

def test_ucum_mgml():
    assert nz.ucum_unit("mg/mL") == "mg.mL-1"

def test_ucum_pgml():
    assert nz.ucum_unit("pg/mL") == "pg.mL-1"

def test_ucum_ngul():
    assert nz.ucum_unit("ng/uL") == "ng.uL-1"

def test_ucum_nM():
    assert nz.ucum_unit("nM") == "nmol.L-1"

def test_ucum_uM():
    assert nz.ucum_unit("uM") == "umol.L-1"

def test_ucum_mM():
    assert nz.ucum_unit("mM") == "mmol.L-1"

def test_ucum_M():
    assert nz.ucum_unit("M") == "mol.L-1"

def test_ucum_pM():
    assert nz.ucum_unit("pM") == "pmol.L-1"

def test_ucum_fM():
    assert nz.ucum_unit("fM") == "fmol.L-1"

def test_ucum_UmL():
    assert nz.ucum_unit("U/mL") == "U.mL-1"

def test_ucum_IUmL():
    assert nz.ucum_unit("IU/mL") == "[IU].mL-1"

def test_ucum_mUmL():
    assert nz.ucum_unit("mU/mL") == "mU.mL-1"

# --------------------------------------------------------------------------- #
# ucum_unit — raw inputs normalised via canon_unit first
# --------------------------------------------------------------------------- #

def test_ucum_unicode_micro():
    # µ (U+00B5) → should canonicalise to ug/mL → ucum ug.mL-1
    assert nz.ucum_unit("µg/mL") == "ug.mL-1"

def test_ucum_unicode_micro_greek():
    # μ (U+03BC) → same
    assert nz.ucum_unit("μg/mL") == "ug.mL-1"

def test_ucum_lowercase():
    assert nz.ucum_unit("ng/ml") == "ng.mL-1"

def test_ucum_molar_lowercase():
    assert nz.ucum_unit("nm") == "nmol.L-1"

def test_ucum_nmol_per_L():
    assert nz.ucum_unit("nmol/L") == "nmol.L-1"

def test_ucum_spaced_notation():
    # "ng ml -1" is a common mis-formatted unit
    assert nz.ucum_unit("ng ml -1") == "ng.mL-1"

# --------------------------------------------------------------------------- #
# ucum_unit — non-concentration units return None
# --------------------------------------------------------------------------- #

def test_ucum_invivo_dose_returns_none():
    assert nz.ucum_unit("mg/kg") is None

def test_ucum_volume_returns_none():
    assert nz.ucum_unit("mL") is None

def test_ucum_percent_returns_none():
    # percent → canon_unit returns "%" which is not in UCUM map
    assert nz.ucum_unit("%") is None

def test_ucum_unknown_returns_none():
    assert nz.ucum_unit("cells/well") is None

# --------------------------------------------------------------------------- #
# Round-trip: canon_unit → ucum_unit
# --------------------------------------------------------------------------- #

def test_all_conc_ok_units_have_ucum():
    """Every unit in CONC_OK should map to a UCUM expression."""
    missing = []
    for unit in sorted(nz.CONC_OK):
        ucum = nz.ucum_unit(unit)
        if ucum is None:
            missing.append(unit)
    assert missing == [], f"CONC_OK units missing UCUM: {missing}"
