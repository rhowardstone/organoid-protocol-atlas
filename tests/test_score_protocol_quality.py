"""
Offline tests for score_protocol_quality pure logic.
No network, no real corpus reads.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import score_protocol_quality as spq


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _proto(
    pmcid="PMC001",
    organoid_type="intestinal",
    grounding_rate=1.0,
    reagents_total=10,
    timeline="3-day protocol",
    base_media="DMEM",
    matrix="Matrigel",
    passaging="enzymatic",
    assay_endpoints="immunofluorescence · qPCR",
    n_figure_confirmed=3,
) -> dict:
    return {
        "pmcid": pmcid,
        "organoid_type": organoid_type,
        "grounding_rate": grounding_rate,
        "reagents_total": reagents_total,
        "timeline": timeline,
        "base_media": base_media,
        "matrix": matrix,
        "passaging": passaging,
        "assay_endpoints": assay_endpoints,
        "n_figure_confirmed": n_figure_confirmed,
    }


# --------------------------------------------------------------------------- #
# _has_field
# --------------------------------------------------------------------------- #

def test_has_field_none():
    assert not spq._has_field(None)

def test_has_field_empty():
    assert not spq._has_field("")

def test_has_field_not_reported():
    assert not spq._has_field("not_reported")

def test_has_field_value():
    assert spq._has_field("Matrigel")

def test_has_field_numeric():
    assert spq._has_field(5)


# --------------------------------------------------------------------------- #
# score_protocol
# --------------------------------------------------------------------------- #

def test_score_protocol_perfect():
    """A fully populated protocol should score 1.0 (or near it)."""
    p = _proto(grounding_rate=1.0, reagents_total=5, n_figure_confirmed=3)
    result = spq.score_protocol(p)
    assert result["quality_score"] == pytest.approx(1.0)
    assert result["quality_tier"] == "gold"


def test_score_protocol_zero():
    """A completely empty protocol should score 0."""
    p = _proto(grounding_rate=0.0, reagents_total=0, timeline=None,
               base_media=None, matrix=None, passaging=None,
               assay_endpoints=None, n_figure_confirmed=0)
    result = spq.score_protocol(p)
    assert result["quality_score"] == pytest.approx(0.0)
    assert result["quality_tier"] == "bronze"


def test_score_protocol_grounding_quality():
    p = _proto(grounding_rate=0.8, reagents_total=0, timeline=None,
               base_media=None, matrix=None, passaging=None,
               assay_endpoints=None, n_figure_confirmed=0)
    result = spq.score_protocol(p)
    assert result["score_components"]["grounding_quality"] == pytest.approx(0.8)


def test_score_protocol_reagent_coverage_capped_at_1():
    p = _proto(reagents_total=100, grounding_rate=0, timeline=None,
               base_media=None, matrix=None, passaging=None,
               assay_endpoints=None, n_figure_confirmed=0)
    result = spq.score_protocol(p)
    assert result["score_components"]["reagent_coverage"] == pytest.approx(1.0)


def test_score_protocol_reagent_coverage_partial():
    p = _proto(reagents_total=2, grounding_rate=0, timeline=None,
               base_media=None, matrix=None, passaging=None,
               assay_endpoints=None, n_figure_confirmed=0)
    result = spq.score_protocol(p)
    # 2/5 = 0.4
    assert result["score_components"]["reagent_coverage"] == pytest.approx(0.4)


def test_score_protocol_context_richness_all_four():
    p = _proto(timeline="3d", base_media="DMEM", matrix="Matrigel", passaging="enz")
    result = spq.score_protocol(p)
    assert result["score_components"]["context_richness"] == pytest.approx(1.0)


def test_score_protocol_context_richness_two():
    p = _proto(timeline="3d", base_media="DMEM", matrix=None, passaging=None)
    result = spq.score_protocol(p)
    assert result["score_components"]["context_richness"] == pytest.approx(0.5)


def test_score_protocol_context_richness_none():
    p = _proto(timeline=None, base_media=None, matrix=None, passaging=None)
    result = spq.score_protocol(p)
    assert result["score_components"]["context_richness"] == pytest.approx(0.0)


def test_score_protocol_assay_coverage_present():
    p = _proto(assay_endpoints="immunofluorescence")
    result = spq.score_protocol(p)
    assert result["score_components"]["assay_coverage"] == pytest.approx(1.0)


def test_score_protocol_assay_coverage_absent():
    p = _proto(assay_endpoints=None)
    result = spq.score_protocol(p)
    assert result["score_components"]["assay_coverage"] == pytest.approx(0.0)


def test_score_protocol_figure_support_capped():
    p = _proto(n_figure_confirmed=10, grounding_rate=0, reagents_total=0,
               timeline=None, base_media=None, matrix=None, passaging=None,
               assay_endpoints=None)
    result = spq.score_protocol(p)
    assert result["score_components"]["figure_support"] == pytest.approx(1.0)


def test_score_protocol_figure_support_partial():
    p = _proto(n_figure_confirmed=1, grounding_rate=0, reagents_total=0,
               timeline=None, base_media=None, matrix=None, passaging=None,
               assay_endpoints=None)
    result = spq.score_protocol(p)
    # 1/3 ≈ 0.333
    assert result["score_components"]["figure_support"] == pytest.approx(1/3, abs=0.01)


def test_score_protocol_none_grounding_rate():
    p = _proto(grounding_rate=None)
    result = spq.score_protocol(p)
    assert result["score_components"]["grounding_quality"] == pytest.approx(0.0)


def test_score_protocol_silver_tier():
    # Carefully craft a score between 0.55 and 0.80
    # grounding=1.0, reagent=0, context=0.5, assay=1, figure=0 → mean=0.5 → bronze?
    # grounding=1.0, reagent=1.0, context=0.5, assay=1, figure=0 → mean=0.7 → silver
    p = _proto(grounding_rate=1.0, reagents_total=10, timeline="3d", base_media="DMEM",
               matrix=None, passaging=None, assay_endpoints="qPCR", n_figure_confirmed=0)
    result = spq.score_protocol(p)
    assert result["quality_tier"] == "silver"


def test_score_protocol_gold_tier():
    p = _proto()
    result = spq.score_protocol(p)
    assert result["quality_tier"] == "gold"


def test_score_protocol_returns_pmcid():
    p = _proto(pmcid="PMC12345")
    result = spq.score_protocol(p)
    assert result["pmcid"] == "PMC12345"


# --------------------------------------------------------------------------- #
# score_all_protocols
# --------------------------------------------------------------------------- #

def test_score_all_empty():
    report = spq.score_all_protocols([])
    assert report["n_total"] == 0
    assert report["avg_score"] is None


def test_score_all_counts_tiers():
    ps = [
        _proto(pmcid="PMC001"),               # gold
        _proto(pmcid="PMC002", grounding_rate=0, reagents_total=0,
               timeline=None, base_media=None, matrix=None, passaging=None,
               assay_endpoints=None, n_figure_confirmed=0),  # bronze
    ]
    report = spq.score_all_protocols(ps)
    assert report["n_gold"] == 1
    assert report["n_bronze"] == 1
    assert report["n_total"] == 2


def test_score_all_sorted_descending():
    ps = [
        _proto(pmcid="PMC001", grounding_rate=0.0, reagents_total=0,
               timeline=None, base_media=None, matrix=None, passaging=None,
               assay_endpoints=None, n_figure_confirmed=0),
        _proto(pmcid="PMC002"),  # perfect
    ]
    report = spq.score_all_protocols(ps)
    assert report["scores"][0]["pmcid"] == "PMC002"


def test_score_all_by_type_aggregation():
    ps = [
        _proto(pmcid="PMC001", organoid_type="cardiac"),
        _proto(pmcid="PMC002", organoid_type="cardiac", grounding_rate=0.5,
               reagents_total=2, timeline=None, base_media=None,
               matrix=None, passaging=None, assay_endpoints=None,
               n_figure_confirmed=0),
    ]
    report = spq.score_all_protocols(ps)
    cardiac = report["by_organoid_type"]["cardiac"]
    assert cardiac["n_papers"] == 2
    assert cardiac["n_gold"] == 1


def test_score_all_avg_score():
    ps = [
        _proto(pmcid="PMC001"),  # score=1.0
        _proto(pmcid="PMC002", grounding_rate=0, reagents_total=0,
               timeline=None, base_media=None, matrix=None, passaging=None,
               assay_endpoints=None, n_figure_confirmed=0),  # score=0.0
    ]
    report = spq.score_all_protocols(ps)
    assert report["avg_score"] == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# load_protocols
# --------------------------------------------------------------------------- #

def test_load_protocols_missing():
    result = spq.load_protocols(Path("/tmp/nonexistent_quality_xyz.jsonl"))
    assert result == []


def test_load_protocols_reads_file():
    p = _proto()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps(p) + "\n")
        fname = Path(f.name)
    try:
        rows = spq.load_protocols(fname)
        assert len(rows) == 1
    finally:
        fname.unlink()
