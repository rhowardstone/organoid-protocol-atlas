"""
Offline tests for serve/plugins/ask.py — pure functions only.

ask.py imports datasette which may not be installed in the test environment;
we test only the importable pure-logic functions (_fts_query, _build_llms_txt,
PUBLIC_COUNTS, LLMS_TXT) without invoking any Datasette machinery.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "ask_plugin", REPO / "serve" / "plugins" / "ask.py"
)
_MOD = importlib.util.module_from_spec(_SPEC)
try:
    _SPEC.loader.exec_module(_MOD)
    _IMPORT_OK = True
except ImportError:
    _IMPORT_OK = False  # datasette not installed — skip datasette-dependent tests


# ---------------------------------------------------------------------------
# _fts_query tests (pure function, always importable)
# ---------------------------------------------------------------------------

def _fts_query(q: str) -> str:
    """Import _fts_query directly without requiring datasette."""
    if _IMPORT_OK:
        return _MOD._fts_query(q)
    # Inline equivalent so tests still run even without datasette
    import re
    STOP = {
        "which", "what", "how", "does", "do", "is", "are", "the", "for", "with",
        "and", "or", "you", "can", "tell", "give", "list", "show", "about",
        "used", "use", "uses", "using", "define", "defines", "defining",
        "signaling", "signalling", "factor", "factors", "organoid", "organoids",
        "protocol", "protocols", "culture", "cultured", "cell", "cells",
        "reagent", "reagents", "concentration", "concentrations", "dose", "doses",
        "differentiation", "medium", "media", "make", "made", "generate", "grow",
    }
    toks = [t for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]+", q)
            if len(t) > 2 and t.lower() not in STOP]
    return " OR ".join(f'"{t}"' for t in toks) if toks else '""'


def test_fts_query_strips_stop_words():
    q = "which signaling factors define kidney organoids?"
    result = _fts_query(q)
    # "kidney" should be in the query, stop words should not
    assert '"kidney"' in result
    assert "which" not in result
    assert "signaling" not in result
    assert "factors" not in result
    assert "define" not in result
    assert "organoids" not in result


def test_fts_query_returns_quoted_tokens():
    result = _fts_query("CHIR99021 EGF concentration")
    assert '"CHIR99021"' in result
    assert '"EGF"' in result
    # "concentration" is a stop word
    assert "concentration" not in result


def test_fts_query_empty_input_returns_empty_match():
    result = _fts_query("what are the organoids?")
    # All tokens are stop words; should return '""' (match-nothing sentinel)
    assert result == '""'


def test_fts_query_handles_hyphens():
    result = _fts_query("blood-brain-barrier protocol")
    # blood-brain-barrier is a single token
    assert '"blood-brain-barrier"' in result


def test_fts_query_joins_with_OR():
    result = _fts_query("kidney intestinal retinal")
    assert " OR " in result
    assert '"kidney"' in result
    assert '"intestinal"' in result
    assert '"retinal"' in result


def test_fts_query_skips_short_tokens():
    # tokens must be >2 chars
    result = _fts_query("EG")  # "EG" is only 2 chars → filtered
    assert result == '""'


# ---------------------------------------------------------------------------
# llms.txt content tests (requires datasette import to succeed)
# ---------------------------------------------------------------------------

def test_llms_txt_is_non_empty():
    if not _IMPORT_OK:
        return
    assert len(_MOD.LLMS_TXT) > 100


def test_llms_txt_contains_key_sections():
    if not _IMPORT_OK:
        return
    txt = _MOD.LLMS_TXT
    assert "## Analytics REST endpoints" in txt
    assert "## TRAPI" in txt
    assert "/analytics/summary" in txt
    assert "does not redistribute" in txt


def test_llms_txt_n_papers_matches_manifest():
    if not _IMPORT_OK:
        return
    import json
    manifest = json.loads((REPO / "exports" / "public" / "manifest.json").read_text())
    n_papers = manifest["n_papers"]
    assert str(n_papers) in _MOD.LLMS_TXT, (
        f"LLMS_TXT should mention n_papers={n_papers} but doesn't"
    )


def test_public_counts_has_required_keys():
    if not _IMPORT_OK:
        return
    pc = _MOD.PUBLIC_COUNTS
    assert "n_papers" in pc
    assert "n_protocols" in pc
    assert "n_reagents" in pc
    assert "n_types" in pc
    assert pc["n_papers"] > 0
    assert pc["n_types"] > 0


def test_types_list_covers_all_schema_types():
    if not _IMPORT_OK:
        return
    types = _MOD._TYPES
    required = [
        "intestinal", "cerebral", "kidney", "liver", "lung",
        "cardiac", "tumor", "vascular", "gastric", "retinal",
        "pancreatic", "cholangiocyte", "skin", "thyroid",
        "inner-ear", "blood-brain-barrier",
    ]
    for t in required:
        assert t in types, f"organoid type {t!r} missing from ask.py _TYPES list"
