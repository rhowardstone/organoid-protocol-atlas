"""
Offline tests for pipeline/validate_predictions.py.

These tests construct minimal prediction JSON dicts in memory (no files on disk
for most cases) to verify every check fires correctly. We use tmp_path for
file-based tests only when the validator's file I/O path needs exercising.

No network. No GPU. No model downloads.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
sys.path.insert(0, str(REPO / "organoid_demo"))

from validate_predictions import (
    Result,
    _check_evidence,
    _check_failure_mode,
    _check_modification,
    _check_reagent,
    validate_file,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _minimal_protocol(**overrides) -> dict:
    """Minimal valid OrganoidProtocol v0.4 dict."""
    base = {
        "source_doi": "10.1038/nature07935",
        "organoid_type": "intestinal",
        "schema_version": "0.4",
        "source_cells": {},
        "matrix": {},
        "base_media": {},
        "media_supplements": [],
        "signaling_factors": [],
        "small_molecules": [],
        "timeline": [],
        "passaging": {},
        "culture_conditions": {},
        "assay_endpoints": [],
        "failure_modes": [],
        "modifications": [],
    }
    base.update(overrides)
    return base


def _write_json(tmp_path: Path, data: dict, name: str = "pred.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return p


# --------------------------------------------------------------------------- #
# _check_evidence
# --------------------------------------------------------------------------- #

def test_evidence_empty_quote_is_error():
    r = Result(Path("x.json"))
    _check_evidence({"quote": ""}, "test", r)
    assert any("quote is empty" in e for e in r.errors)


def test_evidence_null_quote_is_error():
    r = Result(Path("x.json"))
    _check_evidence({"quote": None}, "test", r)
    assert r.errors


def test_evidence_valid_quote_passes():
    r = Result(Path("x.json"))
    _check_evidence({"quote": "cells were treated with EGF (50 ng/mL)"}, "test", r)
    assert not r.errors


def test_evidence_sentence_id_int_passes():
    r = Result(Path("x.json"))
    _check_evidence({"quote": "some quote here", "sentence_id": 3}, "test", r)
    assert not r.errors


def test_evidence_sentence_id_string_is_error():
    r = Result(Path("x.json"))
    _check_evidence({"quote": "some quote here", "sentence_id": "3"}, "test", r)
    assert any("sentence_id" in e for e in r.errors)


def test_evidence_sentence_id_negative_is_error():
    r = Result(Path("x.json"))
    _check_evidence({"quote": "some quote here", "sentence_id": -1}, "test", r)
    assert any("sentence_id" in e for e in r.errors)


def test_evidence_confidence_out_of_range_is_error():
    r = Result(Path("x.json"))
    _check_evidence({"quote": "some quote here", "confidence": 1.5}, "test", r)
    assert any("confidence" in e for e in r.errors)


def test_evidence_confidence_valid_passes():
    r = Result(Path("x.json"))
    _check_evidence({"quote": "some quote here", "confidence": 0.9}, "test", r)
    assert not r.errors


# --------------------------------------------------------------------------- #
# _check_reagent
# --------------------------------------------------------------------------- #

def test_reagent_empty_name_is_error():
    r = Result(Path("x.json"))
    _check_reagent({"name": ""}, "sf[0]", r)
    assert r.errors


def test_reagent_concentration_value_without_unit_warns():
    r = Result(Path("x.json"))
    _check_reagent({"name": "EGF", "concentration": {"value": 50, "unit": None}}, "sf[0]", r)
    assert r.warnings


def test_reagent_with_unit_passes():
    r = Result(Path("x.json"))
    _check_reagent({"name": "EGF", "concentration": {"value": 50, "unit": "ng/mL"}}, "sf[0]", r)
    assert not r.errors and not r.warnings


# --------------------------------------------------------------------------- #
# _check_failure_mode
# --------------------------------------------------------------------------- #

def test_failure_mode_empty_description_is_error():
    r = Result(Path("x.json"))
    _check_failure_mode({"description": ""}, 0, r)
    assert r.errors


def test_failure_mode_valid_passes():
    r = Result(Path("x.json"))
    _check_failure_mode({"description": "organoids detach from Matrigel"}, 0, r)
    assert not r.errors


# --------------------------------------------------------------------------- #
# _check_modification
# --------------------------------------------------------------------------- #

def test_modification_empty_change_desc_is_error():
    r = Result(Path("x.json"))
    _check_modification({"change_description": ""}, 0, r)
    assert r.errors


def test_modification_bad_doi_format_is_error():
    r = Result(Path("x.json"))
    _check_modification({"change_description": "replaced Noggin", "cited_doi": "PMID:12345"}, 0, r)
    assert any("cited_doi" in e for e in r.errors)


def test_modification_valid_doi_passes():
    r = Result(Path("x.json"))
    _check_modification({"change_description": "replaced Noggin with LDN-193189",
                          "cited_doi": "10.1038/nmeth.1940"}, 0, r)
    assert not r.errors


def test_modification_doi_not_in_quote_warns():
    r = Result(Path("x.json"))
    _check_modification({
        "change_description": "replaced Noggin",
        "cited_doi": "10.1038/nmeth.1940",
        "evidence": {"quote": "as described previously", "source_doi": "10.x/x"},
    }, 0, r)
    assert r.warnings  # cited_doi not verbatim in quote → warning


# --------------------------------------------------------------------------- #
# validate_file — file-level checks
# --------------------------------------------------------------------------- #

def test_validate_minimal_valid_file_passes(tmp_path):
    p = _write_json(tmp_path, _minimal_protocol())
    res = validate_file(p)
    assert res.ok, res.errors


def test_validate_wrong_schema_version_is_error(tmp_path):
    p = _write_json(tmp_path, _minimal_protocol(schema_version="0.3"))
    res = validate_file(p)
    assert any("schema_version" in e for e in res.errors)


def test_validate_missing_source_doi_is_error(tmp_path):
    data = _minimal_protocol()
    del data["source_doi"]
    p = _write_json(tmp_path, data)
    res = validate_file(p)
    assert any("source_doi" in e for e in res.errors)


def test_validate_bad_doi_prefix_is_error(tmp_path):
    p = _write_json(tmp_path, _minimal_protocol(source_doi="PMID:12345678"))
    res = validate_file(p)
    assert any("source_doi" in e for e in res.errors)


def test_validate_invalid_json_is_error(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json")
    res = validate_file(p)
    assert res.errors


def test_validate_signaling_factor_empty_name_is_error(tmp_path):
    data = _minimal_protocol(signaling_factors=[{"name": ""}])
    p = _write_json(tmp_path, data)
    res = validate_file(p)
    assert any("signaling_factors" in e for e in res.errors)


def test_validate_evidence_sentence_id_string_propagates(tmp_path):
    data = _minimal_protocol(signaling_factors=[{
        "name": "EGF",
        "evidence": {
            "source_doi": "10.x/x",
            "quote": "EGF was added at 50 ng/mL",
            "sentence_id": "2",  # string, should be int
            "confidence": 0.9,
        },
    }])
    p = _write_json(tmp_path, data)
    res = validate_file(p)
    assert any("sentence_id" in e for e in res.errors)


def test_validate_failure_mode_no_description_is_error(tmp_path):
    data = _minimal_protocol(failure_modes=[{"description": "", "condition": "if diluted"}])
    p = _write_json(tmp_path, data)
    res = validate_file(p)
    assert any("failure_modes" in e for e in res.errors)


def test_validate_modification_bad_doi_is_error(tmp_path):
    data = _minimal_protocol(modifications=[{
        "change_description": "replaced Noggin with LDN",
        "cited_doi": "not-a-doi",
    }])
    p = _write_json(tmp_path, data)
    res = validate_file(p)
    assert any("cited_doi" in e for e in res.errors)


def test_validate_modification_valid_passes(tmp_path):
    data = _minimal_protocol(modifications=[{
        "change_description": "replaced Noggin with LDN-193189 at 100 nM",
        "cited_doi": "10.1016/j.stem.2012.04.015",
    }])
    p = _write_json(tmp_path, data)
    res = validate_file(p)
    assert res.ok


def test_validate_new_organoid_types_do_not_warn(tmp_path):
    """New types added in schema v0.4 expansion must not produce unknown-type warnings."""
    new_types = [
        "cardiac", "tumor", "vascular", "cholangiocyte", "skin", "mammary",
        "endometrial", "bone", "prostate", "inner-ear", "salivary-gland",
        "bladder", "neuromuscular", "esophageal", "blood-brain-barrier",
        "thyroid", "fallopian-tube",
    ]
    import json as _json
    for otype in new_types:
        p = tmp_path / f"{otype}.json"
        p.write_text(_json.dumps(_minimal_protocol(organoid_type=otype)))
        res = validate_file(p)
        type_warns = [w for w in res.warnings if "not in known set" in w]
        assert not type_warns, f"organoid_type={otype!r} should be in VALID_TYPES but got warning: {type_warns}"


def test_validate_completely_unknown_organoid_type_warns(tmp_path):
    """A completely unknown organoid type should produce a warning (Pydantic also errors — both are expected)."""
    import json as _json
    p = tmp_path / "unknown_type.json"
    p.write_text(_json.dumps(_minimal_protocol(organoid_type="hamster-brain-chip")))
    res = validate_file(p)
    assert any("not in known set" in w for w in res.warnings), (
        "Expected an unknown-type warning for 'hamster-brain-chip'"
    )
    # Pydantic correctly rejects invalid enum values — that's a co-occurring error, not a problem
    pydantic_errors = [e for e in res.errors if "Pydantic" in e]
    assert pydantic_errors, "Expected a Pydantic enum rejection error for truly unknown type"
