"""
Offline tests for R3 semantic-retrieval PURE logic (no model download): cosine ranking,
entity/type filtering, precision@k. The embedding step is a runtime concern (like
Ollama for extraction) and is not exercised here.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import semantic_index as si  # noqa: E402


DOCS = np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0], [-1.0, 0.0]], dtype=np.float32)


def test_cosine_topk_orders_by_similarity():
    q = np.array([1.0, 0.0], dtype=np.float32)
    res = si.cosine_topk(q, DOCS, k=3)
    idx = [i for i, _ in res]
    assert idx[0] == 0 and idx[1] == 1          # nearest first
    assert idx[2] == 2                           # orthogonal before opposite
    assert res[0][1] > res[1][1] > res[2][1]     # scores descending


def test_cosine_topk_k_capped():
    q = np.array([1.0, 0.0], dtype=np.float32)
    assert len(si.cosine_topk(q, DOCS, k=99)) == 4


def test_cosine_topk_mask_restricts_candidates():
    q = np.array([1.0, 0.0], dtype=np.float32)
    mask = np.array([False, False, True, True])   # only docs 2,3 eligible
    res = si.cosine_topk(q, DOCS, k=2, mask=mask)
    assert [i for i, _ in res] == [2, 3]


def test_type_mask():
    m = si.type_mask(["a", "b", "a", "c"], "a")
    assert list(m) == [True, False, True, False]
    assert si.type_mask(["a", "b"], None) is None


def test_precision_at_k():
    assert si.precision_at_k(["a", "a", "b", "a"], "a", 3) == 2 / 3
    assert si.precision_at_k(["b", "c"], "a", 5) == 0.0
    assert si.precision_at_k([], "a", 5) == 0.0


def test_doc_text_excludes_type_label_and_truncates():
    b = {"methods_text": "X" * 5000, "organoid_type": "intestinal"}
    t = si.doc_text(b)
    assert len(t) == si.MAX_CHARS and "intestinal" not in t  # no label leakage
    assert si.doc_text({"methods_text": "", "body_text": "fallback body"}) == "fallback body"
