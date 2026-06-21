"""
Smoke tests for analytics handlers against the real committed data files
(exports/public/protocols.jsonl, exports/public/reagents.jsonl, etc.).

These complement the monkeypatched unit tests in test_analytics_endpoint.py with
guard rails that catch regressions when corpus batch merges change the underlying
data or when handler normalization logic drifts. No mocking — real data only.

All assertions are robust to expected corpus growth (no exact counts hardcoded).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "serve" / "plugins"))
import analytics_endpoint as ae  # noqa: E402

PROTOCOLS_JSONL = REPO / "exports" / "public" / "protocols.jsonl"
REAGENTS_JSONL = REPO / "exports" / "public" / "reagents.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def require_protocols(func):
    """Skip test if protocols.jsonl doesn't exist (e.g. fresh clone)."""
    return pytest.mark.skipif(
        not PROTOCOLS_JSONL.exists(), reason="protocols.jsonl absent"
    )(func)


def require_reagents(func):
    return pytest.mark.skipif(
        not REAGENTS_JSONL.exists(), reason="reagents.jsonl absent"
    )(func)


# ---------------------------------------------------------------------------
# species-breakdown live smoke tests
# ---------------------------------------------------------------------------

@require_protocols
def test_live_species_breakdown_returns_200():
    data, status = ae.handle_species_breakdown(None)
    assert status == 200
    assert "cross_corpus" in data
    assert "per_type" in data
    assert data["n_types"] >= 1


@require_protocols
def test_live_species_breakdown_human_is_top_species():
    data, _ = ae.handle_species_breakdown(None)
    cc = data["cross_corpus"]
    assert "human" in cc
    # human should be the most common species in a human-biology corpus
    assert cc["human"] == max(cc.values())


@require_protocols
def test_live_species_breakdown_covers_known_types():
    data, _ = ae.handle_species_breakdown(None)
    known = {"intestinal", "kidney", "cerebral", "liver", "lung", "cardiac"}
    missing = known - set(data["per_type"])
    assert not missing, f"Expected organoid types absent from species-breakdown: {missing}"


# ---------------------------------------------------------------------------
# matrix-breakdown live smoke tests
# ---------------------------------------------------------------------------

@require_protocols
def test_live_matrix_breakdown_returns_200():
    data, status = ae.handle_matrix_breakdown(None)
    assert status == 200
    assert "cross_corpus" in data
    assert data["n_types"] >= 1


@require_protocols
def test_live_matrix_breakdown_matrigel_is_top():
    data, _ = ae.handle_matrix_breakdown(None)
    cc = data["cross_corpus"]
    assert "Matrigel" in cc
    # Matrigel is by far the dominant matrix in organoid culture
    assert cc["Matrigel"] > 200


# ---------------------------------------------------------------------------
# base-media-breakdown live smoke tests
# ---------------------------------------------------------------------------

@require_protocols
def test_live_base_media_breakdown_returns_200():
    data, status = ae.handle_base_media_breakdown(None)
    assert status == 200
    assert "cross_corpus" in data
    assert data["n_types"] >= 1


@require_protocols
def test_live_base_media_breakdown_known_media_present():
    data, _ = ae.handle_base_media_breakdown(None)
    cc = data["cross_corpus"]
    # These are canonicalized top media; at least one should appear
    known_media = {"DMEM/F12", "Advanced DMEM/F12", "mTeSR1", "RPMI 1640"}
    assert known_media & set(cc), f"No known base media in cross_corpus: {cc}"


# ---------------------------------------------------------------------------
# source-cell-breakdown live smoke tests
# ---------------------------------------------------------------------------

@require_protocols
def test_live_source_cell_breakdown_returns_200():
    data, status = ae.handle_source_cell_breakdown(None)
    assert status == 200
    assert "cross_corpus" in data
    assert data["n_types"] >= 1


@require_protocols
def test_live_source_cell_breakdown_ipsc_is_top():
    data, _ = ae.handle_source_cell_breakdown(None)
    cc = data["cross_corpus"]
    assert "iPSC" in cc
    # iPSC protocols dominate in the current corpus
    assert cc["iPSC"] > cc.get("adult_stem_cell", 0)


