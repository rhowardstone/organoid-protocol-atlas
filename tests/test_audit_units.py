"""
Offline tests for audit_units.py.
No network, no real reagents.jsonl.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import audit_units as au


def _row(name="EGF", unit="ng/mL", value=100.0, pmcid="PMC001"):
    return {"name": name, "unit": unit, "value": value, "pmcid": pmcid, "id": f"{pmcid}_{name}"}


def test_audit_empty():
    result = au.audit([])
    assert result["n_with_value"] == 0
    assert result["suspect_total"] == 0
    assert result["suspect_rate"] == 0.0


def test_audit_all_concentration():
    rows = [_row("EGF", "ng/mL"), _row("Wnt3a", "nM")]
    result = au.audit(rows)
    assert result["n_with_value"] == 2
    assert result["class_counts"].get("concentration", 0) == 2
    assert result["suspect_total"] == 0


def test_audit_invivo_dose_is_suspect():
    rows = [_row("afatinib", "mg/kg")]
    result = au.audit(rows)
    assert result["suspect_total"] == 1
    assert result["suspect"][0]["class"] == "in_vivo_dose"


def test_audit_volume_is_suspect():
    rows = [_row("media", "mL")]
    result = au.audit(rows)
    assert result["suspect_total"] == 1
    assert result["suspect"][0]["class"] == "volume"


def test_audit_percent_is_suspect():
    rows = [_row("FBS", "%")]
    result = au.audit(rows)
    assert result["suspect_total"] == 1
    assert result["suspect"][0]["class"] == "percent"


def test_audit_no_value_rows_excluded():
    rows = [{"name": "EGF", "unit": "ng/mL", "value": None, "pmcid": "PMC001"}]
    result = au.audit(rows)
    assert result["n_with_value"] == 0


def test_audit_suspect_rate():
    rows = [_row("EGF", "ng/mL"), _row("drug", "mg/kg")]
    result = au.audit(rows)
    assert result["suspect_rate"] == pytest.approx(0.5)


def test_audit_ucum_coverage_present():
    rows = [_row("EGF", "ng/mL"), _row("Wnt3a", "nM")]
    result = au.audit(rows)
    assert "ucum_coverage" in result
    cov = result["ucum_coverage"]
    assert cov["n_concentration_class"] == 2
    assert cov["n_ucum_mapped"] == 2
    assert cov["ucum_rate"] == pytest.approx(1.0)


def test_audit_ucum_coverage_partial():
    rows = [_row("EGF", "ng/mL"), _row("mystery", "cells/well")]
    result = au.audit(rows)
    cov = result["ucum_coverage"]
    # ng/mL is concentration and maps to UCUM; cells/well is "other" class (suspect, excluded from conc_rows)
    assert cov["n_concentration_class"] == 1
    assert cov["n_ucum_mapped"] == 1


def test_audit_ucum_canon_to_ucum_map():
    rows = [_row("EGF", "ng/mL"), _row("IGF1", "µg/mL")]
    result = au.audit(rows)
    cov = result["ucum_coverage"]
    assert "ng/mL" in cov["canon_to_ucum"]
    assert cov["canon_to_ucum"]["ng/mL"] == "ng.mL-1"


def test_audit_returns_method_string():
    result = au.audit([])
    assert "R2" in result["method"]
    assert "ucum_unit" in result["method"]
