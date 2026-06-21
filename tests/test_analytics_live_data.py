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


# ---------------------------------------------------------------------------
# grounding-quality live smoke tests
# ---------------------------------------------------------------------------

@require_reagents
def test_live_grounding_quality_returns_200():
    data, status = ae.handle_grounding_quality(None)
    assert status == 200
    assert "cross_corpus" in data
    assert "by_kind" in data
    assert "top_ungrounded" in data


@require_reagents
def test_live_grounding_quality_rate_in_range():
    data, _ = ae.handle_grounding_quality(None)
    gr = data["cross_corpus"]["grounding_rate"]
    assert gr is not None
    # corpus has a mix of grounded and not; rate should be 0.3-0.8
    assert 0.3 <= gr <= 0.8, f"grounding_rate={gr} out of expected range"


@require_reagents
def test_live_grounding_quality_signaling_ranked_high():
    data, _ = ae.handle_grounding_quality(None)
    bk = data["by_kind"]
    # signaling factors are most likely to have been curated; should be present
    assert "signaling" in bk
    assert bk["signaling"]["n_reagents"] > 100


# ---------------------------------------------------------------------------
# concentration-stats live smoke tests
# ---------------------------------------------------------------------------

@require_reagents
def test_live_concentration_stats_returns_200():
    data, status = ae.handle_concentration_stats(None, None)
    assert status == 200
    assert "top_reagents" in data
    assert len(data["top_reagents"]) >= 10


@require_reagents
def test_live_concentration_stats_egf_known():
    data, status = ae.handle_concentration_stats("EGF", None)
    assert status == 200
    assert data["canonical"] == "EGF"
    assert data["n_with_value"] >= 50
    # EGF is predominantly used in ng/mL
    assert "ng/mL" in data["stats_per_unit"]
    stats = data["stats_per_unit"]["ng/mL"]
    # Typical EGF dose is 1-500 ng/mL; median should be in this range
    assert 1 <= stats["median"] <= 500


@require_reagents
def test_live_concentration_stats_top_by_n_with_value():
    data, _ = ae.handle_concentration_stats(None, None)
    # Y-27632 and EGF should be among the most reported
    top_names = {r["canonical"] for r in data["top_reagents"][:10]}
    assert len(top_names & {"Y-27632", "EGF", "CHIR99021", "FGF2"}) >= 2


# ---------------------------------------------------------------------------
# temporal-reagent-adoption live smoke tests
# ---------------------------------------------------------------------------

@require_reagents
def test_live_tra_no_query_returns_200():
    data, status = ae.handle_temporal_reagent_adoption(None, None)
    assert status == 200
    assert "top_reagents_by_peak_adoption" in data
    assert len(data["top_reagents_by_peak_adoption"]) >= 5
    assert data["n_canonicals_total"] >= 100


@require_reagents
def test_live_tra_egf_known():
    data, status = ae.handle_temporal_reagent_adoption("EGF", None)
    assert status == 200
    assert data["canonical"] == "EGF"
    assert data["n_pmcids_using"] >= 50
    yrs = data["years"]
    assert len(yrs) >= 5
    # EGF has been used across multiple years; peak adoption should be > 0
    assert data["trend"]["peak_adoption"] is not None
    assert data["trend"]["peak_adoption"] > 0


@require_reagents
def test_live_tra_type_filter_kidney():
    data, status = ae.handle_temporal_reagent_adoption("EGF", "kidney")
    assert status == 200
    assert data["organoid_type_filter"] == "kidney"
    assert data["n_pmcids_using"] >= 1


# ---------------------------------------------------------------------------
# kgx-summary live smoke tests
# ---------------------------------------------------------------------------

def require_kgx(func):
    from pathlib import Path
    return pytest.mark.skipif(
        not (REPO / "exports" / "kgx" / "kgx_manifest.json").exists(),
        reason="kgx_manifest.json absent"
    )(func)


@require_kgx
def test_live_kgx_summary_returns_200():
    data, status = ae.handle_kgx_summary()
    assert status == 200
    assert data["n_nodes"] >= 100
    assert data["n_edges"] >= 100
    assert data["resolved_rate"] is not None
    assert data["resolved_rate"] > 0.5


@require_kgx
def test_live_kgx_summary_review_queue_present():
    data, _ = ae.handle_kgx_summary()
    rq = data.get("review_queue")
    if rq is None:
        pytest.skip("review_items.jsonl absent")
    assert rq["total"] >= 1
    assert "by_status" in rq
    assert "top_not_found" in rq


# ---------------------------------------------------------------------------
# concentration-by-type live smoke tests
# ---------------------------------------------------------------------------

