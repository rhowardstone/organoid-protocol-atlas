"""
Offline tests for pipeline/discover_candidates.py — PURE helpers only, no network.

Covers license normalization, row-building / field mapping from a sample Europe
PMC core-result dict, and the dedup logic. No assertion touches the network.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import discover_candidates as dc  # noqa: E402


# A trimmed but realistic Europe PMC `core` result.
SAMPLE = {
    "id": "12345678",
    "pmid": "12345678",
    "pmcid": "PMC9999999",
    "doi": "10.1000/example.2026.001",
    "title": "Protocol to generate human cardiac organoids from iPSCs.",
    "authorString": "Doe J, Roe A, Smith B.",
    "authorList": {"author": [
        {"fullName": "Doe J", "firstName": "Jane", "lastName": "Doe"},
        {"fullName": "Roe A", "firstName": "Alex", "lastName": "Roe"},
    ]},
    "pubYear": "2026",
    "journalInfo": {"journal": {"title": "STAR protocols"}},
    "license": "cc by",
    "isOpenAccess": "Y",
    "inEPMC": "Y",
    "citedByCount": 7,
}


# --- license normalization --------------------------------------------------

def test_license_cc_by():
    assert dc.normalize_license("cc by") == "CC-BY"
    assert dc.normalize_license("CC BY") == "CC-BY"
    assert dc.normalize_license("cc-by") == "CC-BY"


def test_license_cc_by_nc():
    assert dc.normalize_license("cc by-nc") == "CC-BY-NC"
    assert dc.normalize_license("cc by nc nd") == "CC-BY-NC"


def test_license_cc0():
    assert dc.normalize_license("cc0") == "CC0"
    assert dc.normalize_license("public domain") == "CC0"


def test_license_unknown():
    assert dc.normalize_license(None) == "unknown"
    assert dc.normalize_license("") == "unknown"
    assert dc.normalize_license("all rights reserved") == "unknown"


# --- field mapping / row builder -------------------------------------------

def test_build_row_basic():
    row = dc.build_row(SAMPLE, "cardiac")
    assert row is not None
    assert row["organoid_type"] == "cardiac"
    assert row["pmcid"] == "PMC9999999"
    assert row["doi"] == "10.1000/example.2026.001"
    assert row["first_author"] == "Doe"
    assert row["year"] == "2026"
    assert row["journal"] == "STAR protocols"
    assert row["license"] == "CC-BY"
    assert row["has_methods"] == "yes"
    assert row["flags"] == "epmc-ft"
    assert row["gold_candidate"] == "no"
    assert row["in_current_corpus"] == "no"
    assert row["pmid"] == "12345678"
    assert row["cited_by"] == "7"
    assert row["notes"] == "europepmc discover cardiac"
    # title trailing period stripped
    assert row["title"].endswith("iPSCs")
    # exactly the 18 expected columns
    assert set(row.keys()) == set(dc.HEADER)


def test_build_row_requires_pmcid():
    no_pmcid = dict(SAMPLE, pmcid="")
    assert dc.build_row(no_pmcid, "cardiac") is None


def test_build_row_requires_oa_in_epmc():
    not_oa = dict(SAMPLE, isOpenAccess="N")
    assert dc.build_row(not_oa, "cardiac") is None
    not_epmc = dict(SAMPLE, inEPMC="N")
    assert dc.build_row(not_epmc, "cardiac") is None


def test_first_author_fallback_to_authorstring():
    no_list = dict(SAMPLE)
    no_list.pop("authorList")
    assert dc.first_author_lastname(no_list) == "Doe"


def test_cited_by_blank_when_absent():
    no_cite = dict(SAMPLE)
    no_cite.pop("citedByCount")
    row = dc.build_row(no_cite, "lung")
    assert row["cited_by"] == ""


# --- dedup logic ------------------------------------------------------------

def test_is_new_blocks_seen_pmcid():
    seen_p = {"PMC9999999"}
    row = dc.build_row(SAMPLE, "cardiac")
    assert dc.is_new(row, seen_p, set()) is False


def test_is_new_blocks_seen_doi():
    seen_d = {"10.1000/example.2026.001"}
    row = dc.build_row(SAMPLE, "cardiac")
    assert dc.is_new(row, set(), seen_d) is False


def test_is_new_case_insensitive():
    row = dc.build_row(SAMPLE, "cardiac")
    # corpus stores pmcid in any case; dedup is case-insensitive
    assert dc.is_new(row, {"pmc9999999"}, set()) is False
    assert dc.is_new(row, set(), {"10.1000/EXAMPLE.2026.001"}) is False


def test_is_new_true_for_fresh():
    row = dc.build_row(SAMPLE, "cardiac")
    assert dc.is_new(row, {"PMC0000000"}, {"10.9/other"}) is True


def test_is_new_ignores_empty_doi():
    no_doi = dict(SAMPLE, doi="")
    row = dc.build_row(no_doi, "cardiac")
    # empty doi must not collide with an empty entry in seen set
    assert dc.is_new(row, {"PMC0000000"}, {""}) is True
