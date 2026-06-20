"""
Tier-1 extraction tests for the v0.3 fields (culture_conditions + cell-line RRID).

Pins the grounding discipline (no network): a numeric culture condition is kept
only when the model's quote is verbatim AND the number appears in that quote;
RRID/line_name are kept only when verbatim in the source — RRID must not become an
ungrounded convenience field (PR #4 supervisor note). Honest NOT_EXTRACTED default.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from tier1_extract import to_protocol  # noqa: E402

DOI = "10.0/test"


def test_culture_conditions_grounded_when_quote_verbatim():
    evidence = "Organoids were cultured at 37 °C in 5% CO2 and ambient (20%) O2."
    m = {"culture_conditions": {"temperature_c": 37, "co2_pct": 5, "o2_pct": 20,
                                "evidence_quote": "cultured at 37 °C in 5% CO2"}}
    p, _ = to_protocol(DOI, m, evidence)
    assert p.culture_conditions.reporting.value == "reported"
    assert p.culture_conditions.temperature_c == 37 and p.culture_conditions.co2_pct == 5
    # o2=20 is NOT in the provided quote -> dropped (number not in the verbatim span)
    assert p.culture_conditions.o2_pct is None


def test_culture_conditions_rejected_when_quote_not_verbatim():
    evidence = "Standard incubation was used."
    m = {"culture_conditions": {"temperature_c": 37, "co2_pct": 5,
                                "evidence_quote": "cultured at 37 C in 5% CO2"}}  # not in evidence
    p, _ = to_protocol(DOI, m, evidence)
    assert p.culture_conditions.reporting.value == "not_extracted"
    assert p.culture_conditions.temperature_c is None


def test_rrid_and_line_name_must_be_verbatim():
    evidence = "iPSC line WTC-11 (RRID:CVCL_Y803) was maintained on Matrigel."
    m = {"source_cells": {"line_name": "WTC-11", "rrid": "CVCL_Y803"}}
    p, _ = to_protocol(DOI, m, evidence)
    assert p.source_cells.line_name == "WTC-11"
    assert p.source_cells.rrid == "CVCL_Y803"
    assert p.source_cells.evidence is not None


def test_hallucinated_rrid_is_dropped():
    evidence = "iPSCs were used; no accession given."
    m = {"source_cells": {"line_name": "H9", "rrid": "CVCL_9773"}}  # neither in evidence
    p, _ = to_protocol(DOI, m, evidence)
    assert p.source_cells.rrid is None and p.source_cells.line_name is None
