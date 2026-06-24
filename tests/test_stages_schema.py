"""
Schema v0.6 stages[] tests — closes #178.

Validates the TimelineStage richer fields and OrganoidProtocol.is_generation_protocol
gate. All tests run offline against inline data; no network, no filesystem.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "organoid_demo"))
from schema import (  # noqa: E402
    Concentration, OrganoidProtocol, OrganoidType, Reagent, SourceCells, TimelineStage,
)


# ---------------------------------------------------------------------------
# TimelineStage: new v0.6 fields
# ---------------------------------------------------------------------------

def test_timeline_stage_rich_fields():
    s = TimelineStage(
        name="EB aggregation",
        start_day=0,
        end_day=5,
        culture_vessel="ultra-low attachment 96-well",
        medium_base="E6",
        reagents=[
            Reagent(name="dorsomorphin",
                    concentration=Concentration(value=2.5, unit="µM"),
                    role="BMP inhibitor"),
            Reagent(name="SB431542",
                    concentration=Concentration(value=10.0, unit="µM"),
                    role="TGF-β inhibitor"),
        ],
        transition="Day 6: switch to neural differentiation medium",
    )
    d = s.model_dump()
    assert d["name"] == "EB aggregation"
    assert d["start_day"] == 0
    assert d["end_day"] == 5
    assert d["culture_vessel"] == "ultra-low attachment 96-well"
    assert d["medium_base"] == "E6"
    assert len(d["reagents"]) == 2
    assert d["reagents"][0]["name"] == "dorsomorphin"
    assert d["transition"] == "Day 6: switch to neural differentiation medium"


def test_timeline_stage_null_days_ok():
    """Condition-keyed protocols have null start/end days — must not raise."""
    s = TimelineStage(
        name="colonoid monolayer",
        start_day=None,
        end_day=None,
        transition="TEER > 150 Ω/cm²",
    )
    d = s.model_dump()
    assert d["start_day"] is None
    assert d["end_day"] is None
    assert "TEER" in d["transition"]


def test_timeline_stage_minimal():
    """Name is the only required field — all v0.6 additions are optional."""
    s = TimelineStage(name="neural induction")
    d = s.model_dump()
    assert d["culture_vessel"] is None
    assert d["medium_base"] is None
    assert d["transition"] is None
    assert d["reagents"] == []


# ---------------------------------------------------------------------------
# OrganoidProtocol: is_generation_protocol gate + stages[]
# ---------------------------------------------------------------------------

def test_is_generation_protocol_true():
    p = OrganoidProtocol(
        source_doi="10.1038/s41556-020-00613-6",
        organoid_type=OrganoidType.CEREBRAL,
        is_generation_protocol=True,
        stages=[
            TimelineStage(name="EB aggregation", start_day=0, end_day=5,
                          culture_vessel="ultra-low attachment 96-well", medium_base="E6"),
            TimelineStage(name="neural induction", start_day=6, end_day=24, medium_base="DMEM/F12"),
        ],
    )
    d = p.model_dump()
    assert d["is_generation_protocol"] is True
    assert len(d["stages"]) == 2
    assert d["schema_version"] == "0.6"


def test_is_generation_protocol_false_gates_stages():
    """Drug studies should produce is_generation_protocol=False and stages=[]."""
    p = OrganoidProtocol(
        source_doi="10.1016/j.stem.2020.01.001",
        organoid_type=OrganoidType.TUMOR,
        is_generation_protocol=False,
        stages=[],
    )
    d = p.model_dump()
    assert d["is_generation_protocol"] is False
    assert d["stages"] == []


def test_is_generation_protocol_none_ok():
    """None = not yet determined (old records before v0.6). Must not raise."""
    p = OrganoidProtocol(source_doi="10.1234/old", is_generation_protocol=None)
    assert p.is_generation_protocol is None


def test_schema_version():
    p = OrganoidProtocol(source_doi="10.1234/test")
    assert p.schema_version == "0.6"


# ---------------------------------------------------------------------------
# Backward compatibility: stages[] not present → empty list default
# ---------------------------------------------------------------------------

def test_stages_default_empty():
    p = OrganoidProtocol(source_doi="10.1234/compat")
    assert p.stages == []
