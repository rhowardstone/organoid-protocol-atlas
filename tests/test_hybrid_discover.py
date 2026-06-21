"""
Offline tests for hybrid_discover pure logic: centroid computation, cosine scoring,
and graceful fallback. No network calls, no model downloads.
"""
from __future__ import annotations

import json
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import hybrid_discover as hd


# --------------------------------------------------------------------------- #
# cosine_to_centroid
# --------------------------------------------------------------------------- #

def test_cosine_identical_unit_vectors():
    v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    assert hd.cosine_to_centroid(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors():
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    assert hd.cosine_to_centroid(a, b) == pytest.approx(0.0, abs=1e-6)


def test_cosine_zero_vector_returns_zero():
    z = np.zeros(4, dtype=np.float32)
    c = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    assert hd.cosine_to_centroid(z, c) == pytest.approx(0.0)


def test_cosine_opposite_vectors():
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([-1.0, 0.0], dtype=np.float32)
    assert hd.cosine_to_centroid(a, b) == pytest.approx(-1.0)


# --------------------------------------------------------------------------- #
# type_centroids
# --------------------------------------------------------------------------- #

def _write_synthetic_index(tmp: Path, vecs: np.ndarray, docs: list[dict]) -> None:
    np.save(tmp / "vectors.npy", vecs)
    (tmp / "docs.jsonl").write_text(
        "\n".join(json.dumps(d) for d in docs) + "\n"
    )


def test_type_centroids_correct_direction():
    vecs = np.array(
        [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0], [0.1, 0.9]], dtype=np.float32
    )
    docs = [
        {"pmcid": "A", "organoid_type": "cardiac", "doi": ""},
        {"pmcid": "B", "organoid_type": "cardiac", "doi": ""},
        {"pmcid": "C", "organoid_type": "intestinal", "doi": ""},
        {"pmcid": "D", "organoid_type": "intestinal", "doi": ""},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        _write_synthetic_index(Path(tmp), vecs, docs)
        result = hd.type_centroids(Path(tmp))

    assert result is not None
    _, _, centroids = result
    assert "cardiac" in centroids and "intestinal" in centroids
    # cardiac centroid points more toward axis-0 (x)
    assert centroids["cardiac"][0] > centroids["cardiac"][1]
    # intestinal centroid points more toward axis-1 (y)
    assert centroids["intestinal"][1] > centroids["intestinal"][0]


def test_type_centroids_are_unit_vectors():
    vecs = np.array([[3.0, 4.0], [1.0, 0.0]], dtype=np.float32)
    docs = [
        {"pmcid": "A", "organoid_type": "hepatic", "doi": ""},
        {"pmcid": "B", "organoid_type": "hepatic", "doi": ""},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        _write_synthetic_index(Path(tmp), vecs, docs)
        _, _, centroids = hd.type_centroids(Path(tmp))
    assert np.linalg.norm(centroids["hepatic"]) == pytest.approx(1.0, abs=1e-5)


def test_type_centroids_missing_index_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        assert hd.type_centroids(Path(tmp)) is None


def test_type_centroids_skips_unknown_type():
    vecs = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    docs = [
        {"pmcid": "A", "organoid_type": "cardiac", "doi": ""},
        {"pmcid": "B", "organoid_type": None, "doi": ""},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        _write_synthetic_index(Path(tmp), vecs, docs)
        _, _, centroids = hd.type_centroids(Path(tmp))
    assert list(centroids.keys()) == ["cardiac"]


# --------------------------------------------------------------------------- #
# embed_texts graceful fallback
# --------------------------------------------------------------------------- #

def test_embed_texts_fallback_when_dep_missing(monkeypatch):
    """embed_texts returns None (with a warning) when sentence-transformers absent."""
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = hd.embed_texts(["organoid culture protocol"])
    assert result is None
    assert any("sentence-transformers" in str(warning.message) for warning in w)
