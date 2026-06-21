"""
Offline tests for find_substitutions pure search logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import find_substitutions as fs


def _mod(pmcid, src_doi, change, cited_doi="", otype="intestinal"):
    return {"pmcid": pmcid, "source_doi": src_doi, "change_description": change,
            "cited_doi": cited_doi, "organoid_type": otype}


MODS = [
    _mod("PMC1", "10.1/a", "replaced Matrigel with Geltrex"),
    _mod("PMC2", "10.1/b", "substituted Noggin with LDN-193189"),
    _mod("PMC3", "10.1/c", "increased EGF from 50 ng/mL to 100 ng/mL"),
    _mod("PMC4", "10.1/d", "changed base media from DMEM to Advanced DMEM/F12"),
    _mod("PMC5", "10.1/e", "replaced Noggin and Matrigel with recombinant alternatives"),
]


# --------------------------------------------------------------------------- #
# _matches
# --------------------------------------------------------------------------- #

def test_matches_case_insensitive():
    assert fs._matches("replaced MATRIGEL with Geltrex", "matrigel")
    assert fs._matches("replaced Matrigel", "MATRIGEL")


def test_matches_false_for_absent_term():
    assert not fs._matches("replaced EGF", "Matrigel")


def test_matches_partial_word():
    assert fs._matches("Matrigel-coated surface", "Matrigel")


# --------------------------------------------------------------------------- #
# search_substitutions
# --------------------------------------------------------------------------- #

def test_search_basic_match():
    hits = fs.search_substitutions(MODS, "Matrigel", None)
    pmcids = [h["pmcid"] for h in hits]
    assert "PMC1" in pmcids
    assert "PMC5" in pmcids
    assert "PMC2" not in pmcids


def test_search_two_term_both_required():
    hits = fs.search_substitutions(MODS, "Noggin", "LDN-193189")
    assert len(hits) == 1
    assert hits[0]["pmcid"] == "PMC2"


def test_search_two_term_order_independent():
    """Both terms match regardless of which is 'from' and which is 'to'."""
    hits_ab = fs.search_substitutions(MODS, "Matrigel", "Geltrex")
    hits_ba = fs.search_substitutions(MODS, "Geltrex", "Matrigel")
    assert len(hits_ab) == 1 and len(hits_ba) == 1
    assert hits_ab[0]["pmcid"] == hits_ba[0]["pmcid"] == "PMC1"


def test_search_no_match():
    hits = fs.search_substitutions(MODS, "Dispase", None)
    assert hits == []


def test_search_empty_modifications():
    hits = fs.search_substitutions([], "Matrigel", None)
    assert hits == []


def test_search_empty_query():
    hits = fs.search_substitutions(MODS, "", None)
    assert hits == []


def test_search_skips_empty_change_description():
    mods = [{"pmcid": "PMC9", "source_doi": "x", "change_description": "",
              "organoid_type": "int"}]
    hits = fs.search_substitutions(mods, "Matrigel", None)
    assert hits == []


def test_search_partial_term_matches():
    """'EGF' matches 'increased EGF from 50'."""
    hits = fs.search_substitutions(MODS, "EGF", None)
    assert len(hits) == 1
    assert hits[0]["pmcid"] == "PMC3"


def test_search_case_insensitive():
    hits_upper = fs.search_substitutions(MODS, "MATRIGEL", None)
    hits_lower = fs.search_substitutions(MODS, "matrigel", None)
    assert len(hits_upper) == len(hits_lower)


def test_search_second_term_not_found_filters():
    """First term matches but second term doesn't → filtered out."""
    hits = fs.search_substitutions(MODS, "Matrigel", "laminin")
    assert hits == []


def test_search_returns_all_fields():
    hits = fs.search_substitutions(MODS, "Geltrex", None)
    assert len(hits) == 1
    h = hits[0]
    assert "pmcid" in h and "source_doi" in h and "change_description" in h
