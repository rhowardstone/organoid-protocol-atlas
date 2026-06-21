"""
Offline tests for compare_protocols pure diff logic.
No filesystem access, no model downloads, no network calls.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import compare_protocols as cp


# --------------------------------------------------------------------------- #
# diff_scalar_fields
# --------------------------------------------------------------------------- #

def test_scalar_diff_detects_change():
    a = {"organoid_type": "intestinal", "matrix": "Matrigel"}
    b = {"organoid_type": "cerebral",   "matrix": "Matrigel"}
    result = cp.diff_scalar_fields(a, b, ["organoid_type", "matrix"])
    assert "organoid_type" in result
    assert result["organoid_type"] == {"a": "intestinal", "b": "cerebral"}
    assert "matrix" not in result


def test_scalar_diff_no_change():
    a = {"organoid_type": "hepatic", "species": "human"}
    b = {"organoid_type": "hepatic", "species": "human"}
    assert cp.diff_scalar_fields(a, b, ["organoid_type", "species"]) == {}


def test_scalar_diff_none_vs_value():
    a = {"matrix": None}
    b = {"matrix": "Matrigel"}
    result = cp.diff_scalar_fields(a, b, ["matrix"])
    assert result["matrix"] == {"a": None, "b": "Matrigel"}


# --------------------------------------------------------------------------- #
# diff_reagent_lists
# --------------------------------------------------------------------------- #

def _reagent(name, canonical=None, value=None, unit=None, role=None):
    r = {"name": name, "canonical_name": canonical, "role": role}
    if value is not None:
        r["concentration"] = {"value": value, "unit": unit, "canonical_unit": unit, "raw": f"{value} {unit}"}
    return r


def test_reagent_diff_added():
    a = [_reagent("EGF", "EGF", 50, "ng/mL")]
    b = [_reagent("EGF", "EGF", 50, "ng/mL"), _reagent("Noggin", "Noggin", 100, "ng/mL")]
    result = cp.diff_reagent_lists(a, b)
    assert len(result["added_in_b"]) == 1
    assert result["added_in_b"][0]["name"] == "Noggin"
    assert result["removed_in_b"] == []


def test_reagent_diff_removed():
    a = [_reagent("EGF", "EGF", 50, "ng/mL"), _reagent("Noggin", "Noggin", 100, "ng/mL")]
    b = [_reagent("EGF", "EGF", 50, "ng/mL")]
    result = cp.diff_reagent_lists(a, b)
    assert len(result["removed_in_b"]) == 1
    assert result["removed_in_b"][0]["name"] == "Noggin"
    assert result["added_in_b"] == []


def test_reagent_concentration_change():
    a = [_reagent("EGF", "EGF", 50, "ng/mL")]
    b = [_reagent("EGF", "EGF", 100, "ng/mL")]
    result = cp.diff_reagent_lists(a, b)
    assert len(result["concentration_changed"]) == 1
    assert result["concentration_changed"][0]["a"]["value"] == 50
    assert result["concentration_changed"][0]["b"]["value"] == 100


def test_reagent_no_concentration_no_change():
    a = [_reagent("EGF", "EGF")]
    b = [_reagent("EGF", "EGF")]
    result = cp.diff_reagent_lists(a, b)
    assert result["concentration_changed"] == []


def test_reagent_uses_canonical_name_for_key():
    """Canonical name takes precedence over raw name for identity matching."""
    a = [{"name": "recombinant EGF", "canonical_name": "EGF", "concentration": None}]
    b = [{"name": "mouse EGF",       "canonical_name": "EGF", "concentration": None}]
    result = cp.diff_reagent_lists(a, b)
    # Same canonical → not added or removed
    assert result["added_in_b"] == []
    assert result["removed_in_b"] == []


# --------------------------------------------------------------------------- #
# diff_timeline
# --------------------------------------------------------------------------- #

def _stage(name, duration=None):
    return {"name": name, "duration": duration}


def test_timeline_added_stage():
    a = [_stage("expansion", 3)]
    b = [_stage("expansion", 3), _stage("maturation", 7)]
    result = cp.diff_timeline(a, b)
    assert len(result["added_in_b"]) == 1
    assert result["added_in_b"][0]["name"] == "maturation"


def test_timeline_removed_stage():
    a = [_stage("expansion", 3), _stage("maturation", 7)]
    b = [_stage("expansion", 3)]
    result = cp.diff_timeline(a, b)
    assert len(result["removed_in_b"]) == 1


def test_timeline_duration_changed():
    a = [_stage("expansion", 3)]
    b = [_stage("expansion", 5)]
    result = cp.diff_timeline(a, b)
    assert len(result["duration_changed"]) == 1
    assert result["duration_changed"][0]["a"] == 3
    assert result["duration_changed"][0]["b"] == 5


def test_timeline_empty_lists():
    result = cp.diff_timeline([], [])
    assert result["added_in_b"] == []
    assert result["removed_in_b"] == []
    assert result["duration_changed"] == []


# --------------------------------------------------------------------------- #
# diff_failure_modes
# --------------------------------------------------------------------------- #

def _fm(desc, condition=None):
    return {"description": desc, "condition": condition}


def test_failure_modes_added():
    a = [_fm("organoids collapse")]
    b = [_fm("organoids collapse"), _fm("matrix not set")]
    result = cp.diff_failure_modes(a, b)
    assert len(result["added_in_b"]) == 1
    assert result["added_in_b"][0]["description"] == "matrix not set"


def test_failure_modes_removed():
    a = [_fm("organoids collapse"), _fm("matrix not set")]
    b = [_fm("organoids collapse")]
    result = cp.diff_failure_modes(a, b)
    assert len(result["removed_in_b"]) == 1


def test_failure_modes_no_diff():
    a = [_fm("organoids collapse")]
    b = [_fm("organoids collapse")]
    result = cp.diff_failure_modes(a, b)
    assert result["added_in_b"] == []
    assert result["removed_in_b"] == []


# --------------------------------------------------------------------------- #
# diff_text_list
# --------------------------------------------------------------------------- #

def test_text_list_diff():
    a = ["Lgr5 expression", "crypt morphology"]
    b = ["Lgr5 expression", "scRNA-seq"]
    result = cp.diff_text_list(a, b, "endpoints")
    assert "scRNA-seq" in result["added_in_b"] or "scrna-seq" in result["added_in_b"]
    assert any("crypt morphology" in v or "crypt morphology" == v for v in result["removed_in_b"])


# --------------------------------------------------------------------------- #
# compare_protocols (integration)
# --------------------------------------------------------------------------- #

def _make_protocol(pmcid, organoid_type="intestinal", signaling=None, failure_modes=None):
    return {
        "source_doi": f"10.0000/{pmcid}",
        "organoid_type": organoid_type,
        "source_cells": {"species": "human", "cell_type": "adult_stem_cell"},
        "matrix": {"name": "Matrigel"},
        "base_media": {"name": "DMEM/F12"},
        "signaling_factors": signaling or [],
        "media_supplements": [],
        "small_molecules": [],
        "timeline": [],
        "failure_modes": failure_modes or [],
        "modifications": [],
        "assay_endpoints": [],
        "schema_version": "0.4",
    }


def test_compare_protocols_metadata_diff():
    pa = _make_protocol("PMC111", organoid_type="intestinal")
    pb = _make_protocol("PMC222", organoid_type="cerebral")
    result = cp.compare_protocols(pa, pb, "PMC111", "PMC222")
    assert "organoid_type" in result["metadata_diff"]


def test_compare_protocols_reagent_diff():
    pa = _make_protocol("PMC111", signaling=[_reagent("EGF", "EGF", 50, "ng/mL")])
    pb = _make_protocol("PMC222", signaling=[_reagent("EGF", "EGF", 100, "ng/mL")])
    result = cp.compare_protocols(pa, pb, "PMC111", "PMC222")
    assert len(result["signaling_factors_diff"]["concentration_changed"]) == 1


def test_compare_protocols_summary_counts():
    pa = _make_protocol("PMC111", signaling=[_reagent("EGF")], failure_modes=[_fm("fm1")])
    pb = _make_protocol("PMC222", signaling=[_reagent("EGF"), _reagent("Noggin")],
                        failure_modes=[_fm("fm1"), _fm("fm2")])
    result = cp.compare_protocols(pa, pb, "PMC111", "PMC222")
    s = result["summary"]
    assert s["signaling_factors_diff_added"] == 1
    assert s["failure_modes_added"] == 1
    assert s["total_differences"] >= 2


# --------------------------------------------------------------------------- #
# load_protocol — fallback to protocols.jsonl
# --------------------------------------------------------------------------- #

def test_load_protocol_falls_back_to_summary(tmp_path, monkeypatch):
    """If local prediction not found, loads from protocols.jsonl."""
    # Redirect PRED_DIR and PROTOCOLS_JSONL into tmp_path
    monkeypatch.setattr(cp, "PRED_DIR", tmp_path / "predictions")
    jsonl_path = tmp_path / "protocols.jsonl"
    jsonl_path.write_text(json.dumps({
        "pmcid": "PMC99999",
        "organoid_type": "hepatic",
        "matrix": "Matrigel",
    }) + "\n")
    monkeypatch.setattr(cp, "PROTOCOLS_JSONL", jsonl_path)

    rec = cp.load_protocol("PMC99999")
    assert rec["organoid_type"] == "hepatic"
    assert rec["_source"] == "public_summary"


def test_load_protocol_raises_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "PRED_DIR", tmp_path / "predictions")
    monkeypatch.setattr(cp, "PROTOCOLS_JSONL", tmp_path / "nonexistent.jsonl")
    with pytest.raises(FileNotFoundError):
        cp.load_protocol("PMCNOTREAL")


def test_load_protocol_prefers_local(tmp_path, monkeypatch):
    pred_dir = tmp_path / "predictions"
    pred_dir.mkdir()
    proto = {"source_doi": "10.1/test", "schema_version": "0.4", "organoid_type": "cardiac"}
    (pred_dir / "PMC12345.json").write_text(json.dumps(proto))
    monkeypatch.setattr(cp, "PRED_DIR", pred_dir)
    monkeypatch.setattr(cp, "PROTOCOLS_JSONL", tmp_path / "none.jsonl")

    rec = cp.load_protocol("PMC12345")
    assert rec["_source"] == "local_prediction"
    assert rec["organoid_type"] == "cardiac"
