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


def test_consensus_list_skips_all_aggregate_list(tmp_path, monkeypatch):
    """consensus_all.json is the aggregate LIST (not a per-type dict). The index must
    skip it instead of calling .get() on a list — regression for the live 500
    ('list' object has no attribute 'get')."""
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    (tmp_path / "consensus_intestinal.json").write_text(
        json.dumps({"organoid_type": "intestinal", "n_protocols": 12})
    )
    (tmp_path / "consensus_all.json").write_text(
        json.dumps([{"organoid_type": "intestinal"}, {"organoid_type": "cerebral"}])
    )
    data, status = ae.handle_consensus_list()
    assert status == 200                                   # no 500
    types = {r["organoid_type"] for r in data["available"]}
    assert types == {"intestinal"}                         # 'all' aggregate excluded


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


def test_load_public_protocol_returns_none_when_jsonl_missing(tmp_path, monkeypatch):
    """_load_public_protocol returns None gracefully when JSONL files aren't present."""
    monkeypatch.setattr(ae, "REAGENTS_JSONL", tmp_path / "missing_reagents.jsonl")
    result = ae._load_public_protocol("PMC999")
    assert result is None


def test_load_public_protocol_builds_protocol_with_reagents(tmp_path, monkeypatch):
    """_load_public_protocol assembles signaling_factors + supplements from reagents.jsonl."""
    proto_jsonl = tmp_path / "protocols.jsonl"
    reag_jsonl = tmp_path / "reagents.jsonl"
    proto_jsonl.write_text(
        json.dumps({"pmcid": "PMC123", "organoid_type": "kidney", "doi": "10.1/x", "license": "CC-BY"}) + "\n"
    )
    reag_jsonl.write_text(
        json.dumps({"pmcid": "PMC123", "name": "EGF", "canonical": "EGF",
                    "kind": "signaling", "role": "component", "value": 10.0,
                    "canonical_unit": "ng/mL", "evidence_quote": "EGF 10 ng/mL",
                    "grounded": True}) + "\n" +
        json.dumps({"pmcid": "PMC123", "name": "B27", "canonical": "B27",
                    "kind": "supplement", "role": "supplement", "value": None,
                    "canonical_unit": None, "evidence_quote": "B27 supplement",
                    "grounded": False}) + "\n"
    )
    monkeypatch.setattr(ae, "REAGENTS_JSONL", reag_jsonl)
    # Patch PROTOCOLS_JSONL path used inside _load_public_protocol
    import unittest.mock as mock
    with mock.patch.object(ae.Path, "__new__",
                           side_effect=lambda cls, *a: proto_jsonl if "protocols.jsonl" in str(a) else ae.Path(*a)):
        pass  # can't easily mock open-file path; test indirectly via compare

    # Direct approach: monkeypatch REPO so PROTOCOLS_JSONL resolves correctly
    original = ae.REPO
    monkeypatch.setattr(ae, "REPO", tmp_path)
    (tmp_path / "exports").mkdir(exist_ok=True)
    (tmp_path / "exports" / "public").mkdir(exist_ok=True)
    (tmp_path / "exports" / "public" / "protocols.jsonl").write_text(
        json.dumps({"pmcid": "PMC123", "organoid_type": "kidney"}) + "\n"
    )
    (tmp_path / "exports" / "public" / "reagents.jsonl").write_text(
        json.dumps({"pmcid": "PMC123", "name": "EGF", "canonical": "EGF",
                    "kind": "signaling", "role": "component", "value": 10.0,
                    "canonical_unit": "ng/mL", "evidence_quote": "EGF 10 ng/mL",
                    "grounded": True}) + "\n"
    )
    # Need to re-derive PROTOCOLS_JSONL in the function — it uses a local constant
    # Instead, test via the REAGENTS_JSONL monkeypatch + a tmp protocols JSONL
    # The function constructs PROTOCOLS_JSONL = REPO / "exports" / "public" / "protocols.jsonl"
    # so patching REPO is the right approach
    result = ae._load_public_protocol("PMC123")
    assert result is not None
    assert result["organoid_type"] == "kidney"
    assert result["_source"] == "public_summary"
    sig = result.get("signaling_factors", [])
    assert len(sig) == 1
    assert sig[0]["name"] == "EGF"


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
    assert "mior" in data["analytics_ready"]


def test_summary_includes_manifest_n_reagents(tmp_path, monkeypatch):
    """Summary endpoint embeds manifest.n_reagents so dashboard avoids a 4th fetch."""
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    monkeypatch.setattr(ae, "COVERAGE_REPORT_PATH", tmp_path / "nonexistent.json")
    monkeypatch.setattr(ae, "MANIFEST_PATH", tmp_path / "manifest.json")
    (tmp_path / "protocol_quality_scores.json").write_text('{"avg_score": 0.7}')
    (tmp_path / "manifest.json").write_text(json.dumps({
        "schema_version": "0.4",
        "n_papers": 582,
        "n_types": 26,
        "tables": {"protocols": 582, "reagents": 5458},
        "papers": [],
    }))
    data, status = ae.handle_summary()
    assert status == 200
    assert "manifest" in data
    assert data["manifest"]["n_reagents"] == 5458
    assert data["manifest"]["schema_version"] == "0.4"


def test_summary_includes_mior_when_present(tmp_path, monkeypatch):
    """Summary endpoint embeds MIOR stats so callers avoid a second fetch."""
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    monkeypatch.setattr(ae, "COVERAGE_REPORT_PATH", tmp_path / "nonexistent.json")
    (tmp_path / "protocol_quality_scores.json").write_text('{"avg_score": 0.7}')
    mior_payload = {
        "avg_mior_completeness": 0.63,
        "n_full": 120,
        "n_partial": 280,
        "n_sparse": 182,
        "n_total": 582,
    }
    (tmp_path / "mior_completeness.json").write_text(json.dumps(mior_payload))
    data, status = ae.handle_summary()
    assert status == 200
    assert "mior" in data
    assert data["mior"]["avg_mior_completeness"] == 0.63
    assert data["mior"]["n_full"] == 120
    assert data["mior"]["n_total"] == 582
    assert data["analytics_ready"]["mior"]


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


# --------------------------------------------------------------------------- #
# handle_reagent_network
# --------------------------------------------------------------------------- #

def _write_reagents_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows))


def test_reagent_network_400_when_no_query(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", tmp_path / "reagents.jsonl")
    data, status = ae.handle_reagent_network("", 20)
    assert status == 400
    assert "error" in data


def test_reagent_network_404_when_jsonl_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", tmp_path / "reagents.jsonl")
    data, status = ae.handle_reagent_network("EGF", 20)
    assert status == 404
    assert "hint" in data


def test_reagent_network_empty_when_no_match(tmp_path, monkeypatch):
    reagents = tmp_path / "reagents.jsonl"
    _write_reagents_jsonl(reagents, [
        {"pmcid": "PMC001", "canonical": "WNT3A", "name": "WNT3A"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", reagents)
    data, status = ae.handle_reagent_network("EGF", 20)
    assert status == 200
    assert data["n_papers"] == 0
    assert data["co_occurring"] == []


def test_reagent_network_returns_cooccurring_reagents(tmp_path, monkeypatch):
    reagents = tmp_path / "reagents.jsonl"
    rows = [
        # PMC001 has EGF + WNT3A + Noggin
        {"pmcid": "PMC001", "canonical": "EGF",    "name": "EGF"},
        {"pmcid": "PMC001", "canonical": "WNT3A",  "name": "WNT3A"},
        {"pmcid": "PMC001", "canonical": "Noggin", "name": "Noggin"},
        # PMC002 has EGF + WNT3A
        {"pmcid": "PMC002", "canonical": "EGF",   "name": "EGF"},
        {"pmcid": "PMC002", "canonical": "WNT3A", "name": "WNT3A"},
        # PMC003 has only WNT3A (should not contribute to EGF co-occurrence)
        {"pmcid": "PMC003", "canonical": "WNT3A", "name": "WNT3A"},
    ]
    _write_reagents_jsonl(reagents, rows)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", reagents)
    data, status = ae.handle_reagent_network("EGF", 20)
    assert status == 200
    assert data["n_papers"] == 2
    names = [r["name"] for r in data["co_occurring"]]
    assert "WNT3A" in names
    assert "Noggin" in names
    # EGF itself must not appear in its own network
    assert "EGF" not in names
    # WNT3A appears in 2 EGF papers; Noggin in 1 — WNT3A should rank higher
    assert names[0] == "WNT3A"


def test_reagent_network_respects_limit(tmp_path, monkeypatch):
    reagents = tmp_path / "reagents.jsonl"
    rows = [{"pmcid": "PMC001", "canonical": "EGF", "name": "EGF"}]
    for i in range(10):
        rows.append({"pmcid": "PMC001", "canonical": f"R{i:02d}", "name": f"R{i:02d}"})
    _write_reagents_jsonl(reagents, rows)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", reagents)
    data, status = ae.handle_reagent_network("EGF", 3)
    assert status == 200
    assert len(data["co_occurring"]) == 3


def test_reagent_network_rank_field(tmp_path, monkeypatch):
    reagents = tmp_path / "reagents.jsonl"
    rows = [
        {"pmcid": "PMC001", "canonical": "EGF",   "name": "EGF"},
        {"pmcid": "PMC001", "canonical": "WNT3A", "name": "WNT3A"},
    ]
    _write_reagents_jsonl(reagents, rows)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", reagents)
    data, status = ae.handle_reagent_network("EGF", 20)
    assert status == 200
    assert data["co_occurring"][0]["rank"] == 1


def test_reagent_network_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/reagent-network?q=TERM" in data["endpoints"]


# --------------------------------------------------------------------------- #
# handle_type_similarity
# --------------------------------------------------------------------------- #

def test_type_similarity_404_when_jsonl_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", tmp_path / "reagents.jsonl")
    data, status = ae.handle_type_similarity(5)
    assert status == 404
    assert "hint" in data


def test_type_similarity_returns_all_types(tmp_path, monkeypatch):
    reagents = tmp_path / "reagents.jsonl"
    rows = [
        {"pmcid": "PMC001", "organoid_type": "cerebral",   "canonical": "EGF"},
        {"pmcid": "PMC001", "organoid_type": "cerebral",   "canonical": "WNT3A"},
        {"pmcid": "PMC002", "organoid_type": "intestinal", "canonical": "EGF"},
        {"pmcid": "PMC002", "organoid_type": "intestinal", "canonical": "Noggin"},
        {"pmcid": "PMC003", "organoid_type": "kidney",     "canonical": "Noggin"},
    ]
    reagents.write_text("\n".join(json.dumps(r) for r in rows))
    monkeypatch.setattr(ae, "REAGENTS_JSONL", reagents)
    data, status = ae.handle_type_similarity(5)
    assert status == 200
    assert data["n_types"] == 3
    assert "cerebral" in data["per_type"]
    assert "intestinal" in data["per_type"]
    assert "kidney" in data["per_type"]


def test_type_similarity_jaccard_correct(tmp_path, monkeypatch):
    reagents = tmp_path / "reagents.jsonl"
    rows = [
        # cerebral: {EGF, WNT3A}; intestinal: {EGF, Noggin}
        # Jaccard = |{EGF}| / |{EGF,WNT3A,Noggin}| = 1/3 ≈ 0.333
        {"pmcid": "PMC001", "organoid_type": "cerebral",   "canonical": "EGF"},
        {"pmcid": "PMC001", "organoid_type": "cerebral",   "canonical": "WNT3A"},
        {"pmcid": "PMC002", "organoid_type": "intestinal", "canonical": "EGF"},
        {"pmcid": "PMC002", "organoid_type": "intestinal", "canonical": "Noggin"},
    ]
    reagents.write_text("\n".join(json.dumps(r) for r in rows))
    monkeypatch.setattr(ae, "REAGENTS_JSONL", reagents)
    data, status = ae.handle_type_similarity(5)
    assert status == 200
    # cerebral's top_similar should list intestinal with jaccard ≈ 0.333
    top = data["per_type"]["cerebral"]["top_similar"]
    assert len(top) == 1
    assert top[0]["type"] == "intestinal"
    assert abs(top[0]["jaccard"] - 1/3) < 0.001
    assert top[0]["n_shared"] == 1


def test_type_similarity_respects_top_n(tmp_path, monkeypatch):
    reagents = tmp_path / "reagents.jsonl"
    rows = []
    for i in range(5):
        t = f"type{i}"
        rows.append({"pmcid": f"PMC{i:03d}", "organoid_type": t, "canonical": "EGF"})
    reagents.write_text("\n".join(json.dumps(r) for r in rows))
    monkeypatch.setattr(ae, "REAGENTS_JSONL", reagents)
    data, status = ae.handle_type_similarity(2)
    assert status == 200
    for t in data["per_type"].values():
        assert len(t["top_similar"]) <= 2


def test_type_similarity_n_reagents_field(tmp_path, monkeypatch):
    reagents = tmp_path / "reagents.jsonl"
    rows = [
        {"pmcid": "PMC001", "organoid_type": "cerebral", "canonical": "EGF"},
        {"pmcid": "PMC001", "organoid_type": "cerebral", "canonical": "WNT3A"},
    ]
    reagents.write_text("\n".join(json.dumps(r) for r in rows))
    monkeypatch.setattr(ae, "REAGENTS_JSONL", reagents)
    data, status = ae.handle_type_similarity(5)
    assert status == 200
    assert data["per_type"]["cerebral"]["n_reagents"] == 2


def test_type_similarity_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/type-similarity" in data["endpoints"]


# --------------------------------------------------------------------------- #
# handle_type_timeseries
# --------------------------------------------------------------------------- #

def _write_protocols_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows))


def test_type_timeseries_404_when_jsonl_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", tmp_path / "protocols.jsonl")
    data, status = ae.handle_type_timeseries()
    assert status == 404
    assert "hint" in data


def test_type_timeseries_returns_years_and_types(tmp_path, monkeypatch):
    protos = tmp_path / "protocols.jsonl"
    rows = [
        {"pmcid": "PMC001", "organoid_type": "cardiac",   "year": 2021},
        {"pmcid": "PMC002", "organoid_type": "cerebral",  "year": 2021},
        {"pmcid": "PMC003", "organoid_type": "cardiac",   "year": 2022},
        {"pmcid": "PMC004", "organoid_type": "intestinal","year": 2022},
    ]
    _write_protocols_jsonl(protos, rows)
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", protos)
    data, status = ae.handle_type_timeseries()
    assert status == 200
    assert "2021" in data["years"]
    assert "2022" in data["years"]
    assert data["by_year"]["2021"]["cardiac"] == 1
    assert data["by_year"]["2022"]["cardiac"] == 1
    assert data["by_year"]["2022"]["intestinal"] == 1
    assert data["total_by_year"]["2021"] == 2
    assert data["total_by_year"]["2022"] == 2


def test_type_timeseries_by_type(tmp_path, monkeypatch):
    protos = tmp_path / "protocols.jsonl"
    rows = [
        {"pmcid": "PMC001", "organoid_type": "cardiac", "year": 2020},
        {"pmcid": "PMC002", "organoid_type": "cardiac", "year": 2021},
    ]
    _write_protocols_jsonl(protos, rows)
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", protos)
    data, status = ae.handle_type_timeseries()
    assert status == 200
    assert data["by_type"]["cardiac"]["2020"] == 1
    assert data["by_type"]["cardiac"]["2021"] == 1


def test_type_timeseries_first_appearance(tmp_path, monkeypatch):
    protos = tmp_path / "protocols.jsonl"
    rows = [
        {"pmcid": "PMC001", "organoid_type": "cardiac",  "year": 2018},
        {"pmcid": "PMC002", "organoid_type": "cerebral", "year": 2014},
        {"pmcid": "PMC003", "organoid_type": "cardiac",  "year": 2020},
    ]
    _write_protocols_jsonl(protos, rows)
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", protos)
    data, status = ae.handle_type_timeseries()
    assert status == 200
    assert data["first_appearance"]["cardiac"] == "2018"
    assert data["first_appearance"]["cerebral"] == "2014"


def test_type_timeseries_excludes_other(tmp_path, monkeypatch):
    protos = tmp_path / "protocols.jsonl"
    rows = [
        {"pmcid": "PMC001", "organoid_type": "other",  "year": 2022},
        {"pmcid": "PMC002", "organoid_type": "cardiac", "year": 2022},
    ]
    _write_protocols_jsonl(protos, rows)
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", protos)
    data, status = ae.handle_type_timeseries()
    assert status == 200
    assert "other" not in data["by_type"]
    assert data["total_by_year"]["2022"] == 1


def test_type_timeseries_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/type-timeseries" in data["endpoints"]


# --------------------------------------------------------------------------- #
# handle_universal_reagents
# --------------------------------------------------------------------------- #

def _make_reagents_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows))