# ---------------------------------------------------------------------------
# protocol-complexity live smoke tests
# ---------------------------------------------------------------------------

@require_protocols
def test_live_protocol_complexity_returns_200():
    data, status = ae.handle_protocol_complexity(None)
    assert status == 200
    assert "per_type" in data
    assert data["n_types"] >= 1


@require_protocols
def test_live_protocol_complexity_ranking_nonempty():
    data, _ = ae.handle_protocol_complexity(None)
    ranking = data["ranking_by_avg_signaling_factors"]
    assert len(ranking) >= 5
    # liver is known to be among the most complex (7+ avg SF)
    assert "liver" in ranking


@require_protocols
def test_live_protocol_complexity_single_type_kidney():
    data, status = ae.handle_protocol_complexity("kidney")
    assert status == 200
    assert data["organoid_type"] == "kidney"
    sf = data.get("n_signaling_factors")
    assert sf is not None
    assert sf["n"] >= 1
    assert sf["mean"] > 0


# ---------------------------------------------------------------------------
# reporting-gaps live smoke tests
# ---------------------------------------------------------------------------

@require_protocols
def test_live_reporting_gaps_returns_200():
    data, status = ae.handle_reporting_gaps(None)
    assert status == 200
    assert "cross_corpus" in data
    assert "ranking_by_gap" in data


@require_protocols
def test_live_reporting_gaps_timeline_is_least_reported():
    data, _ = ae.handle_reporting_gaps(None)
    ranking = data["ranking_by_gap"]
    cc = data["cross_corpus"]
    # timeline has the lowest reporting rate — should appear first (biggest gap)
    assert ranking[0] == "timeline"
    assert cc["timeline"]["reporting_rate"] < 0.30


@require_protocols
def test_live_reporting_gaps_source_cell_type_always_reported():
    data, _ = ae.handle_reporting_gaps(None)
    cc = data["cross_corpus"]
    # source_cell_type is always populated by the pipeline (100% rate)
    assert cc["source_cell_type"]["reporting_rate"] == 1.0
    # highest-rate field should be last in the ranking_by_gap list
    ranking = data["ranking_by_gap"]
    assert ranking[-1] == "source_cell_type"


# ---------------------------------------------------------------------------
# Summary snapshot live smoke tests
# ---------------------------------------------------------------------------

@require_protocols
def test_live_summary_has_all_snapshots():
    """handle_summary() single-pass must populate all 4 live snapshots."""
    import os
    # summary can 404 if no analysis outputs exist; check gracefully
    data, status = ae.handle_summary()
    if status == 404:
        pytest.skip("no analytics outputs generated yet")
    assert "species_snapshot" in data
    assert "matrix_snapshot" in data
    assert "base_media_snapshot" in data
    assert "source_cell_snapshot" in data


@require_protocols
def test_live_summary_snapshots_consistent_with_breakdown_endpoints():
    """Top entry in each summary snapshot must match top entry from the full breakdown."""
    data, status = ae.handle_summary()
    if status == 404:
        pytest.skip("no analytics outputs generated yet")

    # species
    sp_snap = data.get("species_snapshot", {})
    sp_full, _ = ae.handle_species_breakdown(None)
    if sp_snap and sp_full.get("cross_corpus"):
        top_snap = max(sp_snap, key=sp_snap.get)
        top_full = max(sp_full["cross_corpus"], key=sp_full["cross_corpus"].get)
        assert top_snap == top_full, f"species_snapshot top={top_snap} != breakdown top={top_full}"

    # source_cell
    sc_snap = data.get("source_cell_snapshot", {})
    sc_full, _ = ae.handle_source_cell_breakdown(None)
    if sc_snap and sc_full.get("cross_corpus"):
        top_snap = max(sc_snap, key=sc_snap.get)
        top_full = max(sc_full["cross_corpus"], key=sc_full["cross_corpus"].get)
        assert top_snap == top_full, f"source_cell_snapshot top={top_snap} != breakdown top={top_full}"
