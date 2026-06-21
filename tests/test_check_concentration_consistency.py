"""
Offline tests for check_concentration_consistency.py.
No filesystem access — all functions are pure.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import check_concentration_consistency as ccc


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _row(
    canonical="EGF",
    unit="ng/mL",
    value=100.0,
    pmcid="PMC001",
    organoid_type="intestinal",
    name="EGF",
    id_=None,
    evidence_quote="",
):
    return {
        "canonical": canonical,
        "canonical_unit": unit,
        "value": value,
        "pmcid": pmcid,
        "organoid_type": organoid_type,
        "name": name,
        "id": id_ or f"{pmcid}_{canonical}",
        "evidence_quote": evidence_quote,
    }


# --------------------------------------------------------------------------- #
# _median
# --------------------------------------------------------------------------- #

def test_median_odd():
    assert ccc._median([1, 2, 3]) == 2.0


def test_median_even():
    assert ccc._median([1, 2, 3, 4]) == 2.5


def test_median_single():
    assert ccc._median([7.0]) == 7.0


def test_median_sorted_order_independence():
    assert ccc._median([3, 1, 2]) == ccc._median([1, 2, 3])


# --------------------------------------------------------------------------- #
# group_reagents — filtering
# --------------------------------------------------------------------------- #

def test_group_empty_input():
    assert ccc.group_reagents([]) == {}


def test_group_skips_missing_canonical():
    rows = [_row(canonical="", unit="ng/mL", value=10.0)]
    assert ccc.group_reagents(rows) == {}


def test_group_skips_missing_unit():
    rows = [_row(canonical="EGF", unit="", value=10.0)]
    assert ccc.group_reagents(rows) == {}


def test_group_skips_none_value():
    row = _row()
    row["value"] = None
    assert ccc.group_reagents([row]) == {}


def test_group_skips_zero_value():
    assert ccc.group_reagents([_row(value=0.0)]) == {}


def test_group_skips_negative_value():
    assert ccc.group_reagents([_row(value=-5.0)]) == {}


def test_group_skips_non_numeric_value():
    row = _row()
    row["value"] = "unknown"
    assert ccc.group_reagents([row]) == {}


def test_group_accepts_string_numeric_value():
    # Pipeline sometimes writes numbers as strings
    row = _row(value="50.0")
    groups = ccc.group_reagents([row])
    assert ("EGF", "ng/mL") in groups
    assert groups[("EGF", "ng/mL")][0]["value"] == 50.0


def test_group_strips_whitespace_from_canonical():
    rows = [_row(canonical="  EGF  ", unit="ng/mL", value=10.0)]
    groups = ccc.group_reagents(rows)
    assert ("EGF", "ng/mL") in groups


def test_group_single_record():
    rows = [_row(canonical="EGF", unit="ng/mL", value=100.0)]
    groups = ccc.group_reagents(rows)
    assert len(groups) == 1
    assert len(groups[("EGF", "ng/mL")]) == 1


def test_group_two_records_same_group():
    rows = [
        _row(canonical="EGF", unit="ng/mL", value=100.0, pmcid="PMC001"),
        _row(canonical="EGF", unit="ng/mL", value=200.0, pmcid="PMC002"),
    ]
    groups = ccc.group_reagents(rows)
    assert len(groups[("EGF", "ng/mL")]) == 2


def test_group_different_units_produce_separate_groups():
    rows = [
        _row(canonical="EGF", unit="ng/mL", value=100.0, pmcid="PMC001"),
        _row(canonical="EGF", unit="nM", value=50.0, pmcid="PMC002"),
    ]
    groups = ccc.group_reagents(rows)
    assert ("EGF", "ng/mL") in groups
    assert ("EGF", "nM") in groups
    assert len(groups) == 2


def test_group_evidence_quote_truncated():
    long_quote = "x" * 200
    rows = [_row(evidence_quote=long_quote)]
    groups = ccc.group_reagents(rows)
    member = groups[("EGF", "ng/mL")][0]
    assert len(member["evidence_quote"]) <= ccc.EVIDENCE_SNIPPET_MAX


# --------------------------------------------------------------------------- #
# find_outliers — group filtering
# --------------------------------------------------------------------------- #

def test_outliers_empty_groups():
    stats, flagged = ccc.find_outliers({})
    assert stats == []
    assert flagged == []


def test_outliers_single_member_group_skipped():
    groups = {("EGF", "ng/mL"): [{"value": 100.0, "id": "a", "pmcid": "P1", "organoid_type": None, "name": "EGF", "evidence_quote": ""}]}
    stats, flagged = ccc.find_outliers(groups)
    assert stats == []
    assert flagged == []


def test_outliers_two_consistent_records():
    groups = {
        ("EGF", "ng/mL"): [
            {"value": 100.0, "id": "a", "pmcid": "P1", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
            {"value": 110.0, "id": "b", "pmcid": "P2", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
        ]
    }
    stats, flagged = ccc.find_outliers(groups)
    assert len(stats) == 1
    assert stats[0]["n_outliers"] == 0
    assert flagged == []


def test_outliers_high_outlier_flagged():
    # median = 100, outlier = 1100 (ratio 11 > 10)
    groups = {
        ("EGF", "ng/mL"): [
            {"value": 100.0, "id": "a", "pmcid": "P1", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
            {"value": 100.0, "id": "b", "pmcid": "P2", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
            {"value": 1100.0, "id": "c", "pmcid": "P3", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
        ]
    }
    stats, flagged = ccc.find_outliers(groups)
    assert len(flagged) == 1
    assert flagged[0]["id"] == "c"
    assert flagged[0]["ratio_to_median"] > 10.0
    assert flagged[0]["canonical"] == "EGF"
    assert flagged[0]["unit"] == "ng/mL"


def test_outliers_low_outlier_flagged():
    # median = 100, outlier = 5 (ratio 0.05 < 0.1)
    groups = {
        ("EGF", "ng/mL"): [
            {"value": 100.0, "id": "a", "pmcid": "P1", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
            {"value": 100.0, "id": "b", "pmcid": "P2", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
            {"value": 5.0, "id": "c", "pmcid": "P3", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
        ]
    }
    stats, flagged = ccc.find_outliers(groups)
    assert len(flagged) == 1
    assert flagged[0]["id"] == "c"


def test_outliers_exactly_at_threshold_not_flagged():
    # ratio = exactly 10.0, threshold is > 10, so NOT flagged
    groups = {
        ("EGF", "ng/mL"): [
            {"value": 100.0, "id": "a", "pmcid": "P1", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
            {"value": 100.0, "id": "b", "pmcid": "P2", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
            {"value": 1000.0, "id": "c", "pmcid": "P3", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
        ]
    }
    stats, flagged = ccc.find_outliers(groups)
    assert len(flagged) == 0


def test_outliers_custom_threshold():
    # threshold=2: value 5x median should be flagged
    groups = {
        ("EGF", "ng/mL"): [
            {"value": 100.0, "id": "a", "pmcid": "P1", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
            {"value": 100.0, "id": "b", "pmcid": "P2", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
            {"value": 500.0, "id": "c", "pmcid": "P3", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
        ]
    }
    stats, flagged = ccc.find_outliers(groups, threshold=2.0)
    assert len(flagged) == 1


def test_outliers_group_stats_structure():
    groups = {
        ("EGF", "ng/mL"): [
            {"value": 100.0, "id": "a", "pmcid": "P1", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
            {"value": 200.0, "id": "b", "pmcid": "P2", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
        ]
    }
    stats, _ = ccc.find_outliers(groups)
    s = stats[0]
    assert s["canonical"] == "EGF"
    assert s["unit"] == "ng/mL"
    assert s["n"] == 2
    assert s["median"] == 150.0
    assert s["min"] == 100.0
    assert s["max"] == 200.0
    assert "n_outliers" in s


def test_outliers_flagged_record_structure():
    groups = {
        ("EGF", "ng/mL"): [
            {"value": 100.0, "id": "a", "pmcid": "P1", "organoid_type": "intestinal", "name": "EGF", "evidence_quote": "q1"},
            {"value": 100.0, "id": "b", "pmcid": "P2", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
            {"value": 5000.0, "id": "c", "pmcid": "P3", "organoid_type": None, "name": "EGF", "evidence_quote": ""},
        ]
    }
    _, flagged = ccc.find_outliers(groups)
    f = flagged[0]
    assert "canonical" in f
    assert "unit" in f
    assert "ratio_to_median" in f
    assert "median" in f
    assert "value" in f
    assert "pmcid" in f


# --------------------------------------------------------------------------- #
# build_report
# --------------------------------------------------------------------------- #

def test_build_report_empty():
    result = ccc.build_report([], [])
    assert result["n_groups"] == 0
    assert result["n_records_with_concentration"] == 0
    assert result["n_flagged_outliers"] == 0
    assert result["outlier_rate"] == 0.0


def test_build_report_required_keys():
    result = ccc.build_report([], [])
    for k in ("method", "n_groups", "n_records_with_concentration",
              "n_flagged_outliers", "outlier_rate", "threshold", "groups", "flagged"):
        assert k in result


def test_build_report_threshold_stored():
    result = ccc.build_report([], [], threshold=5.0)
    assert result["threshold"] == 5.0


def test_build_report_outlier_rate():
    group_stats = [{"canonical": "EGF", "unit": "ng/mL", "n": 10, "median": 100, "min": 90, "max": 200, "n_outliers": 2}]
    flagged = [{"ratio_to_median": 15.0}] * 2
    result = ccc.build_report(group_stats, flagged)
    assert result["outlier_rate"] == pytest.approx(0.2)


def test_build_report_groups_sorted_by_n_outliers():
    group_stats = [
        {"canonical": "A", "unit": "nM", "n": 5, "median": 10, "min": 5, "max": 15, "n_outliers": 1},
        {"canonical": "B", "unit": "nM", "n": 8, "median": 10, "min": 5, "max": 15, "n_outliers": 3},
    ]
    result = ccc.build_report(group_stats, [])
    assert result["groups"][0]["canonical"] == "B"


def test_build_report_flagged_sorted_by_log_ratio():
    # flagged list should be sorted by abs(log10(ratio_to_median)) descending
    flagged = [
        {"ratio_to_median": 100.0},   # log10 = 2.0
        {"ratio_to_median": 50.0},    # log10 = 1.7
    ]
    result = ccc.build_report([], flagged)
    assert result["flagged"][0]["ratio_to_median"] == 100.0


def test_build_report_method_contains_threshold():
    result = ccc.build_report([], [], threshold=10.0)
    assert "10" in result["method"]


# --------------------------------------------------------------------------- #
# end-to-end: group_reagents -> find_outliers -> build_report
# --------------------------------------------------------------------------- #

def test_end_to_end_no_outliers():
    rows = [
        _row(canonical="EGF", unit="ng/mL", value=100.0, pmcid="PMC001"),
        _row(canonical="EGF", unit="ng/mL", value=110.0, pmcid="PMC002"),
        _row(canonical="EGF", unit="ng/mL", value=90.0, pmcid="PMC003"),
    ]
    groups = ccc.group_reagents(rows)
    stats, flagged = ccc.find_outliers(groups)
    result = ccc.build_report(stats, flagged)
    assert result["n_flagged_outliers"] == 0
    assert result["n_groups"] == 1
    assert result["n_records_with_concentration"] == 3


def test_end_to_end_with_outlier():
    rows = [
        _row(canonical="Wnt3a", unit="nM", value=100.0, pmcid="PMC001"),
        _row(canonical="Wnt3a", unit="nM", value=100.0, pmcid="PMC002"),
        _row(canonical="Wnt3a", unit="nM", value=2000.0, pmcid="PMC003"),  # 20x median
    ]
    groups = ccc.group_reagents(rows)
    stats, flagged = ccc.find_outliers(groups)
    result = ccc.build_report(stats, flagged)
    assert result["n_flagged_outliers"] == 1
    assert result["flagged"][0]["canonical"] == "Wnt3a"
