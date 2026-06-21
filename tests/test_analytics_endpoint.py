"""
Offline tests for analytics_endpoint pure handler logic.
No Datasette, no filesystem beyond temp directories, no network.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "serve" / "plugins"))
import analytics_endpoint as ae


# --------------------------------------------------------------------------- #
# handle_index
# --------------------------------------------------------------------------- #

def test_index_returns_endpoints():
    data, status = ae.handle_index()
    assert status == 200
    assert "endpoints" in data
    assert "/analytics/consensus/{organoid_type}" in data["endpoints"]
    assert "/analytics/compare/{pmcid_a}/{pmcid_b}" in data["endpoints"]


# --------------------------------------------------------------------------- #
# handle_consensus_list
# --------------------------------------------------------------------------- #

def test_consensus_list_empty_when_no_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path / "nonexistent")
    data, status = ae.handle_consensus_list()
    assert status == 200
    assert data["available"] == []
    assert "hint" in data


def test_consensus_list_finds_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    (tmp_path / "consensus_intestinal.json").write_text(
        json.dumps({"organoid_type": "intestinal", "n_protocols": 12})
    )
    (tmp_path / "consensus_cerebral.json").write_text(
        json.dumps({"organoid_type": "cerebral", "n_protocols": 7})
    )
    data, status = ae.handle_consensus_list()
    assert status == 200
    types = {r["organoid_type"] for r in data["available"]}
    assert "intestinal" in types
    assert "cerebral" in types


# --------------------------------------------------------------------------- #
# handle_consensus
# --------------------------------------------------------------------------- #

def test_consensus_returns_data(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    payload = {"organoid_type": "intestinal", "n_protocols": 5, "signaling_factors": []}
    (tmp_path / "consensus_intestinal.json").write_text(json.dumps(payload))
    data, status = ae.handle_consensus("intestinal")
    assert status == 200
    assert data["n_protocols"] == 5


def test_consensus_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    data, status = ae.handle_consensus("hepatic")
    assert status == 404
    assert "hint" in data


def test_consensus_rejects_invalid_type(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    data, status = ae.handle_consensus("../../etc/passwd")
    assert status == 400
    assert "error" in data


def test_consensus_rejects_type_with_slash(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    _, status = ae.handle_consensus("foo/bar")
    assert status == 400


# --------------------------------------------------------------------------- #
# handle_failure_modes
# --------------------------------------------------------------------------- #

def test_failure_modes_returns_data(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    payload = {"total_failure_modes": 42, "n_organoid_types": 5}
    (tmp_path / "failure_mode_summary.json").write_text(json.dumps(payload))
    data, status = ae.handle_failure_modes()
    assert status == 200
    assert data["total_failure_modes"] == 42


def test_failure_modes_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    data, status = ae.handle_failure_modes()
    assert status == 404
    assert "hint" in data


# --------------------------------------------------------------------------- #
# handle_lineage
# --------------------------------------------------------------------------- #

def test_lineage_returns_data(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    payload = {"n_nodes": 10, "n_edges": 12, "roots": [], "nodes": [], "edges": []}
    (tmp_path / "protocol_lineage.json").write_text(json.dumps(payload))
    data, status = ae.handle_lineage()
    assert status == 200
    assert data["n_nodes"] == 10


def test_lineage_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    data, status = ae.handle_lineage()
    assert status == 404


# --------------------------------------------------------------------------- #
# handle_compare
# --------------------------------------------------------------------------- #

def test_compare_returns_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "COMPARISON_DIR", tmp_path)
    payload = {"pmcid_a": "PMC111", "pmcid_b": "PMC222", "summary": {"total_differences": 3}}
    (tmp_path / "PMC111_vs_PMC222.json").write_text(json.dumps(payload))
    data, status = ae.handle_compare("PMC111", "PMC222")
    assert status == 200
    assert data["summary"]["total_differences"] == 3


def test_compare_finds_reverse_order(tmp_path, monkeypatch):
    """If PMC222_vs_PMC111.json exists, /compare/PMC111/PMC222 should find it."""
    monkeypatch.setattr(ae, "COMPARISON_DIR", tmp_path)
    payload = {"pmcid_a": "PMC222", "pmcid_b": "PMC111"}
    (tmp_path / "PMC222_vs_PMC111.json").write_text(json.dumps(payload))
    data, status = ae.handle_compare("PMC111", "PMC222")
    assert status == 200


def test_compare_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "COMPARISON_DIR", tmp_path)
    data, status = ae.handle_compare("PMC111", "PMC999")
    assert status == 404
    assert "hint" in data


def test_compare_rejects_invalid_pmcid(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "COMPARISON_DIR", tmp_path)
    _, status = ae.handle_compare("INVALID", "PMC222")
    assert status == 400


def test_compare_rejects_non_numeric(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "COMPARISON_DIR", tmp_path)
    _, status = ae.handle_compare("PMCabc", "PMC222")
    assert status == 400


def test_compare_normalizes_case(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "COMPARISON_DIR", tmp_path)
    payload = {"pmcid_a": "PMC111", "pmcid_b": "PMC222"}
    (tmp_path / "PMC111_vs_PMC222.json").write_text(json.dumps(payload))
    # lowercase input
    data, status = ae.handle_compare("pmc111", "pmc222")
    assert status == 200


# --------------------------------------------------------------------------- #
# handle_substitutions
# --------------------------------------------------------------------------- #

def test_substitutions_requires_query():
    data, status = ae.handle_substitutions("", None, None)
    assert status == 400
    assert "error" in data


def test_substitutions_empty_when_no_records(monkeypatch):
    """With no modification records, returns empty results (not an error)."""
    import find_substitutions as fs
    monkeypatch.setattr(fs, "PRED_DIR", Path("/tmp/nonexistent_pred"))
    monkeypatch.setattr(fs, "SUMMARY_PATH", Path("/tmp/nonexistent_sum.json"))
    data, status = ae.handle_substitutions("Matrigel", None, None)
    assert status == 200
    assert data["n_hits"] == 0
    assert "hint" in data


def test_substitutions_truncates_long_query():
    """Query longer than 100 chars is truncated (no error)."""
    long_q = "x" * 200
    # No records but should not crash
    import find_substitutions as fs
    from unittest.mock import patch
    with patch.object(fs, "load_all_modifications", return_value=[]):
        data, status = ae.handle_substitutions(long_q, None, None)
    assert status == 200
    assert len(data["query"]) <= 100


# --------------------------------------------------------------------------- #
# handle_coverage
# --------------------------------------------------------------------------- #

def test_coverage_returns_data(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "COVERAGE_REPORT_PATH", tmp_path / "coverage_report.json")
    payload = {
        "n_total_papers": 582,
        "n_organoid_types": 26,
        "overall_avg_grounding_rate": 0.87,
        "corpus_pooled_grounding_rate": 0.86,
        "types_by_completeness": [],
        "by_organoid_type": {"cardiac": {"n_papers": 59, "completeness_score": 0.75}},
    }
    (tmp_path / "coverage_report.json").write_text(json.dumps(payload))
    data, status = ae.handle_coverage()
    assert status == 200
    assert data["n_total_papers"] == 582
    assert data["n_organoid_types"] == 26


def test_coverage_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "COVERAGE_REPORT_PATH", tmp_path / "nonexistent.json")
    data, status = ae.handle_coverage()
    assert status == 404
    assert "hint" in data


# --------------------------------------------------------------------------- #
# handle_coverage_type
# --------------------------------------------------------------------------- #

def test_coverage_type_returns_specific_type(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "COVERAGE_REPORT_PATH", tmp_path / "coverage_report.json")
    payload = {
        "n_total_papers": 582,
        "n_organoid_types": 26,
        "overall_avg_grounding_rate": 0.87,
        "corpus_pooled_grounding_rate": 0.86,
        "types_by_completeness": [],
        "by_organoid_type": {
            "cardiac": {"n_papers": 59, "completeness_score": 0.75,
                        "avg_grounding_rate": 0.9},
        },
    }
    (tmp_path / "coverage_report.json").write_text(json.dumps(payload))
    data, status = ae.handle_coverage_type("cardiac")
    assert status == 200
    assert data["organoid_type"] == "cardiac"
    assert data["n_papers"] == 59
    assert "corpus_summary" in data


def test_coverage_type_404_when_type_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "COVERAGE_REPORT_PATH", tmp_path / "coverage_report.json")
    payload = {
        "n_total_papers": 10,
        "n_organoid_types": 1,
        "overall_avg_grounding_rate": 0.9,
        "corpus_pooled_grounding_rate": 0.9,
        "types_by_completeness": [],
        "by_organoid_type": {"cardiac": {"n_papers": 10, "completeness_score": 0.7}},
    }
    (tmp_path / "coverage_report.json").write_text(json.dumps(payload))
    data, status = ae.handle_coverage_type("retinal")
    assert status == 404
    assert "available" in data


def test_coverage_type_rejects_invalid(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "COVERAGE_REPORT_PATH", tmp_path / "coverage_report.json")
    _, status = ae.handle_coverage_type("../../etc/passwd")
    assert status == 400


def test_index_includes_coverage_endpoints():
    data, status = ae.handle_index()
    assert status == 200
    assert "/analytics/coverage" in data["endpoints"]
    assert "/analytics/coverage/{organoid_type}" in data["endpoints"]
    assert "coverage" in data["generate"]


# --------------------------------------------------------------------------- #
# handle_reagent
# --------------------------------------------------------------------------- #

def test_reagent_requires_query(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", tmp_path / "reagents.jsonl")
    data, status = ae.handle_reagent("", None, 1)
    assert status == 400
    assert "error" in data


def test_reagent_404_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", tmp_path / "nonexistent.jsonl")
    data, status = ae.handle_reagent("EGF", None, 1)
    assert status == 404


def test_reagent_returns_results(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", tmp_path / "reagents.jsonl")
    records = [
        {"canonical": "EGF", "name": "EGF", "organoid_type": "intestinal",
         "pmcid": "PMC001", "kind": "signaling", "value": 50.0,
         "unit": "ng/mL", "canonical_unit": "ng/mL", "grounded": 1,
         "figure_confirmed": 0, "evidence_quote": "EGF 50 ng/mL"},
    ]
    (tmp_path / "reagents.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records)
    )
    data, status = ae.handle_reagent("EGF", None, 1)
    assert status == 200
    assert data["n_hits"] == 1
    assert len(data["results"]) == 1
    assert data["results"][0]["canonical"] == "EGF"


def test_reagent_truncates_long_query(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", tmp_path / "reagents.jsonl")
    (tmp_path / "reagents.jsonl").write_text("")
    long_q = "x" * 200
    data, status = ae.handle_reagent(long_q, None, 1)
    # empty file returns 404; but query must have been accepted (truncated)
    assert status == 404  # empty file


def test_index_includes_reagent_endpoint():
    data, _ = ae.handle_index()
    assert "/analytics/reagent?q=TERM" in data["endpoints"]


# --------------------------------------------------------------------------- #
# handle_assay_endpoints
# --------------------------------------------------------------------------- #

def test_assay_endpoints_returns_data(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    payload = {
        "n_total_papers": 582,
        "n_with_assay_endpoints": 342,
        "coverage_fraction": 0.587,
        "cross_type_cluster_usage": {},
        "by_organoid_type": {},
        "raw_top_terms": [],
    }
    (tmp_path / "assay_endpoint_summary.json").write_text(json.dumps(payload))
    data, status = ae.handle_assay_endpoints()
    assert status == 200
    assert data["n_total_papers"] == 582
    assert data["coverage_fraction"] == pytest.approx(0.587)


def test_assay_endpoints_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    data, status = ae.handle_assay_endpoints()
    assert status == 404
    assert "hint" in data


def test_index_includes_assay_endpoint():
    data, _ = ae.handle_index()
    assert "/analytics/assay-endpoints" in data["endpoints"]
    assert "assay_endpoints" in data["generate"]


# --------------------------------------------------------------------------- #
# handle_quality
# --------------------------------------------------------------------------- #

def _quality_payload():
    return {
        "n_total": 582,
        "avg_score": 0.72,
        "n_gold": 150,
        "n_silver": 280,
        "n_bronze": 152,
        "gold_threshold": 0.80,
        "silver_threshold": 0.55,
        "by_organoid_type": {"cardiac": {"n_papers": 59, "avg_score": 0.75}},
        "scores": [
            {"pmcid": "PMC001", "organoid_type": "cardiac",
             "quality_score": 0.9, "quality_tier": "gold", "score_components": {}},
            {"pmcid": "PMC002", "organoid_type": "retinal",
             "quality_score": 0.6, "quality_tier": "silver", "score_components": {}},
        ],
    }


def test_quality_returns_data(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    (tmp_path / "protocol_quality_scores.json").write_text(json.dumps(_quality_payload()))
    data, status = ae.handle_quality(None, None)
    assert status == 200
    assert data["n_total"] == 582
    assert data["n_results"] == 2


def test_quality_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    data, status = ae.handle_quality(None, None)
    assert status == 404
    assert "hint" in data


def test_quality_filters_by_type(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    (tmp_path / "protocol_quality_scores.json").write_text(json.dumps(_quality_payload()))
    data, status = ae.handle_quality("cardiac", None)
    assert status == 200
    assert data["n_results"] == 1
    assert data["scores"][0]["organoid_type"] == "cardiac"


def test_quality_filters_by_tier(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    (tmp_path / "protocol_quality_scores.json").write_text(json.dumps(_quality_payload()))
    data, status = ae.handle_quality(None, "gold")
    assert status == 200
    assert all(r["quality_tier"] == "gold" for r in data["scores"])


def test_quality_rejects_invalid_tier(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    (tmp_path / "protocol_quality_scores.json").write_text(json.dumps(_quality_payload()))
    _, status = ae.handle_quality(None, "platinum")
    assert status == 400


def test_index_includes_quality_endpoint():
    data, _ = ae.handle_index()
    assert "/analytics/quality" in data["endpoints"]
    assert "quality" in data["generate"]


# --------------------------------------------------------------------------- #
# handle_status
# --------------------------------------------------------------------------- #

def test_status_returns_structure(tmp_path, monkeypatch):
    """handle_status returns a dict with 'healthy' key."""
    import system_status as ss
    monkeypatch.setattr(ss, "PROTOCOLS_JSONL", tmp_path / "protocols.jsonl")
    monkeypatch.setattr(ss, "OUTPUTS", tmp_path)
    monkeypatch.setattr(ss, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(ss, "ANALYTICS_ARTIFACTS", [])
    # No protocols.jsonl → corpus not ok → unhealthy
    data, status = ae.handle_status()
    assert "healthy" in data
    assert status in (200, 503)


def test_status_unhealthy_when_corpus_missing(tmp_path, monkeypatch):
    import system_status as ss
    monkeypatch.setattr(ss, "PROTOCOLS_JSONL", tmp_path / "protocols.jsonl")
    monkeypatch.setattr(ss, "OUTPUTS", tmp_path)
    monkeypatch.setattr(ss, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(ss, "ANALYTICS_ARTIFACTS", [])
    data, status = ae.handle_status()
    assert not data["healthy"]
    assert status == 503


def test_index_includes_status_endpoint():
    data, _ = ae.handle_index()
    assert "/analytics/status" in data["endpoints"]


# --------------------------------------------------------------------------- #
# handle_summary
# --------------------------------------------------------------------------- #

def test_summary_404_when_no_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    monkeypatch.setattr(ae, "COVERAGE_REPORT_PATH", tmp_path / "nonexistent.json")
    data, status = ae.handle_summary()
    assert status == 404
    assert "hint" in data


def test_summary_returns_corpus_when_coverage_present(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    monkeypatch.setattr(ae, "COVERAGE_REPORT_PATH", tmp_path / "coverage_report.json")
    payload = {
        "n_total_papers": 582,
        "n_organoid_types": 26,
        "overall_avg_grounding_rate": 0.87,
        "corpus_pooled_grounding_rate": 0.86,
        "types_by_completeness": [
            {"organoid_type": "cardiac", "n_papers": 59, "completeness_score": 0.85,
             "avg_grounding_rate": 0.9},
        ],
        "by_organoid_type": {},
    }
    (tmp_path / "coverage_report.json").write_text(json.dumps(payload))
    data, status = ae.handle_summary()
    assert status == 200
    assert data["corpus"]["n_papers"] == 582
    assert len(data["top_types_by_completeness"]) == 1


def test_summary_includes_quality(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    monkeypatch.setattr(ae, "COVERAGE_REPORT_PATH", tmp_path / "nonexistent.json")
    (tmp_path / "protocol_quality_scores.json").write_text(json.dumps({
        "avg_score": 0.72, "n_gold": 150, "n_silver": 280, "n_bronze": 152, "n_total": 582,
    }))
    data, status = ae.handle_summary()
    assert status == 200
    assert data["quality"]["n_gold"] == 150


def test_summary_includes_analytics_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    monkeypatch.setattr(ae, "COVERAGE_REPORT_PATH", tmp_path / "nonexistent.json")
    (tmp_path / "protocol_quality_scores.json").write_text('{"avg_score": 0.7}')
    data, status = ae.handle_summary()
    assert status == 200
    assert "analytics_ready" in data
    assert not data["analytics_ready"]["coverage"]
    assert data["analytics_ready"]["quality"]


def test_index_includes_summary_endpoint():
    data, _ = ae.handle_index()
    assert "/analytics/summary" in data["endpoints"]


# --------------------------------------------------------------------------- #
# handle_mior
# --------------------------------------------------------------------------- #

def test_mior_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    data, status = ae.handle_mior()
    assert status == 404
    assert "hint" in data


def test_mior_returns_data_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    payload = {
        "n_total": 582,
        "avg_mior_completeness": 0.73,
        "n_full": 150, "n_partial": 300, "n_sparse": 132,
    }
    (tmp_path / "mior_completeness.json").write_text(json.dumps(payload))
    data, status = ae.handle_mior()
    assert status == 200
    assert data["n_total"] == 582
    assert data["avg_mior_completeness"] == pytest.approx(0.73)


def test_mior_500_on_bad_json(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    (tmp_path / "mior_completeness.json").write_text("not json{{{")
    data, status = ae.handle_mior()
    assert status == 500


def test_index_includes_mior_endpoint():
    data, _ = ae.handle_index()
    assert "/analytics/mior" in data["endpoints"]


# --------------------------------------------------------------------------- #
# handle_candidates
# --------------------------------------------------------------------------- #

def test_candidates_returns_pool_counts(tmp_path, monkeypatch):
    incoming = tmp_path / "data" / "corpus" / "incoming"
    incoming.mkdir(parents=True)
    # Write a small candidate CSV
    csv_text = "organoid_type,doi,pmcid,license\ncardiac,10.1/a,PMC001,CC-BY\ncardiac,10.1/b,PMC002,CC-BY-NC\n"
    (incoming / "organoid_corpus_candidates_180.csv").write_text(csv_text)
    monkeypatch.setattr(ae, "REPO", tmp_path)
    data, status = ae.handle_candidates()
    assert status == 200
    assert data["total_candidates"] == 2
    assert "organoid_corpus_candidates_180.csv" in data["pools"]
    assert data["oa_verified"] is None
    assert "hint" in data


def test_candidates_with_oa_results(tmp_path, monkeypatch):
    incoming = tmp_path / "data" / "corpus" / "incoming"
    incoming.mkdir(parents=True)
    (incoming / "organoid_corpus_candidates_180.csv").write_text(
        "organoid_type,doi,pmcid,license\ncardiac,10.1/a,PMC001,CC-BY\n"
    )
    oa_dir = tmp_path / "data" / "corpus" / "oa_verified"
    oa_dir.mkdir(parents=True)
    oa_payload = {
        "pool_size": 1, "public_ok": 1, "rejected": 0,
        "quarantine": 0, "license_mismatches": 0,
        "public_pmcids": ["PMC001"], "rejected_pmcids": [],
        "quarantine_pmcids": [], "mismatch_details": [],
    }
    (oa_dir / "oa_results.json").write_text(json.dumps(oa_payload))
    monkeypatch.setattr(ae, "REPO", tmp_path)
    data, status = ae.handle_candidates()
    assert status == 200
    assert data["oa_verified"]["public_ok"] == 1
    assert "PMC001" in data["public_pmcids_sample"]


def test_candidates_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/candidates" in data["endpoints"]
