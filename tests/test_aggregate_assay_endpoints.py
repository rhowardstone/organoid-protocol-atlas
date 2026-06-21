"""
Offline tests for aggregate_assay_endpoints pure logic.
No network, no real corpus reads.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import aggregate_assay_endpoints as aae


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _proto(
    pmcid="PMC001",
    organoid_type="intestinal",
    assay_endpoints="immunofluorescence · qPCR",
) -> dict:
    return {"pmcid": pmcid, "organoid_type": organoid_type, "assay_endpoints": assay_endpoints}


# --------------------------------------------------------------------------- #
# parse_assay_terms
# --------------------------------------------------------------------------- #

def test_parse_terms_bullet_sep():
    terms = aae.parse_assay_terms("immunofluorescence · qPCR")
    assert "immunofluorescence" in terms
    assert "qpcr" in terms

def test_parse_terms_comma_sep():
    terms = aae.parse_assay_terms("gene expression, flow cytometry")
    assert "gene expression" in terms
    assert "flow cytometry" in terms

def test_parse_terms_empty():
    assert aae.parse_assay_terms("") == []

def test_parse_terms_null():
    assert aae.parse_assay_terms(None) == []

def test_parse_terms_lowercased():
    terms = aae.parse_assay_terms("RNA Sequencing")
    assert "rna sequencing" in terms

def test_parse_terms_strips_whitespace():
    terms = aae.parse_assay_terms("  immunostaining  ")
    assert all(t == t.strip() for t in terms)


# --------------------------------------------------------------------------- #
# assign_clusters
# --------------------------------------------------------------------------- #

def test_assign_clusters_immunofluorescence():
    labels = aae.assign_clusters("immunofluorescence staining", aae.ASSAY_CLUSTERS)
    assert "immunostaining_IF_IHC" in labels

def test_assign_clusters_qpcr():
    labels = aae.assign_clusters("rt-qpcr", aae.ASSAY_CLUSTERS)
    assert "gene_expression_qPCR" in labels

def test_assign_clusters_rna_seq():
    labels = aae.assign_clusters("rna-seq", aae.ASSAY_CLUSTERS)
    assert "RNA_sequencing" in labels

def test_assign_clusters_facs():
    labels = aae.assign_clusters("flow cytometry", aae.ASSAY_CLUSTERS)
    assert "flow_cytometry_FACS" in labels

def test_assign_clusters_western():
    labels = aae.assign_clusters("western blot", aae.ASSAY_CLUSTERS)
    assert "western_blot" in labels

def test_assign_clusters_unknown_returns_other():
    labels = aae.assign_clusters("novel exotic assay xyz", aae.ASSAY_CLUSTERS)
    assert labels == ["other"]

def test_assign_clusters_multi_label():
    # "single-cell rna-seq" matches both RNA_sequencing and single_cell_analysis
    labels = aae.assign_clusters("single-cell rna-seq", aae.ASSAY_CLUSTERS)
    assert "RNA_sequencing" in labels
    assert "single_cell_analysis" in labels

def test_assign_clusters_case_insensitive():
    labels = aae.assign_clusters("Immunofluorescence", aae.ASSAY_CLUSTERS)
    assert "immunostaining_IF_IHC" in labels


# --------------------------------------------------------------------------- #
# aggregate_assay_endpoints
# --------------------------------------------------------------------------- #

def test_aggregate_empty():
    result = aae.aggregate_assay_endpoints([])
    assert result["n_total_papers"] == 0
    assert result["n_with_assay_endpoints"] == 0


def test_aggregate_skips_null_assays():
    protocols = [_proto(assay_endpoints="not_reported")]
    result = aae.aggregate_assay_endpoints(protocols)
    assert result["n_with_assay_endpoints"] == 0


def test_aggregate_counts_papers_with_assays():
    protocols = [
        _proto(pmcid="PMC001", assay_endpoints="immunofluorescence"),
        _proto(pmcid="PMC002", assay_endpoints=""),
        _proto(pmcid="PMC003", assay_endpoints="qPCR"),
    ]
    result = aae.aggregate_assay_endpoints(protocols)
    assert result["n_with_assay_endpoints"] == 2
    assert result["coverage_fraction"] == pytest.approx(2 / 3, abs=0.01)


def test_aggregate_by_type_fractions():
    protocols = [
        _proto(pmcid="PMC001", organoid_type="cardiac",
               assay_endpoints="immunofluorescence"),
        _proto(pmcid="PMC002", organoid_type="cardiac",
               assay_endpoints="immunofluorescence"),
        _proto(pmcid="PMC003", organoid_type="cardiac",
               assay_endpoints="gene expression"),
    ]
    result = aae.aggregate_assay_endpoints(protocols)
    cardiac = result["by_organoid_type"]["cardiac"]
    assert "immunostaining_IF_IHC" in cardiac
    assert cardiac["immunostaining_IF_IHC"]["n_papers"] == 2
    assert cardiac["immunostaining_IF_IHC"]["fraction"] == pytest.approx(2 / 3, abs=0.01)


def test_aggregate_cross_type_cluster():
    protocols = [
        _proto(pmcid="PMC001", organoid_type="cardiac",
               assay_endpoints="immunofluorescence"),
        _proto(pmcid="PMC002", organoid_type="intestinal",
               assay_endpoints="immunofluorescence"),
    ]
    result = aae.aggregate_assay_endpoints(protocols)
    cross = result["cross_type_cluster_usage"]
    assert "immunostaining_IF_IHC" in cross
    assert cross["immunostaining_IF_IHC"]["n_types"] == 2
    assert cross["immunostaining_IF_IHC"]["n_papers"] == 2


def test_aggregate_raw_top_terms():
    protocols = [
        _proto(pmcid="PMC001", assay_endpoints="immunofluorescence · qPCR"),
        _proto(pmcid="PMC002", assay_endpoints="immunofluorescence · western blot"),
    ]
    result = aae.aggregate_assay_endpoints(protocols)
    raw_terms = {r["term"]: r["count"] for r in result["raw_top_terms"]}
    assert raw_terms.get("immunofluorescence", 0) == 2


def test_aggregate_deduplicates_clusters_per_paper():
    # Same paper with two IF terms should only count once per cluster
    protocols = [
        _proto(pmcid="PMC001", organoid_type="cardiac",
               assay_endpoints="immunofluorescence · immunohistochemistry"),
    ]
    result = aae.aggregate_assay_endpoints(protocols)
    cardiac = result["by_organoid_type"]["cardiac"]
    assert cardiac["immunostaining_IF_IHC"]["n_papers"] == 1


def test_aggregate_multiple_types_isolated():
    protocols = [
        _proto(pmcid="PMC001", organoid_type="cardiac",
               assay_endpoints="immunofluorescence"),
        _proto(pmcid="PMC002", organoid_type="retinal",
               assay_endpoints="gene expression"),
    ]
    result = aae.aggregate_assay_endpoints(protocols)
    assert "cardiac" in result["by_organoid_type"]
    assert "retinal" in result["by_organoid_type"]
    # Each type should not contain the other's cluster
    assert "gene_expression_qPCR" not in result["by_organoid_type"]["cardiac"]


def test_aggregate_coverage_fraction():
    protocols = [
        _proto(pmcid="PMC001", assay_endpoints="qPCR"),
        _proto(pmcid="PMC002", assay_endpoints=None),
        _proto(pmcid="PMC003", assay_endpoints=""),
        _proto(pmcid="PMC004", assay_endpoints="immunofluorescence"),
    ]
    result = aae.aggregate_assay_endpoints(protocols)
    assert result["coverage_fraction"] == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# load_protocols
# --------------------------------------------------------------------------- #

def test_load_protocols_missing():
    result = aae.load_protocols(Path("/tmp/nonexistent_assay_agg_xyz.jsonl"))
    assert result == []

def test_load_protocols_reads_file():
    p = _proto()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps(p) + "\n")
        fname = Path(f.name)
    try:
        rows = aae.load_protocols(fname)
        assert len(rows) == 1
    finally:
        fname.unlink()