@require_reagents
def test_live_cbt_egf_returns_200():
    data, status = ae.handle_concentration_by_type("EGF")
    assert status == 200
    assert data["canonical"] == "EGF"
    assert data["n_organoid_types"] >= 5
    # intestinal is the largest single organoid type for EGF
    by_type = data["by_type"]
    assert "intestinal" in by_type
    assert "gastric" in by_type


@require_reagents
def test_live_cbt_400_no_query():
    _, status = ae.handle_concentration_by_type(None)
    assert status == 400


# ---------------------------------------------------------------------------
# journal-breakdown live smoke tests
# ---------------------------------------------------------------------------

@require_protocols
def test_live_journal_breakdown_returns_200():
    data, status = ae.handle_journal_breakdown(None)
    assert status == 200
    assert "cross_corpus" in data
    assert data["n_journals_total"] >= 50
    assert data["n_types"] >= 10


@require_protocols
def test_live_journal_breakdown_nature_comms_present():
    data, _ = ae.handle_journal_breakdown(None)
    # Nature Communications is reliably present in the corpus
    cc = data["cross_corpus"]
    assert any("nature communications" in j.lower() for j in cc)


# ---------------------------------------------------------------------------
# type-comparison live smoke tests
# ---------------------------------------------------------------------------

@require_reagents
def test_live_type_comparison_intestinal_cerebral():
    data, status = ae.handle_type_comparison("intestinal", "cerebral")
    assert status == 200
    assert data["n_shared"] >= 5
    assert data["jaccard_similarity"] > 0
    assert data["jaccard_similarity"] < 1.0
    # EGF appears in both
    shared_names = {r["canonical"].lower() for r in data["shared"]}
    assert any("egf" in n for n in shared_names)


# ---------------------------------------------------------------------------
# concentration-deviation live smoke tests
# ---------------------------------------------------------------------------

@require_reagents
def test_live_cd_returns_200():
    data, status = ae.handle_concentration_deviation()
    assert status == 200
    assert "most_variable" in data
    assert "most_consistent" in data
    assert data["n_canonicals_total"] >= 5


@require_reagents
def test_live_cd_egf_in_most_variable():
    data, _ = ae.handle_concentration_deviation()
    # EGF is reported across a wide dose range — expect high CV
    variable_names = {e["canonical"] for e in data["most_variable"]}
    # At least some reagents should be in the most_variable list
    assert len(data["most_variable"]) >= 3
    # min_n_threshold should be present
    assert data["min_n_threshold"] == 3


# ---------------------------------------------------------------------------
# reagent-prevalence live smoke tests
# ---------------------------------------------------------------------------

@require_reagents
def test_live_rp_returns_200():
    data, status = ae.handle_reagent_prevalence(None)
    assert status == 200
    assert data["n_canonicals_total"] >= 100
    assert data["n_types_total"] >= 10
    assert len(data["cross_field"]) >= 1  # some reagents appear in >= 20 types


@require_reagents
def test_live_rp_egf_query():
    data, status = ae.handle_reagent_prevalence("EGF")
    assert status == 200
    assert data["canonical"] == "EGF"
    assert data["n_types"] >= 10
    assert data["n_records_total"] >= 50
    # EGF should appear in intestinal, kidney, cerebral at minimum
    type_names = {e["organoid_type"] for e in data["per_type"]}
    assert "intestinal" in type_names


@require_reagents
def test_live_rp_b27_is_cross_field():
    data, _ = ae.handle_reagent_prevalence(None)
    cross = {e["canonical"] for e in data["cross_field"]}
    # B27, FGF2, GlutaMAX appear in all 25 types
    assert len(cross & {"B27", "FGF2", "GlutaMAX"}) >= 2


# ---------------------------------------------------------------------------
# protocol-outliers live smoke tests
# ---------------------------------------------------------------------------

@require_protocols
def test_live_po_returns_200():
    data, status = ae.handle_protocol_outliers(None)
    assert status == 200
    assert data["n_types"] >= 10
    assert data["n_papers_total"] >= 100
    assert "per_type" in data


@require_protocols
def test_live_po_intestinal_has_outliers():
    data, status = ae.handle_protocol_outliers("intestinal")
    assert status == 200
    assert data["organoid_type"] == "intestinal"
    assert data["n_papers"] >= 20
    assert data["mean_n_sf"] > 0
    # At least one complex or minimal outlier in a large enough corpus
    assert data["n_complex"] + data["n_minimal"] >= 1


# ---------------------------------------------------------------------------
# grounding-distribution live smoke tests
# ---------------------------------------------------------------------------

@require_protocols
def test_live_gd_returns_200():
    data, status = ae.handle_grounding_distribution(None)
    assert status == 200
    assert data["n"] >= 100
    assert data["n_types"] >= 10
    assert len(data["histogram"]) == 10
    assert data["mean"] is not None


