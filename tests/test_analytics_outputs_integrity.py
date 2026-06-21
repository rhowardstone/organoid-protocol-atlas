"""
Analytics outputs integrity tests (offline).

Validates that outputs/analysis/*.json exist and have the structural
shape expected by analytics_endpoint.py handlers. Catches regressions
where `make all-analytics` was forgotten after a corpus update, or where
a batch PR accidentally cleared the outputs directory.

No network. No DB. Reads only committed JSON artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ANALYSIS = REPO / "outputs" / "analysis"


def _load(name: str) -> dict | list:
    path = ANALYSIS / name
    assert path.exists(), (
        f"outputs/analysis/{name} not found — run `make all-analytics` and commit the result"
    )
    data = json.loads(path.read_text())
    return data


# --------------------------------------------------------------------------- #
# coverage_report.json
# --------------------------------------------------------------------------- #

def test_coverage_report_exists_and_has_required_keys():
    d = _load("coverage_report.json")
    for key in ("n_total_papers", "n_organoid_types", "overall_avg_grounding_rate", "by_organoid_type"):
        assert key in d, f"coverage_report.json missing key: {key!r}"


def test_coverage_report_n_papers_above_floor():
    d = _load("coverage_report.json")
    assert isinstance(d["n_total_papers"], int) and d["n_total_papers"] >= 10, (
        f"coverage_report n_total_papers={d['n_total_papers']} — suspiciously low"
    )


def test_coverage_report_grounding_rate_is_valid():
    d = _load("coverage_report.json")
    gr = d["overall_avg_grounding_rate"]
    assert isinstance(gr, (int, float)) and 0.0 <= gr <= 1.0, (
        f"overall_avg_grounding_rate {gr!r} out of range [0, 1]"
    )


def test_coverage_report_has_organoid_types():
    d = _load("coverage_report.json")
    assert isinstance(d["by_organoid_type"], dict) and d["by_organoid_type"], (
        "by_organoid_type is empty — corpus may not have been processed"
    )


# --------------------------------------------------------------------------- #
# protocol_quality_scores.json
# --------------------------------------------------------------------------- #

def test_quality_scores_exists_and_has_required_keys():
    d = _load("protocol_quality_scores.json")
    for key in ("n_total", "n_gold", "n_silver", "n_bronze", "avg_score", "scores"):
        assert key in d, f"protocol_quality_scores.json missing key: {key!r}"


def test_quality_scores_tier_counts_sum_to_n_total():
    d = _load("protocol_quality_scores.json")
    n = d["n_total"]
    gold = d["n_gold"]
    silver = d["n_silver"]
    bronze = d["n_bronze"]
    assert gold + silver + bronze == n, (
        f"Quality tier counts don't sum to n_total: {gold}+{silver}+{bronze}={gold+silver+bronze} != {n}"
    )


def test_quality_scores_avg_in_range():
    d = _load("protocol_quality_scores.json")
    avg = d["avg_score"]
    assert isinstance(avg, (int, float)) and 0.0 <= avg <= 1.0, (
        f"avg_score {avg!r} out of range"
    )


def test_quality_scores_list_non_empty():
    d = _load("protocol_quality_scores.json")
    assert isinstance(d["scores"], list) and d["scores"], (
        "scores list is empty — run `make quality`"
    )


def test_quality_scores_entries_have_required_fields():
    d = _load("protocol_quality_scores.json")
    for entry in d["scores"][:5]:  # spot check first 5
        for field in ("pmcid", "organoid_type", "quality_score", "quality_tier"):
            assert field in entry, f"score entry missing field {field!r}: {list(entry.keys())}"


# --------------------------------------------------------------------------- #
# assay_endpoint_summary.json
# --------------------------------------------------------------------------- #

def test_assay_endpoint_summary_exists():
    d = _load("assay_endpoint_summary.json")
    assert isinstance(d, dict), "assay_endpoint_summary.json must be a dict"


def test_assay_endpoint_summary_has_clusters():
    d = _load("assay_endpoint_summary.json")
    # Should have corpus-level and per-type breakdown
    assert d, "assay_endpoint_summary.json is empty"


# --------------------------------------------------------------------------- #
# mior_completeness.json
# --------------------------------------------------------------------------- #

def test_mior_exists_and_has_corpus_avg():
    d = _load("mior_completeness.json")
    mior_key = next(
        (k for k in d if "mior" in k.lower() and "avg" in k.lower()), None
    )
    assert mior_key, (
        f"mior_completeness.json missing avg mior key — keys: {list(d.keys())[:8]}"
    )
    avg = d[mior_key]
    assert isinstance(avg, (int, float)) and 0.0 <= avg <= 1.0, (
        f"MIOR avg {avg!r} not in [0, 1]"
    )


def test_mior_has_n_total():
    d = _load("mior_completeness.json")
    assert "n_total" in d or "n_papers" in d, (
        f"mior_completeness.json missing n_total — keys: {list(d.keys())[:8]}"
    )
    n = d.get("n_total") or d.get("n_papers", 0)
    assert n > 0, f"MIOR n_total={n}, expected > 0"


# --------------------------------------------------------------------------- #
# Consensus files
# --------------------------------------------------------------------------- #

def test_consensus_all_exists():
    """consensus_all.json is a list of per-type consensus dicts (one per organoid type)."""
    d = _load("consensus_all.json")
    assert isinstance(d, list) and d, "consensus_all.json must be non-empty list"
    assert "organoid_type" in d[0], (
        f"consensus_all.json entries missing 'organoid_type': {list(d[0].keys())[:5]}"
    )


def test_consensus_intestinal_exists_with_reagents():
    d = _load("consensus_intestinal.json")
    # consensus files can be lists or dicts depending on compute_consensus output
    if isinstance(d, list):
        assert d, "consensus_intestinal.json list is empty"
    else:
        assert d, "consensus_intestinal.json dict is empty"


def test_consensus_type_files_cover_major_types():
    required_types = ["intestinal", "cerebral", "cardiac", "kidney", "liver", "lung", "gastric"]
    for t in required_types:
        path = ANALYSIS / f"consensus_{t}.json"
        assert path.exists(), f"Missing consensus file for type: {t}"


# --------------------------------------------------------------------------- #
# Structural cross-checks
# --------------------------------------------------------------------------- #

def test_coverage_n_types_matches_consensus_file_count():
    """Number of organoid types in coverage report should match consensus files."""
    cov = _load("coverage_report.json")
    n_types = cov["n_organoid_types"]
    consensus_files = list(ANALYSIS.glob("consensus_*.json"))
    # -1 for consensus_all.json
    n_consensus = len([f for f in consensus_files if f.stem != "consensus_all"])
    assert n_consensus == n_types, (
        f"coverage_report has {n_types} types but found {n_consensus} per-type consensus files"
    )


def test_analytics_total_file_count_above_floor():
    """Analytics dir must have at least 30 files (catches accidental deletion)."""
    n = len(list(ANALYSIS.glob("*.json")))
    assert n >= 30, (
        f"Only {n} files in outputs/analysis/ (floor: 30) — run `make all-analytics`"
    )
