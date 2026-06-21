"""
Offline tests for generate_coverage_report pure logic.
No network, no filesystem beyond fixtures.
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import generate_coverage_report as gcr


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_protocol(
    organoid_type="cardiac",
    grounding_rate=0.9,
    n_signaling_factors=5,
    timeline="3-day",
    base_media="DMEM",
    matrix="Matrigel",
    passaging="enzymatic",
    assay_endpoints="qPCR · immunostaining",
    n_figure_confirmed=2,
    species="human",
    source_cell_type="adult_stem_cell",
    year="2022",
    reagents_grounded=9,
    reagents_total=10,
) -> dict:
    return {
        "organoid_type": organoid_type,
        "grounding_rate": grounding_rate,
        "n_signaling_factors": n_signaling_factors,
        "timeline": timeline,
        "base_media": base_media,
        "matrix": matrix,
        "passaging": passaging,
        "assay_endpoints": assay_endpoints,
        "n_figure_confirmed": n_figure_confirmed,
        "species": species,
        "source_cell_type": source_cell_type,
        "year": year,
        "reagents_grounded": reagents_grounded,
        "reagents_total": reagents_total,
    }


# --------------------------------------------------------------------------- #
# _is_truthy
# --------------------------------------------------------------------------- #

def test_is_truthy_none():
    assert not gcr._is_truthy(None)

def test_is_truthy_empty_string():
    assert not gcr._is_truthy("")

def test_is_truthy_not_reported():
    assert not gcr._is_truthy("not_reported")

def test_is_truthy_not_extracted():
    assert not gcr._is_truthy("not_extracted")

def test_is_truthy_not_applicable():
    assert not gcr._is_truthy("not_applicable")

def test_is_truthy_tbd():
    assert not gcr._is_truthy("tbd")

def test_is_truthy_real_value():
    assert gcr._is_truthy("Matrigel")

def test_is_truthy_zero_string():
    assert not gcr._is_truthy("0")

def test_is_truthy_numeric_nonzero():
    assert gcr._is_truthy("5")


# --------------------------------------------------------------------------- #
# compute_type_coverage
# --------------------------------------------------------------------------- #

def test_compute_type_coverage_empty():
    result = gcr.compute_type_coverage([])
    assert result["n_papers"] == 0
    assert result["completeness_score"] == 0.0


def test_compute_type_coverage_single():
    p = _make_protocol()
    result = gcr.compute_type_coverage([p])
    assert result["n_papers"] == 1
    assert result["avg_grounding_rate"] == pytest.approx(0.9)
    assert result["n_with_signaling_factors"] == 1
    assert result["n_with_timeline"] == 1
    assert result["n_with_base_media"] == 1
    assert result["n_with_matrix"] == 1
    assert result["n_with_passaging"] == 1
    assert result["n_with_assay_endpoints"] == 1
    assert result["n_figure_confirmed_total"] == 2
    assert result["year_range"] == [2022, 2022]


def test_compute_type_coverage_grounding_average():
    ps = [_make_protocol(grounding_rate=0.8), _make_protocol(grounding_rate=1.0)]
    result = gcr.compute_type_coverage(ps)
    assert result["avg_grounding_rate"] == pytest.approx(0.9)


def test_compute_type_coverage_pooled_grounding():
    # 8/10 + 9/10 = 17/20 = 0.85
    ps = [
        _make_protocol(reagents_grounded=8, reagents_total=10),
        _make_protocol(reagents_grounded=9, reagents_total=10),
    ]
    result = gcr.compute_type_coverage(ps)
    assert result["pooled_grounding_rate"] == pytest.approx(0.85)


def test_compute_type_coverage_missing_grounding_rate():
    p = _make_protocol(grounding_rate=None)
    result = gcr.compute_type_coverage([p])
    assert result["avg_grounding_rate"] is None


def test_compute_type_coverage_none_fields_not_counted():
    p = _make_protocol(timeline=None, base_media=None, matrix=None,
                       passaging=None, assay_endpoints=None)
    result = gcr.compute_type_coverage([p])
    assert result["n_with_timeline"] == 0
    assert result["n_with_base_media"] == 0
    assert result["n_with_matrix"] == 0
    assert result["n_with_passaging"] == 0
    assert result["n_with_assay_endpoints"] == 0


def test_compute_type_coverage_not_reported_not_counted():
    p = _make_protocol(timeline="not_reported", base_media="not_extracted")
    result = gcr.compute_type_coverage([p])
    assert result["n_with_timeline"] == 0
    assert result["n_with_base_media"] == 0


def test_compute_type_coverage_zero_signaling_not_counted():
    p = _make_protocol(n_signaling_factors=0)
    result = gcr.compute_type_coverage([p])
    assert result["n_with_signaling_factors"] == 0


def test_compute_type_coverage_species_aggregation():
    ps = [
        _make_protocol(species="human"),
        _make_protocol(species="human"),
        _make_protocol(species="mouse"),
    ]
    result = gcr.compute_type_coverage(ps)
    assert result["n_species"] == 2
    top = {s["species"]: s["count"] for s in result["top_species"]}
    assert top["human"] == 2
    assert top["mouse"] == 1


def test_compute_type_coverage_year_range():
    ps = [_make_protocol(year="2019"), _make_protocol(year="2023")]
    result = gcr.compute_type_coverage(ps)
    assert result["year_range"] == [2019, 2023]


def test_compute_type_coverage_grounding_distribution():
    # poor (<0.5), moderate (0.5–0.8), good (0.8–1.0), perfect (1.0)
    ps = [
        _make_protocol(grounding_rate=0.3),   # poor
        _make_protocol(grounding_rate=0.65),  # moderate
        _make_protocol(grounding_rate=0.9),   # good
        _make_protocol(grounding_rate=1.0),   # perfect
    ]
    result = gcr.compute_type_coverage(ps)
    dist = result["grounding_distribution"]
    assert dist["poor_lt50"] == 1
    assert dist["moderate_50_80"] == 1
    assert dist["good_80_100"] == 1
    assert dist["perfect_100"] == 1


def test_compute_type_coverage_figure_confirmed_total():
    ps = [_make_protocol(n_figure_confirmed=3), _make_protocol(n_figure_confirmed=2)]
    result = gcr.compute_type_coverage(ps)
    assert result["n_figure_confirmed_total"] == 5


# --------------------------------------------------------------------------- #
# _completeness_score
# --------------------------------------------------------------------------- #

def test_completeness_score_all_zero():
    assert gcr._completeness_score(0, None, 0, 0, 0) == 0.0


def test_completeness_score_perfect():
    # All components = 1.0 → score = 1.0
    score = gcr._completeness_score(100, 1.0, 100, 100, 100)
    assert score == pytest.approx(1.0)


def test_completeness_score_partial():
    # n=10: breadth = log10(10)/2 = 0.5
    score = gcr._completeness_score(10, 0.8, 5, 5, 5)
    # sf=0.5, bm=0.5, mx=0.5, gr=0.8, breadth=0.5 → mean = 0.56
    assert 0.4 < score < 0.7


def test_completeness_score_no_grounding():
    # grounding = 0.0 when None
    score = gcr._completeness_score(100, None, 100, 100, 100)
    # sf=1, bm=1, mx=1, gr=0, breadth=1 → mean = 0.8
    assert score == pytest.approx(0.8)


# --------------------------------------------------------------------------- #
# generate_coverage_report
# --------------------------------------------------------------------------- #

def test_generate_coverage_report_groups_by_type():
    ps = [
        _make_protocol(organoid_type="cardiac"),
        _make_protocol(organoid_type="cardiac"),
        _make_protocol(organoid_type="retinal"),
    ]
    report = gcr.generate_coverage_report(ps)
    assert report["n_organoid_types"] == 2
    assert report["n_total_papers"] == 3
    assert report["by_organoid_type"]["cardiac"]["n_papers"] == 2
    assert report["by_organoid_type"]["retinal"]["n_papers"] == 1


def test_generate_coverage_report_min_papers_filter():
    ps = [
        _make_protocol(organoid_type="cardiac"),
        _make_protocol(organoid_type="cardiac"),
        _make_protocol(organoid_type="rare"),
    ]
    report = gcr.generate_coverage_report(ps, min_papers=2)
    assert report["n_organoid_types"] == 1
    assert "rare" not in report["by_organoid_type"]


def test_generate_coverage_report_ranked_by_completeness():
    # cardiac: 10 papers, perfect grounding; retinal: 1 paper, 0 grounding
    ps_cardiac = [_make_protocol(organoid_type="cardiac")] * 10
    ps_retinal = [_make_protocol(organoid_type="retinal", grounding_rate=0.0,
                                 n_signaling_factors=0, base_media=None, matrix=None)] * 1
    report = gcr.generate_coverage_report(ps_cardiac + ps_retinal)
    ranked = [r["organoid_type"] for r in report["types_by_completeness"]]
    assert ranked[0] == "cardiac"


def test_generate_coverage_report_overall_avg_grounding():
    ps = [
        _make_protocol(organoid_type="cardiac", grounding_rate=0.8),
        _make_protocol(organoid_type="retinal", grounding_rate=1.0),
    ]
    report = gcr.generate_coverage_report(ps)
    # avg of type averages: (0.8 + 1.0) / 2 = 0.9
    assert report["overall_avg_grounding_rate"] == pytest.approx(0.9)


def test_generate_coverage_report_corpus_pooled_grounding():
    ps = [
        _make_protocol(organoid_type="cardiac", reagents_grounded=8, reagents_total=10),
        _make_protocol(organoid_type="retinal", reagents_grounded=9, reagents_total=10),
    ]
    report = gcr.generate_coverage_report(ps)
    # pooled: 17 / 20 = 0.85
    assert report["corpus_pooled_grounding_rate"] == pytest.approx(0.85)


def test_generate_coverage_report_empty():
    report = gcr.generate_coverage_report([])
    assert report["n_total_papers"] == 0
    assert report["n_organoid_types"] == 0


# --------------------------------------------------------------------------- #
# load_protocols
# --------------------------------------------------------------------------- #

def test_load_protocols_from_file():
    p = _make_protocol()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps(p) + "\n")
        fname = Path(f.name)
    try:
        rows = gcr.load_protocols(fname)
        assert len(rows) == 1
        assert rows[0]["organoid_type"] == "cardiac"
    finally:
        fname.unlink()


def test_load_protocols_skips_blank_lines():
    p = _make_protocol()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps(p) + "\n\n\n")
        fname = Path(f.name)
    try:
        rows = gcr.load_protocols(fname)
        assert len(rows) == 1
    finally:
        fname.unlink()


def test_load_protocols_missing_file():
    rows = gcr.load_protocols(Path("/tmp/nonexistent_coverage_report_xyz.jsonl"))
    assert rows == []
