"""Tests for pipeline/aggregate_silver_gold.py — silver-gold adjudication aggregation.

Guards the error-taxonomy classifier and the end-to-end aggregation (precision, recall
miss bucketing, verdict tally, malformed-file tolerance). Offline: synthetic silver JSON
files in tmp_path, with SILVER/OUT redirected via monkeypatch.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import aggregate_silver_gold as ag  # noqa: E402


def test_classify_buckets():
    assert ag.classify({"field": "cell_type", "source_says": "hESC", "extracted": "iPSC"}) \
        == "cell_type_ESC_vs_iPSC"
    assert ag.classify({"field": "dose", "source_says": "absent in source", "extracted": "5"}) \
        == "fabrication"
    assert ag.classify({"field": "medium", "source_says": "DMEM", "extracted": "RPMI"}) \
        == "media_conflation"
    assert ag.classify({"field": "species", "source_says": "mouse", "extracted": "human"}) \
        == "species"
    assert ag.classify({"field": "temperature", "source_says": "37C", "extracted": "38C"}) \
        == "other_value_unit_name"


def test_classify_precedence_cell_type_beats_media():
    """An entry mentioning both a cell type and a medium classifies as cell-type
    (ESC/iPSC is checked before media), guarding the ordered if-chain."""
    e = {"field": "cell line + medium", "source_says": "iPSC grown in mTeSR", "extracted": "hESC"}
    assert ag.classify(e) == "cell_type_ESC_vs_iPSC"


def _write(d: Path, name: str, obj):
    (d / name).write_text(json.dumps(obj))


def test_main_aggregates_precision_recall_and_taxonomy(monkeypatch, tmp_path, capsys):
    silver = tmp_path / "silver"
    silver.mkdir()
    out = tmp_path / "out" / "silver_gold_summary.json"
    monkeypatch.setattr(ag, "REPO", tmp_path)   # so OUT.relative_to(REPO) works under tmp
    monkeypatch.setattr(ag, "SILVER", silver)
    monkeypatch.setattr(ag, "OUT", out)

    _write(silver, "PMC1.json", {
        "pmcid": "PMC1", "multimodal": True, "n_fields_checked": 10, "n_correct": 9,
        "verdict": "pass",
        "incorrect": [{"field": "cell", "source_says": "hESC", "extracted": "iPSC"}],
        "recall_misses": [{"source_loc": "Table 2"}, {"source_loc": "Figure 3 schematic"}],
    })
    _write(silver, "PMC2.json", {
        "pmcid": "PMC2", "multimodal": False, "n_fields_checked": 5, "n_correct": 5,
        "verdict": "pass", "incorrect": [],
        "recall_misses": [{"source_loc": "supplementary methods"}],
    })
    # malformed file must be skipped, not crash
    (silver / "bad.json").write_text("{ not valid json")

    ag.main()

    summary = json.loads(out.read_text())
    assert summary["n_papers"] == 2
    assert summary["n_multimodal"] == 1
    assert summary["n_fields_checked"] == 15
    assert summary["n_correct"] == 14
    assert summary["field_precision"] == round(14 / 15, 4)
    assert summary["n_incorrect"] == 1
    assert summary["recall_misses_total"] == 3
    assert summary["recall_misses_per_paper"] == 1.5
    assert summary["recall_miss_location"] == {"table": 1, "figure": 1, "supplementary": 1}
    assert summary["verdicts"] == {"pass": 2}
    assert summary["correctness_error_taxonomy"] == {"cell_type_ESC_vs_iPSC": 1}
    assert summary["papers"] == ["PMC1", "PMC2"]


def test_main_empty_dir_yields_null_precision(monkeypatch, tmp_path):
    """No silver files → zero papers, null precision, no crash (fixed in #171)."""
    silver = tmp_path / "silver"
    silver.mkdir()
    out = tmp_path / "out" / "summary.json"
    monkeypatch.setattr(ag, "REPO", tmp_path)
    monkeypatch.setattr(ag, "SILVER", silver)
    monkeypatch.setattr(ag, "OUT", out)
    ag.main()
    summary = json.loads(out.read_text())
    assert summary["n_papers"] == 0
    assert summary["field_precision"] is None
    assert summary["recall_misses_per_paper"] is None
