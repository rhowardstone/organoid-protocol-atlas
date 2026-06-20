"""
Schema v0.3 contract tests.

Pins the deliberate v0.3 additions (approved in issue #2): culture_conditions
{temperature_c, co2_pct, o2_pct}, cell-line identity via SourceCells.rrid, and the
three-state reporting with an honest NOT_EXTRACTED default. No extraction wiring is
exercised here — these guard the contract itself.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "organoid_demo"))
from schema import (  # noqa: E402
    CultureConditions, OrganoidProtocol, Reporting, SourceCells,
)


def test_schema_version_is_03():
    assert OrganoidProtocol(source_doi="10.x").schema_version == "0.3"


def test_reporting_has_not_extracted():
    assert Reporting.NOT_EXTRACTED.value == "not_extracted"
    # the original three states still exist (no silent removal)
    assert {Reporting.REPORTED, Reporting.NOT_REPORTED, Reporting.NOT_APPLICABLE}


def test_culture_conditions_defaults_to_not_extracted():
    # honest unknown by default — never asserts "not reported" without evidence
    p = OrganoidProtocol(source_doi="10.x")
    assert p.culture_conditions.reporting == Reporting.NOT_EXTRACTED
    assert p.culture_conditions.o2_pct is None


def test_culture_conditions_populated():
    cc = CultureConditions(temperature_c=37.0, co2_pct=5.0, o2_pct=40.0,
                           reporting=Reporting.REPORTED)
    assert (cc.temperature_c, cc.co2_pct, cc.o2_pct) == (37.0, 5.0, 40.0)


def test_cell_line_rrid():
    sc = SourceCells(line_name="H9", rrid="CVCL_9773")
    assert sc.line_name == "H9" and sc.rrid == "CVCL_9773"
    # rrid is optional — absence is allowed
    assert SourceCells().rrid is None
