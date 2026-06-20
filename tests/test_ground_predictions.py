"""
Offline tests for the S1 grounding-sidecar generator's pure helpers
(pipeline/ground_predictions.py). No network: we test entity collection and
coverage accounting, which decide what enters the A->B sidecar handoff.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import ground_predictions as gp  # noqa: E402


def test_collect_entities_covers_factors_molecules_and_cell_line():
    pred = {
        "signaling_factors": [{"name": "CHIR99021"}, {"name": " "}, {"name": "Wnt3A"}],
        "small_molecules": [{"name": "Y-27632"}],
        "source_cells": {"line_name": "H9"},
    }
    got = set(gp.collect_entities(pred))
    assert ("CHIR99021", "reagent", "signaling_factors") in got
    assert ("Wnt3A", "reagent", "signaling_factors") in got
    assert ("Y-27632", "reagent", "small_molecules") in got
    assert ("H9", "cell_line", "source_cells.line_name") in got
    # blank/whitespace names are skipped
    assert all(n.strip() for n, _, _ in got)


def test_collect_entities_handles_missing_fields():
    assert list(gp.collect_entities({})) == []
    assert list(gp.collect_entities({"signaling_factors": None, "source_cells": None})) == []


def test_coverage_tallies_all_four_states():
    ents = [
        {"grounding_status": "resolved"},
        {"grounding_status": "resolved"},
        {"grounding_status": "needs_review"},
        {"grounding_status": "not_found"},
    ]
    c = gp.coverage(ents)
    assert c == {"total": 4, "resolved": 2, "needs_review": 1, "not_found": 1, "not_attempted": 0}


def test_coverage_empty():
    assert gp.coverage([])["total"] == 0
