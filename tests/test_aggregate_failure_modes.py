"""
Offline tests for aggregate_failure_modes pure logic.
No filesystem access, no model downloads.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import aggregate_failure_modes as afm


# --------------------------------------------------------------------------- #
# assign_cluster
# --------------------------------------------------------------------------- #

CLUSTERS = afm.KEYWORD_CLUSTERS


def test_assign_cluster_matrix():
    labels = afm.assign_cluster("organoids fail when Matrigel does not solidify", CLUSTERS)
    assert "matrix_gelation" in labels


def test_assign_cluster_contamination():
    labels = afm.assign_cluster("bacterial contamination kills culture", CLUSTERS)
    assert "contamination" in labels


def test_assign_cluster_multiple():
    labels = afm.assign_cluster(
        "organoids collapse due to Matrigel concentration issues", CLUSTERS
    )
    # Should match both organoid_collapse and concentration_critical (and matrix_gelation)
    assert len(labels) >= 2


def test_assign_cluster_other():
    labels = afm.assign_cluster("unclassified random failure event", CLUSTERS)
    assert labels == ["other"]


def test_assign_cluster_case_insensitive():
    labels = afm.assign_cluster("MATRIGEL not polymerizing", CLUSTERS)
    assert "matrix_gelation" in labels


def test_assign_cluster_empty_string():
    labels = afm.assign_cluster("", CLUSTERS)
    assert labels == ["other"]


def test_assign_cluster_growth_arrest():
    labels = afm.assign_cluster("cells stop growing after passage 5", CLUSTERS)
    assert "growth_arrest" in labels


# --------------------------------------------------------------------------- #
# aggregate_failure_modes
# --------------------------------------------------------------------------- #

def _rec(pmcid, otype, desc, condition=None):
    return {"pmcid": pmcid, "organoid_type": otype, "description": desc,
            "condition": condition, "source_doi": f"10.0/{pmcid}"}


def test_aggregate_groups_by_type():
    records = [
        _rec("PMC1", "intestinal", "Matrigel not solidifying"),
        _rec("PMC2", "intestinal", "bacterial contamination"),
        _rec("PMC3", "cerebral",   "organoids collapse"),
    ]
    result = afm.aggregate_failure_modes(records, CLUSTERS)
    assert "intestinal" in result["by_organoid_type"]
    assert "cerebral" in result["by_organoid_type"]
    assert result["by_organoid_type"]["intestinal"]["total_failure_modes"] == 2
    assert result["by_organoid_type"]["cerebral"]["total_failure_modes"] == 1


def test_aggregate_total_count():
    records = [_rec(f"PMC{i}", "intestinal", "Matrigel issue") for i in range(5)]
    result = afm.aggregate_failure_modes(records, CLUSTERS)
    assert result["total_failure_modes"] == 5


def test_aggregate_global_ranking_sorted():
    records = [
        _rec("PMC1", "intestinal", "Matrigel not polymerizing"),
        _rec("PMC2", "intestinal", "Matrigel concentration problem"),
        _rec("PMC3", "intestinal", "bacterial contamination"),
    ]
    result = afm.aggregate_failure_modes(records, CLUSTERS)
    ranking = result["global_cluster_ranking"]
    # matrix_gelation (2) should outrank contamination (1)
    counts = {c["cluster"]: c["count"] for c in ranking}
    assert counts.get("matrix_gelation", 0) >= counts.get("contamination", 0)


def test_aggregate_examples_capped_at_5():
    records = [_rec(f"PMC{i}", "intestinal", "Matrigel not solidifying") for i in range(10)]
    result = afm.aggregate_failure_modes(records, CLUSTERS)
    for c in result["by_organoid_type"]["intestinal"]["clusters"]:
        assert len(c["examples"]) <= 5


def test_aggregate_empty_records():
    result = afm.aggregate_failure_modes([], CLUSTERS)
    assert result["total_failure_modes"] == 0
    assert result["n_organoid_types"] == 0
    assert result["by_organoid_type"] == {}


def test_aggregate_skips_empty_descriptions():
    records = [
        _rec("PMC1", "intestinal", ""),
        _rec("PMC2", "intestinal", "Matrigel issue"),
    ]
    result = afm.aggregate_failure_modes(records, CLUSTERS)
    assert result["total_failure_modes"] == 1


def test_aggregate_n_organoid_types():
    records = [_rec(f"PMC{i}", ["intestinal", "cerebral", "hepatic"][i % 3], "failure") for i in range(9)]
    result = afm.aggregate_failure_modes(records, CLUSTERS)
    assert result["n_organoid_types"] == 3


# --------------------------------------------------------------------------- #
# load_all_failure_modes — filesystem patching
# --------------------------------------------------------------------------- #

def test_load_from_local_predictions(tmp_path, monkeypatch):
    pred_dir = tmp_path / "predictions" / "local"
    pred_dir.mkdir(parents=True)
    proto = {
        "source_doi": "10.1/test",
        "organoid_type": "intestinal",
        "failure_modes": [
            {"description": "Matrigel gelation failure", "condition": "if cold"},
        ],
    }
    (pred_dir / "PMC99.json").write_text(json.dumps(proto))
    monkeypatch.setattr(afm, "PRED_DIR", pred_dir)

    records = afm._load_from_local_predictions(None)
    assert len(records) == 1
    assert records[0]["pmcid"] == "PMC99"
    assert "Matrigel" in records[0]["description"]


def test_load_from_extraction_summary(tmp_path, monkeypatch):
    summary = {
        "rows": [
            {
                "pmcid": "PMC77",
                "doi": "10.1/pmc77",
                "organoid_type": "cerebral",
                "failure_modes": [
                    {"description": "contamination risk", "condition": None},
                ],
            }
        ]
    }
    sp = tmp_path / "extraction_summary.json"
    sp.write_text(json.dumps(summary))
    monkeypatch.setattr(afm, "SUMMARY_PATH", sp)

    records = afm._load_from_extraction_summary(None)
    assert len(records) == 1
    assert records[0]["pmcid"] == "PMC77"


def test_load_deduplicates_across_sources(tmp_path, monkeypatch):
    """Same (pmcid, description) from both local and summary → deduplicated."""
    pred_dir = tmp_path / "predictions"
    pred_dir.mkdir()
    proto = {
        "source_doi": "10.1/x",
        "organoid_type": "intestinal",
        "failure_modes": [{"description": "matrix failure"}],
    }
    (pred_dir / "PMC55.json").write_text(json.dumps(proto))
    monkeypatch.setattr(afm, "PRED_DIR", pred_dir)

    summary = {
        "rows": [{
            "pmcid": "PMC55", "doi": "10.1/x", "organoid_type": "intestinal",
            "failure_modes": [{"description": "matrix failure"}],
        }]
    }
    sp = tmp_path / "sum.json"
    sp.write_text(json.dumps(summary))
    monkeypatch.setattr(afm, "SUMMARY_PATH", sp)

    records = afm.load_all_failure_modes(None)
    assert len(records) == 1


def test_load_filter_by_organoid_type(tmp_path, monkeypatch):
    pred_dir = tmp_path / "predictions"
    pred_dir.mkdir()
    for pmcid, otype in [("PMC1", "intestinal"), ("PMC2", "cerebral")]:
        proto = {
            "source_doi": f"10.1/{pmcid}",
            "organoid_type": otype,
            "failure_modes": [{"description": "some failure"}],
        }
        (pred_dir / f"{pmcid}.json").write_text(json.dumps(proto))
    monkeypatch.setattr(afm, "PRED_DIR", pred_dir)
    monkeypatch.setattr(afm, "SUMMARY_PATH", tmp_path / "none.json")

    records = afm.load_all_failure_modes("intestinal")
    assert all(r["organoid_type"] == "intestinal" for r in records)
    assert len(records) == 1