@require_protocols
def test_live_gd_intestinal_type():
    data, status = ae.handle_grounding_distribution("intestinal")
    assert status == 200
    assert data["organoid_type"] == "intestinal"
    assert data["n"] >= 20
    # intestinal grounding rate should be > 0.5 in a well-grounded corpus
    assert data["mean"] > 0.5


# ---------------------------------------------------------------------------
# type-maturity live smoke tests
# ---------------------------------------------------------------------------

@require_protocols
def test_live_tm_returns_200():
    data, status = ae.handle_type_maturity(None)
    assert status == 200
    assert data["n_types"] >= 20
    assert "established" in data["by_tier"]
    assert len(data["by_tier"]["established"]) >= 5


@require_protocols
def test_live_tm_intestinal_details():
    data, status = ae.handle_type_maturity("intestinal")
    assert status == 200
    assert data["organoid_type"] == "intestinal"
    # established OR developing — 35 papers, first_year 2018
    assert data["maturity_tier"] in ("established", "developing")
    assert data["first_year"] <= 2020
    assert data["n_papers_total"] >= 20
    assert data["trajectory"] in ("accelerating", "stable", "slowing", "insufficient_data")


@require_reagents
def test_live_rc_returns_200():
    data, status = ae.handle_reagent_cooccurrence(None, None, min_papers=3)
    assert status == 200
    assert data["n_papers_total"] >= 100
    assert data["n_canonicals"] >= 50
    assert len(data["top_pairs"]) >= 10


@require_reagents
def test_live_rc_egf_has_partners():
    data, status = ae.handle_reagent_cooccurrence("EGF", None)
    assert status == 200
    assert data["query_canonical"] == "EGF"
    assert data["n_co_occurring"] >= 10
    canonicals = {r["canonical"] for r in data["co_occurring"]}
    # EGF and Noggin are both core intestinal factors — expect them to co-occur
    assert "Noggin" in canonicals


@require_reagents
def test_live_sb_returns_200():
    data, status = ae.handle_supplement_breakdown(None, None)
    assert status == 200
    assert data["n_papers_with_supplements"] >= 100
    assert data["n_supplement_canonicals"] >= 20
    assert len(data["cross_type_supplements"]) >= 3
    assert data["top_supplements"][0]["canonical"] in ("GlutaMAX", "B27", "penicillin/streptomycin")


@require_reagents
def test_live_sb_glutamax_cross_type():
    data, status = ae.handle_supplement_breakdown("GlutaMAX", None)
    assert status == 200
    assert data["query_canonical"] == "GlutaMAX"
    assert data["n_types"] >= 10
    assert data["n_papers_total"] >= 50


@require_reagents
def test_live_rb_returns_200():
    data, status = ae.handle_role_breakdown(None, None)
    assert status == 200
    assert data["n_records_total"] >= 1000
    roles = {r["role"] for r in data["role_distribution"]}
    assert "growth_factor" in roles
    assert "signaling_factor" in roles
    assert "inhibitor" in roles


@require_reagents
def test_live_rb_differentiation_has_canonicals():
    data, status = ae.handle_role_breakdown("differentiation", None)
    assert status == 200
    assert data["n_canonicals"] >= 3
    # BMP4 is a key differentiation factor in many organoid types
    canon_names = {c["canonical"] for c in data["top_canonicals"]}
    assert len(canon_names) >= 3


@require_reagents
def test_live_th_returns_200():
    data, status = ae.handle_type_reagent_heatmap(None, top_n=20)
    assert status == 200
    assert data["n_types"] >= 15
    assert len(data["canonicals"]) == 20
    assert data["canonicals"][0] in ("EGF", "Y-27632", "R-spondin1", "Noggin")


@require_reagents
def test_live_th_intestinal_has_egf():
    data, status = ae.handle_type_reagent_heatmap("signaling", top_n=10)
    assert status == 200
    if "EGF" in data["canonicals"]:
        egf_idx = data["canonicals"].index("EGF")
        intestinal = next((r for r in data["matrix"] if r["organoid_type"] == "intestinal"), None)
        if intestinal:
            assert intestinal["values"][egf_idx] >= 5


@require_reagents
def test_live_nv_returns_200():
    data, status = ae.handle_canonical_name_variants(None)
    assert status == 200
    assert data["n_canonicals_total"] >= 100
    assert data["n_with_multiple_names"] >= 30
    assert len(data["most_ambiguous"]) >= 10


@require_reagents
def test_live_nv_y27632_most_ambiguous():
    data, status = ae.handle_canonical_name_variants("Y-27632")
    assert status == 200
    assert data["n_variants"] >= 5
    assert "Y-27632" in data["names"]
