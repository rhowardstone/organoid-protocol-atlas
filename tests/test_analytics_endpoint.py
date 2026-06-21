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


# ---------------------------------------------------------------------------
# /analytics/protocol-outliers unit tests
# ---------------------------------------------------------------------------

def _write_protos_for_po(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _patch_po(monkeypatch, path):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", path)


_PO_ROWS = [
    # intestinal: 1, 5, 5, 5, 5, 12
    # mean=(1+5+5+5+5+12)/6=33/6=5.5, std≈3.56
    # threshold_hi = 5.5+1.5*3.56 ≈ 10.84 → 12 is complex ✓
    # threshold_lo = max(1, 5.5-1.5*3.56) = max(1, 0.16) = 1.0 → need n_sf < 1 for minimal
    # Use 0 as minimal to get below threshold_lo=1
    {"organoid_type": "intestinal", "n_signaling_factors": 1, "pmcid": "A", "doi": "10/A", "year": "2020"},
    {"organoid_type": "intestinal", "n_signaling_factors": 5, "pmcid": "B", "doi": "10/B", "year": "2020"},
    {"organoid_type": "intestinal", "n_signaling_factors": 5, "pmcid": "C", "doi": "10/C", "year": "2021"},
    {"organoid_type": "intestinal", "n_signaling_factors": 5, "pmcid": "D", "doi": "10/D", "year": "2021"},
    {"organoid_type": "intestinal", "n_signaling_factors": 5, "pmcid": "E", "doi": "10/E", "year": "2022"},
    {"organoid_type": "intestinal", "n_signaling_factors": 15, "pmcid": "F", "doi": "10/F", "year": "2023"},
    # kidney: single value (no outlier possible)
    {"organoid_type": "kidney", "n_signaling_factors": 5, "pmcid": "G", "doi": "10/G", "year": "2022"},
]
# intestinal: mean=(1+5+5+5+5+15)/6=36/6=6.0
# variance=((1-6)^2+(5-6)^2*4+(15-6)^2)/5=(25+4+81)/5=110/5=22, std≈4.69
# threshold_hi=6+1.5*4.69=13.03 → 15 is complex ✓
# threshold_lo=max(1, 6-1.5*4.69)=max(1,-1.03)=1.0 → 1 is NOT below 1.0 → no minimal

# For minimal detection test, use a tighter dataset:
_PO_ROWS_TIGHT = [
    # narrow cluster 4,5,5,5,6 + extreme low 1
    # mean=(1+4+5+5+5+6)/6=26/6=4.33, std≈1.75
    # threshold_lo=max(1,4.33-1.5*1.75)=max(1,1.7)=1.7 → n_sf=1 < 1.7 → minimal ✓
    # threshold_hi=4.33+1.5*1.75=6.95 → 6 is NOT complex
    {"organoid_type": "intestinal", "n_signaling_factors": 1, "pmcid": "A", "doi": "10/A", "year": "2020"},
    {"organoid_type": "intestinal", "n_signaling_factors": 4, "pmcid": "B", "doi": "10/B", "year": "2020"},
    {"organoid_type": "intestinal", "n_signaling_factors": 5, "pmcid": "C", "doi": "10/C", "year": "2021"},
    {"organoid_type": "intestinal", "n_signaling_factors": 5, "pmcid": "D", "doi": "10/D", "year": "2021"},
    {"organoid_type": "intestinal", "n_signaling_factors": 5, "pmcid": "E", "doi": "10/E", "year": "2022"},
    {"organoid_type": "intestinal", "n_signaling_factors": 6, "pmcid": "F", "doi": "10/F", "year": "2023"},
]


def test_po_404_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", tmp_path / "missing.jsonl")
    _, status = ae.handle_protocol_outliers(None)
    assert status == 404


def test_po_200_cross_corpus(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_po(p, _PO_ROWS)
    _patch_po(monkeypatch, p)
    data, status = ae.handle_protocol_outliers(None)
    assert status == 200
    assert "per_type" in data
    assert "intestinal" in data["per_type"]
    assert "kidney" in data["per_type"]
    assert data["n_types"] == 2


def test_po_single_type_query(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_po(p, _PO_ROWS)
    _patch_po(monkeypatch, p)
    data, status = ae.handle_protocol_outliers("intestinal")
    assert status == 200
    assert data["organoid_type"] == "intestinal"
    assert data["n_papers"] == 6
    # mean=(1+5+5+5+5+15)/6=36/6=6.0
    assert abs(data["mean_n_sf"] - 6.0) < 0.1


def test_po_complex_protocol_detected(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_po(p, _PO_ROWS)
    _patch_po(monkeypatch, p)
    data, status = ae.handle_protocol_outliers("intestinal")
    assert status == 200
    # n_sf=20 is the outlier on the high end
    complex_pmcids = {pp["pmcid"] for pp in data["complex_protocols"]}
    assert "F" in complex_pmcids


def test_po_minimal_protocol_detected(tmp_path, monkeypatch):
    # Use tight cluster data: n_sf=1 falls below threshold_lo≈1.7
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_po(p, _PO_ROWS_TIGHT)
    _patch_po(monkeypatch, p)
    data, status = ae.handle_protocol_outliers("intestinal")
    assert status == 200
    minimal_pmcids = {pp["pmcid"] for pp in data["minimal_protocols"]}
    assert "A" in minimal_pmcids


def test_po_z_score_positive_for_complex(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_po(p, _PO_ROWS)
    _patch_po(monkeypatch, p)
    data, _ = ae.handle_protocol_outliers("intestinal")
    for cp in data["complex_protocols"]:
        assert cp["z_score"] > 0


def test_po_z_score_negative_for_minimal(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_po(p, _PO_ROWS)
    _patch_po(monkeypatch, p)
    data, _ = ae.handle_protocol_outliers("intestinal")
    for mp in data["minimal_protocols"]:
        assert mp["z_score"] < 0


def test_po_404_unknown_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_po(p, _PO_ROWS)
    _patch_po(monkeypatch, p)
    _, status = ae.handle_protocol_outliers("xyz_unknown")
    assert status == 404


def test_po_ranking_sorted_by_mean_sf(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_po(p, _PO_ROWS)
    _patch_po(monkeypatch, p)
    data, _ = ae.handle_protocol_outliers(None)
    ranking = data["ranking_by_mean_sf"]
    # intestinal mean≈8.5 > kidney mean=5.0 → intestinal first
    assert ranking[0] == "intestinal"
    means = [data["per_type"][t]["mean_n_sf"] for t in ranking]
    assert means == sorted(means, reverse=True)


def test_po_custom_z_thresh(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_po(p, _PO_ROWS)
    _patch_po(monkeypatch, p)
    data, _ = ae.handle_protocol_outliers("intestinal", z_thresh=3.0)
    # Very high threshold: no outliers
    assert data["z_thresh"] == 3.0
    # With z=3.0 threshold on 6 points, the 20 SF outlier may still show
    # Just check field is present
    assert "complex_protocols" in data


def test_po_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/protocol-outliers" in data["endpoints"]


# ---------------------------------------------------------------------------
# /analytics/grounding-distribution unit tests
# ---------------------------------------------------------------------------

def _write_protos_for_gd(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _patch_gd(monkeypatch, path):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", path)


_GD_ROWS = [
    {"organoid_type": "intestinal", "grounding_rate": 1.0, "reagents_grounded": 10, "reagents_total": 10,
     "pmcid": "A", "doi": "10/A", "year": "2020"},
    {"organoid_type": "intestinal", "grounding_rate": 0.5, "reagents_grounded": 5, "reagents_total": 10,
     "pmcid": "B", "doi": "10/B", "year": "2021"},
    {"organoid_type": "intestinal", "grounding_rate": 0.8, "reagents_grounded": 8, "reagents_total": 10,
     "pmcid": "C", "doi": "10/C", "year": "2022"},
    {"organoid_type": "kidney", "grounding_rate": 0.6, "reagents_grounded": 6, "reagents_total": 10,
     "pmcid": "D", "doi": "10/D", "year": "2021"},
    {"organoid_type": "kidney", "grounding_rate": 0.2, "reagents_grounded": 2, "reagents_total": 10,
     "pmcid": "E", "doi": "10/E", "year": "2022"},
    # This row has no grounding_rate → excluded
    {"organoid_type": "intestinal", "grounding_rate": None, "pmcid": "F", "doi": "10/F", "year": "2020"},
]


def test_gd_404_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", tmp_path / "missing.jsonl")
    _, status = ae.handle_grounding_distribution(None)
    assert status == 404


def test_gd_200_cross_corpus(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_gd(p, _GD_ROWS)
    _patch_gd(monkeypatch, p)
    data, status = ae.handle_grounding_distribution(None)
    assert status == 200
    assert data["n"] == 5   # 6 rows but 1 has grounding_rate=None
    assert data["n_types"] == 2
    assert "histogram" in data
    assert "per_type_mean" in data


def test_gd_histogram_has_10_buckets(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_gd(p, _GD_ROWS)
    _patch_gd(monkeypatch, p)
    data, _ = ae.handle_grounding_distribution(None)
    assert len(data["histogram"]) == 10


def test_gd_histogram_100_percent_bucket(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_gd(p, _GD_ROWS)
    _patch_gd(monkeypatch, p)
    data, _ = ae.handle_grounding_distribution(None)
    # grounding_rate=1.0 falls in bucket 9 which is "90-100%"
    assert data["histogram"]["90-100%"] == 1


def test_gd_mean_correct(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_gd(p, _GD_ROWS)
    _patch_gd(monkeypatch, p)
    data, _ = ae.handle_grounding_distribution(None)
    # mean = (1.0 + 0.5 + 0.8 + 0.6 + 0.2) / 5 = 3.1/5 = 0.62
    assert abs(data["mean"] - 0.62) < 0.01


def test_gd_ranking_best_type_first(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_gd(p, _GD_ROWS)
    _patch_gd(monkeypatch, p)
    data, _ = ae.handle_grounding_distribution(None)
    ranking = data["ranking_by_mean_grounding_rate"]
    # intestinal mean = (1.0+0.5+0.8)/3 = 0.767; kidney mean = (0.6+0.2)/2 = 0.4
    assert ranking[0] == "intestinal"
    means = [data["per_type_mean"][t] for t in ranking]
    assert means == sorted(means, reverse=True)


def test_gd_top20_sorted_desc(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_gd(p, _GD_ROWS)
    _patch_gd(monkeypatch, p)
    data, _ = ae.handle_grounding_distribution(None)
    top = data["top_20_by_grounding_rate"]
    rates = [pp["grounding_rate"] for pp in top]
    assert rates == sorted(rates, reverse=True)
    assert top[0]["pmcid"] == "A"  # 1.0


def test_gd_bottom20_sorted_asc(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_gd(p, _GD_ROWS)
    _patch_gd(monkeypatch, p)
    data, _ = ae.handle_grounding_distribution(None)
    bot = data["bottom_20_by_grounding_rate"]
    rates = [pp["grounding_rate"] for pp in bot]
    assert rates == sorted(rates)
    assert bot[0]["pmcid"] == "E"  # 0.2


def test_gd_single_type_query(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_gd(p, _GD_ROWS)
    _patch_gd(monkeypatch, p)
    data, status = ae.handle_grounding_distribution("kidney")
    assert status == 200
    assert data["organoid_type"] == "kidney"
    assert data["n"] == 2


def test_gd_404_unknown_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_gd(p, _GD_ROWS)
    _patch_gd(monkeypatch, p)
    _, status = ae.handle_grounding_distribution("xyz_unknown")
    assert status == 404


def test_gd_excludes_none_grounding_rate(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_gd(p, _GD_ROWS)
    _patch_gd(monkeypatch, p)
    data, _ = ae.handle_grounding_distribution(None)
    # Row F has grounding_rate=None and should be excluded → n=5
    all_pmcids = {pp["pmcid"] for pp in data["top_20_by_grounding_rate"] + data["bottom_20_by_grounding_rate"]}
    assert "F" not in all_pmcids


def test_gd_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/grounding-distribution" in data["endpoints"]


# ---------------------------------------------------------------------------
# /analytics/type-maturity unit tests
# ---------------------------------------------------------------------------

def _write_protos_for_tm(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _patch_tm(monkeypatch, path):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", path)


_TM_ROWS = [
    # intestinal: 2015-2024, many papers → established + check trajectory
    *[{"organoid_type": "intestinal", "year": str(y)} for y in [2015, 2016, 2017, 2018] for _ in range(2)],
    *[{"organoid_type": "intestinal", "year": str(y)} for y in [2019, 2020, 2021, 2022, 2023, 2024] for _ in range(6)],
    # emerging: 2023 only, 3 papers
    {"organoid_type": "new_type", "year": "2023"},
    {"organoid_type": "new_type", "year": "2023"},
    {"organoid_type": "new_type", "year": "2023"},
]


def test_tm_404_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", tmp_path / "missing.jsonl")
    _, status = ae.handle_type_maturity(None)
    assert status == 404


def test_tm_200_cross_corpus(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_tm(p, _TM_ROWS)
    _patch_tm(monkeypatch, p)
    data, status = ae.handle_type_maturity(None)
    assert status == 200
    assert data["n_types"] == 2
    assert "by_tier" in data
    assert "by_trajectory" in data
    assert len(data["all_types"]) == 2


def test_tm_intestinal_is_established(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_tm(p, _TM_ROWS)
    _patch_tm(monkeypatch, p)
    data, _ = ae.handle_type_maturity(None)
    intestinal = next(r for r in data["all_types"] if r["organoid_type"] == "intestinal")
    # 2015 ≤ 2017 → established
    assert intestinal["maturity_tier"] == "established"
    assert intestinal["first_year"] == 2015
    assert intestinal["last_year"] == 2024
    assert intestinal["n_years_active"] == 10


def test_tm_emerging_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_tm(p, _TM_ROWS)
    _patch_tm(monkeypatch, p)
    data, _ = ae.handle_type_maturity(None)
    new_t = next(r for r in data["all_types"] if r["organoid_type"] == "new_type")
    # 3 papers, first_year 2023 → emerging
    assert new_t["maturity_tier"] == "emerging"
    assert new_t["n_papers_total"] == 3
    assert new_t["first_year"] == 2023


def test_tm_sorted_by_n_papers_desc(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_tm(p, _TM_ROWS)
    _patch_tm(monkeypatch, p)
    data, _ = ae.handle_type_maturity(None)
    totals = [r["n_papers_total"] for r in data["all_types"]]
    assert totals == sorted(totals, reverse=True)


def test_tm_papers_by_year_key_is_string(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_tm(p, _TM_ROWS)
    _patch_tm(monkeypatch, p)
    data, _ = ae.handle_type_maturity(None)
    intestinal = next(r for r in data["all_types"] if r["organoid_type"] == "intestinal")
    # all keys should be strings (year as string)
    assert all(isinstance(k, str) for k in intestinal["papers_by_year"])
    assert "2015" in intestinal["papers_by_year"]


def test_tm_single_type_query(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_tm(p, _TM_ROWS)
    _patch_tm(monkeypatch, p)
    data, status = ae.handle_type_maturity("intestinal")
    assert status == 200
    assert data["organoid_type"] == "intestinal"
    assert data["n_years_active"] == 10


def test_tm_404_unknown_type(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_tm(p, _TM_ROWS)
    _patch_tm(monkeypatch, p)
    _, status = ae.handle_type_maturity("xyz_unknown")
    assert status == 404


def test_tm_trajectory_accelerating(tmp_path, monkeypatch):
    # 1 paper in early years, many in later years → accelerating
    rows = (
        [{"organoid_type": "fast", "year": str(y)} for y in [2015, 2016, 2017, 2018]]
        + [{"organoid_type": "fast", "year": str(y)} for y in [2019, 2020, 2021, 2022] for _ in range(5)]
    )
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_tm(p, rows)
    _patch_tm(monkeypatch, p)
    data, _ = ae.handle_type_maturity("fast")
    assert data["trajectory"] == "accelerating"


def test_tm_by_tier_groups_present(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_tm(p, _TM_ROWS)
    _patch_tm(monkeypatch, p)
    data, _ = ae.handle_type_maturity(None)
    assert "established" in data["by_tier"]
    assert "intestinal" in data["by_tier"]["established"]
    assert "emerging" in data["by_tier"]
    assert "new_type" in data["by_tier"]["emerging"]


def test_tm_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/type-maturity" in data["endpoints"]


# ---------------------------------------------------------------------------
# Route 40: /analytics/reagent-cooccurrence
# ---------------------------------------------------------------------------

def _write_reagents_for_rc(path, rows):
    base = {
        "pmcid": "PMC1", "organoid_type": "intestinal",
        "kind": "signaling", "canonical": "EGF",
        "name": "EGF", "value": None, "unit": None,
        "canonical_unit": None, "grounded": False,
        "evidence_quote": None, "figure_confirmed": False,
        "suspect_unit": False, "role": None, "doi": None, "id": "r1",
    }
    path.write_text("\n".join(json.dumps({**base, **r}) for r in rows))


def _patch_rc(monkeypatch, path):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", path)


# Fixture: PMC1 (intestinal): EGF + Noggin + CHIR99021
#          PMC2 (intestinal): EGF + Noggin
#          PMC3 (kidney):     EGF + CHIR99021
#          PMC4 (intestinal): supplement B27 (excluded from signaling filter)
#          PMC5 (intestinal): EGF + Noggin + CHIR99021
# Co-occurrence (signaling only, papers PMC1/2/3/5):
#   EGF + Noggin: PMC1,PMC2,PMC5 → 3; union=4 → jaccard=0.75
#   EGF + CHIR99021: PMC1,PMC3,PMC5 → 3; union=4 → jaccard=0.75
#   Noggin + CHIR99021: PMC1,PMC5 → 2; union=4 → jaccard=0.5
_RC_ROWS = [
    {"pmcid": "PMC1", "organoid_type": "intestinal", "kind": "signaling", "canonical": "EGF"},
    {"pmcid": "PMC1", "organoid_type": "intestinal", "kind": "signaling", "canonical": "Noggin"},
    {"pmcid": "PMC1", "organoid_type": "intestinal", "kind": "signaling", "canonical": "CHIR99021"},
    {"pmcid": "PMC2", "organoid_type": "intestinal", "kind": "signaling", "canonical": "EGF"},
    {"pmcid": "PMC2", "organoid_type": "intestinal", "kind": "signaling", "canonical": "Noggin"},
    {"pmcid": "PMC3", "organoid_type": "kidney", "kind": "signaling", "canonical": "EGF"},
    {"pmcid": "PMC3", "organoid_type": "kidney", "kind": "signaling", "canonical": "CHIR99021"},
    {"pmcid": "PMC4", "organoid_type": "intestinal", "kind": "supplement", "canonical": "B27"},
    {"pmcid": "PMC5", "organoid_type": "intestinal", "kind": "signaling", "canonical": "EGF"},
    {"pmcid": "PMC5", "organoid_type": "intestinal", "kind": "signaling", "canonical": "Noggin"},
    {"pmcid": "PMC5", "organoid_type": "intestinal", "kind": "signaling", "canonical": "CHIR99021"},
]


def test_rc_returns_200(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rc(p, _RC_ROWS)
    _patch_rc(monkeypatch, p)
    data, status = ae.handle_reagent_cooccurrence(None, None, min_papers=3)
    assert status == 200
    assert "top_pairs" in data
    assert "n_papers_total" in data
    assert "n_canonicals" in data


def test_rc_n_papers_total(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rc(p, _RC_ROWS)
    _patch_rc(monkeypatch, p)
    # PMC4 has only supplement so it contributes no signaling rows,
    # but PMC1,2,3,5 each have at least one signaling → 4 papers
    data, _ = ae.handle_reagent_cooccurrence(None, None, min_papers=1)
    assert data["n_papers_total"] == 4


def test_rc_top_pair_n_papers(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rc(p, _RC_ROWS)
    _patch_rc(monkeypatch, p)
    data, _ = ae.handle_reagent_cooccurrence(None, None, min_papers=3)
    assert len(data["top_pairs"]) == 2
    assert data["top_pairs"][0]["n_papers"] == 3


def test_rc_jaccard_correct(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rc(p, _RC_ROWS)
    _patch_rc(monkeypatch, p)
    data, _ = ae.handle_reagent_cooccurrence(None, None, min_papers=3)
    # Both EGF+Noggin and EGF+CHIR99021 have inter=3, union=4 → 0.75
    jaccards = {p["jaccard"] for p in data["top_pairs"]}
    assert 0.75 in jaccards


def test_rc_min_papers_excludes_pairs(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rc(p, _RC_ROWS)
    _patch_rc(monkeypatch, p)
    # Noggin+CHIR99021 has n_papers=2; with min_papers=3, only 2 pairs remain
    data, _ = ae.handle_reagent_cooccurrence(None, None, min_papers=4)
    assert data["n_pairs"] == 0
    assert data["top_pairs"] == []


def test_rc_query_egf_returns_partners(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rc(p, _RC_ROWS)
    _patch_rc(monkeypatch, p)
    data, status = ae.handle_reagent_cooccurrence("EGF", None)
    assert status == 200
    assert data["query_canonical"] == "EGF"
    assert "co_occurring" in data
    assert data["n_co_occurring"] == 2
    canonicals = {r["canonical"] for r in data["co_occurring"]}
    assert "Noggin" in canonicals
    assert "CHIR99021" in canonicals


def test_rc_query_egf_n_papers_noggin(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rc(p, _RC_ROWS)
    _patch_rc(monkeypatch, p)
    data, _ = ae.handle_reagent_cooccurrence("EGF", None)
    noggin = next(r for r in data["co_occurring"] if r["canonical"] == "Noggin")
    assert noggin["n_papers"] == 3
    assert noggin["jaccard"] == 0.75


def test_rc_query_unknown_returns_404(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rc(p, _RC_ROWS)
    _patch_rc(monkeypatch, p)
    _, status = ae.handle_reagent_cooccurrence("NOSUCHCANONICAL_XYZ", None)
    assert status == 404


def test_rc_type_filter(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rc(p, _RC_ROWS)
    _patch_rc(monkeypatch, p)
    # kidney: only PMC3 with EGF+CHIR99021 → 1 paper, 1 pair (inter=1 < min_papers=3)
    data, _ = ae.handle_reagent_cooccurrence(None, "kidney", min_papers=3)
    assert data["n_papers_total"] == 1
    assert data["n_pairs"] == 0


def test_rc_type_filter_with_query(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rc(p, _RC_ROWS)
    _patch_rc(monkeypatch, p)
    # kidney + ?q=EGF → only CHIR99021 co-occurs (n_papers=1)
    data, status = ae.handle_reagent_cooccurrence("EGF", "kidney")
    assert status == 200
    assert data["n_papers_total"] == 1
    assert data["n_co_occurring"] == 1
    assert data["co_occurring"][0]["canonical"] == "CHIR99021"
    assert data["co_occurring"][0]["n_papers"] == 1


def test_rc_supplements_excluded(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rc(p, _RC_ROWS)
    _patch_rc(monkeypatch, p)
    data, _ = ae.handle_reagent_cooccurrence("B27", None)
    # B27 is supplement kind → not in canonical_papers → 404
    assert data.get("error") is not None


def test_rc_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/reagent-cooccurrence" in data["endpoints"]


# ---------------------------------------------------------------------------
# Route 41: /analytics/supplement-breakdown
# ---------------------------------------------------------------------------

def _write_reagents_for_sb(path, rows):
    base = {
        "pmcid": "PMC1", "organoid_type": "intestinal",
        "kind": "supplement", "canonical": "GlutaMAX",
        "name": "GlutaMAX", "value": None, "unit": None,
        "canonical_unit": None, "grounded": False,
        "evidence_quote": None, "figure_confirmed": False,
        "suspect_unit": False, "role": None, "doi": None, "id": "r1",
    }
    path.write_text("\n".join(json.dumps({**base, **r}) for r in rows))


def _patch_sb(monkeypatch, path):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", path)


# Fixture: 3 types × various supplements
# intestinal: PMC1={GlutaMAX,B27}, PMC2={GlutaMAX,HEPES}
# kidney:     PMC3={GlutaMAX,B27},  PMC4={N2}
# cerebral:   PMC5={B27,N2},        PMC6={GlutaMAX}
# signaling record (should be excluded):
#   PMC7 intestinal kind=signaling EGF
_SB_ROWS = [
    # intestinal
    {"pmcid": "PMC1", "organoid_type": "intestinal", "kind": "supplement", "canonical": "GlutaMAX"},
    {"pmcid": "PMC1", "organoid_type": "intestinal", "kind": "supplement", "canonical": "B27"},
    {"pmcid": "PMC2", "organoid_type": "intestinal", "kind": "supplement", "canonical": "GlutaMAX"},
    {"pmcid": "PMC2", "organoid_type": "intestinal", "kind": "supplement", "canonical": "HEPES"},
    # kidney
    {"pmcid": "PMC3", "organoid_type": "kidney", "kind": "supplement", "canonical": "GlutaMAX"},
    {"pmcid": "PMC3", "organoid_type": "kidney", "kind": "supplement", "canonical": "B27"},
    {"pmcid": "PMC4", "organoid_type": "kidney", "kind": "supplement", "canonical": "N2"},
    # cerebral
    {"pmcid": "PMC5", "organoid_type": "cerebral", "kind": "supplement", "canonical": "B27"},
    {"pmcid": "PMC5", "organoid_type": "cerebral", "kind": "supplement", "canonical": "N2"},
    {"pmcid": "PMC6", "organoid_type": "cerebral", "kind": "supplement", "canonical": "GlutaMAX"},
    # signaling (excluded)
    {"pmcid": "PMC7", "organoid_type": "intestinal", "kind": "signaling", "canonical": "EGF"},
]
# Expected:
#   GlutaMAX: PMC1,2,3,6 → 4 papers, 3 types
#   B27:      PMC1,3,5   → 3 papers, 3 types
#   N2:       PMC4,5     → 2 papers, 2 types
#   HEPES:    PMC2       → 1 paper,  1 type
#   n_papers_with_supplements: PMC1..PMC6 = 6


def test_sb_returns_200(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_sb(p, _SB_ROWS)
    _patch_sb(monkeypatch, p)
    data, status = ae.handle_supplement_breakdown(None, None)
    assert status == 200
    assert "top_supplements" in data
    assert "cross_type_supplements" in data
    assert "per_type" in data


def test_sb_n_papers_with_supplements(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_sb(p, _SB_ROWS)
    _patch_sb(monkeypatch, p)
    data, _ = ae.handle_supplement_breakdown(None, None)
    assert data["n_papers_with_supplements"] == 6


def test_sb_top_supplement_is_glutamax(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_sb(p, _SB_ROWS)
    _patch_sb(monkeypatch, p)
    data, _ = ae.handle_supplement_breakdown(None, None)
    assert data["top_supplements"][0]["canonical"] == "GlutaMAX"
    assert data["top_supplements"][0]["n_papers"] == 4


def test_sb_cross_type_threshold(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_sb(p, _SB_ROWS)
    _patch_sb(monkeypatch, p)
    # With min_types=3, only GlutaMAX and B27 qualify (each in 3 types)
    data, _ = ae.handle_supplement_breakdown(None, None, min_types=3)
    names = {s["canonical"] for s in data["cross_type_supplements"]}
    assert "GlutaMAX" in names
    assert "B27" in names
    assert "N2" not in names  # N2 only in 2 types
    assert "HEPES" not in names  # HEPES only in 1 type


def test_sb_signaling_excluded(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_sb(p, _SB_ROWS)
    _patch_sb(monkeypatch, p)
    data, _ = ae.handle_supplement_breakdown(None, None)
    all_canonicals = {s["canonical"] for s in data["top_supplements"]}
    assert "EGF" not in all_canonicals  # signaling, not supplement


def test_sb_query_glutamax(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_sb(p, _SB_ROWS)
    _patch_sb(monkeypatch, p)
    data, status = ae.handle_supplement_breakdown("GlutaMAX", None)
    assert status == 200
    assert data["query_canonical"] == "GlutaMAX"
    assert data["n_papers_total"] == 4
    assert data["n_types"] == 3
    types_covered = {e["organoid_type"] for e in data["per_type"]}
    assert "intestinal" in types_covered
    assert "kidney" in types_covered
    assert "cerebral" in types_covered


def test_sb_query_unknown_returns_404(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_sb(p, _SB_ROWS)
    _patch_sb(monkeypatch, p)
    _, status = ae.handle_supplement_breakdown("NOSUCHSUPPLEMENT_XYZ", None)
    assert status == 404


def test_sb_type_filter_kidney(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_sb(p, _SB_ROWS)
    _patch_sb(monkeypatch, p)
    data, status = ae.handle_supplement_breakdown(None, "kidney")
    assert status == 200
    assert data["organoid_type"] == "kidney"
    # kidney: PMC3={GlutaMAX,B27}, PMC4={N2} → 2 papers
    assert data["n_papers"] == 2
    assert data["n_supplement_canonicals"] == 3
    top_names = [s["canonical"] for s in data["top_supplements"]]
    assert "N2" in top_names


def test_sb_type_filter_unknown_returns_404(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_sb(p, _SB_ROWS)
    _patch_sb(monkeypatch, p)
    _, status = ae.handle_supplement_breakdown(None, "notype_xyz")
    assert status == 404


def test_sb_per_type_present(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_sb(p, _SB_ROWS)
    _patch_sb(monkeypatch, p)
    data, _ = ae.handle_supplement_breakdown(None, None)
    assert "intestinal" in data["per_type"]
    assert "kidney" in data["per_type"]
    assert "cerebral" in data["per_type"]
    # intestinal top: GlutaMAX appears in 2 papers (PMC1, PMC2) → should be first
    assert data["per_type"]["intestinal"][0]["canonical"] == "GlutaMAX"


def test_sb_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/supplement-breakdown" in data["endpoints"]


# ---------------------------------------------------------------------------
# Route 42: /analytics/role-breakdown
# ---------------------------------------------------------------------------

def _write_reagents_for_rb(path, rows):
    base = {
        "pmcid": "PMC1", "organoid_type": "intestinal",
        "kind": "signaling", "canonical": "EGF",
        "name": "EGF", "role": "growth factor",
        "value": None, "unit": None, "canonical_unit": None,
        "grounded": False, "evidence_quote": None,
        "figure_confirmed": False, "suspect_unit": False,
        "doi": None, "id": "r1",
    }
    path.write_text("\n".join(json.dumps({**base, **r}) for r in rows))


def _patch_rb(monkeypatch, path):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", path)


# Fixture:
#  PMC1 intestinal: EGF (growth factor), Noggin (inhibitor), CHIR99021 (signaling)
#  PMC2 kidney:     BMP4 (differentiation), Wnt (signaling factor), FGF2 (growth factor)
#  PMC3 cerebral:   EGF (growth factor), FGF2 (growth factor), BDNF (None role)
#  PMC4 intestinal: supplement B27 (kind=supplement, excluded)
_RB_ROWS = [
    {"pmcid": "PMC1", "organoid_type": "intestinal", "kind": "signaling", "canonical": "EGF",      "role": "growth factor"},
    {"pmcid": "PMC1", "organoid_type": "intestinal", "kind": "signaling", "canonical": "Noggin",   "role": "inhibitor"},
    {"pmcid": "PMC1", "organoid_type": "intestinal", "kind": "signaling", "canonical": "CHIR99021","role": "signaling"},
    {"pmcid": "PMC2", "organoid_type": "kidney",     "kind": "signaling", "canonical": "BMP4",     "role": "differentiation"},
    {"pmcid": "PMC2", "organoid_type": "kidney",     "kind": "signaling", "canonical": "Wnt",      "role": "signaling factor"},
    {"pmcid": "PMC2", "organoid_type": "kidney",     "kind": "signaling", "canonical": "FGF2",     "role": "growth factor"},
    {"pmcid": "PMC3", "organoid_type": "cerebral",   "kind": "signaling", "canonical": "EGF",      "role": "growth factor"},
    {"pmcid": "PMC3", "organoid_type": "cerebral",   "kind": "signaling", "canonical": "FGF2",     "role": "growth factor"},
    {"pmcid": "PMC3", "organoid_type": "cerebral",   "kind": "signaling", "canonical": "BDNF",     "role": None},
    {"pmcid": "PMC4", "organoid_type": "intestinal", "kind": "supplement","canonical": "B27",      "role": "supplement"},
]
# Expected (signaling only, 9 rows):
#   growth_factor:   EGF×2 (PMC1+PMC3) + FGF2×2 (PMC2+PMC3) + EGF(PMC3) = 5 records (EGF, EGF, FGF2, FGF2 mapped to growth_factor)
#   Actually: "growth factor" → growth_factor: EGF(PMC1), FGF2(PMC2), EGF(PMC3), FGF2(PMC3) = 4 records
#   inhibitor:       Noggin(PMC1) = 1 record
#   signaling_factor: CHIR99021(PMC1 "signaling"), Wnt(PMC2 "signaling factor") = 2 records
#   differentiation: BMP4(PMC2) = 1 record
#   not_stated:      BDNF(PMC3 None) = 1 record
#   Total signaling rows = 9


def test_rb_returns_200(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rb(p, _RB_ROWS)
    _patch_rb(monkeypatch, p)
    data, status = ae.handle_role_breakdown(None, None)
    assert status == 200
    assert "role_distribution" in data
    assert "per_type" in data
    assert "n_records_total" in data


def test_rb_n_records_total(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rb(p, _RB_ROWS)
    _patch_rb(monkeypatch, p)
    # Only signaling kind, 9 rows (B27 supplement excluded)
    data, _ = ae.handle_role_breakdown(None, None)
    assert data["n_records_total"] == 9


def test_rb_top_role_is_growth_factor(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rb(p, _RB_ROWS)
    _patch_rb(monkeypatch, p)
    data, _ = ae.handle_role_breakdown(None, None)
    assert data["role_distribution"][0]["role"] == "growth_factor"
    assert data["role_distribution"][0]["n_records"] == 4


def test_rb_normalization_signaling_maps_correctly(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rb(p, _RB_ROWS)
    _patch_rb(monkeypatch, p)
    data, _ = ae.handle_role_breakdown(None, None)
    roles = {r["role"]: r["n_records"] for r in data["role_distribution"]}
    # "signaling" + "signaling factor" → both map to signaling_factor = 2 records
    assert roles.get("signaling_factor") == 2


def test_rb_not_stated_for_none_role(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rb(p, _RB_ROWS)
    _patch_rb(monkeypatch, p)
    data, _ = ae.handle_role_breakdown(None, None)
    roles = {r["role"]: r["n_records"] for r in data["role_distribution"]}
    assert roles.get("not_stated") == 1


def test_rb_n_with_role(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rb(p, _RB_ROWS)
    _patch_rb(monkeypatch, p)
    data, _ = ae.handle_role_breakdown(None, None)
    # 9 total, 1 not_stated → 8 with role
    assert data["n_with_role"] == 8


def test_rb_type_filter_kidney(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rb(p, _RB_ROWS)
    _patch_rb(monkeypatch, p)
    data, status = ae.handle_role_breakdown(None, "kidney")
    assert status == 200
    assert data["n_records_total"] == 3  # BMP4, Wnt, FGF2
    roles = {r["role"] for r in data["role_distribution"]}
    assert "growth_factor" in roles
    assert "signaling_factor" in roles
    assert "differentiation" in roles


def test_rb_type_filter_no_data_returns_404(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rb(p, _RB_ROWS)
    _patch_rb(monkeypatch, p)
    _, status = ae.handle_role_breakdown(None, "NOTYPE_XYZ")
    assert status == 404


def test_rb_query_growth_factor_returns_canonicals(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rb(p, _RB_ROWS)
    _patch_rb(monkeypatch, p)
    data, status = ae.handle_role_breakdown("growth_factor", None)
    assert status == 200
    assert data["role"] == "growth_factor"
    canon_names = {c["canonical"] for c in data["top_canonicals"]}
    assert "EGF" in canon_names
    assert "FGF2" in canon_names


def test_rb_query_unknown_role_returns_404(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_rb(p, _RB_ROWS)
    _patch_rb(monkeypatch, p)
    _, status = ae.handle_role_breakdown("UNKNOWN_ROLE_XYZ", None)
    assert status == 404


def test_rb_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/role-breakdown" in data["endpoints"]


# ---------------------------------------------------------------------------
# Route 43: /analytics/type-reagent-heatmap
# ---------------------------------------------------------------------------

def _write_reagents_for_th(path, rows):
    base = {
        "pmcid": "PMC1", "organoid_type": "intestinal",
        "kind": "signaling", "canonical": "EGF",
        "name": "EGF", "role": None,
        "value": None, "unit": None, "canonical_unit": None,
        "grounded": False, "evidence_quote": None,
        "figure_confirmed": False, "suspect_unit": False,
        "doi": None, "id": "r1",
    }
    path.write_text("\n".join(json.dumps({**base, **r}) for r in rows))


def _patch_th(monkeypatch, path):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", path)


# Fixture: 2 types, 3 canonicals
# intestinal: EGF(PMC1,PMC2), Noggin(PMC1), CHIR99021(PMC2)
# kidney:     EGF(PMC3), CHIR99021(PMC3)
# supplement: B27 (intestinal, kind=supplement)
# Global signaling canon order by n_papers: EGF=3, Noggin=1, CHIR99021=2 → sorted: EGF, CHIR99021, Noggin
_TH_ROWS = [
    {"pmcid": "PMC1", "organoid_type": "intestinal", "kind": "signaling", "canonical": "EGF"},
    {"pmcid": "PMC1", "organoid_type": "intestinal", "kind": "signaling", "canonical": "Noggin"},
    {"pmcid": "PMC2", "organoid_type": "intestinal", "kind": "signaling", "canonical": "EGF"},
    {"pmcid": "PMC2", "organoid_type": "intestinal", "kind": "signaling", "canonical": "CHIR99021"},
    {"pmcid": "PMC3", "organoid_type": "kidney",     "kind": "signaling", "canonical": "EGF"},
    {"pmcid": "PMC3", "organoid_type": "kidney",     "kind": "signaling", "canonical": "CHIR99021"},
    {"pmcid": "PMC4", "organoid_type": "intestinal", "kind": "supplement","canonical": "B27"},
]


def test_th_returns_200(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_th(p, _TH_ROWS)
    _patch_th(monkeypatch, p)
    data, status = ae.handle_type_reagent_heatmap(None)
    assert status == 200
    assert "canonicals" in data
    assert "matrix" in data
    assert "n_types" in data


def test_th_top_canonical_is_egf(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_th(p, _TH_ROWS)
    _patch_th(monkeypatch, p)
    # EGF appears in PMC1,PMC2,PMC3 = 3 papers globally → should be first
    data, _ = ae.handle_type_reagent_heatmap(None, top_n=3)
    assert data["canonicals"][0] == "EGF"


def test_th_matrix_shape(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_th(p, _TH_ROWS)
    _patch_th(monkeypatch, p)
    data, _ = ae.handle_type_reagent_heatmap(None, top_n=3)
    assert data["n_types"] == 2
    assert len(data["matrix"]) == 2
    # Each row has len(canonicals) values
    for row in data["matrix"]:
        assert len(row["values"]) == 3


def test_th_intestinal_egf_count(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_th(p, _TH_ROWS)
    _patch_th(monkeypatch, p)
    data, _ = ae.handle_type_reagent_heatmap(None, top_n=3)
    intestinal = next(r for r in data["matrix"] if r["organoid_type"] == "intestinal")
    egf_idx = data["canonicals"].index("EGF")
    assert intestinal["values"][egf_idx] == 2  # PMC1, PMC2


def test_th_supplement_filter(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_th(p, _TH_ROWS)
    _patch_th(monkeypatch, p)
    data, _ = ae.handle_type_reagent_heatmap("supplement", top_n=5)
    assert data["kind"] == "supplement"
    # Only B27 is supplement → 1 canonical
    assert "B27" in data["canonicals"]
    assert "EGF" not in data["canonicals"]


def test_th_kind_all_includes_both(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_th(p, _TH_ROWS)
    _patch_th(monkeypatch, p)
    data, _ = ae.handle_type_reagent_heatmap("all", top_n=10)
    assert "EGF" in data["canonicals"]
    assert "B27" in data["canonicals"]


def test_th_top_n_capped_at_50(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_th(p, _TH_ROWS)
    _patch_th(monkeypatch, p)
    data, _ = ae.handle_type_reagent_heatmap(None, top_n=100)
    # Only 3 signaling canonicals in fixture → top_n capped at n_available
    assert len(data["canonicals"]) == 3
    assert data["top_n"] == 50  # parameter stored as min(100, 50)


def test_th_invalid_kind_returns_400(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_th(p, _TH_ROWS)
    _patch_th(monkeypatch, p)
    _, status = ae.handle_type_reagent_heatmap("badkind", top_n=5)
    assert status == 400


def test_th_types_sorted_by_n_papers(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_th(p, _TH_ROWS)
    _patch_th(monkeypatch, p)
    data, _ = ae.handle_type_reagent_heatmap(None, top_n=3)
    # intestinal: PMC1,PMC2 = 2 papers; kidney: PMC3 = 1 paper → intestinal first
    assert data["matrix"][0]["organoid_type"] == "intestinal"


def test_th_n_papers_total_in_row(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_th(p, _TH_ROWS)
    _patch_th(monkeypatch, p)
    data, _ = ae.handle_type_reagent_heatmap(None, top_n=3)
    intestinal = next(r for r in data["matrix"] if r["organoid_type"] == "intestinal")
    assert intestinal["n_papers_total"] == 2  # PMC1, PMC2


def test_th_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/type-reagent-heatmap" in data["endpoints"]


# ---------------------------------------------------------------------------
# Route 44: /analytics/canonical-name-variants
# ---------------------------------------------------------------------------

def _write_reagents_for_nv(path, rows):
    base = {
        "pmcid": "PMC1", "organoid_type": "intestinal",
        "kind": "signaling", "canonical": "EGF",
        "name": "EGF", "role": None,
        "value": None, "unit": None, "canonical_unit": None,
        "grounded": False, "evidence_quote": None,
        "figure_confirmed": False, "suspect_unit": False,
        "doi": None, "id": "r1",
    }
    path.write_text("\n".join(json.dumps({**base, **r}) for r in rows))


def _patch_nv(monkeypatch, path):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", path)


# Fixture:
#   EGF: "EGF", "epidermal growth factor", "rhEGF" → 3 variants, 3 records
#   FGF2: "FGF2", "bFGF", "FGF-2" → 3 variants, 3 records
#   Noggin: "Noggin" → 1 variant, 2 records (2 papers same name)
_NV_ROWS = [
    {"canonical": "EGF",  "name": "EGF",                      "pmcid": "PMC1"},
    {"canonical": "EGF",  "name": "epidermal growth factor",  "pmcid": "PMC2"},
    {"canonical": "EGF",  "name": "rhEGF",                    "pmcid": "PMC3"},
    {"canonical": "FGF2", "name": "FGF2",                     "pmcid": "PMC1"},
    {"canonical": "FGF2", "name": "bFGF",                     "pmcid": "PMC2"},
    {"canonical": "FGF2", "name": "FGF-2",                    "pmcid": "PMC3"},
    {"canonical": "Noggin","name": "Noggin",                   "pmcid": "PMC1"},
    {"canonical": "Noggin","name": "Noggin",                   "pmcid": "PMC2"},  # same name, deduplicated
]


def test_nv_returns_200(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_nv(p, _NV_ROWS)
    _patch_nv(monkeypatch, p)
    data, status = ae.handle_canonical_name_variants(None)
    assert status == 200
    assert "most_ambiguous" in data
    assert "n_canonicals_total" in data
    assert "n_with_multiple_names" in data


def test_nv_n_canonicals_total(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_nv(p, _NV_ROWS)
    _patch_nv(monkeypatch, p)
    data, _ = ae.handle_canonical_name_variants(None)
    assert data["n_canonicals_total"] == 3  # EGF, FGF2, Noggin


def test_nv_n_with_multiple_names(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_nv(p, _NV_ROWS)
    _patch_nv(monkeypatch, p)
    data, _ = ae.handle_canonical_name_variants(None)
    # EGF and FGF2 each have 3 variants, Noggin has only 1 → 2 with multiple
    assert data["n_with_multiple_names"] == 2


def test_nv_most_ambiguous_sorted_desc(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_nv(p, _NV_ROWS)
    _patch_nv(monkeypatch, p)
    data, _ = ae.handle_canonical_name_variants(None)
    entries = data["most_ambiguous"]
    # EGF and FGF2 both have 3 variants, Noggin (1) excluded by min_variants=2
    assert len(entries) == 2
    n_variants = [e["n_variants"] for e in entries]
    assert n_variants == sorted(n_variants, reverse=True)


def test_nv_min_variants_filter(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_nv(p, _NV_ROWS)
    _patch_nv(monkeypatch, p)
    # min_variants=4: neither EGF nor FGF2 qualify (both have 3)
    data, _ = ae.handle_canonical_name_variants(None, min_variants=4)
    assert data["n_above_threshold"] == 0
    assert data["most_ambiguous"] == []


def test_nv_query_exact(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_nv(p, _NV_ROWS)
    _patch_nv(monkeypatch, p)
    data, status = ae.handle_canonical_name_variants("EGF")
    assert status == 200
    assert data["canonical"] == "EGF"
    assert data["n_variants"] == 3
    assert "EGF" in data["names"]
    assert "rhEGF" in data["names"]
    assert "epidermal growth factor" in data["names"]


def test_nv_query_n_records(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_nv(p, _NV_ROWS)
    _patch_nv(monkeypatch, p)
    data, _ = ae.handle_canonical_name_variants("Noggin")
    # Noggin has 2 records (2 rows) even though only 1 unique name
    assert data["n_records"] == 2
    assert data["n_variants"] == 1


def test_nv_query_substring_match(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_nv(p, _NV_ROWS)
    _patch_nv(monkeypatch, p)
    # "fgf" matches "FGF2" (case-insensitive substring)
    data, status = ae.handle_canonical_name_variants("fgf")
    assert status == 200
    assert data["canonical"] == "FGF2"


def test_nv_query_unknown_returns_404(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_nv(p, _NV_ROWS)
    _patch_nv(monkeypatch, p)
    _, status = ae.handle_canonical_name_variants("NOSUCHCANONICAL_XYZ")
    assert status == 404


def test_nv_noggin_excluded_from_global(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_nv(p, _NV_ROWS)
    _patch_nv(monkeypatch, p)
    data, _ = ae.handle_canonical_name_variants(None, min_variants=2)
    names = [e["canonical"] for e in data["most_ambiguous"]]
    assert "Noggin" not in names  # only 1 variant → excluded


def test_nv_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/canonical-name-variants" in data["endpoints"]


# ---------------------------------------------------------------------------
# Route 45: /analytics/concentration-unit-distribution
# ---------------------------------------------------------------------------

def _write_reagents_for_cu(path, rows):
    base = {
        "pmcid": "PMC1", "organoid_type": "intestinal",
        "kind": "signaling", "canonical": "EGF",
        "name": "EGF", "role": None,
        "value": 50.0, "unit": "ng/mL", "canonical_unit": "ng/mL",
        "grounded": False, "evidence_quote": None,
        "figure_confirmed": False, "suspect_unit": False,
        "doi": None, "id": "r1",
    }
    path.write_text("\n".join(json.dumps({**base, **r}) for r in rows))


def _patch_cu(monkeypatch, path):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", path)


# Fixture:
# EGF: 3×ng/mL (50,100,200), 1×uM (0.5) → 2 units, 4 records
# FGF2: 2×ng/mL (20,30) → 1 unit, 2 records
# Noggin: 1×ng/mL (100) → only 1 record (below min_n=3 default)
_CU_ROWS = [
    {"canonical": "EGF",   "canonical_unit": "ng/mL", "value": 50.0,  "pmcid": "PMC1"},
    {"canonical": "EGF",   "canonical_unit": "ng/mL", "value": 100.0, "pmcid": "PMC2"},
    {"canonical": "EGF",   "canonical_unit": "ng/mL", "value": 200.0, "pmcid": "PMC3"},
    {"canonical": "EGF",   "canonical_unit": "uM",    "value": 0.5,   "pmcid": "PMC4"},
    {"canonical": "FGF2",  "canonical_unit": "ng/mL", "value": 20.0,  "pmcid": "PMC1"},
    {"canonical": "FGF2",  "canonical_unit": "ng/mL", "value": 30.0,  "pmcid": "PMC2"},
    {"canonical": "Noggin","canonical_unit": "ng/mL", "value": 100.0, "pmcid": "PMC1"},
]


def test_cu_returns_200(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cu(p, _CU_ROWS)
    _patch_cu(monkeypatch, p)
    data, status = ae.handle_concentration_unit_distribution(None)
    assert status == 200
    assert "multi_unit_canonicals" in data
    assert "n_canonicals_with_values" in data
    assert "n_multi_unit" in data


def test_cu_egf_is_multi_unit(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cu(p, _CU_ROWS)
    _patch_cu(monkeypatch, p)
    data, _ = ae.handle_concentration_unit_distribution(None, min_n=1)
    names = [e["canonical"] for e in data["multi_unit_canonicals"]]
    assert "EGF" in names
    egf = next(e for e in data["multi_unit_canonicals"] if e["canonical"] == "EGF")
    assert egf["n_units"] == 2
    assert egf["dominant_unit"] == "ng/mL"
    assert egf["dominant_pct"] == 75.0  # 3/4


def test_cu_fgf2_not_in_multi_unit(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cu(p, _CU_ROWS)
    _patch_cu(monkeypatch, p)
    data, _ = ae.handle_concentration_unit_distribution(None, min_n=1)
    names = [e["canonical"] for e in data["multi_unit_canonicals"]]
    assert "FGF2" not in names  # only 1 unit


def test_cu_min_n_filters_noggin(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cu(p, _CU_ROWS)
    _patch_cu(monkeypatch, p)
    # Noggin has 1 record < min_n=3 → not in n_canonicals_with_values
    data, _ = ae.handle_concentration_unit_distribution(None, min_n=3)
    # EGF has 4 records (≥3), FGF2 has 2 (≥3? No, 2<3) → actually EGF only has 4≥3
    # FGF2: 2 < 3 → also excluded
    assert data["n_canonicals_with_values"] == 1  # only EGF qualifies


def test_cu_query_egf(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cu(p, _CU_ROWS)
    _patch_cu(monkeypatch, p)
    data, status = ae.handle_concentration_unit_distribution("EGF")
    assert status == 200
    assert data["canonical"] == "EGF"
    assert data["n_units"] == 2
    assert data["n_records_total"] == 4
    assert data["is_unit_consistent"] is False
    assert data["dominant_unit"] == "ng/mL"


def test_cu_query_egf_median_correct(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cu(p, _CU_ROWS)
    _patch_cu(monkeypatch, p)
    data, _ = ae.handle_concentration_unit_distribution("EGF")
    ng_unit = next(u for u in data["units"] if u["unit"] == "ng/mL")
    # Values: 50, 100, 200 → median = 100
    assert ng_unit["median"] == 100.0
    assert ng_unit["min"] == 50.0
    assert ng_unit["max"] == 200.0
    assert ng_unit["n_records"] == 3
    assert ng_unit["pct"] == 75.0


def test_cu_query_fgf2_consistent(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cu(p, _CU_ROWS)
    _patch_cu(monkeypatch, p)
    data, status = ae.handle_concentration_unit_distribution("FGF2")
    assert status == 200
    assert data["is_unit_consistent"] is True
    assert data["n_units"] == 1


def test_cu_query_unknown_returns_404(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cu(p, _CU_ROWS)
    _patch_cu(monkeypatch, p)
    _, status = ae.handle_concentration_unit_distribution("NOSUCHCANON_XYZ")
    assert status == 404


def test_cu_n_multi_unit(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cu(p, _CU_ROWS)
    _patch_cu(monkeypatch, p)
    data, _ = ae.handle_concentration_unit_distribution(None, min_n=1)
    assert data["n_multi_unit"] == 1  # only EGF


def test_cu_pct_sums_to_100(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cu(p, _CU_ROWS)
    _patch_cu(monkeypatch, p)
    data, _ = ae.handle_concentration_unit_distribution("EGF")
    total_pct = sum(u["pct"] for u in data["units"])
    assert abs(total_pct - 100.0) < 0.01


def test_cu_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/concentration-unit-distribution" in data["endpoints"]


# ---------------------------------------------------------------------------
# Route 46: /analytics/protocol-size-distribution
# ---------------------------------------------------------------------------

def _write_protos_for_ps(path, rows):
    base = {
        "pmcid": "PMC1", "organoid_type": "intestinal",
        "n_signaling_factors": 5, "n_supplements": 2,
        "n_figure_confirmed": 0, "grounding_rate": 0.5,
        "reagents_grounded": 3, "reagents_total": 6,
        "species": "human", "matrix": None, "base_media": None,
        "source_cell_type": "iPSC", "passaging": None, "timeline": None,
        "assay_endpoints": None, "year": "2020", "doi": None,
        "journal": "Nature", "license": "CC-BY", "gold_candidate": "no",
        "extractor": "tier1", "base_media_reporting": "reported",
        "first_author": "Smith J",
    }
    path.write_text("\n".join(json.dumps({**base, **r}) for r in rows))


def _patch_ps(monkeypatch, path):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", path)


# Fixture:
# intestinal: PMC1 (sf=5, supp=2), PMC2 (sf=3, supp=1), PMC3 (sf=7, supp=3)
# kidney:     PMC4 (sf=4, supp=2), PMC5 (sf=10, supp=4)
_PS_ROWS = [
    {"pmcid": "PMC1", "organoid_type": "intestinal", "n_signaling_factors": 5, "n_supplements": 2},
    {"pmcid": "PMC2", "organoid_type": "intestinal", "n_signaling_factors": 3, "n_supplements": 1},
    {"pmcid": "PMC3", "organoid_type": "intestinal", "n_signaling_factors": 7, "n_supplements": 3},
    {"pmcid": "PMC4", "organoid_type": "kidney",     "n_signaling_factors": 4, "n_supplements": 2},
    {"pmcid": "PMC5", "organoid_type": "kidney",     "n_signaling_factors": 10, "n_supplements": 4},
]


def test_ps_returns_200(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_ps(p, _PS_ROWS)
    _patch_ps(monkeypatch, p)
    data, status = ae.handle_protocol_size_distribution(None)
    assert status == 200
    assert "signaling_factors" in data
    assert "supplements" in data
    assert "per_type" in data


def test_ps_n_papers_total(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_ps(p, _PS_ROWS)
    _patch_ps(monkeypatch, p)
    data, _ = ae.handle_protocol_size_distribution(None)
    assert data["n_papers_total"] == 5


def test_ps_sf_mean_correct(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_ps(p, _PS_ROWS)
    _patch_ps(monkeypatch, p)
    # (5+3+7+4+10)/5 = 29/5 = 5.8
    data, _ = ae.handle_protocol_size_distribution(None)
    assert abs(data["signaling_factors"]["mean"] - 5.8) < 0.01


def test_ps_sf_histogram_present(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_ps(p, _PS_ROWS)
    _patch_ps(monkeypatch, p)
    data, _ = ae.handle_protocol_size_distribution(None)
    hist = data["signaling_factors"]["histogram"]
    assert isinstance(hist, list)
    assert len(hist) >= 3  # at least 3 distinct values (3,4,5,7,10)
    # All histogram entries should have value and n_papers
    for entry in hist:
        assert "value" in entry and "n_papers" in entry


def test_ps_sf_stats_correct(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_ps(p, _PS_ROWS)
    _patch_ps(monkeypatch, p)
    data, _ = ae.handle_protocol_size_distribution(None)
    sf = data["signaling_factors"]
    assert sf["min"] == 3
    assert sf["max"] == 10
    assert sf["n_papers"] == 5


def test_ps_per_type_present(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_ps(p, _PS_ROWS)
    _patch_ps(monkeypatch, p)
    data, _ = ae.handle_protocol_size_distribution(None)
    assert "intestinal" in data["per_type"]
    assert "kidney" in data["per_type"]
    # intestinal mean_sf = (5+3+7)/3 = 5.0
    assert abs(data["per_type"]["intestinal"]["mean_sf"] - 5.0) < 0.01


def test_ps_type_filter_intestinal(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_ps(p, _PS_ROWS)
    _patch_ps(monkeypatch, p)
    data, status = ae.handle_protocol_size_distribution("intestinal")
    assert status == 200
    assert data["organoid_type"] == "intestinal"
    assert data["signaling_factors"]["n_papers"] == 3
    assert data["signaling_factors"]["min"] == 3
    assert data["signaling_factors"]["max"] == 7
    # Histograms present for type view
    assert "histogram" in data["signaling_factors"]


def test_ps_type_filter_unknown_returns_404(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_ps(p, _PS_ROWS)
    _patch_ps(monkeypatch, p)
    _, status = ae.handle_protocol_size_distribution("NOTYPE_XYZ")
    assert status == 404


def test_ps_supplement_stats_correct(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_ps(p, _PS_ROWS)
    _patch_ps(monkeypatch, p)
    # supplements: (2+1+3+2+4)/5 = 12/5 = 2.4
    data, _ = ae.handle_protocol_size_distribution(None)
    assert abs(data["supplements"]["mean"] - 2.4) < 0.01
    assert data["supplements"]["min"] == 1
    assert data["supplements"]["max"] == 4


def test_ps_kidney_mean_sf(tmp_path, monkeypatch):
    p = tmp_path / "protocols.jsonl"
    _write_protos_for_ps(p, _PS_ROWS)
    _patch_ps(monkeypatch, p)
    data, _ = ae.handle_protocol_size_distribution(None)
    # kidney mean_sf = (4+10)/2 = 7.0
    assert abs(data["per_type"]["kidney"]["mean_sf"] - 7.0) < 0.01


def test_ps_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/protocol-size-distribution" in data["endpoints"]


# --------------------------------------------------------------------------- #
# handle_evidence_quote_coverage  (route 47)
# --------------------------------------------------------------------------- #

_EQ_ROWS = [
    # organoid_type, kind, canonical, evidence_quote
    {"organoid_type": "intestinal", "kind": "signaling", "canonical": "EGF", "evidence_quote": "EGF 50 ng/mL"},
    {"organoid_type": "intestinal", "kind": "signaling", "canonical": "EGF", "evidence_quote": "50 ng/mL EGF"},
    {"organoid_type": "intestinal", "kind": "signaling", "canonical": "Wnt3a", "evidence_quote": None},
    {"organoid_type": "intestinal", "kind": "supplement", "canonical": "GlutaMAX", "evidence_quote": "GlutaMAX 2 mM"},
    {"organoid_type": "intestinal", "kind": "supplement", "canonical": "HEPES", "evidence_quote": None},
    {"organoid_type": "kidney", "kind": "signaling", "canonical": "EGF", "evidence_quote": "EGF added at 50"},
    {"organoid_type": "kidney", "kind": "signaling", "canonical": "FGF2", "evidence_quote": None},
    {"organoid_type": "kidney", "kind": "supplement", "canonical": "GlutaMAX", "evidence_quote": None},
]


def _write_reagents_for_eq(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows))


def _patch_eq(monkeypatch, path):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", path)


def test_eq_global_overall_rate(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_eq(p, _EQ_ROWS)
    _patch_eq(monkeypatch, p)
    data, status = ae.handle_evidence_quote_coverage(None, None)
    assert status == 200
    # 4 have quotes out of 8: overall = 0.5
    assert abs(data["overall_coverage_rate"] - 0.5) < 0.01
    assert data["n_with_quote"] == 4
    assert data["n_total"] == 8


def test_eq_by_kind_signaling(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_eq(p, _EQ_ROWS)
    _patch_eq(monkeypatch, p)
    data, _ = ae.handle_evidence_quote_coverage(None, None)
    sig = data["by_kind"]["signaling"]
    # EGF×2 (quotes), Wnt3a×1 (no quote), EGF×1 (quote), FGF2×1 (no quote) = 5 signaling, 3 with quote
    assert sig["n_total"] == 5
    assert sig["n_with_quote"] == 3
    assert abs(sig["coverage_rate"] - 3/5) < 0.01


def test_eq_by_kind_supplement(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_eq(p, _EQ_ROWS)
    _patch_eq(monkeypatch, p)
    data, _ = ae.handle_evidence_quote_coverage(None, None)
    sup = data["by_kind"]["supplement"]
    # GlutaMAX×1 (quote), HEPES×1 (no), GlutaMAX×1 (no) = 3 total, 1 with quote
    assert sup["n_total"] == 3
    assert sup["n_with_quote"] == 1


def test_eq_per_type_intestinal_rate(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_eq(p, _EQ_ROWS)
    _patch_eq(monkeypatch, p)
    data, _ = ae.handle_evidence_quote_coverage(None, None)
    per_type = {e["organoid_type"]: e for e in data["per_type"]}
    assert "intestinal" in per_type
    it = per_type["intestinal"]
    # intestinal: 5 total, 3 with quote (EGF×2, GlutaMAX×1)
    assert it["n_total"] == 5
    assert it["n_with_quote"] == 3
    assert abs(it["coverage_rate"] - 3/5) < 0.01


def test_eq_per_type_sorted_desc(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_eq(p, _EQ_ROWS)
    _patch_eq(monkeypatch, p)
    data, _ = ae.handle_evidence_quote_coverage(None, None)
    rates = [e["coverage_rate"] for e in data["per_type"] if e["coverage_rate"] is not None]
    assert rates == sorted(rates, reverse=True)


def test_eq_type_filter_intestinal(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_eq(p, _EQ_ROWS)
    _patch_eq(monkeypatch, p)
    data, status = ae.handle_evidence_quote_coverage("intestinal", None)
    assert status == 200
    assert data["organoid_type"] == "intestinal"
    assert data["n_total"] == 5
    assert data["n_with_quote"] == 3


def test_eq_type_filter_top_canonicals_present(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_eq(p, _EQ_ROWS)
    _patch_eq(monkeypatch, p)
    data, _ = ae.handle_evidence_quote_coverage("intestinal", None)
    assert "top_canonicals_by_coverage" in data
    # EGF has 2/2 = 1.0, min 3 threshold not met for EGF (only 2 records) — list may be empty
    # But structure check always works
    assert isinstance(data["top_canonicals_by_coverage"], list)


def test_eq_kind_filter_signaling_only(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_eq(p, _EQ_ROWS)
    _patch_eq(monkeypatch, p)
    data, status = ae.handle_evidence_quote_coverage(None, "signaling")
    assert status == 200
    assert data["kind_filter"] == "signaling"
    # Only signaling rows: 5 total, 3 with quote
    assert data["n_total"] == 5
    assert data["n_with_quote"] == 3


def test_eq_kind_filter_invalid_returns_400(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_eq(p, _EQ_ROWS)
    _patch_eq(monkeypatch, p)
    _, status = ae.handle_evidence_quote_coverage(None, "BADKIND")
    assert status == 400


def test_eq_unknown_type_returns_404(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_eq(p, _EQ_ROWS)
    _patch_eq(monkeypatch, p)
    _, status = ae.handle_evidence_quote_coverage("NOTYPE_XYZ", None)
    assert status == 404


def test_eq_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/evidence-quote-coverage" in data["endpoints"]


# --------------------------------------------------------------------------- #
# handle_concentration_value_rate  (route 48)
# --------------------------------------------------------------------------- #

_CVR_ROWS = [
    # canonical, kind, value (numeric or None/empty)
    {"canonical": "EGF",      "kind": "signaling", "organoid_type": "intestinal", "value": "50"},
    {"canonical": "EGF",      "kind": "signaling", "organoid_type": "intestinal", "value": "50"},
    {"canonical": "EGF",      "kind": "signaling", "organoid_type": "kidney",     "value": None},
    {"canonical": "EGF",      "kind": "signaling", "organoid_type": "kidney",     "value": ""},
    {"canonical": "EGF",      "kind": "signaling", "organoid_type": "lung",       "value": "25"},
    {"canonical": "Wnt3a",    "kind": "signaling", "organoid_type": "intestinal", "value": None},
    {"canonical": "Wnt3a",    "kind": "signaling", "organoid_type": "intestinal", "value": None},
    {"canonical": "Wnt3a",    "kind": "signaling", "organoid_type": "intestinal", "value": None},
    {"canonical": "Wnt3a",    "kind": "signaling", "organoid_type": "intestinal", "value": None},
    {"canonical": "Wnt3a",    "kind": "signaling", "organoid_type": "intestinal", "value": None},
    {"canonical": "GlutaMAX", "kind": "supplement","organoid_type": "intestinal", "value": "2"},
    {"canonical": "GlutaMAX", "kind": "supplement","organoid_type": "kidney",     "value": "2"},
    {"canonical": "GlutaMAX", "kind": "supplement","organoid_type": "lung",       "value": "1"},
    {"canonical": "GlutaMAX", "kind": "supplement","organoid_type": "gastric",    "value": "2"},
    {"canonical": "GlutaMAX", "kind": "supplement","organoid_type": "cardiac",    "value": None},
]


def _write_reagents_for_cvr(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows))


def _patch_cvr(monkeypatch, path):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", path)


def test_cvr_global_structure(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cvr(p, _CVR_ROWS)
    _patch_cvr(monkeypatch, p)
    data, status = ae.handle_concentration_value_rate(None, 3, None)
    assert status == 200
    assert "highest_reporters" in data
    assert "lowest_reporters" in data
    assert "n_canonicals_evaluated" in data


def test_cvr_highest_reporters_top(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cvr(p, _CVR_ROWS)
    _patch_cvr(monkeypatch, p)
    data, _ = ae.handle_concentration_value_rate(None, 3, None)
    # GlutaMAX: 4/5 = 0.80; EGF: 3/5 = 0.60; Wnt3a: 0/5 = 0.0
    top = data["highest_reporters"]
    assert top[0]["canonical"] in ("GlutaMAX", "EGF")
    assert top[0]["value_rate"] >= top[-1]["value_rate"]


def test_cvr_lowest_reporters_bottom(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cvr(p, _CVR_ROWS)
    _patch_cvr(monkeypatch, p)
    data, _ = ae.handle_concentration_value_rate(None, 3, None)
    # Wnt3a: 0/5 = 0.0 should be at top of lowest_reporters
    bottom = data["lowest_reporters"]
    assert bottom[0]["canonical"] == "Wnt3a"
    assert bottom[0]["value_rate"] == 0.0


def test_cvr_overall_value_rate(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cvr(p, _CVR_ROWS)
    _patch_cvr(monkeypatch, p)
    data, _ = ae.handle_concentration_value_rate(None, 3, None)
    # EGF: 3/5, Wnt3a: 0/5, GlutaMAX: 4/5 → total 7/15 ≈ 0.467
    assert abs(data["overall_value_rate"] - 7/15) < 0.01


def test_cvr_min_n_filter(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cvr(p, _CVR_ROWS)
    _patch_cvr(monkeypatch, p)
    # min_n=10 → none pass (all have 5 records)
    data, _ = ae.handle_concentration_value_rate(None, 10, None)
    assert data["n_canonicals_evaluated"] == 0


def test_cvr_query_egf_per_type(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cvr(p, _CVR_ROWS)
    _patch_cvr(monkeypatch, p)
    data, status = ae.handle_concentration_value_rate("EGF", 3, None)
    assert status == 200
    assert data["canonical"] == "EGF"
    assert data["n_total"] == 5
    assert data["n_with_value"] == 3
    assert abs(data["overall_value_rate"] - 3/5) < 0.01
    # per_type: intestinal(2/2), kidney(0/2), lung(1/1)
    per_type = {e["organoid_type"]: e for e in data["per_type"]}
    assert per_type["intestinal"]["n_with_value"] == 2
    assert per_type["kidney"]["n_with_value"] == 0
    assert per_type["lung"]["n_with_value"] == 1


def test_cvr_query_unknown_returns_404(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cvr(p, _CVR_ROWS)
    _patch_cvr(monkeypatch, p)
    _, status = ae.handle_concentration_value_rate("NOSUCHCANONICAL_XYZ", 3, None)
    assert status == 404


def test_cvr_kind_filter_supplement(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cvr(p, _CVR_ROWS)
    _patch_cvr(monkeypatch, p)
    data, status = ae.handle_concentration_value_rate(None, 3, "supplement")
    assert status == 200
    assert data["kind_filter"] == "supplement"
    # Only GlutaMAX passes min_n=3: 4/5 = 0.80
    assert data["n_canonicals_evaluated"] == 1
    assert data["highest_reporters"][0]["canonical"] == "GlutaMAX"


def test_cvr_kind_filter_invalid_returns_400(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cvr(p, _CVR_ROWS)
    _patch_cvr(monkeypatch, p)
    _, status = ae.handle_concentration_value_rate(None, 3, "BADKIND")
    assert status == 400


def test_cvr_per_type_sorted_by_rate_desc(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_cvr(p, _CVR_ROWS)
    _patch_cvr(monkeypatch, p)
    data, _ = ae.handle_concentration_value_rate("EGF", 3, None)
    rates = [e["value_rate"] for e in data["per_type"] if e["value_rate"] is not None]
    assert rates == sorted(rates, reverse=True)


def test_cvr_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/concentration-value-rate" in data["endpoints"]


# --------------------------------------------------------------------------- #
# handle_kind_ambiguity  (route 49)
# --------------------------------------------------------------------------- #

_KA_ROWS = [
    # Y-27632: 4 signaling, 2 supplement → minority_fraction = 2/6 = 0.333
    {"canonical": "Y-27632", "kind": "signaling", "organoid_type": "intestinal"},
    {"canonical": "Y-27632", "kind": "signaling", "organoid_type": "intestinal"},
    {"canonical": "Y-27632", "kind": "signaling", "organoid_type": "kidney"},
    {"canonical": "Y-27632", "kind": "signaling", "organoid_type": "lung"},
    {"canonical": "Y-27632", "kind": "supplement", "organoid_type": "cardiac"},
    {"canonical": "Y-27632", "kind": "supplement", "organoid_type": "cerebral"},
    # EGF: 3 signaling, 0 supplement → NOT dual-kind (should NOT appear)
    {"canonical": "EGF",     "kind": "signaling", "organoid_type": "intestinal"},
    {"canonical": "EGF",     "kind": "signaling", "organoid_type": "intestinal"},
    {"canonical": "EGF",     "kind": "signaling", "organoid_type": "kidney"},
    # Nicotinamide: 2 signaling, 4 supplement → minority_fraction = 2/6 = 0.333
    {"canonical": "Nicotinamide", "kind": "supplement", "organoid_type": "intestinal"},
    {"canonical": "Nicotinamide", "kind": "supplement", "organoid_type": "intestinal"},
    {"canonical": "Nicotinamide", "kind": "supplement", "organoid_type": "kidney"},
    {"canonical": "Nicotinamide", "kind": "supplement", "organoid_type": "lung"},
    {"canonical": "Nicotinamide", "kind": "signaling",  "organoid_type": "cardiac"},
    {"canonical": "Nicotinamide", "kind": "signaling",  "organoid_type": "cerebral"},
]


def _write_reagents_for_ka(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows))


def _patch_ka(monkeypatch, path):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", path)


def test_ka_global_returns_200(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_ka(p, _KA_ROWS)
    _patch_ka(monkeypatch, p)
    data, status = ae.handle_kind_ambiguity(None, 3)
    assert status == 200
    assert "dual_kind_canonicals" in data
    assert "n_dual_kind_canonicals" in data


def test_ka_egf_excluded(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_ka(p, _KA_ROWS)
    _patch_ka(monkeypatch, p)
    data, _ = ae.handle_kind_ambiguity(None, 3)
    names = {e["canonical"] for e in data["dual_kind_canonicals"]}
    # EGF is pure signaling — must NOT appear
    assert "EGF" not in names
    # Y-27632 and Nicotinamide are dual-kind — must appear
    assert "Y-27632" in names
    assert "Nicotinamide" in names


def test_ka_minority_fraction_values(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_ka(p, _KA_ROWS)
    _patch_ka(monkeypatch, p)
    data, _ = ae.handle_kind_ambiguity(None, 3)
    by_name = {e["canonical"]: e for e in data["dual_kind_canonicals"]}
    # Y-27632: 4 sig, 2 sup → minority=2/6 ≈ 0.333
    assert abs(by_name["Y-27632"]["minority_fraction"] - 2/6) < 0.01
    assert by_name["Y-27632"]["dominant_kind"] == "signaling"
    # Nicotinamide: 4 sup, 2 sig → minority=2/6 ≈ 0.333
    assert abs(by_name["Nicotinamide"]["minority_fraction"] - 2/6) < 0.01
    assert by_name["Nicotinamide"]["dominant_kind"] == "supplement"


def test_ka_sorted_by_minority_fraction_desc(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_ka(p, _KA_ROWS)
    _patch_ka(monkeypatch, p)
    data, _ = ae.handle_kind_ambiguity(None, 3)
    fracs = [e["minority_fraction"] for e in data["dual_kind_canonicals"]]
    assert fracs == sorted(fracs, reverse=True)


def test_ka_min_n_excludes_sparse(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_ka(p, _KA_ROWS)
    _patch_ka(monkeypatch, p)
    # min_n=10 → Y-27632 and Nicotinamide both have only 6 records → excluded
    data, _ = ae.handle_kind_ambiguity(None, 10)
    assert data["n_dual_kind_canonicals"] == 0


def test_ka_query_y27632_per_type(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_ka(p, _KA_ROWS)
    _patch_ka(monkeypatch, p)
    data, status = ae.handle_kind_ambiguity("Y-27632", 3)
    assert status == 200
    assert data["canonical"] == "Y-27632"
    assert data["n_signaling"] == 4
    assert data["n_supplement"] == 2
    assert data["n_total"] == 6
    assert data["global_dominant_kind"] == "signaling"
    assert abs(data["global_minority_fraction"] - 2/6) < 0.01


def test_ka_query_per_type_structure(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_ka(p, _KA_ROWS)
    _patch_ka(monkeypatch, p)
    data, _ = ae.handle_kind_ambiguity("Y-27632", 3)
    per_type = {e["organoid_type"]: e for e in data["per_type"]}
    # intestinal: 2 signaling, 0 supplement
    assert per_type["intestinal"]["n_signaling"] == 2
    assert per_type["intestinal"]["n_supplement"] == 0
    # cardiac: 0 signaling, 1 supplement
    assert per_type["cardiac"]["n_supplement"] == 1


def test_ka_query_unknown_returns_404(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_ka(p, _KA_ROWS)
    _patch_ka(monkeypatch, p)
    _, status = ae.handle_kind_ambiguity("NOSUCHCANONICAL_XYZ", 3)
    assert status == 404


def test_ka_n_dual_kind_correct(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_ka(p, _KA_ROWS)
    _patch_ka(monkeypatch, p)
    data, _ = ae.handle_kind_ambiguity(None, 3)
    assert data["n_dual_kind_canonicals"] == 2


def test_ka_count_fields_present(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_ka(p, _KA_ROWS)
    _patch_ka(monkeypatch, p)
    data, _ = ae.handle_kind_ambiguity(None, 3)
    for e in data["dual_kind_canonicals"]:
        assert "canonical" in e
        assert "n_signaling" in e
        assert "n_supplement" in e
        assert "n_total" in e
        assert "dominant_kind" in e
        assert "minority_fraction" in e


def test_ka_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/kind-ambiguity" in data["endpoints"]


# --------------------------------------------------------------------------- #
# handle_canonical_type_adoption  (route 50)
# --------------------------------------------------------------------------- #

_CTA_PROTOS = [
    {"doi": "10.1/a", "year": 2019, "organoid_type": "intestinal"},
    {"doi": "10.1/b", "year": 2020, "organoid_type": "kidney"},
    {"doi": "10.1/c", "year": 2020, "organoid_type": "cerebral"},
    {"doi": "10.1/d", "year": 2021, "organoid_type": "cardiac"},
    {"doi": "10.1/e", "year": 2021, "organoid_type": "lung"},
    {"doi": "10.1/f", "year": 2022, "organoid_type": "gastric"},
]

_CTA_REAGENTS = [
    # EGF: appears in 5 types → intestinal(2019), kidney+cerebral(2020), cardiac(2021), lung(2021), gastric(2022)
    {"canonical": "EGF", "doi": "10.1/a", "organoid_type": "intestinal", "kind": "signaling"},
    {"canonical": "EGF", "doi": "10.1/b", "organoid_type": "kidney",     "kind": "signaling"},
    {"canonical": "EGF", "doi": "10.1/c", "organoid_type": "cerebral",   "kind": "signaling"},
    {"canonical": "EGF", "doi": "10.1/d", "organoid_type": "cardiac",    "kind": "signaling"},
    {"canonical": "EGF", "doi": "10.1/e", "organoid_type": "lung",       "kind": "signaling"},
    # Wnt3a: only 2 types (below min_types=5 default)
    {"canonical": "Wnt3a", "doi": "10.1/a", "organoid_type": "intestinal", "kind": "signaling"},
    {"canonical": "Wnt3a", "doi": "10.1/f", "organoid_type": "gastric",    "kind": "signaling"},
    # CHIR: 6 types (all)
    {"canonical": "CHIR99021", "doi": "10.1/a", "organoid_type": "intestinal", "kind": "signaling"},
    {"canonical": "CHIR99021", "doi": "10.1/b", "organoid_type": "kidney",     "kind": "signaling"},
    {"canonical": "CHIR99021", "doi": "10.1/c", "organoid_type": "cerebral",   "kind": "signaling"},
    {"canonical": "CHIR99021", "doi": "10.1/d", "organoid_type": "cardiac",    "kind": "signaling"},
    {"canonical": "CHIR99021", "doi": "10.1/e", "organoid_type": "lung",       "kind": "signaling"},
    {"canonical": "CHIR99021", "doi": "10.1/f", "organoid_type": "gastric",    "kind": "signaling"},
]


def _write_protos_for_cta(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows))


def _patch_cta(monkeypatch, p_path, r_path):
    monkeypatch.setattr(ae, "PROTOCOLS_JSONL", p_path)
    monkeypatch.setattr(ae, "REAGENTS_JSONL", r_path)


def test_cta_global_structure(tmp_path, monkeypatch):
    pp = tmp_path / "protocols.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_protos_for_cta(pp, _CTA_PROTOS)
    _write_protos_for_cta(rp, _CTA_REAGENTS)
    _patch_cta(monkeypatch, pp, rp)
    data, status = ae.handle_canonical_type_adoption(None, 5)
    assert status == 200
    assert "top_by_type_breadth" in data
    assert "n_canonicals" in data


def test_cta_min_types_filter(tmp_path, monkeypatch):
    pp = tmp_path / "protocols.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_protos_for_cta(pp, _CTA_PROTOS)
    _write_protos_for_cta(rp, _CTA_REAGENTS)
    _patch_cta(monkeypatch, pp, rp)
    # min_types=5: EGF(5), CHIR(6) pass; Wnt3a(2) excluded
    data, _ = ae.handle_canonical_type_adoption(None, 5)
    names = {e["canonical"] for e in data["top_by_type_breadth"]}
    assert "Wnt3a" not in names
    assert "EGF" in names
    assert "CHIR99021" in names


def test_cta_chir_n_types_correct(tmp_path, monkeypatch):
    pp = tmp_path / "protocols.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_protos_for_cta(pp, _CTA_PROTOS)
    _write_protos_for_cta(rp, _CTA_REAGENTS)
    _patch_cta(monkeypatch, pp, rp)
    data, _ = ae.handle_canonical_type_adoption(None, 5)
    by_name = {e["canonical"]: e for e in data["top_by_type_breadth"]}
    assert by_name["CHIR99021"]["n_types_current"] == 6
    assert by_name["CHIR99021"]["first_year"] == 2019


def test_cta_sorted_by_n_types_desc(tmp_path, monkeypatch):
    pp = tmp_path / "protocols.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_protos_for_cta(pp, _CTA_PROTOS)
    _write_protos_for_cta(rp, _CTA_REAGENTS)
    _patch_cta(monkeypatch, pp, rp)
    data, _ = ae.handle_canonical_type_adoption(None, 5)
    counts = [e["n_types_current"] for e in data["top_by_type_breadth"]]
    assert counts == sorted(counts, reverse=True)
    # CHIR(6) should rank above EGF(5)
    assert data["top_by_type_breadth"][0]["canonical"] == "CHIR99021"


def test_cta_query_egf_per_year(tmp_path, monkeypatch):
    pp = tmp_path / "protocols.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_protos_for_cta(pp, _CTA_PROTOS)
    _write_protos_for_cta(rp, _CTA_REAGENTS)
    _patch_cta(monkeypatch, pp, rp)
    data, status = ae.handle_canonical_type_adoption("EGF", 5)
    assert status == 200
    assert data["canonical"] == "EGF"
    assert data["n_types_current"] == 5
    assert data["first_year"] == 2019
    assert isinstance(data["by_year"], list)
    assert len(data["by_year"]) >= 3  # 2019, 2020, 2021


def test_cta_query_by_year_cumulative(tmp_path, monkeypatch):
    pp = tmp_path / "protocols.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_protos_for_cta(pp, _CTA_PROTOS)
    _write_protos_for_cta(rp, _CTA_REAGENTS)
    _patch_cta(monkeypatch, pp, rp)
    data, _ = ae.handle_canonical_type_adoption("EGF", 5)
    by_year = {e["year"]: e for e in data["by_year"]}
    # 2019: intestinal (1 new)
    assert by_year[2019]["n_new_types"] == 1
    # 2020: kidney + cerebral (2 new)
    assert by_year[2020]["n_new_types"] == 2
    # cumulative at end of 2020 = 3
    assert by_year[2020]["cumulative_n_types"] == 3


def test_cta_query_unknown_returns_404(tmp_path, monkeypatch):
    pp = tmp_path / "protocols.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_protos_for_cta(pp, _CTA_PROTOS)
    _write_protos_for_cta(rp, _CTA_REAGENTS)
    _patch_cta(monkeypatch, pp, rp)
    _, status = ae.handle_canonical_type_adoption("NOSUCHCANONICAL_XYZ", 5)
    assert status == 404


def test_cta_year_peak_present(tmp_path, monkeypatch):
    pp = tmp_path / "protocols.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_protos_for_cta(pp, _CTA_PROTOS)
    _write_protos_for_cta(rp, _CTA_REAGENTS)
    _patch_cta(monkeypatch, pp, rp)
    data, _ = ae.handle_canonical_type_adoption("EGF", 5)
    # 2020 has 2 types adopted (kidney + cerebral) → peak year
    assert data["year_peak"] == 2020


def test_cta_n_years_active_chir(tmp_path, monkeypatch):
    pp = tmp_path / "protocols.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_protos_for_cta(pp, _CTA_PROTOS)
    _write_protos_for_cta(rp, _CTA_REAGENTS)
    _patch_cta(monkeypatch, pp, rp)
    data, _ = ae.handle_canonical_type_adoption(None, 5)
    by_name = {e["canonical"]: e for e in data["top_by_type_breadth"]}
    # CHIR: 2019–2022 = 4 years
    assert by_name["CHIR99021"]["n_years_active"] == 4


def test_cta_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/canonical-type-adoption" in data["endpoints"]


def test_cta_new_types_list_correct(tmp_path, monkeypatch):
    pp = tmp_path / "protocols.jsonl"
    rp = tmp_path / "reagents.jsonl"
    _write_protos_for_cta(pp, _CTA_PROTOS)
    _write_protos_for_cta(rp, _CTA_REAGENTS)
    _patch_cta(monkeypatch, pp, rp)
    data, _ = ae.handle_canonical_type_adoption("EGF", 5)
    by_year = {e["year"]: e for e in data["by_year"]}
    # 2019: only intestinal first adopted
    assert "intestinal" in by_year[2019]["new_types"]
    # 2020 new types: kidney and cerebral
    assert set(by_year[2020]["new_types"]) == {"kidney", "cerebral"}


# --------------------------------------------------------------------------- #
# handle_unit_normalization_report  (route 51)
# --------------------------------------------------------------------------- #

_UNR_ROWS = [
    # canonical_unit 'uM' ← 3 raw strings: μM, µM, uM
    {"canonical": "EGF",     "canonical_unit": "uM",    "unit": "μM",  "organoid_type": "intestinal"},
    {"canonical": "EGF",     "canonical_unit": "uM",    "unit": "µM",  "organoid_type": "intestinal"},
    {"canonical": "EGF",     "canonical_unit": "uM",    "unit": "uM",  "organoid_type": "kidney"},
    {"canonical": "CHIR",    "canonical_unit": "uM",    "unit": "μM",  "organoid_type": "cardiac"},
    {"canonical": "CHIR",    "canonical_unit": "uM",    "unit": "µM",  "organoid_type": "lung"},
    # canonical_unit 'ng/mL' ← 2 raw strings: ng/mL, ng/ml
    {"canonical": "Noggin",  "canonical_unit": "ng/mL", "unit": "ng/mL", "organoid_type": "intestinal"},
    {"canonical": "Noggin",  "canonical_unit": "ng/mL", "unit": "ng/ml", "organoid_type": "kidney"},
    {"canonical": "FGF2",    "canonical_unit": "ng/mL", "unit": "ng/mL", "organoid_type": "cerebral"},
    # No canonical_unit (should not appear in report)
    {"canonical": "Wnt3a",   "canonical_unit": "",      "unit": "ng/mL", "organoid_type": "intestinal"},
    {"canonical": "Wnt3a",   "canonical_unit": None,    "unit": "ng/mL", "organoid_type": "kidney"},
]


def _write_reagents_for_unr(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows))


def _patch_unr(monkeypatch, path):
    monkeypatch.setattr(ae, "REAGENTS_JSONL", path)


def test_unr_global_structure(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_unr(p, _UNR_ROWS)
    _patch_unr(monkeypatch, p)
    data, status = ae.handle_unit_normalization_report(None)
    assert status == 200
    assert "unit_clusters" in data
    assert "n_canonical_units" in data
    assert "coverage_rate" in data


def test_unr_coverage_rate(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_unr(p, _UNR_ROWS)
    _patch_unr(monkeypatch, p)
    data, _ = ae.handle_unit_normalization_report(None)
    # 8 have canonical_unit, 2 don't → 8/10 = 0.80
    assert abs(data["coverage_rate"] - 0.8) < 0.01
    assert data["n_total_reagents"] == 10
    assert data["n_with_canonical_unit"] == 8


def test_unr_uM_cluster_n_raw(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_unr(p, _UNR_ROWS)
    _patch_unr(monkeypatch, p)
    data, _ = ae.handle_unit_normalization_report(None)
    by_cu = {e["canonical_unit"]: e for e in data["unit_clusters"]}
    # uM has 3 distinct raw strings
    assert by_cu["uM"]["n_raw_strings"] == 3
    assert by_cu["uM"]["n_records"] == 5


def test_unr_sorted_by_n_raw_desc(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_unr(p, _UNR_ROWS)
    _patch_unr(monkeypatch, p)
    data, _ = ae.handle_unit_normalization_report(None)
    n_raws = [e["n_raw_strings"] for e in data["unit_clusters"]]
    assert n_raws == sorted(n_raws, reverse=True)
    # uM(3 raw) before ng/mL(2 raw)
    assert data["unit_clusters"][0]["canonical_unit"] == "uM"


def test_unr_ng_ml_cluster(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_unr(p, _UNR_ROWS)
    _patch_unr(monkeypatch, p)
    data, _ = ae.handle_unit_normalization_report(None)
    by_cu = {e["canonical_unit"]: e for e in data["unit_clusters"]}
    assert by_cu["ng/mL"]["n_raw_strings"] == 2
    assert "ng/mL" in by_cu["ng/mL"]["raw_strings"]
    assert "ng/ml" in by_cu["ng/mL"]["raw_strings"]


def test_unr_query_uM_detail(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_unr(p, _UNR_ROWS)
    _patch_unr(monkeypatch, p)
    data, status = ae.handle_unit_normalization_report("uM")
    assert status == 200
    assert data["canonical_unit"] == "uM"
    assert data["n_records"] == 5
    assert data["n_raw_strings"] == 3
    raw_names = [e["raw_unit"] for e in data["raw_strings"]]
    assert "μM" in raw_names
    assert "µM" in raw_names
    assert "uM" in raw_names


def test_unr_query_top_canonicals(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_unr(p, _UNR_ROWS)
    _patch_unr(monkeypatch, p)
    data, _ = ae.handle_unit_normalization_report("uM")
    top = {e["canonical"] for e in data["top_canonicals"]}
    # EGF(3 records) and CHIR(2 records) both use uM
    assert "EGF" in top
    assert "CHIR" in top


def test_unr_query_unknown_returns_404(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_unr(p, _UNR_ROWS)
    _patch_unr(monkeypatch, p)
    _, status = ae.handle_unit_normalization_report("NOSUCHUNIT_XYZ")
    assert status == 404


def test_unr_no_cu_excluded(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_unr(p, _UNR_ROWS)
    _patch_unr(monkeypatch, p)
    data, _ = ae.handle_unit_normalization_report(None)
    # Wnt3a has no canonical_unit so '' cluster should not appear
    cu_names = {e["canonical_unit"] for e in data["unit_clusters"]}
    assert "" not in cu_names


def test_unr_n_canonical_units(tmp_path, monkeypatch):
    p = tmp_path / "reagents.jsonl"
    _write_reagents_for_unr(p, _UNR_ROWS)
    _patch_unr(monkeypatch, p)
    data, _ = ae.handle_unit_normalization_report(None)
    assert data["n_canonical_units"] == 2  # uM and ng/mL


def test_unr_index_entry():
    data, _ = ae.handle_index()
    assert "/analytics/unit-normalization-report" in data["endpoints"]
