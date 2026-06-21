"""
Offline tests for R5 semantic candidate re-ranking (ingest_orchestrator.
rank_candidates_by_relevance). Pure logic with synthetic vectors/centroids — no model.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import ingest_orchestrator as io  # noqa: E402

# two unit centroids pointing along orthogonal axes
CENTROIDS = {"intestinal": np.array([1.0, 0.0], dtype=np.float32),
             "cardiac": np.array([0.0, 1.0], dtype=np.float32)}


def test_on_topic_ranks_above_off_topic():
    cands = [{"pmcid": "A", "organoid_type": "intestinal"},   # vec aligned -> high
             {"pmcid": "B", "organoid_type": "intestinal"}]   # vec orthogonal -> low
    vecs = [np.array([1.0, 0.0], dtype=np.float32), np.array([0.0, 1.0], dtype=np.float32)]
    out = io.rank_candidates_by_relevance(cands, vecs, CENTROIDS)
    assert [c["pmcid"] for c in out] == ["A", "B"]
    assert out[0]["_relevance"] > out[1]["_relevance"]
    assert abs(out[0]["_relevance"] - 1.0) < 1e-6


def test_min_relevance_filters_low_scorers():
    cands = [{"pmcid": "A", "organoid_type": "intestinal"},
             {"pmcid": "B", "organoid_type": "intestinal"}]
    vecs = [np.array([1.0, 0.0], dtype=np.float32), np.array([0.0, 1.0], dtype=np.float32)]
    out = io.rank_candidates_by_relevance(cands, vecs, CENTROIDS, min_relevance=0.5)
    assert [c["pmcid"] for c in out] == ["A"]   # B (score 0) dropped


def test_no_centroid_for_type_is_retained_unscored_and_sorted_last():
    cands = [{"pmcid": "A", "organoid_type": "intestinal"},
             {"pmcid": "Z", "organoid_type": "exotic"}]       # no centroid
    vecs = [np.array([1.0, 0.0], dtype=np.float32), np.array([1.0, 1.0], dtype=np.float32)]
    out = io.rank_candidates_by_relevance(cands, vecs, CENTROIDS, min_relevance=0.9)
    ids = [c["pmcid"] for c in out]
    assert ids == ["A", "Z"]                    # Z retained despite filter (no reference)
    assert out[-1]["_relevance"] is None


def test_none_vector_is_retained_unscored():
    cands = [{"pmcid": "A", "organoid_type": "intestinal"}]
    out = io.rank_candidates_by_relevance(cands, [None], CENTROIDS, min_relevance=0.9)
    assert out[0]["pmcid"] == "A" and out[0]["_relevance"] is None
