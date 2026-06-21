"""
Offline tests for R2 concentration-unit validity (pipeline/normalize.concentration_class
+ canon_unit improvements) and the audit helper.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import normalize as nz  # noqa: E402
import audit_units as au  # noqa: E402


def test_canon_unit_now_handles_per_uL_spaced_molar_and_activity():
    assert nz.canon_unit("ng/µl") == "ng/uL"
    assert nz.canon_unit("ng/μL") == "ng/uL"
    assert nz.canon_unit("n m") == "nM"        # spaced molar
    assert nz.canon_unit("u m") == "uM"
    assert nz.canon_unit("mU ml -1") == "mU/mL"  # activity per volume
    assert nz.canon_unit("ng ml-1") == "ng/mL"   # regression: still works


def test_concentration_class_real_concentrations():
    for u in ["ng/mL", "µM", "uM", "nM", "pM", "mg/mL", "ng/µl", "n m", "mU ml -1", "U/mL"]:
        assert nz.concentration_class(u) == "concentration", u


def test_concentration_class_in_vivo_doses_flagged():
    for u in ["mg/kg", "10 mg kg-1 day-1", "mg kg−1", "mpk", "µg/kg"]:
        assert nz.concentration_class(u) == "in_vivo_dose", u


def test_concentration_class_volume_and_percent_and_missing():
    assert nz.concentration_class("µl") == "volume"
    assert nz.concentration_class("ml") == "volume"
    assert nz.concentration_class("%") == "percent"
    assert nz.concentration_class("50% v/v") == "percent"
    assert nz.concentration_class("") == "missing"
    assert nz.concentration_class(None) == "missing"
    assert nz.concentration_class("widgets") == "other"


def test_is_suspect_concentration():
    assert nz.is_suspect_concentration("mg/kg")
    assert nz.is_suspect_concentration("%")
    assert nz.is_suspect_concentration("µl")
    assert not nz.is_suspect_concentration("ng/mL")
    assert not nz.is_suspect_concentration("nM")


def test_audit_shape_on_inline_rows():
    rows = [
        {"id": 1, "name": "EGF", "value": 50, "unit": "ng/mL", "pmcid": "PMC1"},
        {"id": 2, "name": "afatinib", "value": 10, "unit": "mg/kg", "pmcid": "PMC2"},
        {"id": 3, "name": "X", "value": None, "unit": "ng/mL", "pmcid": "PMC3"},  # no value -> skipped
    ]
    a = au.audit(rows)
    assert a["n_with_value"] == 2
    assert a["class_counts"].get("concentration") == 1
    assert a["class_counts"].get("in_vivo_dose") == 1
    assert a["suspect_total"] == 1 and a["suspect"][0]["name"] == "afatinib"
