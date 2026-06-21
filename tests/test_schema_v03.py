"""
Schema v0.3/v0.4 contract tests.

Pins the deliberate v0.3 additions (approved in issue #2): culture_conditions
{temperature_c, co2_pct, o2_pct}, cell-line identity via SourceCells.rrid, and the
three-state reporting with an honest NOT_EXTRACTED default.

v0.4 additions: FailureMode, ProtocolModification, Evidence.sentence_id.
No extraction wiring is exercised here -- these guard the contract itself.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "organoid_demo"))
from schema import (  # noqa: E402
    CultureConditions, Evidence, FailureMode, OrganoidProtocol,
    ProtocolModification, Reporting, SourceCells,
)


# --------------------------------------------------------------------------- #
# v0.3 contract tests (unchanged -- backward-compat guard)
# --------------------------------------------------------------------------- #

def test_schema_version_is_03():
    # NOTE: this test is superseded by test_schema_version_is_04 below.
    # Kept (renamed) so any external tooling referencing it does not silently
    # disappear. The version is now 0.4.
    pass  # see test_schema_version_is_04


def test_reporting_has_not_extracted():
    assert Reporting.NOT_EXTRACTED.value == "not_extracted"
    # the original three states still exist (no silent removal)
    assert {Reporting.REPORTED, Reporting.NOT_REPORTED, Reporting.NOT_APPLICABLE}


def test_culture_conditions_defaults_to_not_extracted():
    # honest unknown by default -- never asserts "not reported" without evidence
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
    # rrid is optional -- absence is allowed
    assert SourceCells().rrid is None


# --------------------------------------------------------------------------- #
# v0.4 contract tests
# --------------------------------------------------------------------------- #

def test_schema_version_is_04():
    """Schema version must be 0.4 in a fresh OrganoidProtocol."""
    p = OrganoidProtocol(source_doi="10.x")
    assert p.schema_version == "0.4", (
        f"Expected schema_version '0.4', got {p.schema_version!r}"
    )


def test_failure_mode_model():
    """FailureMode captures description + optional condition + optional Evidence."""
    fm = FailureMode(
        description="Organoids detach from Matrigel during expansion",
        condition="if Matrigel is thawed at room temperature before use",
        evidence=Evidence(
            source_doi="10.1016/j.stem.2019.08.001",
            quote="Matrigel must remain on ice; premature warming causes gelation failure.",
            section="Methods",
            sentence_id=4,
            confidence=0.88,
        ),
    )
    assert fm.description == "Organoids detach from Matrigel during expansion"
    assert fm.condition == "if Matrigel is thawed at room temperature before use"
    assert fm.evidence is not None
    assert fm.evidence.sentence_id == 4
    assert fm.evidence.confidence == 0.88

    # condition and evidence are both optional
    fm_minimal = FailureMode(description="Protocol fails without Y-27632 at seeding")
    assert fm_minimal.condition is None
    assert fm_minimal.evidence is None


def test_protocol_modification_model():
    """ProtocolModification captures the delta from a cited prior protocol."""
    mod = ProtocolModification(
        cited_doi="10.1038/nmeth.1940",
        change_description="Replaced Noggin with LDN-193189 (1 uM) for BMP inhibition",
        evidence=Evidence(
            source_doi="10.1016/j.stem.2021.04.005",
            quote="We substituted Noggin with the small-molecule inhibitor LDN-193189.",
            section="Methods",
            sentence_id=1,
            confidence=0.95,
        ),
    )
    assert mod.cited_doi == "10.1038/nmeth.1940"
    assert "LDN-193189" in mod.change_description
    assert mod.evidence is not None
    assert mod.evidence.sentence_id == 1

    # cited_doi and evidence are both optional
    mod_minimal = ProtocolModification(
        change_description="Extended neural induction phase from 6 to 10 days"
    )
    assert mod_minimal.cited_doi is None
    assert mod_minimal.evidence is None


def test_evidence_sentence_id():
    """Evidence.sentence_id is Optional[int] and defaults to None."""
    ev_with = Evidence(
        source_doi="10.x",
        quote="Cells were seeded at 5000 per well.",
        section="Methods",
        sentence_id=3,
        confidence=0.9,
    )
    assert ev_with.sentence_id == 3

    ev_without = Evidence(source_doi="10.x", quote="Cells were seeded.", confidence=0.7)
    assert ev_without.sentence_id is None


def test_organoid_protocol_has_failure_modes_and_modifications():
    """OrganoidProtocol.failure_modes and .modifications default to empty lists."""
    p = OrganoidProtocol(source_doi="10.x")
    assert p.failure_modes == []
    assert p.modifications == []

    # Can be populated at construction
    p2 = OrganoidProtocol(
        source_doi="10.x",
        failure_modes=[FailureMode(description="Spheroid collapse after day 14")],
        modifications=[
            ProtocolModification(
                cited_doi="10.1234/base",
                change_description="Added 10 uM CHIR99021 at day 2",
            )
        ],
    )
    assert len(p2.failure_modes) == 1
    assert p2.failure_modes[0].description == "Spheroid collapse after day 14"
    assert len(p2.modifications) == 1
    assert p2.modifications[0].cited_doi == "10.1234/base"
