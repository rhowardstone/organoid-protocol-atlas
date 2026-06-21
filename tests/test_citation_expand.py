#!/usr/bin/env python3
"""Tests for pipeline/citation_expand.py — all offline, HTTP mocked."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add pipeline dir to path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))

from citation_expand import enrich_reference, expand_corpus, fetch_references  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session_with_json(json_data: dict) -> MagicMock:
    """Create a mock requests.Session whose .get() returns a response with json_data."""
    session = MagicMock()
    response = MagicMock()
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    session.get.return_value = response
    return session


# ---------------------------------------------------------------------------
# fetch_references tests
# ---------------------------------------------------------------------------

def test_fetch_references_parses_response():
    """fetch_references should parse referenceList.reference from EPMC response."""
    mock_response = {
        "referenceList": {
            "reference": [
                {
                    "id": "12345678",
                    "source": "MED",
                    "title": "A seminal organoid paper",
                    "authorString": "Smith J, Doe A",
                    "pubYear": "2021",
                }
            ]
        }
    }
    session = _make_session_with_json(mock_response)
    refs = fetch_references("PMC3033971", session)
    assert len(refs) == 1
    assert refs[0]["title"] == "A seminal organoid paper"
    assert refs[0]["id"] == "12345678"


def test_fetch_references_empty_on_no_results():
    """fetch_references returns [] when referenceList is empty."""
    session = _make_session_with_json({"referenceList": {"reference": []}})
    refs = fetch_references("PMC0000000", session)
    assert refs == []


# ---------------------------------------------------------------------------
# enrich_reference tests
# ---------------------------------------------------------------------------

def test_enrich_reference_oa_paper():
    """enrich_reference returns enriched dict for a valid OA paper with PMCID."""
    mock_search = {
        "resultList": {
            "result": [
                {
                    "pmcid": "PMC9999999",
                    "isOpenAccess": "Y",
                    "inEPMC": "Y",
                    "license": "cc by",
                    "doi": "10.1234/test",
                    "pubYear": "2021",
                    "title": "Great Organoid Paper",
                    "authorList": {"author": [{"lastName": "Jones"}]},
                    "journalInfo": {"journal": {"title": "Nature"}},
                    "pmid": "12345678",
                    "citedByCount": 5,
                }
            ]
        }
    }
    session = _make_session_with_json(mock_search)
    ref = {"id": "12345678", "source": "MED"}
    result = enrich_reference(ref, session)
    assert result is not None
    assert result["pmcid"] == "PMC9999999"


def test_enrich_reference_non_oa_returns_none():
    """enrich_reference returns None for a non-OA paper."""
    mock_search = {
        "resultList": {
            "result": [
                {
                    "pmcid": "PMC8888888",
                    "isOpenAccess": "N",
                    "inEPMC": "Y",
                    "license": "publisher-specific",
                    "doi": "10.1234/restricted",
                }
            ]
        }
    }
    session = _make_session_with_json(mock_search)
    ref = {"id": "99999999", "source": "MED"}
    result = enrich_reference(ref, session)
    assert result is None


# ---------------------------------------------------------------------------
# expand_corpus tests
# ---------------------------------------------------------------------------

def test_expand_corpus_deduplicates():
    """Two corpus papers both citing the same new paper -> appears once in output."""
    enriched = {
        "pmcid": "PMC7777777",
        "isOpenAccess": "Y",
        "inEPMC": "Y",
        "license": "cc by",
        "doi": "10.5678/new",
        "pubYear": "2022",
        "title": "Shared Cited Paper",
        "authorString": "Lee K",
        "authorList": {"author": [{"lastName": "Lee"}]},
        "journalInfo": {"journal": {"title": "Cell"}},
        "pmid": "77777777",
        "citedByCount": 10,
    }
    ref = {"id": "77777777", "source": "MED"}

    with (
        patch("citation_expand.fetch_references", return_value=[ref]),
        patch("citation_expand.enrich_reference", return_value=enriched),
        patch("citation_expand.time.sleep"),  # skip sleep
    ):
        session = MagicMock()
        results = expand_corpus(
            ["PMC3033971", "PMC4120977"],
            existing_pmcids=set(),
            existing_dois=set(),
            session=session,
            limit_per_paper=50,
        )

    assert len(results) == 1
    assert results[0]["pmcid"] == "PMC7777777"
    assert results[0]["flags"] == "citation-expansion"


def test_expand_corpus_skips_existing():
    """If the enriched reference's pmcid is already in corpus, it is skipped."""
    enriched = {
        "pmcid": "PMC3033971",  # already in existing_pmcids
        "isOpenAccess": "Y",
        "inEPMC": "Y",
        "license": "cc by",
        "doi": "10.1038/nature09691",
        "pubYear": "2011",
        "title": "Already There",
        "authorString": "Spence J",
        "authorList": {"author": [{"lastName": "Spence"}]},
        "journalInfo": {"journal": {"title": "Nature"}},
        "pmid": "11111111",
        "citedByCount": 100,
    }
    ref = {"id": "11111111", "source": "MED"}

    with (
        patch("citation_expand.fetch_references", return_value=[ref]),
        patch("citation_expand.enrich_reference", return_value=enriched),
        patch("citation_expand.time.sleep"),
    ):
        session = MagicMock()
        results = expand_corpus(
            ["PMC6906116"],
            existing_pmcids={"PMC3033971"},
            existing_dois={"10.1038/nature09691"},
            session=session,
            limit_per_paper=50,
        )

    assert results == []
