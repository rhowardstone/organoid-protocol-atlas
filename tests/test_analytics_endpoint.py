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
