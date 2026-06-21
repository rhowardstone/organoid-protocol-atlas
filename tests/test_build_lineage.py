"""
Offline tests for build_lineage pure graph logic.
No filesystem access, no network calls.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import build_lineage as bl


# --------------------------------------------------------------------------- #
# build_graph
# --------------------------------------------------------------------------- #

def _mod(src, cited, change="changed X", pmcid="PMC1", otype="intestinal"):
    return {"source_doi": src, "cited_doi": cited, "change_description": change,
            "pmcid": pmcid, "organoid_type": otype}


DOI_A = "10.1038/nature07935"  # seminal
DOI_B = "10.1016/j.cell.2013"  # derived once
DOI_C = "10.1016/j.stem.2020"  # derived twice


def test_build_graph_basic():
    mods = [_mod(DOI_B, DOI_A, "added Wnt3a"), _mod(DOI_C, DOI_B, "removed Noggin")]
    g = bl.build_graph(mods)
    assert g["n_nodes"] == 3
    assert g["n_edges"] == 2


def test_build_graph_roots():
    """Root = has outgoing but no incoming edges."""
    mods = [_mod(DOI_B, DOI_A), _mod(DOI_C, DOI_B)]
    g = bl.build_graph(mods)
    assert DOI_A in g["roots"]
    assert DOI_B not in g["roots"]
    assert DOI_C not in g["roots"]


def test_build_graph_edge_direction():
    """Edge goes from cited → source (ancestral → derived)."""
    mods = [_mod(DOI_B, DOI_A, "EGF increase")]
    g = bl.build_graph(mods)
    assert g["edges"][0]["from"] == DOI_A
    assert g["edges"][0]["to"] == DOI_B


def test_build_graph_deduplicates_edges():
    """Same (from, to, change[:60]) pair → single edge."""
    mods = [_mod(DOI_B, DOI_A, "added Wnt"), _mod(DOI_B, DOI_A, "added Wnt")]
    g = bl.build_graph(mods)
    assert g["n_edges"] == 1


def test_build_graph_skips_missing_endpoints():
    """If source_doi or cited_doi is empty → skip."""
    mods = [
        {"source_doi": DOI_B, "cited_doi": "", "change_description": "x", "pmcid": "", "organoid_type": ""},
        {"source_doi": "", "cited_doi": DOI_A, "change_description": "x", "pmcid": "", "organoid_type": ""},
    ]
    g = bl.build_graph(mods)
    assert g["n_edges"] == 0
    assert g["n_nodes"] == 0


def test_build_graph_empty():
    g = bl.build_graph([])
    assert g["n_nodes"] == 0
    assert g["n_edges"] == 0
    assert g["roots"] == []


def test_build_graph_n_in_n_out():
    """Check in/out degree tracking."""
    mods = [_mod(DOI_B, DOI_A), _mod(DOI_C, DOI_A)]
    g = bl.build_graph(mods)
    node_map = {n["doi"]: n for n in g["nodes"]}
    assert node_map[DOI_A]["n_out"] == 2
    assert node_map[DOI_A]["n_in"] == 0
    assert node_map[DOI_B]["n_in"] == 1
    assert node_map[DOI_C]["n_in"] == 1


def test_build_graph_organoid_types_aggregated():
    """Multiple organoid types referencing the same DOI → set aggregation."""
    mods = [
        _mod(DOI_B, DOI_A, otype="intestinal"),
        _mod(DOI_C, DOI_A, otype="cerebral"),
    ]
    g = bl.build_graph(mods)
    node_map = {n["doi"]: n for n in g["nodes"]}
    types = set(node_map[DOI_A]["organoid_types"])
    assert "intestinal" in types
    assert "cerebral" in types


# --------------------------------------------------------------------------- #
# subgraph_from_root
# --------------------------------------------------------------------------- #

def test_subgraph_from_root():
    mods = [_mod(DOI_B, DOI_A), _mod(DOI_C, DOI_B)]
    g = bl.build_graph(mods)
    sub = bl.subgraph_from_root(g, DOI_A)
    # Should include all 3 nodes reachable from DOI_A
    dois = {n["doi"] for n in sub["nodes"]}
    assert DOI_A in dois and DOI_B in dois and DOI_C in dois


def test_subgraph_excludes_unreachable():
    DOI_D = "10.1/d"
    mods = [
        _mod(DOI_B, DOI_A),   # lineage 1: A→B
        _mod(DOI_D, DOI_C),   # lineage 2: C→D (separate)
    ]
    g = bl.build_graph(mods)
    sub = bl.subgraph_from_root(g, DOI_A)
    dois = {n["doi"] for n in sub["nodes"]}
    assert DOI_C not in dois
    assert DOI_D not in dois


def test_subgraph_single_node():
    mods = [_mod(DOI_B, DOI_A)]
    g = bl.build_graph(mods)
    # Subgraph from a leaf (no outgoing)
    sub = bl.subgraph_from_root(g, DOI_B)
    assert sub["n_nodes"] == 1
    assert sub["n_edges"] == 0


# --------------------------------------------------------------------------- #
# to_dot
# --------------------------------------------------------------------------- #

def test_to_dot_contains_edges():
    mods = [_mod(DOI_B, DOI_A, "added EGF")]
    g = bl.build_graph(mods)
    dot = bl.to_dot(g)
    assert "->" in dot
    assert "added EGF" in dot


def test_to_dot_starts_with_digraph():
    dot = bl.to_dot({"nodes": [], "edges": []})
    assert dot.startswith("digraph")


# --------------------------------------------------------------------------- #
# load_all_modifications — filesystem patching
# --------------------------------------------------------------------------- #

def test_load_from_local_predictions(tmp_path, monkeypatch):
    pred_dir = tmp_path / "predictions"
    pred_dir.mkdir()
    proto = {
        "source_doi": "10.1/src",
        "organoid_type": "intestinal",
        "modifications": [
            {"cited_doi": "10.1/base", "change_description": "replaced Noggin"},
        ],
    }
    (pred_dir / "PMC123.json").write_text(json.dumps(proto))
    monkeypatch.setattr(bl, "PRED_DIR", pred_dir)

    recs = bl._load_from_local_predictions()
    assert len(recs) == 1
    assert recs[0]["source_doi"] == "10.1/src"
    assert recs[0]["cited_doi"] == "10.1/base"


def test_load_deduplication(tmp_path, monkeypatch):
    pred_dir = tmp_path / "predictions"
    pred_dir.mkdir()
    proto = {
        "source_doi": "10.1/src",
        "organoid_type": "intestinal",
        "modifications": [{"cited_doi": "10.1/base", "change_description": "changed X"}],
    }
    (pred_dir / "PMC1.json").write_text(json.dumps(proto))
    monkeypatch.setattr(bl, "PRED_DIR", pred_dir)

    # Summary with same record
    summary = {"rows": [{
        "pmcid": "PMC1", "doi": "10.1/src", "organoid_type": "intestinal",
        "modifications": [{"cited_doi": "10.1/base", "change_description": "changed X"}],
    }]}
    sp = tmp_path / "sum.json"
    sp.write_text(json.dumps(summary))
    monkeypatch.setattr(bl, "SUMMARY_PATH", sp)

    recs = bl.load_all_modifications()
    assert len(recs) == 1
