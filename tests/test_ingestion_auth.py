#!/usr/bin/env python3
"""Tests for pipeline/ingestion_auth.py — all offline, no network."""

from __future__ import annotations

import sys
from pathlib import Path

# Add pipeline dir to path so we can import ingestion_auth
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))

from ingestion_auth import classify, classify_batch, is_public_license  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candidate(**overrides) -> dict:
    """Build a minimal valid candidate dict (would pass to auto_ingest)."""
    base = {
        "pmcid": "PMC1111111",
        "doi": "10.1234/test",
        "license": "CC-BY",
        "organoid_type": "cardiac",
        "has_methods": "yes",
    }
    base.update(overrides)
    return base


EMPTY_PMCIDS: set = set()
EMPTY_DOIS: set = set()


# ---------------------------------------------------------------------------
# Blocked tests
# ---------------------------------------------------------------------------

def test_blocked_nc_license():
    cand = _make_candidate(license="CC-BY-NC")
    decision, reason = classify(cand, EMPTY_PMCIDS, EMPTY_DOIS)
    assert decision == "blocked"
    assert "license" in reason


def test_blocked_already_in_corpus_pmcid():
    cand = _make_candidate(pmcid="PMC9999999")
    decision, reason = classify(cand, {"PMC9999999"}, EMPTY_DOIS)
    assert decision == "blocked"
    assert "already_in_corpus" in reason
    assert "PMC9999999" in reason


def test_blocked_already_in_corpus_doi():
    cand = _make_candidate(doi="10.9999/exists")
    decision, reason = classify(cand, EMPTY_PMCIDS, {"10.9999/exists"})
    assert decision == "blocked"
    assert "already_in_corpus" in reason
    assert "10.9999/exists" in reason


def test_blocked_empty_pmcid():
    cand = _make_candidate(pmcid="")
    decision, reason = classify(cand, EMPTY_PMCIDS, EMPTY_DOIS)
    assert decision == "blocked"
    assert "pmcid=empty" in reason


def test_blocked_tier3_no_confirmation():
    cand = _make_candidate(tier="tier3")
    decision, reason = classify(cand, EMPTY_PMCIDS, EMPTY_DOIS)
    assert decision == "blocked"
    assert "tier3" in reason
    assert "no_human_confirmation" in reason


# ---------------------------------------------------------------------------
# Review required tests
# ---------------------------------------------------------------------------

def test_review_required_low_sem_score():
    cand = _make_candidate(sem_score=0.2)
    decision, reason = classify(cand, EMPTY_PMCIDS, EMPTY_DOIS)
    assert decision == "review_required"
    assert "sem_score" in reason


def test_review_required_low_grounding_rate():
    cand = _make_candidate(grounding_rate=0.3)
    decision, reason = classify(cand, EMPTY_PMCIDS, EMPTY_DOIS)
    assert decision == "review_required"
    assert "grounding_rate" in reason


def test_review_required_no_methods():
    cand = _make_candidate(has_methods="no")
    decision, reason = classify(cand, EMPTY_PMCIDS, EMPTY_DOIS)
    assert decision == "review_required"
    assert "has_methods" in reason


def test_review_required_unknown_organoid_type():
    cand = _make_candidate(organoid_type="unicorn-organoid")
    decision, reason = classify(cand, EMPTY_PMCIDS, EMPTY_DOIS)
    assert decision == "review_required"
    assert "organoid_type" in reason


# ---------------------------------------------------------------------------
# Auto-ingest test
# ---------------------------------------------------------------------------

def test_auto_ingest_clean_candidate():
    cand = _make_candidate()
    decision, reason = classify(cand, EMPTY_PMCIDS, EMPTY_DOIS)
    assert decision == "auto_ingest"
    assert reason == "all_checks_passed"


# ---------------------------------------------------------------------------
# Batch test
# ---------------------------------------------------------------------------

def test_classify_batch_adds_fields():
    candidates = [
        _make_candidate(pmcid="PMC1000001"),
        _make_candidate(pmcid="PMC1000002", license="CC-BY-NC"),
        _make_candidate(pmcid="PMC1000003", has_methods="no"),
    ]
    results = classify_batch(candidates, EMPTY_PMCIDS, EMPTY_DOIS)
    assert len(results) == 3
    for r in results:
        assert "auth_decision" in r
        assert "auth_reason" in r
    assert results[0]["auth_decision"] == "auto_ingest"
    assert results[1]["auth_decision"] == "blocked"
    assert results[2]["auth_decision"] == "review_required"
