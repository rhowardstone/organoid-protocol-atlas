"""
Offline tests for the corpus-integrity screen's pure helpers (no network):
title_similar, is_retracted, has_tortured_phrase.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import screen_corpus_integrity as sci  # noqa: E402


def test_title_similar_matches_same_work_despite_punctuation():
    assert sci.title_similar(
        "Efficient generation of iPSC-derived liver organoids",
        "Efficient generation of iPSC derived liver organoids!") is True


def test_title_similar_rejects_different_work():
    assert sci.title_similar(
        "Kidney organoid differentiation protocol",
        "A study of cardiac arrhythmia in zebrafish") is False


def test_is_retracted_via_update_to():
    assert sci.is_retracted({"update-to": [{"type": "retraction"}]}) is True


def test_is_retracted_via_work_type():
    assert sci.is_retracted({"type": "retracted-article"}) is True


def test_not_retracted_normal_article():
    assert sci.is_retracted({"type": "journal-article", "update-to": []}) is False


def test_tortured_phrase_flag():
    assert sci.has_tortured_phrase("Detection of bosom peril using deep learning") is True
    assert sci.has_tortured_phrase("Generation of intestinal organoids from iPSCs") is False
