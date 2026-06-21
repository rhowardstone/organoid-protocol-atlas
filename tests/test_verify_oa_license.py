"""
OA/license verification tests — fully offline, backed by committed fixtures
in data/corpus/oa_cache/. No network calls made.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from verify_oa_license import (  # noqa: E402
    _normalize_license,
    fetch_epmc_license,
    is_public_ok,
    verify_pool,
    write_manifest,
)

REPO = Path(__file__).resolve().parent.parent
POOL_180 = REPO / "data" / "corpus" / "incoming" / "organoid_corpus_candidates_180.csv"


# ─── _normalize_license ────────────────────────────────────────────────────────

def test_normalize_cc_by():
    assert _normalize_license("CC BY") == "CC-BY"
    assert _normalize_license("cc-by") == "CC-BY"
    assert _normalize_license("CC-BY-4.0") == "CC-BY"
    assert _normalize_license("cc by 4.0") == "CC-BY"


def test_normalize_cc0():
    assert _normalize_license("CC0") == "CC0"
    assert _normalize_license("CC-ZERO") == "CC0"
    assert _normalize_license("cc0 1.0") == "CC0"


def test_normalize_nc_variants():
    assert _normalize_license("CC BY NC") == "CC-BY-NC"
    assert _normalize_license("cc-by-nc-nd") == "CC-BY-NC-ND"
    assert _normalize_license("CC-BY-ND-4.0") == "CC-BY-ND"


def test_normalize_author_manuscript():
    assert _normalize_license("author manuscript") == "author-manuscript"


def test_normalize_empty_is_unknown():
    assert _normalize_license(None) == "unknown"
    assert _normalize_license("") == "unknown"
    assert _normalize_license("  ") == "unknown"


# ─── is_public_ok ──────────────────────────────────────────────────────────────

def test_cc_by_is_public_ok():
    assert is_public_ok("CC-BY") is True
    assert is_public_ok("CC0") is True


def test_nc_is_not_public():
    assert is_public_ok("CC-BY-NC") is False
    assert is_public_ok("CC-BY-NC-ND") is False
    assert is_public_ok("CC-BY-ND") is False
    assert is_public_ok("unknown") is False
    assert is_public_ok("author-manuscript") is False


# ─── fetch_epmc_license (offline, fixture-backed) ─────────────────────────────

def test_cc_by_paper_returns_public_ok():
    r = fetch_epmc_license("PMC5358113", offline=True)
    assert r["license"] == "CC-BY"
    assert r["source"] == "epmc"
    assert r["verified"] is True


def test_cc_by_nc_nd_paper_is_rejected():
    r = fetch_epmc_license("PMC12992950", offline=True)
    assert r["license"] in ("CC-BY-NC", "CC-BY-NC-ND", "CC-BY-ND")
    assert is_public_ok(r["license"]) is False


def test_offline_cache_miss_returns_unknown_not_attempted():
    r = fetch_epmc_license("PMC00000000FAKE", offline=True)
    assert r["license"] == "unknown"
    assert r["source"] == "cache_miss"
    assert r["verified"] is False


def test_fixture_is_real_epmc_response():
    r = fetch_epmc_license("PMC7471119", offline=True)
    assert r["source"] == "epmc"
    assert r["license"] == "CC-BY"


# ─── verify_pool (offline) ─────────────────────────────────────────────────────

def test_verify_pool_returns_list_of_dicts(tmp_path):
    results = verify_pool(POOL_180, offline=True, limit=5)
    assert isinstance(results, list)
    assert len(results) == 5
    for r in results:
        assert "pmcid" in r and "verdict" in r and "public_ok" in r


def test_verify_pool_verdicts_are_valid_enum(tmp_path):
    results = verify_pool(POOL_180, offline=True, limit=10)
    for r in results:
        assert r["verdict"] in ("public_ok", "rejected", "quarantine")


def test_verify_pool_cached_papers_match_expected_license():
    results = verify_pool(POOL_180, offline=True, limit=180)
    by_pmcid = {r["pmcid"]: r for r in results}
    # PMC5358113 is in the 180 pool and has a fixture
    if "PMC5358113" in by_pmcid:
        r = by_pmcid["PMC5358113"]
        assert r["verified_license"] == "CC-BY"
        assert r["public_ok"] is True
    # PMC12992950 is in the 180 pool (cardiac CC-BY-NC entry)
    if "PMC12992950" in by_pmcid:
        r = by_pmcid["PMC12992950"]
        assert is_public_ok(r["verified_license"]) is False
        assert r["verdict"] == "rejected"


# ─── write_manifest ────────────────────────────────────────────────────────────

def test_write_manifest_structure(tmp_path):
    results = [
        {"pmcid": "PMC001", "doi": "10.1/a", "organoid_type": "intestinal",
         "candidate_license": "CC-BY", "verified_license": "CC-BY",
         "verified_license_raw": "cc by", "license_match": True,
         "verdict": "public_ok", "public_ok": True, "source": "epmc",
         "title": "T1", "journal": "J1"},
        {"pmcid": "PMC002", "doi": "10.1/b", "organoid_type": "cerebral",
         "candidate_license": "CC-BY-NC", "verified_license": "CC-BY-NC",
         "verified_license_raw": "cc by nc", "license_match": True,
         "verdict": "rejected", "public_ok": False, "source": "epmc",
         "title": "T2", "journal": "J2"},
    ]
    out = tmp_path / "oa_results.json"
    write_manifest(results, out)
    m = json.loads(out.read_text())
    assert m["pool_size"] == 2
    assert m["public_ok"] == 1
    assert m["rejected"] == 1
    assert m["quarantine"] == 0
    assert "PMC001" in m["public_pmcids"]
    assert m["rejected_pmcids"][0]["pmcid"] == "PMC002"


def test_write_manifest_flags_license_mismatch(tmp_path):
    results = [
        {"pmcid": "PMC003", "doi": "10.1/c", "organoid_type": "kidney",
         "candidate_license": "CC-BY", "verified_license": "CC-BY-NC",
         "verified_license_raw": "cc by nc", "license_match": False,
         "verdict": "rejected", "public_ok": False, "source": "epmc",
         "title": "T3", "journal": "J3"},
    ]
    out = tmp_path / "oa_results.json"
    write_manifest(results, out)
    m = json.loads(out.read_text())
    assert m["license_mismatches"] == 1
    assert m["mismatch_details"][0]["candidate"] == "CC-BY"
    assert m["mismatch_details"][0]["verified"] == "CC-BY-NC"
