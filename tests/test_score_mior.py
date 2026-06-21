"""
Offline tests for score_mior.py MIOR completeness scoring.
No network, no real corpus reads.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import score_mior as sm


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _proto(
    pmcid="PMC001",
    organoid_type="intestinal",
    species="human",
    source_cell_type="adult_stem_cell",
    base_media="DMEM",
    matrix="Matrigel",
    passaging="enzymatic",
    timeline="21-day protocol",
    assay_endpoints="immunofluorescence · qPCR",
    n_signaling_factors=5,
    n_supplements=3,
    n_figure_confirmed=2,
    grounding_rate=0.9,
) -> dict:
    return {
        "pmcid": pmcid,
        "organoid_type": organoid_type,
        "species": species,
        "source_cell_type": source_cell_type,
        "base_media": base_media,
        "matrix": matrix,
        "passaging": passaging,
        "timeline": timeline,
        "assay_endpoints": assay_endpoints,
        "n_signaling_factors": n_signaling_factors,
        "n_supplements": n_supplements,
        "n_figure_confirmed": n_figure_confirmed,
        "grounding_rate": grounding_rate,
        "doi": "10.1000/test",
        "year": "2023",
    }


# --------------------------------------------------------------------------- #
# _field_status
# --------------------------------------------------------------------------- #

def test_field_status_none_is_not_extracted():
    assert sm._field_status(None, "species") == "not_extracted"

def test_field_status_empty_is_not_reported():
    assert sm._field_status("", "species") == "not_reported"

def test_field_status_not_reported_string():
    assert sm._field_status("not_reported", "species") == "not_reported"

def test_field_status_value_is_present():
    assert sm._field_status("human", "species") == "present"

def test_field_status_numeric_zero_is_not_reported():
    assert sm._field_status(0, "n_signaling_factors") == "not_reported"

def test_field_status_numeric_positive_is_present():
    assert sm._field_status(5, "n_signaling_factors") == "present"

def test_field_status_string_zero_is_not_reported():
    assert sm._field_status("0", "n_signaling_factors") == "not_reported"

def test_field_status_grounding_rate_zero_is_present():
    # 0.0 grounding rate is a valid (if poor) measurement
    assert sm._field_status(0.0, "grounding_rate") == "present"

def test_field_status_not_applicable():
    assert sm._field_status("not_applicable", "matrix") == "not_reported"


# --------------------------------------------------------------------------- #
# score_mior — single protocol
# --------------------------------------------------------------------------- #

def test_score_mior_full_protocol():
    """A fully populated protocol should have high completeness."""
    p = _proto()
    result = sm.score_mior(p)
    assert result["mior_completeness"] == pytest.approx(1.0)
    assert result["required_completeness"] == pytest.approx(1.0)
    assert result["n_present"] == len(sm.MIOR_ITEMS)
    assert result["n_not_reported"] == 0


def test_score_mior_empty_protocol():
    """Protocol with all None fields should have all not_extracted."""
    p = {
        "pmcid": "PMC000",
        "organoid_type": None,
        "species": None,
        "source_cell_type": None,
        "base_media": None,
        "matrix": None,
        "passaging": None,
        "timeline": None,
        "assay_endpoints": None,
        "n_signaling_factors": None,
        "n_supplements": None,
        "n_figure_confirmed": None,
        "grounding_rate": None,
    }
    result = sm.score_mior(p)
    assert result["n_not_extracted"] == len(sm.MIOR_ITEMS)
    assert result["mior_completeness"] is None  # no known items


def test_score_mior_explicitly_not_reported():
    """Fields explicitly not_reported count against completeness."""
    p = _proto(base_media="not_reported", matrix="not_reported")
    result = sm.score_mior(p)
    assert result["n_not_reported"] >= 2
    assert result["mior_completeness"] is not None
    assert result["mior_completeness"] < 1.0


def test_score_mior_items_have_all_fields():
    p = _proto()
    result = sm.score_mior(p)
    for item in result["items"]:
        assert "module" in item
        assert "item_id" in item
        assert "label" in item
        assert "status" in item
        assert item["status"] in ("present", "not_reported", "not_extracted")


def test_score_mior_returns_pmcid():
    p = _proto(pmcid="PMC99999")
    result = sm.score_mior(p)
    assert result["pmcid"] == "PMC99999"


def test_score_mior_required_vs_optional():
    """Protocols with only required fields present are still scored."""
    p = _proto(passaging=None, n_supplements=0, n_figure_confirmed=0)
    result = sm.score_mior(p)
    # required_completeness should still be 1.0 (all required present)
    assert result["required_completeness"] == pytest.approx(1.0)


def test_score_mior_completeness_formula():
    """Completeness = present / (present + not_reported)."""
    p = _proto(base_media="not_reported")
    result = sm.score_mior(p)
    expected = result["n_present"] / (result["n_present"] + result["n_not_reported"])
    assert result["mior_completeness"] == pytest.approx(expected, abs=0.001)


# --------------------------------------------------------------------------- #
# score_all_protocols
# --------------------------------------------------------------------------- #

def test_score_all_empty():
    report = sm.score_all_protocols([])
    assert report["n_total"] == 0
    assert report["avg_mior_completeness"] is None


def test_score_all_counts_tiers():
    ps = [
        _proto(pmcid="PMC001"),                           # full → ≥ 0.80
        _proto(pmcid="PMC002", base_media="not_reported",
               matrix="not_reported", timeline="not_reported"),  # partial
    ]
    report = sm.score_all_protocols(ps)
    assert report["n_total"] == 2
    assert report["n_full"] + report["n_partial"] + report["n_sparse"] == 2


def test_score_all_sorted_descending():
    ps = [
        _proto(pmcid="PMC001", base_media=None, matrix=None,
               timeline=None, assay_endpoints=None,
               n_signaling_factors=0),
        _proto(pmcid="PMC002"),  # high completeness
    ]
    report = sm.score_all_protocols(ps)
    assert report["scores"][0]["pmcid"] == "PMC002"


def test_score_all_item_reporting_rates_present():
    ps = [_proto()]
    report = sm.score_all_protocols(ps)
    assert "item_reporting_rates" in report
    for iid, stats in report["item_reporting_rates"].items():
        assert "label" in stats
        assert "reporting_rate" in stats


def test_score_all_by_type_aggregation():
    ps = [
        _proto(pmcid="PMC001", organoid_type="cardiac"),
        _proto(pmcid="PMC002", organoid_type="cardiac"),
    ]
    report = sm.score_all_protocols(ps)
    assert "cardiac" in report["by_organoid_type"]
    assert report["by_organoid_type"]["cardiac"]["n_papers"] == 2


def test_score_all_module_stats():
    ps = [_proto()]
    report = sm.score_all_protocols(ps)
    assert "module_stats" in report
    assert "M1_source_material" in report["module_stats"]


def test_score_all_avg_completeness():
    ps = [
        _proto(pmcid="PMC001"),  # 1.0
        _proto(pmcid="PMC002",
               species="not_reported", organoid_type="not_reported",
               source_cell_type="not_reported", base_media="not_reported",
               matrix="not_reported", passaging="not_reported",
               timeline="not_reported", assay_endpoints="not_reported",
               n_signaling_factors=0, n_supplements=0,
               n_figure_confirmed=0),  # 0.0
    ]
    report = sm.score_all_protocols(ps)
    assert report["avg_mior_completeness"] == pytest.approx(0.5, abs=0.05)


def test_score_all_scores_strip_items():
    """Corpus-level scores list should not include per-item detail (too large)."""
    ps = [_proto()]
    report = sm.score_all_protocols(ps)
    assert "items" not in report["scores"][0]


# --------------------------------------------------------------------------- #
# load_protocols
# --------------------------------------------------------------------------- #

def test_load_protocols_missing():
    result = sm.load_protocols(Path("/tmp/nonexistent_mior_xyz.jsonl"))
    assert result == []


def test_load_protocols_reads_file():
    p = _proto()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps(p) + "\n")
        fname = Path(f.name)
    try:
        rows = sm.load_protocols(fname)
        assert len(rows) == 1
        assert rows[0]["pmcid"] == "PMC001"
    finally:
        fname.unlink()


# --------------------------------------------------------------------------- #
# MIOR module structure
# --------------------------------------------------------------------------- #

def test_mior_items_have_required_modules():
    modules = {item.module for item in sm.MIOR_ITEMS}
    assert "M1_source_material" in modules
    assert "M2_culture_system" in modules
    assert "M3_timeline" in modules
    assert "M4_endpoints" in modules
    assert "M5_reproducibility" in modules


def test_mior_required_items_count():
    required = [i for i in sm.MIOR_ITEMS if i.required]
    # At minimum: species, organoid_type, source_cell_type, base_media, matrix,
    # signaling_factors, timeline, assay_endpoints
    assert len(required) >= 7


def test_mior_item_ids_unique():
    ids = [i.item_id for i in sm.MIOR_ITEMS]
    assert len(ids) == len(set(ids))