def test_universal_reagents_404_when_jsonl_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", tmp_path / "r.jsonl")
    data, status = ae.handle_universal_reagents(None, 0.5)
    assert status == 404
    assert "hint" in data


def test_universal_reagents_returns_per_type_essentials(tmp_path, monkeypatch):
    reagents = tmp_path / "r.jsonl"
    rows = [
        # intestinal: 2 papers; EGF appears in both (100%), WNT3A in 1 (50%)
        {"pmcid": "PMC001", "organoid_type": "intestinal", "canonical": "EGF"},
        {"pmcid": "PMC001", "organoid_type": "intestinal", "canonical": "WNT3A"},
        {"pmcid": "PMC002", "organoid_type": "intestinal", "canonical": "EGF"},
    ]
    _make_reagents_jsonl(reagents, rows)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", reagents)
    data, status = ae.handle_universal_reagents(None, 0.5)
    assert status == 200
    pt = data["per_type"]["intestinal"]
    names = [e["canonical"] for e in pt["essentials"]]
    assert "egf" in names
    assert "wnt3a" in names
    egf_entry = next(e for e in pt["essentials"] if e["canonical"] == "egf")
    assert egf_entry["fraction"] == 1.0
    assert egf_entry["n_papers"] == 2


def test_universal_reagents_min_fraction_filter(tmp_path, monkeypatch):
    reagents = tmp_path / "r.jsonl"
    rows = [
        # EGF: 1/3 = 33%; WNT3A: 3/3 = 100%
        {"pmcid": "PMC001", "organoid_type": "intestinal", "canonical": "EGF"},
        {"pmcid": "PMC001", "organoid_type": "intestinal", "canonical": "WNT3A"},
        {"pmcid": "PMC002", "organoid_type": "intestinal", "canonical": "WNT3A"},
        {"pmcid": "PMC003", "organoid_type": "intestinal", "canonical": "WNT3A"},
    ]
    _make_reagents_jsonl(reagents, rows)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", reagents)
    data, status = ae.handle_universal_reagents(None, 0.5)
    assert status == 200
    names = [e["canonical"] for e in data["per_type"]["intestinal"]["essentials"]]
    assert "wnt3a" in names
    assert "egf" not in names   # 33% < 50% threshold


def test_universal_reagents_single_type_filter(tmp_path, monkeypatch):
    reagents = tmp_path / "r.jsonl"
    rows = [
        {"pmcid": "PMC001", "organoid_type": "cardiac",   "canonical": "CHIR"},
        {"pmcid": "PMC001", "organoid_type": "intestinal","canonical": "WNT3A"},
    ]
    _make_reagents_jsonl(reagents, rows)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", reagents)
    data, status = ae.handle_universal_reagents("cardiac", 0.5)
    assert status == 200
    assert data["organoid_type"] == "cardiac"
    assert "cardiac" in data["per_type"]
    assert "intestinal" not in data["per_type"]


