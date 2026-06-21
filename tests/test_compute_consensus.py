"""
Offline tests for compute_consensus pure aggregation logic.
No filesystem, no model, no network.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import compute_consensus as cc


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _reagent(name, canonical=None, value=None, unit=None, role=None):
    r = {"name": name, "canonical_name": canonical, "role": role}
    if value is not None:
        r["concentration"] = {"value": value, "unit": unit, "canonical_unit": unit, "raw": f"{value} {unit}"}
    return r


def _protocol(pmcid, organoid_type, base_media=None, matrix=None,
              signaling_factors=None, source_cell_type=None, timeline=None):
    return {
        "pmcid": pmcid,
        "organoid_type": organoid_type,
        "base_media": base_media,
        "matrix": matrix,
        "source_cell_type": source_cell_type,
        "signaling_factors": signaling_factors or [],
        "media_supplements": [],
        "small_molecules": [],
        "timeline": timeline or [],
    }


# --------------------------------------------------------------------------- #
# median
# --------------------------------------------------------------------------- #

def test_median_odd():
    assert cc.median([1.0, 3.0, 5.0]) == 3.0


def test_median_even():
    assert cc.median([1.0, 2.0, 3.0, 4.0]) == pytest.approx(2.5)


def test_median_single():
    assert cc.median([42.0]) == 42.0


def test_median_empty():
    assert math.isnan(cc.median([]))


# --------------------------------------------------------------------------- #
# compute_reagent_consensus
# --------------------------------------------------------------------------- #

def test_reagent_consensus_prevalence():
    protocols = [
        _protocol("PMC1", "intestinal", signaling_factors=[_reagent("EGF", "EGF", 50, "ng/mL")]),
        _protocol("PMC2", "intestinal", signaling_factors=[_reagent("EGF", "EGF", 100, "ng/mL")]),
        _protocol("PMC3", "intestinal", signaling_factors=[_reagent("Noggin", "Noggin", 100, "ng/mL")]),
    ]
    result = cc.compute_reagent_consensus(protocols, "signaling_factors")
    egf = next(r for r in result if r["canonical_key"] == "egf")
    assert egf["n_papers"] == 2
    assert egf["prevalence"] == pytest.approx(2 / 3, abs=0.01)


def test_reagent_consensus_median_concentration():
    protocols = [
        _protocol("PMC1", "intestinal", signaling_factors=[_reagent("EGF", "EGF", 50, "ng/mL")]),
        _protocol("PMC2", "intestinal", signaling_factors=[_reagent("EGF", "EGF", 100, "ng/mL")]),
        _protocol("PMC3", "intestinal", signaling_factors=[_reagent("EGF", "EGF", 200, "ng/mL")]),
    ]
    result = cc.compute_reagent_consensus(protocols, "signaling_factors")
    egf = next(r for r in result if r["canonical_key"] == "egf")
    assert egf["concentration"]["median"] == pytest.approx(100.0)
    assert egf["concentration"]["min"] == 50.0
    assert egf["concentration"]["max"] == 200.0


def test_reagent_consensus_high_variability_flag():
    """CV > 1.0 → high_variability flagged."""
    protocols = [
        _protocol("PMC1", "intestinal", signaling_factors=[_reagent("EGF", "EGF", 1, "ng/mL")]),
        _protocol("PMC2", "intestinal", signaling_factors=[_reagent("EGF", "EGF", 1000, "ng/mL")]),
    ]
    result = cc.compute_reagent_consensus(protocols, "signaling_factors")
    egf = next(r for r in result if r["canonical_key"] == "egf")
    assert egf["concentration"].get("high_variability") is True


def test_reagent_consensus_no_high_variability_for_consistent():
    """Low CV → no high_variability flag."""
    protocols = [
        _protocol("PMC1", "intestinal", signaling_factors=[_reagent("EGF", "EGF", 50, "ng/mL")]),
        _protocol("PMC2", "intestinal", signaling_factors=[_reagent("EGF", "EGF", 51, "ng/mL")]),
    ]
    result = cc.compute_reagent_consensus(protocols, "signaling_factors")
    egf = next(r for r in result if r["canonical_key"] == "egf")
    assert not egf["concentration"].get("high_variability")


def test_reagent_consensus_sorted_by_prevalence():
    protocols = [
        _protocol("PMC1", "intestinal", signaling_factors=[
            _reagent("EGF", "EGF", 50, "ng/mL"), _reagent("Noggin", "Noggin", 100, "ng/mL")
        ]),
        _protocol("PMC2", "intestinal", signaling_factors=[_reagent("EGF", "EGF", 50, "ng/mL")]),
    ]
    result = cc.compute_reagent_consensus(protocols, "signaling_factors")
    assert result[0]["canonical_key"] == "egf"  # higher prevalence first


def test_reagent_consensus_empty():
    assert cc.compute_reagent_consensus([], "signaling_factors") == []


def test_reagent_consensus_consensus_unit_most_common():
    protocols = [
        _protocol("PMC1", "intestinal", signaling_factors=[_reagent("EGF", "EGF", 50, "ng/mL")]),
        _protocol("PMC2", "intestinal", signaling_factors=[_reagent("EGF", "EGF", 50, "ng/mL")]),
        _protocol("PMC3", "intestinal", signaling_factors=[_reagent("EGF", "EGF", 50, "ug/mL")]),
    ]
    result = cc.compute_reagent_consensus(protocols, "signaling_factors")
    egf = next(r for r in result if r["canonical_key"] == "egf")
    assert egf["concentration"]["unit"] == "ng/mL"


# --------------------------------------------------------------------------- #
# compute_scalar_consensus
# --------------------------------------------------------------------------- #

def test_scalar_consensus_top():
    protocols = [
        {"base_media": "Advanced DMEM/F12"},
        {"base_media": "Advanced DMEM/F12"},
        {"base_media": "RPMI"},
    ]
    result = cc.compute_scalar_consensus(protocols, "base_media")
    assert result["top"] == "Advanced DMEM/F12"
    assert result["n_reported"] == 3


def test_scalar_consensus_skips_none_and_not_reported():
    protocols = [
        {"base_media": None},
        {"base_media": "not_reported"},
        {"base_media": "DMEM/F12"},
    ]
    result = cc.compute_scalar_consensus(protocols, "base_media")
    assert result["n_reported"] == 1
    assert result["n_missing"] == 2


def test_scalar_consensus_empty():
    result = cc.compute_scalar_consensus([], "base_media")
    assert result["top"] is None
    assert result["n_reported"] == 0


# --------------------------------------------------------------------------- #
# compute_timeline_consensus
# --------------------------------------------------------------------------- #

def test_timeline_consensus_prevalence():
    protocols = [
        _protocol("PMC1", "intestinal", timeline=[{"name": "expansion", "duration": 3}]),
        _protocol("PMC2", "intestinal", timeline=[{"name": "expansion", "duration": 5}]),
        _protocol("PMC3", "intestinal", timeline=[]),
    ]
    result = cc.compute_timeline_consensus(protocols)
    stages = {s["stage"]: s for s in result["stages"]}
    assert stages["expansion"]["n_papers"] == 2
    assert stages["expansion"]["prevalence"] == pytest.approx(2 / 3, abs=0.01)


def test_timeline_consensus_median_duration():
    protocols = [
        _protocol("PMC1", "intestinal", timeline=[{"name": "maturation", "duration": 7}]),
        _protocol("PMC2", "intestinal", timeline=[{"name": "maturation", "duration": 14}]),
        _protocol("PMC3", "intestinal", timeline=[{"name": "maturation", "duration": 21}]),
    ]
    result = cc.compute_timeline_consensus(protocols)
    stages = {s["stage"]: s for s in result["stages"]}
    assert stages["maturation"]["median_duration"] == 14.0


def test_timeline_consensus_skips_string_timeline():
    protocols = [
        {"timeline": "3-5 days expansion, then maturation"},
    ]
    result = cc.compute_timeline_consensus(protocols)
    assert result["stages"] == []


def test_timeline_consensus_empty():
    result = cc.compute_timeline_consensus([])
    assert result["stages"] == []


# --------------------------------------------------------------------------- #
# compute_consensus (integration)
# --------------------------------------------------------------------------- #

def test_compute_consensus_universal_reagents():
    """Reagents used in ≥70% of papers → appear in universal_reagents."""
    protocols = [
        _protocol(f"PMC{i}", "intestinal",
                  signaling_factors=[_reagent("EGF", "EGF", 50, "ng/mL")])
        for i in range(4)
    ] + [
        _protocol("PMC5", "intestinal",
                  signaling_factors=[_reagent("Noggin", "Noggin", 100, "ng/mL")])
    ]
    result = cc.compute_consensus(protocols, "intestinal")
    universal_keys = {r["canonical_key"] for r in result["universal_reagents"]}
    assert "egf" in universal_keys
    assert "noggin" not in universal_keys  # only 1/5 = 20%


def test_compute_consensus_empty():
    result = cc.compute_consensus([], "intestinal")
    assert result["n_protocols"] == 0
    assert result["organoid_type"] == "intestinal"


def test_compute_consensus_n_protocols():
    protocols = [_protocol(f"PMC{i}", "intestinal") for i in range(5)]
    result = cc.compute_consensus(protocols, "intestinal")
    assert result["n_protocols"] == 5
