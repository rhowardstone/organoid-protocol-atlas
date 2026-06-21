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