def test_universal_reagents_404_for_unknown_type(tmp_path, monkeypatch):
    reagents = tmp_path / "r.jsonl"
    _make_reagents_jsonl(reagents, [
        {"pmcid": "PMC001", "organoid_type": "cardiac", "canonical": "CHIR"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", reagents)
    data, status = ae.handle_universal_reagents("bladder", 0.5)
    assert status == 404
    assert "available_types" in data


def test_universal_reagents_cross_type_universals(tmp_path, monkeypatch):
    reagents = tmp_path / "r.jsonl"
    # EGF in both cardiac and intestinal (at 100%)
    rows = [
        {"pmcid": "PMC001", "organoid_type": "cardiac",   "canonical": "EGF"},
        {"pmcid": "PMC002", "organoid_type": "intestinal","canonical": "EGF"},
    ]
    _make_reagents_jsonl(reagents, rows)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", reagents)
    data, status = ae.handle_universal_reagents(None, 0.5)
    assert status == 200
    cross = [e["canonical"] for e in data["cross_type_universals"]]
    assert "egf" in cross


def test_universal_reagents_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/universal-reagents" in data["endpoints"]


# --------------------------------------------------------------------------- #
# handle_species_breakdown
# --------------------------------------------------------------------------- #

def _write_protocols_for_species(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_species_breakdown_404_when_jsonl_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", tmp_path / "missing.jsonl")
    data, status = ae.handle_species_breakdown(None)
    assert status == 404
    assert "hint" in data


def test_species_breakdown_400_for_invalid_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_species(p, [{"organoid_type": "kidney", "species": "human"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_species_breakdown("../../etc/passwd")
    assert status == 400


def test_species_breakdown_returns_all_types(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_species(p, [
        {"organoid_type": "kidney",    "species": "human"},
        {"organoid_type": "cerebral",  "species": "mouse"},
        {"organoid_type": "intestinal","species": "human"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_species_breakdown(None)
    assert status == 200
    assert "per_type" in data
    assert "kidney" in data["per_type"]
    assert "cerebral" in data["per_type"]
    assert data["n_types"] == 3


def test_species_breakdown_cross_corpus_totals(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_species(p, [
        {"organoid_type": "kidney",   "species": "human"},
        {"organoid_type": "kidney",   "species": "human"},
        {"organoid_type": "cerebral", "species": "mouse"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_species_breakdown(None)
    assert status == 200
    assert data["cross_corpus"]["human"] == 2
    assert data["cross_corpus"]["mouse"] == 1


def test_species_breakdown_normalises_aliases(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_species(p, [
        {"organoid_type": "kidney", "species": "Mus musculus"},
        {"organoid_type": "kidney", "species": "murine"},
        {"organoid_type": "kidney", "species": "Homo sapiens"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_species_breakdown("kidney")
    assert status == 200
    sp = data["species"]
    assert sp.get("mouse", 0) == 2, f"expected 2 mouse, got {sp}"
    assert sp.get("human", 0) == 1, f"expected 1 human, got {sp}"


def test_species_breakdown_single_type_filter(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_species(p, [
        {"organoid_type": "kidney",   "species": "human"},
        {"organoid_type": "cerebral", "species": "mouse"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_species_breakdown("kidney")
    assert status == 200
    assert "organoid_type" in data
    assert data["organoid_type"] == "kidney"
    assert "species" in data
    assert "per_type" not in data


def test_species_breakdown_404_for_unknown_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_species(p, [{"organoid_type": "kidney", "species": "human"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_species_breakdown("nonexistent")
    assert status == 404
    assert "available_types" in data


def test_species_breakdown_excludes_other_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_species(p, [
        {"organoid_type": "other",  "species": "human"},
        {"organoid_type": "kidney", "species": "human"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_species_breakdown(None)
    assert status == 200
    assert "other" not in data["per_type"]
    assert data["n_types"] == 1


def test_species_breakdown_missing_species_counted_as_not_stated(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_species(p, [
        {"organoid_type": "kidney"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_species_breakdown("kidney")
    assert status == 200
    assert data["species"].get("not_stated", 0) == 1


def test_species_breakdown_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/species-breakdown" in data["endpoints"]


def test_summary_includes_species_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    monkeypatch.setattr(ae, "COVERAGE_REPORT_PATH", tmp_path / "coverage_report.json")
    protocols = tmp_path / "protocols.jsonl"
    _write_protocols_for_species(protocols, [
        {"organoid_type": "kidney",   "species": "human"},
        {"organoid_type": "cerebral", "species": "human"},
        {"organoid_type": "cardiac",  "species": "mouse"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", protocols)
    # Provide minimal coverage so summary returns 200
    (tmp_path / "coverage_report.json").write_text(json.dumps({
        "n_total_papers": 3, "n_organoid_types": 3,
        "overall_avg_grounding_rate": 0.9, "corpus_pooled_grounding_rate": 0.88,
        "types_by_completeness": [],
    }))
    data, status = ae.handle_summary()
    assert status == 200
    assert "species_snapshot" in data
    snap = data["species_snapshot"]
    assert snap.get("human", 0) == 2
    assert snap.get("mouse", 0) == 1


# --------------------------------------------------------------------------- #
# handle_matrix_breakdown
# --------------------------------------------------------------------------- #

def _write_protocols_for_matrix(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_matrix_breakdown_404_when_jsonl_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", tmp_path / "missing.jsonl")
    data, status = ae.handle_matrix_breakdown(None)
    assert status == 404
    assert "hint" in data


def test_matrix_breakdown_400_for_invalid_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_matrix(p, [{"organoid_type": "kidney", "matrix": "Matrigel"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_matrix_breakdown("../../etc/passwd")
    assert status == 400


def test_matrix_breakdown_returns_all_types(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_matrix(p, [
        {"organoid_type": "kidney",    "matrix": "Matrigel"},
        {"organoid_type": "cerebral",  "matrix": "Geltrex"},
        {"organoid_type": "intestinal","matrix": "Matrigel"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_matrix_breakdown(None)
    assert status == 200
    assert "per_type" in data
    assert "kidney" in data["per_type"]
    assert data["n_types"] == 3


def test_matrix_breakdown_cross_corpus_totals(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_matrix(p, [
        {"organoid_type": "kidney",   "matrix": "Matrigel"},
        {"organoid_type": "kidney",   "matrix": "Matrigel"},
        {"organoid_type": "cerebral", "matrix": "Geltrex"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_matrix_breakdown(None)
    assert status == 200
    assert data["cross_corpus"]["Matrigel"] == 2
    assert data["cross_corpus"]["Geltrex"] == 1


def test_matrix_breakdown_normalises_aliases(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_matrix(p, [
        {"organoid_type": "kidney", "matrix": "matrigel"},
        {"organoid_type": "kidney", "matrix": "Matrigel™"},
        {"organoid_type": "kidney", "matrix": "Matrigel TM"},
        {"organoid_type": "kidney", "matrix": "vitronectin"},
        {"organoid_type": "kidney", "matrix": "BME"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_matrix_breakdown("kidney")
    assert status == 200
    mx = data["matrix"]
    assert mx.get("Matrigel", 0) == 3, f"expected 3 Matrigel, got {mx}"
    assert mx.get("Vitronectin", 0) == 1, f"expected 1 Vitronectin, got {mx}"
    assert mx.get("BME", 0) == 1, f"expected 1 BME, got {mx}"


def test_matrix_breakdown_single_type_filter(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_matrix(p, [
        {"organoid_type": "kidney",   "matrix": "Matrigel"},
        {"organoid_type": "cerebral", "matrix": "Geltrex"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_matrix_breakdown("kidney")
    assert status == 200
    assert "organoid_type" in data
    assert data["organoid_type"] == "kidney"
    assert "matrix" in data
    assert "per_type" not in data


def test_matrix_breakdown_404_for_unknown_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_matrix(p, [{"organoid_type": "kidney", "matrix": "Matrigel"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_matrix_breakdown("nonexistent")
    assert status == 404
    assert "available_types" in data


def test_matrix_breakdown_excludes_other_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_matrix(p, [
        {"organoid_type": "other",  "matrix": "Matrigel"},
        {"organoid_type": "kidney", "matrix": "Geltrex"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_matrix_breakdown(None)
    assert status == 200
    assert "other" not in data["per_type"]
    assert data["n_types"] == 1


def test_matrix_breakdown_missing_matrix_counted_as_not_stated(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_matrix(p, [{"organoid_type": "kidney"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_matrix_breakdown("kidney")
    assert status == 200
    assert data["matrix"].get("not_stated", 0) == 1


def test_matrix_breakdown_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/matrix-breakdown" in data["endpoints"]


def test_summary_includes_matrix_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    monkeypatch.setattr(ae, "COVERAGE_REPORT_PATH", tmp_path / "coverage_report.json")
    protocols = tmp_path / "protocols.jsonl"
    _write_protocols_for_matrix(protocols, [
        {"organoid_type": "kidney",   "matrix": "Matrigel"},
        {"organoid_type": "cerebral", "matrix": "Matrigel"},
        {"organoid_type": "cardiac",  "matrix": "Geltrex"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", protocols)
    (tmp_path / "coverage_report.json").write_text(json.dumps({
        "n_total_papers": 3, "n_organoid_types": 3,
        "overall_avg_grounding_rate": 0.9, "corpus_pooled_grounding_rate": 0.88,
        "types_by_completeness": [],
    }))
    data, status = ae.handle_summary()
    assert status == 200
    assert "matrix_snapshot" in data
    snap = data["matrix_snapshot"]
    assert snap.get("Matrigel", 0) == 2
    assert snap.get("Geltrex", 0) == 1


# --------------------------------------------------------------------------- #
# handle_base_media_breakdown
# --------------------------------------------------------------------------- #

def _write_protocols_for_bm(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_base_media_breakdown_404_when_jsonl_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", tmp_path / "missing.jsonl")
    data, status = ae.handle_base_media_breakdown(None)
    assert status == 404
    assert "hint" in data


def test_base_media_breakdown_400_for_invalid_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_bm(p, [{"organoid_type": "kidney", "base_media": "DMEM/F12"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_base_media_breakdown("../../etc/passwd")
    assert status == 400


def test_base_media_breakdown_returns_all_types(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_bm(p, [
        {"organoid_type": "kidney",    "base_media": "DMEM/F12"},
        {"organoid_type": "cerebral",  "base_media": "mTeSR1"},
        {"organoid_type": "intestinal","base_media": "Advanced DMEM/F12"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_base_media_breakdown(None)
    assert status == 200
    assert "per_type" in data
    assert "kidney" in data["per_type"]
    assert data["n_types"] == 3


def test_base_media_breakdown_cross_corpus_totals(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_bm(p, [
        {"organoid_type": "kidney",   "base_media": "DMEM/F12"},
        {"organoid_type": "kidney",   "base_media": "DMEM/F12"},
        {"organoid_type": "cerebral", "base_media": "mTeSR1"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_base_media_breakdown(None)
    assert status == 200
    assert data["cross_corpus"]["DMEM/F12"] == 2
    assert data["cross_corpus"]["mTeSR1"] == 1


def test_base_media_breakdown_normalises_aliases(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_bm(p, [
        {"organoid_type": "kidney", "base_media": "advanced DMEM/F12"},
        {"organoid_type": "kidney", "base_media": "Advanced DMEM/F-12"},
        {"organoid_type": "kidney", "base_media": "AdDMEM/F12"},
        {"organoid_type": "kidney", "base_media": "DMEM/F-12"},
        {"organoid_type": "kidney", "base_media": "RPMI 1640"},
        {"organoid_type": "kidney", "base_media": "RPMI-1640"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_base_media_breakdown("kidney")
    assert status == 200
    bm = data["base_media"]
    assert bm.get("Advanced DMEM/F12", 0) == 3, f"expected 3 Advanced DMEM/F12, got {bm}"
    assert bm.get("DMEM/F12", 0) == 1, f"expected 1 DMEM/F12, got {bm}"
    assert bm.get("RPMI 1640", 0) == 2, f"expected 2 RPMI 1640, got {bm}"


def test_base_media_breakdown_single_type_filter(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_bm(p, [
        {"organoid_type": "kidney",   "base_media": "DMEM/F12"},
        {"organoid_type": "cerebral", "base_media": "mTeSR1"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_base_media_breakdown("kidney")
    assert status == 200
    assert "organoid_type" in data
    assert data["organoid_type"] == "kidney"
    assert "base_media" in data
    assert "per_type" not in data


def test_base_media_breakdown_404_for_unknown_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_bm(p, [{"organoid_type": "kidney", "base_media": "DMEM/F12"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_base_media_breakdown("nonexistent")
    assert status == 404
    assert "available_types" in data


def test_base_media_breakdown_excludes_other_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_bm(p, [
        {"organoid_type": "other",  "base_media": "DMEM"},
        {"organoid_type": "kidney", "base_media": "mTeSR1"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_base_media_breakdown(None)
    assert status == 200
    assert "other" not in data["per_type"]
    assert data["n_types"] == 1


def test_base_media_breakdown_missing_counted_as_not_stated(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_bm(p, [{"organoid_type": "kidney"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_base_media_breakdown("kidney")
    assert status == 200
    assert data["base_media"].get("not_stated", 0) == 1


def test_base_media_breakdown_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/base-media-breakdown" in data["endpoints"]


def test_summary_includes_base_media_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    monkeypatch.setattr(ae, "COVERAGE_REPORT_PATH", tmp_path / "coverage_report.json")
    protocols = tmp_path / "protocols.jsonl"
    _write_protocols_for_bm(protocols, [
        {"organoid_type": "kidney",   "base_media": "DMEM/F12"},
        {"organoid_type": "cerebral", "base_media": "DMEM/F12"},
        {"organoid_type": "cardiac",  "base_media": "mTeSR1"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", protocols)
    (tmp_path / "coverage_report.json").write_text(json.dumps({
        "n_total_papers": 3, "n_organoid_types": 3,
        "overall_avg_grounding_rate": 0.9, "corpus_pooled_grounding_rate": 0.88,
        "types_by_completeness": [],
    }))
    data, status = ae.handle_summary()
    assert status == 200
    assert "base_media_snapshot" in data
    snap = data["base_media_snapshot"]
    assert snap.get("DMEM/F12", 0) == 2
    assert snap.get("mTeSR1", 0) == 1

# ---------------------------------------------------------------------------
# /analytics/source-cell-breakdown
# ---------------------------------------------------------------------------

def _write_protocols_for_sc(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_source_cell_breakdown_404_when_jsonl_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", tmp_path / "missing.jsonl")
    data, status = ae.handle_source_cell_breakdown(None)
    assert status == 404
    assert "hint" in data


def test_source_cell_breakdown_400_for_invalid_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_sc(p, [{"organoid_type": "kidney", "source_cell_type": "iPSC"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_source_cell_breakdown("bad type!")
    assert status == 400


def test_source_cell_breakdown_returns_all_types(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_sc(p, [
        {"organoid_type": "kidney",   "source_cell_type": "iPSC"},
        {"organoid_type": "cerebral", "source_cell_type": "adult_stem_cell"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_source_cell_breakdown(None)
    assert status == 200
    assert "kidney" in data["per_type"]
    assert "cerebral" in data["per_type"]
    assert data["n_types"] == 2


def test_source_cell_breakdown_cross_corpus_totals(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_sc(p, [
        {"organoid_type": "kidney",   "source_cell_type": "iPSC"},
        {"organoid_type": "cerebral", "source_cell_type": "iPSC"},
        {"organoid_type": "cardiac",  "source_cell_type": "adult_stem_cell"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_source_cell_breakdown(None)
    assert status == 200
    assert data["cross_corpus"]["iPSC"] == 2
    assert data["cross_corpus"]["adult_stem_cell"] == 1


def test_source_cell_breakdown_normalises_aliases(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_sc(p, [
        {"organoid_type": "kidney", "source_cell_type": "IPSC"},
        {"organoid_type": "kidney", "source_cell_type": "hIPSC"},
        {"organoid_type": "kidney", "source_cell_type": "induced pluripotent stem cells"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_source_cell_breakdown("kidney")
    assert status == 200
    sc = data["source_cell_type"]
    # "IPSC" → alias → "iPSC"; "hIPSC" falls through to "hIPSC" (not aliased, kept verbatim)
    # "induced pluripotent stem cells" → alias → "iPSC"
    assert sc.get("iPSC", 0) >= 2


def test_source_cell_breakdown_single_type_filter(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_sc(p, [
        {"organoid_type": "kidney",   "source_cell_type": "iPSC"},
        {"organoid_type": "cerebral", "source_cell_type": "adult_stem_cell"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_source_cell_breakdown("kidney")
    assert status == 200
    assert data["organoid_type"] == "kidney"
    assert "source_cell_type" in data
    assert "per_type" not in data


def test_source_cell_breakdown_404_for_unknown_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_sc(p, [{"organoid_type": "kidney", "source_cell_type": "iPSC"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_source_cell_breakdown("unknowntype")
    assert status == 404
    assert "available_types" in data


def test_source_cell_breakdown_excludes_other_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_sc(p, [
        {"organoid_type": "other",  "source_cell_type": "iPSC"},
        {"organoid_type": "kidney", "source_cell_type": "adult_stem_cell"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_source_cell_breakdown(None)
    assert status == 200
    assert "other" not in data["per_type"]
    assert data["n_types"] == 1


def test_source_cell_breakdown_missing_counted_as_not_stated(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_sc(p, [{"organoid_type": "kidney"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_source_cell_breakdown("kidney")
    assert status == 200
    assert data["source_cell_type"].get("not_stated", 0) == 1


def test_source_cell_breakdown_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/source-cell-breakdown" in data["endpoints"]


def test_summary_includes_source_cell_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "ANALYSIS_DIR", tmp_path)
    monkeypatch.setattr(ae, "COVERAGE_REPORT_PATH", tmp_path / "coverage_report.json")
    protocols = tmp_path / "protocols.jsonl"
    _write_protocols_for_sc(protocols, [
        {"organoid_type": "kidney",   "source_cell_type": "iPSC"},
        {"organoid_type": "cerebral", "source_cell_type": "iPSC"},
        {"organoid_type": "cardiac",  "source_cell_type": "adult_stem_cell"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", protocols)
    (tmp_path / "coverage_report.json").write_text(json.dumps({
        "n_total_papers": 3, "n_organoid_types": 3,
        "overall_avg_grounding_rate": 0.9, "corpus_pooled_grounding_rate": 0.88,
        "types_by_completeness": [],
    }))
    data, status = ae.handle_summary()
    assert status == 200
    assert "source_cell_snapshot" in data
    snap = data["source_cell_snapshot"]
    assert snap.get("iPSC", 0) == 2
    assert snap.get("adult_stem_cell", 0) == 1

# ---------------------------------------------------------------------------
# /analytics/protocol-complexity
# ---------------------------------------------------------------------------

def _write_protocols_for_complexity(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_protocol_complexity_404_when_jsonl_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", tmp_path / "missing.jsonl")
    data, status = ae.handle_protocol_complexity(None)
    assert status == 404
    assert "hint" in data


def test_protocol_complexity_400_for_invalid_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_complexity(p, [{"organoid_type": "kidney", "n_signaling_factors": 5}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_protocol_complexity("bad type!")
    assert status == 400


def test_protocol_complexity_returns_all_types(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_complexity(p, [
        {"organoid_type": "kidney",   "n_signaling_factors": 4, "n_supplements": 2, "grounding_rate": 0.9},
        {"organoid_type": "cerebral", "n_signaling_factors": 8, "n_supplements": 4, "grounding_rate": 0.8},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_protocol_complexity(None)
    assert status == 200
    assert "kidney" in data["per_type"]
    assert "cerebral" in data["per_type"]
    assert data["n_types"] == 2


def test_protocol_complexity_stats_correct(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_complexity(p, [
        {"organoid_type": "kidney", "n_signaling_factors": 4, "grounding_rate": 0.8},
        {"organoid_type": "kidney", "n_signaling_factors": 6, "grounding_rate": 1.0},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_protocol_complexity("kidney")
    assert status == 200
    sf = data["n_signaling_factors"]
    assert sf["mean"] == 5.0
    assert sf["min"] == 4
    assert sf["max"] == 6
    assert sf["n"] == 2
    gr = data["grounding_rate"]
    assert abs(gr["mean"] - 0.9) < 0.01


def test_protocol_complexity_ranking_by_signaling_factors(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_complexity(p, [
        {"organoid_type": "kidney",   "n_signaling_factors": 3},
        {"organoid_type": "cerebral", "n_signaling_factors": 8},
        {"organoid_type": "cardiac",  "n_signaling_factors": 5},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_protocol_complexity(None)
    assert status == 200
    ranking = data["ranking_by_avg_signaling_factors"]
    # cerebral (8) > cardiac (5) > kidney (3)
    assert ranking.index("cerebral") < ranking.index("cardiac")
    assert ranking.index("cardiac") < ranking.index("kidney")


def test_protocol_complexity_single_type_filter(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_complexity(p, [
        {"organoid_type": "kidney",   "n_signaling_factors": 5},
        {"organoid_type": "cerebral", "n_signaling_factors": 9},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_protocol_complexity("kidney")
    assert status == 200
    assert data["organoid_type"] == "kidney"
    assert "per_type" not in data
    assert data["n_signaling_factors"]["mean"] == 5.0


def test_protocol_complexity_404_for_unknown_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_complexity(p, [{"organoid_type": "kidney", "n_signaling_factors": 5}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_protocol_complexity("unknowntype")
    assert status == 404
    assert "available_types" in data


def test_protocol_complexity_excludes_other_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_complexity(p, [
        {"organoid_type": "other",  "n_signaling_factors": 5},
        {"organoid_type": "kidney", "n_signaling_factors": 3},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_protocol_complexity(None)
    assert status == 200
    assert "other" not in data["per_type"]
    assert data["n_types"] == 1


def test_protocol_complexity_missing_fields_skipped(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_complexity(p, [
        {"organoid_type": "kidney"},  # no n_signaling_factors etc.
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_protocol_complexity("kidney")
    assert status == 200
    # Fields with no data return None stats
    assert data["n_signaling_factors"] is None
    assert data["n_papers"] == 0  # no fields populated → max(list_lengths) == 0


def test_protocol_complexity_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/protocol-complexity" in data["endpoints"]


def test_protocol_complexity_n_papers_counts_correctly(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_complexity(p, [
        {"organoid_type": "kidney", "n_signaling_factors": 3, "grounding_rate": 0.9},
        {"organoid_type": "kidney", "n_signaling_factors": 7, "grounding_rate": 0.8},
        {"organoid_type": "kidney", "n_signaling_factors": 5, "grounding_rate": 1.0},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_protocol_complexity("kidney")
    assert status == 200
    assert data["n_papers"] == 3

# ---------------------------------------------------------------------------
# /analytics/reporting-gaps
# ---------------------------------------------------------------------------

def _write_protocols_for_gaps(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_reporting_gaps_404_when_jsonl_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", tmp_path / "missing.jsonl")
    data, status = ae.handle_reporting_gaps(None)
    assert status == 404
    assert "hint" in data


def test_reporting_gaps_400_for_invalid_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_gaps(p, [{"organoid_type": "kidney", "species": "human"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_reporting_gaps("bad type!")
    assert status == 400


def test_reporting_gaps_returns_all_fields(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_gaps(p, [
        {"organoid_type": "kidney", "species": "human", "matrix": None,
         "base_media": None, "source_cell_type": "iPSC", "passaging": None, "timeline": None},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_reporting_gaps(None)
    assert status == 200
    cc = data["cross_corpus"]
    for f in ["species", "matrix", "base_media", "source_cell_type", "passaging", "timeline"]:
        assert f in cc


def test_reporting_gaps_correct_rates(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_gaps(p, [
        {"organoid_type": "kidney", "species": "human",   "matrix": "Matrigel"},
        {"organoid_type": "kidney", "species": "mouse",   "matrix": None},
        {"organoid_type": "kidney", "species": None,      "matrix": None},
        {"organoid_type": "kidney", "species": "human",   "matrix": "Geltrex"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_reporting_gaps(None)
    assert status == 200
    cc = data["cross_corpus"]
    assert cc["species"]["reported"] == 3
    assert cc["species"]["not_stated"] == 1
    assert abs(cc["species"]["reporting_rate"] - 0.75) < 0.01
    assert cc["matrix"]["reported"] == 2
    assert cc["matrix"]["not_stated"] == 2


def test_reporting_gaps_not_stated_string_treated_as_missing(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_gaps(p, [
        {"organoid_type": "kidney", "species": "not_stated"},
        {"organoid_type": "kidney", "species": "human"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_reporting_gaps(None)
    assert status == 200
    assert data["cross_corpus"]["species"]["reported"] == 1
    assert data["cross_corpus"]["species"]["not_stated"] == 1


def test_reporting_gaps_single_type_filter(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_gaps(p, [
        {"organoid_type": "kidney",   "species": "human",  "matrix": "Matrigel"},
        {"organoid_type": "cerebral", "species": "mouse",  "matrix": None},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_reporting_gaps("kidney")
    assert status == 200
    assert data["organoid_type"] == "kidney"
    assert data["n_papers"] == 1
    assert "per_type" not in data
    assert data["fields"]["species"]["reported"] == 1


def test_reporting_gaps_404_for_unknown_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_gaps(p, [{"organoid_type": "kidney", "species": "human"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_reporting_gaps("unknowntype")
    assert status == 404
    assert "available_types" in data


def test_reporting_gaps_excludes_other_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_gaps(p, [
        {"organoid_type": "other",  "species": "human"},
        {"organoid_type": "kidney", "species": "mouse"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_reporting_gaps(None)
    assert status == 200
    assert "other" not in data["per_type"]
    assert data["n_types"] == 1
    assert data["n_papers"] == 1


def test_reporting_gaps_ranking_by_gap(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    # species always present, timeline never
    _write_protocols_for_gaps(p, [
        {"organoid_type": "kidney", "species": "human", "timeline": None},
        {"organoid_type": "kidney", "species": "mouse", "timeline": None},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_reporting_gaps(None)
    assert status == 200
    ranked = data["ranking_by_gap"]
    # timeline (rate=0) should be ranked before species (rate=1.0)
    assert ranked.index("timeline") < ranked.index("species")


def test_reporting_gaps_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/reporting-gaps" in data["endpoints"]


def test_reporting_gaps_per_type_present(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_gaps(p, [
        {"organoid_type": "kidney",   "species": "human"},
        {"organoid_type": "cerebral", "species": None},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_reporting_gaps(None)
    assert status == 200
    assert "kidney" in data["per_type"]
    assert "cerebral" in data["per_type"]
    assert data["per_type"]["kidney"]["fields"]["species"]["reported"] == 1
    assert data["per_type"]["cerebral"]["fields"]["species"]["reported"] == 0


# ===========================================================================
# handle_year_trend tests
# ===========================================================================

def _write_protocols_for_year(path, rows):
    """Write minimal protocols.jsonl rows for year-trend tests."""
    lines = []
    for r in rows:
        obj = {
            "organoid_type": r.get("organoid_type", "kidney"),
            "year": r.get("year"),
            "n_signaling_factors": r.get("n_signaling_factors"),
            "grounding_rate": r.get("grounding_rate"),
            "species": r.get("species"),
            "matrix": r.get("matrix"),
            "base_media": r.get("base_media"),
            "passaging": r.get("passaging"),
            "timeline": r.get("timeline"),
        }
        lines.append(json.dumps(obj))
    path.write_text("\n".join(lines) + "\n")


def test_year_trend_404_when_jsonl_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", tmp_path / "missing.jsonl")
    data, status = ae.handle_year_trend()
    assert status == 404
    assert "error" in data


def test_year_trend_returns_200_with_valid_data(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_year(p, [{"year": 2023}, {"year": 2024}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_year_trend()
    assert status == 200
    assert "years" in data
    assert "n_years" in data
    assert "year_range" in data


def test_year_trend_groups_by_year(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_year(p, [
        {"year": 2022}, {"year": 2022},
        {"year": 2023},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, _ = ae.handle_year_trend()
    assert "2022" in data["years"]
    assert "2023" in data["years"]
    assert data["years"]["2022"]["n_papers"] == 2
    assert data["years"]["2023"]["n_papers"] == 1


def test_year_trend_avg_signaling_factors_correct(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_year(p, [
        {"year": 2024, "n_signaling_factors": 4},
        {"year": 2024, "n_signaling_factors": 6},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, _ = ae.handle_year_trend()
    assert data["years"]["2024"]["avg_signaling_factors"] == 5.0


def test_year_trend_avg_grounding_rate_correct(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_year(p, [
        {"year": 2024, "grounding_rate": 0.8},
        {"year": 2024, "grounding_rate": 0.6},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, _ = ae.handle_year_trend()
    assert abs(data["years"]["2024"]["avg_grounding_rate"] - 0.7) < 1e-4


def test_year_trend_reporting_rates_correct(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_year(p, [
        {"year": 2024, "species": "human", "matrix": None},
        {"year": 2024, "species": "mouse", "matrix": "Matrigel"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, _ = ae.handle_year_trend()
    rr = data["years"]["2024"]["reporting_rates"]
    assert rr["species"] == 1.0
    assert rr["matrix"] == 0.5


def test_year_trend_skips_rows_without_year(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_year(p, [
        {"year": None, "n_signaling_factors": 5},
        {"year": 2024, "n_signaling_factors": 3},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, _ = ae.handle_year_trend()
    assert list(data["years"].keys()) == ["2024"]
    assert data["n_years"] == 1


def test_year_trend_year_range_correct(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_year(p, [
        {"year": 2019}, {"year": 2023}, {"year": 2021},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, _ = ae.handle_year_trend()
    assert data["year_range"] == ["2019", "2023"]


def test_year_trend_missing_sf_gives_none(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_year(p, [{"year": 2024}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, _ = ae.handle_year_trend()
    assert data["years"]["2024"]["avg_signaling_factors"] is None
    assert data["years"]["2024"]["avg_grounding_rate"] is None


def test_year_trend_years_sorted_chronologically(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_year(p, [
        {"year": 2023}, {"year": 2021}, {"year": 2022},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, _ = ae.handle_year_trend()
    assert list(data["years"].keys()) == ["2021", "2022", "2023"]


def test_year_trend_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/year-trend" in data["endpoints"]


def test_year_trend_not_stated_matrix_not_counted_as_reported(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_year(p, [
        {"year": 2024, "matrix": "not_stated"},
        {"year": 2024, "matrix": "Matrigel"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, _ = ae.handle_year_trend()
    rr = data["years"]["2024"]["reporting_rates"]
    assert rr["matrix"] == 0.5


# ===========================================================================
# handle_grounding_quality tests
# ===========================================================================

def _write_reagents_for_gq(path, rows):
    """Write minimal reagents.jsonl rows for grounding-quality tests."""
    lines = []
    for r in rows:
        obj = {
            "organoid_type": r.get("organoid_type", "kidney"),
            "kind": r.get("kind", "signaling"),
            "canonical": r.get("canonical", "EGF"),
            "name": r.get("name", "EGF"),
            "grounded": r.get("grounded", 1),
            "evidence_quote": r.get("evidence_quote"),
            "suspect_unit": r.get("suspect_unit", 0),
        }
        lines.append(json.dumps(obj))
    path.write_text("\n".join(lines) + "\n")


def test_grounding_quality_404_when_jsonl_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", tmp_path / "missing.jsonl")
    data, status = ae.handle_grounding_quality(None)
    assert status == 404
    assert "error" in data


def test_grounding_quality_returns_200(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_gq(p, [{"grounded": 1}, {"grounded": 0}])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, status = ae.handle_grounding_quality(None)
    assert status == 200
    assert "cross_corpus" in data
    assert "by_kind" in data
    assert "top_ungrounded" in data
    assert "ranking_by_grounding_rate" in data


def test_grounding_quality_rate_correct(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_gq(p, [
        {"grounded": 1}, {"grounded": 1}, {"grounded": 0},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_grounding_quality(None)
    cc = data["cross_corpus"]
    assert cc["n_reagents"] == 3
    assert cc["n_grounded"] == 2
    assert abs(cc["grounding_rate"] - 2/3) < 1e-4


def test_grounding_quality_evidence_quote_rate(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_gq(p, [
        {"grounded": 1, "evidence_quote": "EGF 50 ng/mL"},
        {"grounded": 0, "evidence_quote": None},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_grounding_quality(None)
    assert data["cross_corpus"]["evidence_quote_rate"] == 0.5
    assert data["cross_corpus"]["n_with_quote"] == 1


def test_grounding_quality_by_kind_breakdown(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_gq(p, [
        {"kind": "signaling", "grounded": 1},
        {"kind": "signaling", "grounded": 0},
        {"kind": "supplement", "grounded": 1},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_grounding_quality(None)
    bk = data["by_kind"]
    assert "signaling" in bk
    assert "supplement" in bk
    assert bk["signaling"]["n_reagents"] == 2
    assert bk["signaling"]["grounding_rate"] == 0.5
    assert bk["supplement"]["grounding_rate"] == 1.0


def test_grounding_quality_per_type(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_gq(p, [
        {"organoid_type": "kidney", "grounded": 1},
        {"organoid_type": "liver", "grounded": 0},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_grounding_quality(None)
    assert "per_type" in data
    assert "kidney" in data["per_type"]
    assert "liver" in data["per_type"]
    assert data["per_type"]["kidney"]["grounding_rate"] == 1.0
    assert data["per_type"]["liver"]["grounding_rate"] == 0.0


def test_grounding_quality_top_ungrounded(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_gq(p, [
        {"canonical": "DMSO", "grounded": 0},
        {"canonical": "DMSO", "grounded": 0},
        {"canonical": "BSA", "grounded": 0},
        {"canonical": "EGF", "grounded": 1},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_grounding_quality(None)
    top = data["top_ungrounded"]
    assert len(top) >= 1
    assert top[0]["canonical"] == "DMSO"
    assert top[0]["count"] == 2


def test_grounding_quality_single_type_filter(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_gq(p, [
        {"organoid_type": "kidney", "grounded": 1},
        {"organoid_type": "liver", "grounded": 0},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, status = ae.handle_grounding_quality("kidney")
    assert status == 200
    assert data["organoid_type"] == "kidney"
    assert "per_type" not in data
    assert "ranking_by_grounding_rate" not in data
    assert data["cross_corpus"]["n_reagents"] == 1


def test_grounding_quality_404_for_unknown_type(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_gq(p, [{"organoid_type": "kidney"}])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, status = ae.handle_grounding_quality("unknowntype")
    assert status == 404
    assert "error" in data


def test_grounding_quality_400_for_invalid_type(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_gq(p, [])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, status = ae.handle_grounding_quality("../evil")
    assert status == 400


def test_grounding_quality_ranking_order(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    rows = (
        [{"organoid_type": "kidney", "grounded": 1}] * 10 +
        [{"organoid_type": "liver", "grounded": 0}] * 10
    )
    _write_reagents_for_gq(p, rows)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_grounding_quality(None)
    ranking = data["ranking_by_grounding_rate"]
    assert ranking[0] == "kidney"
    assert ranking[-1] == "liver"


def test_grounding_quality_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/grounding-quality" in data["endpoints"]


def test_grounding_quality_suspect_unit_counted(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_gq(p, [
        {"grounded": 1, "suspect_unit": 1},
        {"grounded": 1, "suspect_unit": 0},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_grounding_quality(None)
    assert data["cross_corpus"]["n_suspect_unit"] == 1


# ===========================================================================
# handle_concentration_stats tests
# ===========================================================================

def _write_reagents_for_cs(path, rows):
    """Write minimal reagents.jsonl rows for concentration-stats tests."""
    lines = []
    for r in rows:
        obj = {
            "organoid_type": r.get("organoid_type", "kidney"),
            "kind": r.get("kind", "signaling"),
            "canonical": r.get("canonical", "EGF"),
            "name": r.get("name"),
            "value": r.get("value"),
            "unit": r.get("unit"),
            "canonical_unit": r.get("canonical_unit"),
            "grounded": r.get("grounded", 1),
            "evidence_quote": r.get("evidence_quote"),
            "suspect_unit": r.get("suspect_unit", 0),
        }
        lines.append(json.dumps(obj))
    path.write_text("\n".join(lines) + "\n")


def test_cs_404_when_jsonl_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", tmp_path / "missing.jsonl")
    data, status = ae.handle_concentration_stats(None, None)
    assert status == 404


def test_cs_returns_top_reagents(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cs(p, [
        {"canonical": "EGF", "value": 50.0, "canonical_unit": "ng/mL"},
        {"canonical": "EGF", "value": 100.0, "canonical_unit": "ng/mL"},
        {"canonical": "FGF2", "value": 10.0, "canonical_unit": "ng/mL"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, status = ae.handle_concentration_stats(None, None)
    assert status == 200
    assert "top_reagents" in data
    top_names = [r["canonical"] for r in data["top_reagents"]]
    assert "EGF" in top_names


def test_cs_median_correct(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cs(p, [
        {"canonical": "EGF", "value": 10.0, "canonical_unit": "ng/mL"},
        {"canonical": "EGF", "value": 50.0, "canonical_unit": "ng/mL"},
        {"canonical": "EGF", "value": 100.0, "canonical_unit": "ng/mL"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_concentration_stats("EGF", None)
    assert data["canonical"] == "EGF"
    stats = data["stats_per_unit"]["ng/mL"]
    assert stats["median"] == 50.0
    assert stats["min"] == 10.0
    assert stats["max"] == 100.0
    assert stats["n"] == 3


def test_cs_query_filter_case_insensitive(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cs(p, [
        {"canonical": "EGF", "value": 50.0, "canonical_unit": "ng/mL"},
        {"canonical": "FGF2", "value": 10.0, "canonical_unit": "ng/mL"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, status = ae.handle_concentration_stats("egf", None)
    assert status == 200
    assert data["canonical"] == "EGF"


def test_cs_query_404_when_no_match(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cs(p, [{"canonical": "EGF", "value": 50.0}])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, status = ae.handle_concentration_stats("notexist", None)
    assert status == 404


def test_cs_type_filter(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cs(p, [
        {"organoid_type": "kidney", "canonical": "EGF", "value": 50.0, "canonical_unit": "ng/mL"},
        {"organoid_type": "liver", "canonical": "EGF", "value": 100.0, "canonical_unit": "ng/mL"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, status = ae.handle_concentration_stats(None, "kidney")
    assert status == 200
    top = data["top_reagents"]
    assert len(top) == 1
    assert top[0]["canonical"] == "EGF"
    assert top[0]["stats_per_unit"]["ng/mL"]["n"] == 1


def test_cs_no_value_gives_zero_n_with_value(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cs(p, [
        {"canonical": "EGF", "value": None},
        {"canonical": "EGF", "value": None},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_concentration_stats("EGF", None)
    assert data["n_with_value"] == 0
    assert data["stats_per_unit"] == {}


def test_cs_organoid_types_listed(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cs(p, [
        {"organoid_type": "kidney", "canonical": "EGF", "value": 50.0, "canonical_unit": "ng/mL"},
        {"organoid_type": "liver", "canonical": "EGF", "value": 50.0, "canonical_unit": "ng/mL"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_concentration_stats("EGF", None)
    assert set(data["organoid_types"]) == {"kidney", "liver"}


def test_cs_400_for_invalid_type(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cs(p, [])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, status = ae.handle_concentration_stats(None, "../evil")
    assert status == 400


def test_cs_top_by_n_with_value_order(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    rows = (
        [{"canonical": "EGF", "value": float(i), "canonical_unit": "ng/mL"} for i in range(5)] +
        [{"canonical": "FGF2", "value": float(i), "canonical_unit": "ng/mL"} for i in range(3)]
    )
    _write_reagents_for_cs(p, rows)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_concentration_stats(None, None)
    assert data["top_reagents"][0]["canonical"] == "EGF"


def test_cs_dominant_unit_is_most_common(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cs(p, [
        {"canonical": "EGF", "value": 50.0, "canonical_unit": "ng/mL"},
        {"canonical": "EGF", "value": 51.0, "canonical_unit": "ng/mL"},
        {"canonical": "EGF", "value": 0.05, "canonical_unit": "ug/mL"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_concentration_stats("EGF", None)
    assert data["dominant_unit"] == "ng/mL"


def test_cs_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/concentration-stats" in data["endpoints"]


def test_cs_std_zero_for_single_value(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cs(p, [{"canonical": "EGF", "value": 50.0, "canonical_unit": "ng/mL"}])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_concentration_stats("EGF", None)
    assert data["stats_per_unit"]["ng/mL"]["std"] == 0.0


# ---------------------------------------------------------------------------
# temporal-reagent-adoption tests
# ---------------------------------------------------------------------------

def _write_tra_fixtures(proto_path, reagent_path, protocol_rows, reagent_rows):
    """Write minimal protocols.jsonl and reagents.jsonl for TRA tests."""
    proto_lines = []
    for r in protocol_rows:
        proto_lines.append(json.dumps({
            "pmcid": r["pmcid"],
            "organoid_type": r.get("organoid_type", "kidney"),
            "year": r.get("year"),
        }))
    proto_path.write_text("\n".join(proto_lines) + "\n")

    reagent_lines = []
    for r in reagent_rows:
        reagent_lines.append(json.dumps({
            "pmcid": r["pmcid"],
            "canonical": r.get("canonical", "EGF"),
            "organoid_type": r.get("organoid_type", "kidney"),
            "name": r.get("name", r.get("canonical", "EGF")),
        }))
    reagent_path.write_text("\n".join(reagent_lines) + "\n")


def test_tra_404_missing_reagents(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", tmp_path / "missing.jsonl")
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", tmp_path / "proto.jsonl")
    _, status = ae.handle_temporal_reagent_adoption("EGF", None)
    assert status == 404


def test_tra_404_missing_protocols(tmp_path, monkeypatch):
    rp = tmp_path / "reagents.jsonl"
    rp.write_text("")
    monkeypatch.setattr(ae, "REAGENTS_JSONL", rp)
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", tmp_path / "missing.jsonl")
    _, status = ae.handle_temporal_reagent_adoption("EGF", None)
    assert status == 404


def test_tra_query_returns_canonical(tmp_path, monkeypatch):
    pp = tmp_path / "proto.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_tra_fixtures(pp, rp,
        [{"pmcid": "PMC1", "year": "2020"}, {"pmcid": "PMC2", "year": "2021"}],
        [{"pmcid": "PMC1", "canonical": "EGF"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", pp)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", rp)
    data, status = ae.handle_temporal_reagent_adoption("EGF", None)
    assert status == 200
    assert data["canonical"] == "EGF"
    assert "years" in data
    assert "trend" in data


def test_tra_adoption_fraction_correct(tmp_path, monkeypatch):
    """2 papers in 2021, 1 uses EGF → adoption 0.5."""
    pp = tmp_path / "proto.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_tra_fixtures(pp, rp,
        [{"pmcid": "PMC1", "year": "2021"}, {"pmcid": "PMC2", "year": "2021"}],
        [{"pmcid": "PMC1", "canonical": "EGF"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", pp)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", rp)
    data, _ = ae.handle_temporal_reagent_adoption("EGF", None)
    assert data["years"]["2021"]["n_papers_total"] == 2
    assert data["years"]["2021"]["n_papers_with_reagent"] == 1
    assert data["years"]["2021"]["adoption_fraction"] == 0.5


def test_tra_pmcid_deduplication(tmp_path, monkeypatch):
    """Same PMCID appearing multiple times in reagents.jsonl counts once."""
    pp = tmp_path / "proto.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_tra_fixtures(pp, rp,
        [{"pmcid": "PMC1", "year": "2020"}],
        [{"pmcid": "PMC1", "canonical": "EGF"}, {"pmcid": "PMC1", "canonical": "EGF"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", pp)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", rp)
    data, _ = ae.handle_temporal_reagent_adoption("EGF", None)
    assert data["n_pmcids_using"] == 1
    assert data["years"]["2020"]["n_papers_with_reagent"] == 1


def test_tra_case_insensitive_query(tmp_path, monkeypatch):
    pp = tmp_path / "proto.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_tra_fixtures(pp, rp,
        [{"pmcid": "PMC1", "year": "2020"}],
        [{"pmcid": "PMC1", "canonical": "FGF2"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", pp)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", rp)
    data, status = ae.handle_temporal_reagent_adoption("fgf2", None)
    assert status == 200
    assert data["canonical"] == "FGF2"


def test_tra_404_no_match(tmp_path, monkeypatch):
    pp = tmp_path / "proto.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_tra_fixtures(pp, rp,
        [{"pmcid": "PMC1", "year": "2020"}],
        [{"pmcid": "PMC1", "canonical": "EGF"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", pp)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", rp)
    _, status = ae.handle_temporal_reagent_adoption("ZZZNOMATCH", None)
    assert status == 404


def test_tra_400_invalid_type(tmp_path, monkeypatch):
    pp = tmp_path / "proto.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_tra_fixtures(pp, rp, [], [])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", pp)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", rp)
    _, status = ae.handle_temporal_reagent_adoption("EGF", "../evil")
    assert status == 400


def test_tra_type_filter_restricts_corpus(tmp_path, monkeypatch):
    """?type=kidney should exclude liver papers from n_papers_total."""
    pp = tmp_path / "proto.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_tra_fixtures(pp, rp,
        [{"pmcid": "PMC1", "year": "2020", "organoid_type": "kidney"},
         {"pmcid": "PMC2", "year": "2020", "organoid_type": "liver"}],
        [{"pmcid": "PMC1", "canonical": "EGF", "organoid_type": "kidney"},
         {"pmcid": "PMC2", "canonical": "EGF", "organoid_type": "liver"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", pp)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", rp)
    data, status = ae.handle_temporal_reagent_adoption("EGF", "kidney")
    assert status == 200
    # only kidney papers: 1 total, 1 with EGF
    assert data["years"]["2020"]["n_papers_total"] == 1
    assert data["years"]["2020"]["n_papers_with_reagent"] == 1


def test_tra_trend_rising(tmp_path, monkeypatch):
    """Adoption that rises from early to recent years should have direction='rising'."""
    pp = tmp_path / "proto.jsonl"
    rp = tmp_path / "reagents.jsonl"
    # 3 papers per year, 2013-2021
    proto_rows = [{"pmcid": f"PMC{yr}{i}", "year": str(yr)} for yr in range(2013, 2022) for i in range(3)]
    # EGF used in 0 papers in 2013-2015, then 3/3 in 2019-2021
    egf_pmcids = {f"PMC{yr}{i}" for yr in range(2019, 2022) for i in range(3)}
    reagent_rows = [{"pmcid": p, "canonical": "EGF"} for p in egf_pmcids]
    _write_tra_fixtures(pp, rp, proto_rows, reagent_rows)
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", pp)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", rp)
    data, _ = ae.handle_temporal_reagent_adoption("EGF", None)
    assert data["trend"]["direction"] == "rising"
    assert data["trend"]["early_adoption_avg"] == 0.0
    assert data["trend"]["recent_adoption_avg"] == 1.0


def test_tra_trend_falling(tmp_path, monkeypatch):
    """Adoption that drops from early to recent should have direction='falling'."""
    pp = tmp_path / "proto.jsonl"
    rp = tmp_path / "reagents.jsonl"
    proto_rows = [{"pmcid": f"PMC{yr}{i}", "year": str(yr)} for yr in range(2013, 2022) for i in range(3)]
    egf_pmcids = {f"PMC{yr}{i}" for yr in range(2013, 2016) for i in range(3)}
    reagent_rows = [{"pmcid": p, "canonical": "EGF"} for p in egf_pmcids]
    _write_tra_fixtures(pp, rp, proto_rows, reagent_rows)
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", pp)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", rp)
    data, _ = ae.handle_temporal_reagent_adoption("EGF", None)
    assert data["trend"]["direction"] == "falling"


def test_tra_no_query_returns_top_reagents(tmp_path, monkeypatch):
    """Without ?q=, returns top 20 by peak adoption."""
    pp = tmp_path / "proto.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_tra_fixtures(pp, rp,
        [{"pmcid": "PMC1", "year": "2020"}, {"pmcid": "PMC2", "year": "2020"}],
        [{"pmcid": "PMC1", "canonical": "EGF"}, {"pmcid": "PMC1", "canonical": "FGF2"},
         {"pmcid": "PMC2", "canonical": "FGF2"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", pp)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", rp)
    data, status = ae.handle_temporal_reagent_adoption(None, None)
    assert status == 200
    assert "top_reagents_by_peak_adoption" in data
    assert "n_canonicals_total" in data
    top_names = [r["canonical"] for r in data["top_reagents_by_peak_adoption"]]
    # FGF2 used in both papers → peak adoption 1.0; EGF used in 1 of 2 → 0.5
    assert top_names[0] == "FGF2"


def test_tra_peak_year_correct(tmp_path, monkeypatch):
    """peak_year is the year with highest adoption fraction."""
    pp = tmp_path / "proto.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_tra_fixtures(pp, rp,
        [{"pmcid": "PMC1", "year": "2020"}, {"pmcid": "PMC2", "year": "2020"},
         {"pmcid": "PMC3", "year": "2021"}, {"pmcid": "PMC4", "year": "2021"},
         {"pmcid": "PMC5", "year": "2021"}],
        [{"pmcid": "PMC1", "canonical": "EGF"}, {"pmcid": "PMC2", "canonical": "EGF"},
         {"pmcid": "PMC3", "canonical": "EGF"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", pp)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", rp)
    data, _ = ae.handle_temporal_reagent_adoption("EGF", None)
    # 2020: 2/2 = 1.0; 2021: 1/3 = 0.33
    assert data["trend"]["peak_year"] == "2020"
    assert data["trend"]["peak_adoption"] == 1.0


def test_tra_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/temporal-reagent-adoption" in data["endpoints"]


# ---------------------------------------------------------------------------
# kgx-summary tests
# ---------------------------------------------------------------------------

def _write_kgx_fixtures(kgx_dir, manifest_data, review_rows=None):
    """Write minimal KGX artifacts for kgx-summary tests."""
    kgx_dir.mkdir(parents=True, exist_ok=True)
    (kgx_dir / "kgx_manifest.json").write_text(json.dumps(manifest_data))
    if review_rows is not None:
        (kgx_dir / "review_items.jsonl").write_text(
            "\n".join(json.dumps(r) for r in review_rows) + "\n"
        )


def _patch_kgx_dir(monkeypatch, tmp_path):
    kgx_dir = tmp_path / "kgx"
    monkeypatch.setattr(ae, "KGX_DIR", kgx_dir)
    return kgx_dir


def test_kgx_summary_404_when_manifest_missing(tmp_path, monkeypatch):
    kgx_dir = _patch_kgx_dir(monkeypatch, tmp_path)
    kgx_dir.mkdir()
    _, status = ae.handle_kgx_summary()
    assert status == 404


def test_kgx_summary_returns_manifest_fields(tmp_path, monkeypatch):
    kgx_dir = _patch_kgx_dir(monkeypatch, tmp_path)
    _write_kgx_fixtures(kgx_dir, {
        "n_nodes": 100,
        "n_edges": 50,
        "entities_total": 120,
        "entities_resolved": 90,
        "resolved_rate": 0.75,
        "validation": {"ok": True},
    })
    data, status = ae.handle_kgx_summary()
    assert status == 200
    assert data["n_nodes"] == 100
    assert data["n_edges"] == 50
    assert data["resolved_rate"] == 0.75
    assert data["validation"]["ok"] is True


def test_kgx_summary_no_review_jsonl(tmp_path, monkeypatch):
    kgx_dir = _patch_kgx_dir(monkeypatch, tmp_path)
    _write_kgx_fixtures(kgx_dir, {"n_nodes": 10, "n_edges": 5})
    data, status = ae.handle_kgx_summary()
    assert status == 200
    assert data["review_queue"] is None
    assert "hint_review" in data


def test_kgx_summary_review_queue_counts(tmp_path, monkeypatch):
    kgx_dir = _patch_kgx_dir(monkeypatch, tmp_path)
    review_rows = [
        {"query": "EGF", "grounding_status": "needs_review", "flags": ["label_mismatch"], "kind": "reagent"},
        {"query": "TGF-b", "grounding_status": "not_found", "flags": [], "kind": "reagent"},
        {"query": "WTC-11", "grounding_status": "not_found", "flags": [], "kind": "cell_line"},
        {"query": "FGF2", "grounding_status": "not_attempted", "flags": ["error:TimeoutError"], "kind": "reagent"},
    ]
    _write_kgx_fixtures(kgx_dir, {"n_nodes": 10}, review_rows)
    data, status = ae.handle_kgx_summary()
    assert status == 200
    rq = data["review_queue"]
    assert rq["total"] == 4
    assert rq["by_status"]["needs_review"] == 1
    assert rq["by_status"]["not_found"] == 2
    assert rq["by_status"]["not_attempted"] == 1


def test_kgx_summary_top_not_found(tmp_path, monkeypatch):
    kgx_dir = _patch_kgx_dir(monkeypatch, tmp_path)
    review_rows = [
        {"query": "TGF-β", "grounding_status": "not_found", "flags": [], "kind": "reagent"},
        {"query": "TGF-β", "grounding_status": "not_found", "flags": [], "kind": "reagent"},
        {"query": "WTC-11", "grounding_status": "not_found", "flags": [], "kind": "cell_line"},
    ]
    _write_kgx_fixtures(kgx_dir, {"n_nodes": 10}, review_rows)
    data, status = ae.handle_kgx_summary()
    rq = data["review_queue"]
    # TGF-β should be first (count=2)
    assert rq["top_not_found"][0]["query"] == "TGF-β"
    assert rq["top_not_found"][0]["count"] == 2


def test_kgx_summary_by_kind_counts(tmp_path, monkeypatch):
    kgx_dir = _patch_kgx_dir(monkeypatch, tmp_path)
    review_rows = [
        {"query": "EGF", "grounding_status": "not_found", "flags": [], "kind": "reagent"},
        {"query": "WTC-11", "grounding_status": "not_found", "flags": [], "kind": "cell_line"},
        {"query": "FGF2", "grounding_status": "not_found", "flags": [], "kind": "reagent"},
    ]
    _write_kgx_fixtures(kgx_dir, {"n_nodes": 10}, review_rows)
    data, status = ae.handle_kgx_summary()
    rq = data["review_queue"]
    assert rq["by_kind"]["reagent"] == 2
    assert rq["by_kind"]["cell_line"] == 1


def test_kgx_summary_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/kgx-summary" in data["endpoints"]


# ---------------------------------------------------------------------------
# concentration-by-type tests
# ---------------------------------------------------------------------------

def _write_reagents_for_cbt(path, rows):
    """Write minimal reagents.jsonl for concentration-by-type tests."""
    lines = []
    for r in rows:
        lines.append(json.dumps({
            "canonical": r.get("canonical", "EGF"),
            "organoid_type": r.get("organoid_type", "kidney"),
            "value": r.get("value"),
            "canonical_unit": r.get("canonical_unit"),
            "unit": r.get("unit"),
            "name": r.get("name", r.get("canonical", "EGF")),
        }))
    path.write_text("\n".join(lines) + "\n")


def test_cbt_400_when_no_query(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cbt(p, [])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    _, status = ae.handle_concentration_by_type(None)
    assert status == 400


def test_cbt_404_no_match(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cbt(p, [{"canonical": "EGF"}])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    _, status = ae.handle_concentration_by_type("ZZZNOMATCH")
    assert status == 404


def test_cbt_returns_canonical(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cbt(p, [
        {"canonical": "EGF", "organoid_type": "kidney", "value": 50.0, "canonical_unit": "ng/mL"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, status = ae.handle_concentration_by_type("EGF")
    assert status == 200
    assert data["canonical"] == "EGF"
    assert "by_type" in data


def test_cbt_median_correct(tmp_path, monkeypatch):
    """3 kidney rows at 50, 100, 150 → median 100."""
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cbt(p, [
        {"canonical": "EGF", "organoid_type": "kidney", "value": 50.0, "canonical_unit": "ng/mL"},
        {"canonical": "EGF", "organoid_type": "kidney", "value": 100.0, "canonical_unit": "ng/mL"},
        {"canonical": "EGF", "organoid_type": "kidney", "value": 150.0, "canonical_unit": "ng/mL"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_concentration_by_type("EGF")
    kidney = data["by_type"]["kidney"]
    assert kidney["stats_per_unit"]["ng/mL"]["median"] == 100.0
    assert kidney["stats_per_unit"]["ng/mL"]["min"] == 50.0
    assert kidney["stats_per_unit"]["ng/mL"]["max"] == 150.0


def test_cbt_per_type_isolation(tmp_path, monkeypatch):
    """kidney and liver should have separate stats."""
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cbt(p, [
        {"canonical": "EGF", "organoid_type": "kidney", "value": 50.0, "canonical_unit": "ng/mL"},
        {"canonical": "EGF", "organoid_type": "liver", "value": 100.0, "canonical_unit": "ng/mL"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_concentration_by_type("EGF")
    assert data["n_organoid_types"] == 2
    assert data["by_type"]["kidney"]["stats_per_unit"]["ng/mL"]["median"] == 50.0
    assert data["by_type"]["liver"]["stats_per_unit"]["ng/mL"]["median"] == 100.0


def test_cbt_case_insensitive(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cbt(p, [{"canonical": "FGF2", "organoid_type": "kidney"}])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, status = ae.handle_concentration_by_type("fgf2")
    assert status == 200
    assert data["canonical"] == "FGF2"


def test_cbt_no_value_gives_zero_n_with_value(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cbt(p, [
        {"canonical": "EGF", "organoid_type": "kidney", "value": None, "canonical_unit": "ng/mL"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_concentration_by_type("EGF")
    kidney = data["by_type"]["kidney"]
    assert kidney["n_with_value"] == 0


def test_cbt_dominant_unit_is_most_common(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cbt(p, [
        {"canonical": "EGF", "organoid_type": "kidney", "value": 50.0, "canonical_unit": "ng/mL"},
        {"canonical": "EGF", "organoid_type": "kidney", "value": 55.0, "canonical_unit": "ng/mL"},
        {"canonical": "EGF", "organoid_type": "kidney", "value": 0.05, "canonical_unit": "ug/mL"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_concentration_by_type("EGF")
    assert data["by_type"]["kidney"]["dominant_unit"] == "ng/mL"


def test_cbt_all_matches_when_multiple(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cbt(p, [
        {"canonical": "EGF", "organoid_type": "kidney"},
        {"canonical": "EGF-like", "organoid_type": "liver"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_concentration_by_type("EGF")
    assert data["all_matches"] is not None
    assert "EGF" in data["all_matches"]
    assert "EGF-like" in data["all_matches"]


def test_cbt_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/concentration-by-type" in data["endpoints"]


# ---------------------------------------------------------------------------
# journal-breakdown tests
# ---------------------------------------------------------------------------

def _write_protocols_for_jb(path, rows):
    """Write minimal protocols.jsonl for journal-breakdown tests."""
    lines = []
    for r in rows:
        lines.append(json.dumps({
            "organoid_type": r.get("organoid_type", "kidney"),
            "journal": r.get("journal", "Nature"),
        }))
    path.write_text("\n".join(lines) + "\n")


def test_jb_404_missing_protocols(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", tmp_path / "missing.jsonl")
    _, status = ae.handle_journal_breakdown(None)
    assert status == 404


def test_jb_400_invalid_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_jb(p, [])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    _, status = ae.handle_journal_breakdown("../evil")
    assert status == 400


def test_jb_cross_corpus_counts(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_jb(p, [
        {"organoid_type": "kidney", "journal": "Nature"},
        {"organoid_type": "liver", "journal": "Nature"},
        {"organoid_type": "kidney", "journal": "Cell"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_journal_breakdown(None)
    assert status == 200
    assert data["cross_corpus"]["Nature"] == 2
    assert data["cross_corpus"]["Cell"] == 1
    assert data["n_journals_total"] == 2


def test_jb_top_journal_first(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_jb(p, [
        {"journal": "A"},
        {"journal": "B"}, {"journal": "B"}, {"journal": "B"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, _ = ae.handle_journal_breakdown(None)
    journals = list(data["cross_corpus"].keys())
    assert journals[0] == "B"


def test_jb_single_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_jb(p, [
        {"organoid_type": "kidney", "journal": "Nature"},
        {"organoid_type": "kidney", "journal": "Cell"},
        {"organoid_type": "liver", "journal": "Science"},
    ])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_journal_breakdown("kidney")
    assert status == 200
    assert data["organoid_type"] == "kidney"
    assert data["n_papers"] == 2
    assert "Science" not in data["journals"]


def test_jb_404_unknown_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protocols_for_jb(p, [{"organoid_type": "kidney"}])
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    _, status = ae.handle_journal_breakdown("neuromuscular")
    assert status == 404


def test_jb_per_type_top5_present(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    rows = [
        {"organoid_type": "kidney", "journal": f"J{i}"} for i in range(7)
    ] + [{"organoid_type": "liver", "journal": "Nature"}]
    _write_protocols_for_jb(p, rows)
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p)
    data, status = ae.handle_journal_breakdown(None)
    assert status == 200
    kidney_top = data["per_type_top5"]["kidney"]
    assert len(kidney_top) <= 5


def test_jb_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/journal-breakdown" in data["endpoints"]


# ---------------------------------------------------------------------------
# type-comparison tests
# ---------------------------------------------------------------------------

def _write_reagents_for_tc(path, rows):
    lines = []
    for r in rows:
        lines.append(json.dumps({
            "canonical": r.get("canonical", "EGF"),
            "organoid_type": r.get("organoid_type", "kidney"),
            "kind": r.get("kind", "signaling"),
            "name": r.get("name", r.get("canonical", "EGF")),
        }))
    path.write_text("\n".join(lines) + "\n")


def test_tc_400_missing_params(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_tc(p, [])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    _, s = ae.handle_type_comparison(None, "cerebral")
    assert s == 400
    _, s2 = ae.handle_type_comparison("intestinal", None)
    assert s2 == 400


def test_tc_400_same_type(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_tc(p, [{"organoid_type": "kidney", "canonical": "EGF"}])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    _, s = ae.handle_type_comparison("kidney", "kidney")
    assert s == 400


def test_tc_400_invalid_type(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_tc(p, [])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    _, s = ae.handle_type_comparison("kidney", "../evil")
    assert s == 400


def test_tc_shared_and_unique(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_tc(p, [
        {"canonical": "EGF", "organoid_type": "kidney"},
        {"canonical": "EGF", "organoid_type": "liver"},
        {"canonical": "FGF2", "organoid_type": "kidney"},
        {"canonical": "Wnt3a", "organoid_type": "liver"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, status = ae.handle_type_comparison("kidney", "liver")
    assert status == 200
    shared = {r["canonical"] for r in data["shared"]}
    only_a = {r["canonical"] for r in data["only_a"]}
    only_b = {r["canonical"] for r in data["only_b"]}
    assert "EGF" in shared
    assert "FGF2" in only_a
    assert "Wnt3a" in only_b


def test_tc_jaccard_correct(tmp_path, monkeypatch):
    """2 shared out of 4 total → Jaccard = 0.5."""
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_tc(p, [
        {"canonical": "A", "organoid_type": "x"},
        {"canonical": "B", "organoid_type": "x"},
        {"canonical": "A", "organoid_type": "y"},
        {"canonical": "C", "organoid_type": "y"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_type_comparison("x", "y")
    assert data["n_shared"] == 1
    assert data["n_union"] == 3
    assert abs(data["jaccard_similarity"] - round(1/3, 4)) < 0.001


def test_tc_404_unknown_type(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_tc(p, [{"canonical": "EGF", "organoid_type": "kidney"}])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    _, s = ae.handle_type_comparison("kidney", "liver")
    assert s == 404


def test_tc_pmcid_dedup_counts_records_not_pmcids(tmp_path, monkeypatch):
    """n_records should count rows, not unique PMCIDs."""
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_tc(p, [
        {"canonical": "EGF", "organoid_type": "kidney"},
        {"canonical": "EGF", "organoid_type": "kidney"},
        {"canonical": "EGF", "organoid_type": "liver"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_type_comparison("kidney", "liver")
    shared_egf = next(r for r in data["shared"] if r["canonical"] == "EGF")
    # kidney has 2 EGF records
    assert shared_egf["n_records"] == 2


def test_tc_kind_breakdown_shared(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_tc(p, [
        {"canonical": "EGF", "organoid_type": "kidney", "kind": "signaling"},
        {"canonical": "EGF", "organoid_type": "liver", "kind": "supplement"},
    ])
    monkeypatch.setattr(ae, "REAGENTS_JSONL", p)
    data, _ = ae.handle_type_comparison("kidney", "liver")
    kb = data["kind_breakdown_shared"]
    assert "signaling" in kb or "supplement" in kb


def test_tc_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/type-comparison" in data["endpoints"]


# ---------------------------------------------------------------------------
# /analytics/concentration-deviation unit tests
# ---------------------------------------------------------------------------

def _write_reagents_for_cd(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _patch_cd(monkeypatch, path):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", path)


def test_cd_404_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", tmp_path / "missing.jsonl")
    _, status = ae.handle_concentration_deviation()
    assert status == 404


def test_cd_200_empty_corpus(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cd(p, [])
    _patch_cd(monkeypatch, p)
    data, status = ae.handle_concentration_deviation()
    assert status == 200
    assert data["n_canonicals_total"] == 0
    assert data["most_variable"] == []
    assert data["most_consistent"] == []


def test_cd_excludes_below_min_n(tmp_path, monkeypatch):
    # Only 2 records for EGF — below default min_n=3
    rows = [
        {"canonical": "EGF", "value": 10, "canonical_unit": "ng/mL"},
        {"canonical": "EGF", "value": 100, "canonical_unit": "ng/mL"},
    ]
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cd(p, rows)
    _patch_cd(monkeypatch, p)
    data, status = ae.handle_concentration_deviation()
    assert status == 200
    assert data["n_canonicals_total"] == 0
    assert data["n_excluded_too_few"] == 1


def test_cd_includes_above_min_n(tmp_path, monkeypatch):
    rows = [
        {"canonical": "EGF", "value": v, "canonical_unit": "ng/mL"}
        for v in [10, 50, 500]
    ]
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cd(p, rows)
    _patch_cd(monkeypatch, p)
    data, status = ae.handle_concentration_deviation()
    assert status == 200
    assert data["n_canonicals_total"] == 1
    entry = data["most_variable"][0]
    assert entry["canonical"] == "EGF"
    assert entry["n_with_value"] == 3
    assert entry["dominant_unit"] == "ng/mL"
    assert entry["cv"] > 0


def test_cd_cv_correct(tmp_path, monkeypatch):
    # Values: 1, 2, 3 → mean=2, std≈0.8165, cv≈0.4082
    rows = [
        {"canonical": "CHIR", "value": 1.0, "canonical_unit": "uM"},
        {"canonical": "CHIR", "value": 2.0, "canonical_unit": "uM"},
        {"canonical": "CHIR", "value": 3.0, "canonical_unit": "uM"},
    ]
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cd(p, rows)
    _patch_cd(monkeypatch, p)
    data, _ = ae.handle_concentration_deviation()
    entry = data["most_variable"][0]
    assert abs(entry["cv"] - 0.5) < 0.001   # sample std=1, mean=2 → cv=0.5
    assert entry["mean"] == 2.0
    assert entry["median"] == 2.0


def test_cd_most_variable_sorted_desc(tmp_path, monkeypatch):
    # EGF: 10, 50, 500 → high CV; CHIR: 1, 1, 1 → CV=0
    rows = (
        [{"canonical": "EGF", "value": v, "canonical_unit": "ng/mL"} for v in [10, 50, 500]]
        + [{"canonical": "CHIR", "value": 1.0, "canonical_unit": "uM"},
           {"canonical": "CHIR", "value": 1.0, "canonical_unit": "uM"},
           {"canonical": "CHIR", "value": 1.0, "canonical_unit": "uM"}]
    )
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cd(p, rows)
    _patch_cd(monkeypatch, p)
    data, _ = ae.handle_concentration_deviation()
    names = [e["canonical"] for e in data["most_variable"]]
    assert names[0] == "EGF"  # higher CV first


def test_cd_most_consistent_only_low_cv(tmp_path, monkeypatch):
    # CHIR: identical values → CV=0 (consistent); EGF: spread → CV > 0.5
    rows = (
        [{"canonical": "EGF", "value": v, "canonical_unit": "ng/mL"} for v in [1, 100, 10000]]
        + [{"canonical": "CHIR", "value": 3.0, "canonical_unit": "uM"} for _ in range(3)]
    )
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cd(p, rows)
    _patch_cd(monkeypatch, p)
    data, _ = ae.handle_concentration_deviation()
    consistent = data["most_consistent"]
    # CHIR should be in consistent (CV=0); EGF should NOT (CV >> 0.5)
    consistent_names = {e["canonical"] for e in consistent}
    assert "CHIR" in consistent_names
    assert "EGF" not in consistent_names


def test_cd_dominant_unit_by_count(tmp_path, monkeypatch):
    # 3 records in ng/mL, 1 in uM → ng/mL is dominant
    rows = (
        [{"canonical": "EGF", "value": v, "canonical_unit": "ng/mL"} for v in [10, 50, 100]]
        + [{"canonical": "EGF", "value": 1.0, "canonical_unit": "uM"}]
    )
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cd(p, rows)
    _patch_cd(monkeypatch, p)
    data, _ = ae.handle_concentration_deviation()
    entry = data["most_variable"][0]
    assert entry["dominant_unit"] == "ng/mL"
    assert entry["n_with_value"] == 3  # only dominant-unit values


def test_cd_min_n_param(tmp_path, monkeypatch):
    # With min_n=5, EGF with 3 values should be excluded
    rows = [{"canonical": "EGF", "value": v, "canonical_unit": "ng/mL"} for v in [10, 50, 100]]
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cd(p, rows)
    _patch_cd(monkeypatch, p)
    data, _ = ae.handle_concentration_deviation(min_n=5)
    assert data["n_canonicals_total"] == 0
    assert data["min_n_threshold"] == 5


def test_cd_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/concentration-deviation" in data["endpoints"]


# ---------------------------------------------------------------------------
# /analytics/reagent-prevalence unit tests
# ---------------------------------------------------------------------------

def _write_reagents_for_rp(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _patch_rp(monkeypatch, path):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", path)


_RP_ROWS = [
    # EGF in 3 types
    {"canonical": "EGF", "organoid_type": "intestinal", "kind": "signaling"},
    {"canonical": "EGF", "organoid_type": "kidney", "kind": "signaling"},
    {"canonical": "EGF", "organoid_type": "cerebral", "kind": "signaling"},
    {"canonical": "EGF", "organoid_type": "intestinal", "kind": "signaling"},  # second record same type
    # CHIR in 2 types
    {"canonical": "CHIR99021", "organoid_type": "intestinal", "kind": "signaling"},
    {"canonical": "CHIR99021", "organoid_type": "kidney", "kind": "signaling"},
    # Noggin in 1 type
    {"canonical": "Noggin", "organoid_type": "cerebral", "kind": "signaling"},
]


def test_rp_404_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", tmp_path / "missing.jsonl")
    _, status = ae.handle_reagent_prevalence(None)
    assert status == 404


def test_rp_200_cross_corpus(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rp(p, _RP_ROWS)
    _patch_rp(monkeypatch, p)
    data, status = ae.handle_reagent_prevalence(None)
    assert status == 200
    assert data["n_canonicals_total"] == 3
    assert data["n_types_total"] == 3


def test_rp_sorted_by_n_types_desc(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rp(p, _RP_ROWS)
    _patch_rp(monkeypatch, p)
    data, _ = ae.handle_reagent_prevalence(None)
    entries = data["all_canonicals"]
    assert entries[0]["canonical"] == "EGF"  # 3 types, highest
    assert entries[0]["n_types"] == 3
    n_types_list = [e["n_types"] for e in entries]
    assert n_types_list == sorted(n_types_list, reverse=True)


def test_rp_n_records_includes_duplicates(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rp(p, _RP_ROWS)
    _patch_rp(monkeypatch, p)
    data, _ = ae.handle_reagent_prevalence(None)
    egf = next(e for e in data["all_canonicals"] if e["canonical"] == "EGF")
    assert egf["n_records"] == 4  # 4 total EGF rows


def test_rp_specialist_list_is_low_breadth(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rp(p, _RP_ROWS)
    _patch_rp(monkeypatch, p)
    data, _ = ae.handle_reagent_prevalence(None)
    specialist = data["specialist"]
    for e in specialist:
        assert e["n_types"] <= 2
    # CHIR and Noggin are specialist (2 and 1 types)
    specialist_names = {e["canonical"] for e in specialist}
    assert "CHIR99021" in specialist_names
    assert "Noggin" in specialist_names


def test_rp_min_types_filter(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rp(p, _RP_ROWS)
    _patch_rp(monkeypatch, p)
    data, _ = ae.handle_reagent_prevalence(None, min_types=3)
    # Only EGF has 3 types
    assert data["n_canonicals_above_threshold"] == 1
    assert data["all_canonicals"][0]["canonical"] == "EGF"


def test_rp_query_returns_per_type(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rp(p, _RP_ROWS)
    _patch_rp(monkeypatch, p)
    data, status = ae.handle_reagent_prevalence("EGF")
    assert status == 200
    assert data["canonical"] == "EGF"
    assert data["n_types"] == 3
    assert data["n_records_total"] == 4
    types = {e["organoid_type"] for e in data["per_type"]}
    assert types == {"intestinal", "kidney", "cerebral"}


def test_rp_query_case_insensitive(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rp(p, _RP_ROWS)
    _patch_rp(monkeypatch, p)
    data, status = ae.handle_reagent_prevalence("egf")
    assert status == 200
    assert data["canonical"] == "EGF"


def test_rp_query_404_no_match(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rp(p, _RP_ROWS)
    _patch_rp(monkeypatch, p)
    _, status = ae.handle_reagent_prevalence("xyzabc_does_not_exist")
    assert status == 404


def test_rp_breadth_distribution_correct(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rp(p, _RP_ROWS)
    _patch_rp(monkeypatch, p)
    data, _ = ae.handle_reagent_prevalence(None)
    bd = data["breadth_distribution"]
    # EGF→3, CHIR→2, Noggin→1
    assert bd["3"] == 1
    assert bd["2"] == 1
    assert bd["1"] == 1


def test_rp_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/reagent-prevalence" in data["endpoints"]
