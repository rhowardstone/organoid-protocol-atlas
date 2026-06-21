"""
Offline tests for reagent_lookup pure logic.
No network, no filesystem reads from the actual corpus.
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import reagent_lookup as rl


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _r(
    canonical="EGF",
    name="EGF",
    organoid_type="intestinal",
    pmcid="PMC001",
    kind="signaling",
    value=None,
    unit=None,
    canonical_unit=None,
    grounded=1,
    figure_confirmed=0,
    evidence_quote="EGF was added at 50 ng/mL",
) -> dict:
    return {
        "canonical": canonical,
        "name": name,
        "organoid_type": organoid_type,
        "pmcid": pmcid,
        "kind": kind,
        "value": value,
        "unit": unit,
        "canonical_unit": canonical_unit,
        "grounded": grounded,
        "figure_confirmed": figure_confirmed,
        "evidence_quote": evidence_quote,
    }


# --------------------------------------------------------------------------- #
# _matches
# --------------------------------------------------------------------------- #

def test_matches_case_insensitive():
    assert rl._matches("EGF", "egf")
    assert rl._matches("egf", "EGF")

def test_matches_substring():
    assert rl._matches("R-spondin1", "spondin")

def test_matches_none_text():
    assert not rl._matches(None, "EGF")

def test_matches_empty_text():
    assert not rl._matches("", "EGF")

def test_matches_no_match():
    assert not rl._matches("Noggin", "CHIR")


# --------------------------------------------------------------------------- #
# search_reagents
# --------------------------------------------------------------------------- #

def test_search_reagents_basic():
    records = [
        _r(canonical="EGF", name="EGF"),
        _r(canonical="Noggin", name="Noggin"),
        _r(canonical="EGF variant", name="EGF variant"),
    ]
    hits = rl.search_reagents(records, "EGF")
    assert len(hits) == 2

def test_search_reagents_case_insensitive():
    records = [_r(canonical="CHIR99021")]
    hits = rl.search_reagents(records, "chir")
    assert len(hits) == 1

def test_search_reagents_no_match():
    records = [_r(canonical="EGF")]
    hits = rl.search_reagents(records, "Noggin")
    assert hits == []

def test_search_reagents_filters_by_type():
    records = [
        _r(canonical="EGF", organoid_type="intestinal"),
        _r(canonical="EGF", organoid_type="cardiac"),
    ]
    hits = rl.search_reagents(records, "EGF", organoid_type="intestinal")
    assert len(hits) == 1
    assert hits[0]["organoid_type"] == "intestinal"

def test_search_reagents_type_case_insensitive():
    records = [_r(canonical="EGF", organoid_type="Intestinal")]
    hits = rl.search_reagents(records, "EGF", organoid_type="intestinal")
    assert len(hits) == 1

def test_search_reagents_matches_raw_name():
    # If canonical doesn't match but name does, still returns hit
    records = [_r(canonical="Epidermal Growth Factor", name="EGF")]
    hits = rl.search_reagents(records, "EGF")
    assert len(hits) == 1


# --------------------------------------------------------------------------- #
# aggregate_reagent_hits
# --------------------------------------------------------------------------- #

def test_aggregate_empty():
    result = rl.aggregate_reagent_hits([])
    assert result["n_records"] == 0

def test_aggregate_counts_distinct_papers():
    records = [
        _r(pmcid="PMC001"),
        _r(pmcid="PMC001"),  # same paper, different record
        _r(pmcid="PMC002"),
    ]
    result = rl.aggregate_reagent_hits(records)
    assert result["n_papers"] == 2

def test_aggregate_usage_by_type():
    records = [
        _r(organoid_type="intestinal"),
        _r(organoid_type="intestinal"),
        _r(organoid_type="cardiac"),
    ]
    result = rl.aggregate_reagent_hits(records)
    assert result["usage_by_type"]["intestinal"] == 2
    assert result["usage_by_type"]["cardiac"] == 1

def test_aggregate_grounding_rate():
    records = [_r(grounded=1), _r(grounded=1), _r(grounded=0)]
    result = rl.aggregate_reagent_hits(records)
    assert result["grounding_rate"] == pytest.approx(2/3, abs=0.01)

def test_aggregate_figure_confirmed():
    records = [_r(figure_confirmed=1), _r(figure_confirmed=0)]
    result = rl.aggregate_reagent_hits(records)
    assert result["figure_confirmed_count"] == 1

def test_aggregate_concentration_stats():
    records = [
        _r(pmcid="PMC001", value=10.0, canonical_unit="ng/mL"),
        _r(pmcid="PMC002", value=20.0, canonical_unit="ng/mL"),
        _r(pmcid="PMC003", value=50.0, canonical_unit="ng/mL"),
    ]
    result = rl.aggregate_reagent_hits(records)
    conc = result["concentration"]
    assert conc["n_with_value"] == 3
    assert conc["min"] == 10.0
    assert conc["max"] == 50.0
    assert conc["median"] == pytest.approx(20.0)
    assert conc["dominant_unit"] == "ng/mL"

def test_aggregate_concentration_cv_computed():
    records = [
        _r(pmcid="PMC001", value=1.0, canonical_unit="µM"),
        _r(pmcid="PMC002", value=1000.0, canonical_unit="µM"),
    ]
    result = rl.aggregate_reagent_hits(records)
    conc = result["concentration"]
    assert conc.get("cv") is not None
    # For [1, 1000]: mean=500.5, sample_std≈706.4, cv≈1.41
    assert conc["cv"] > 1.0
    assert conc["high_variability"] is True

def test_aggregate_no_high_variability_when_consistent():
    records = [
        _r(pmcid="PMC001", value=10.0, canonical_unit="ng/mL"),
        _r(pmcid="PMC002", value=11.0, canonical_unit="ng/mL"),
    ]
    result = rl.aggregate_reagent_hits(records)
    assert not result["concentration"].get("high_variability")

def test_aggregate_evidence_examples_capped():
    records = [
        _r(pmcid=f"PMC{i:03d}", evidence_quote=f"quote {i}")
        for i in range(10)
    ]
    result = rl.aggregate_reagent_hits(records)
    assert len(result["evidence_examples"]) <= rl.MAX_EXAMPLES

def test_aggregate_evidence_examples_one_per_paper():
    records = [
        _r(pmcid="PMC001", evidence_quote="quote A"),
        _r(pmcid="PMC001", evidence_quote="quote B"),
        _r(pmcid="PMC002", evidence_quote="quote C"),
    ]
    result = rl.aggregate_reagent_hits(records)
    pmcids_in_examples = [ex["pmcid"] for ex in result["evidence_examples"]]
    assert len(set(pmcids_in_examples)) == len(pmcids_in_examples)


# --------------------------------------------------------------------------- #
# group_by_canonical
# --------------------------------------------------------------------------- #

def test_group_by_canonical():
    records = [
        _r(canonical="EGF"),
        _r(canonical="EGF"),
        _r(canonical="Noggin"),
    ]
    groups = rl.group_by_canonical(records)
    assert len(groups["EGF"]) == 2
    assert len(groups["Noggin"]) == 1


def test_group_by_canonical_falls_back_to_name():
    records = [_r(canonical=None, name="EGF")]
    groups = rl.group_by_canonical(records)
    assert "EGF" in groups


# --------------------------------------------------------------------------- #
# lookup
# --------------------------------------------------------------------------- #

def test_lookup_no_hits():
    records = [_r(canonical="EGF")]
    result = rl.lookup(records, "Noggin")
    assert result["n_hits"] == 0
    assert result["results"] == []

def test_lookup_finds_results():
    records = [
        _r(canonical="EGF", pmcid="PMC001"),
        _r(canonical="EGF", pmcid="PMC002"),
    ]
    result = rl.lookup(records, "EGF")
    assert result["n_hits"] == 2
    assert len(result["results"]) == 1
    assert result["results"][0]["canonical"] == "EGF"
    assert result["results"][0]["n_papers"] == 2

def test_lookup_min_papers_filter():
    records = [_r(canonical="Rare", pmcid="PMC001")]
    result = rl.lookup(records, "Rare", min_papers=2)
    assert result["n_hits"] == 1
    assert len(result["results"]) == 0  # filtered out

def test_lookup_respects_organoid_type():
    records = [
        _r(canonical="EGF", organoid_type="intestinal", pmcid="PMC001"),
        _r(canonical="EGF", organoid_type="cardiac", pmcid="PMC002"),
    ]
    result = rl.lookup(records, "EGF", organoid_type="cardiac")
    assert result["n_hits"] == 1
    assert result["results"][0]["n_papers"] == 1

def test_lookup_ranks_by_paper_count():
    records = (
        [_r(canonical="EGF", pmcid=f"PMC{i:03d}") for i in range(5)] +
        [_r(canonical="EGF variant", pmcid="PMC100")]
    )
    result = rl.lookup(records, "EGF")
    assert result["results"][0]["canonical"] == "EGF"

def test_lookup_caps_results():
    # Many distinct canonicals
    records = [_r(canonical=f"Reagent{i}", pmcid=f"PMC{i:03d}") for i in range(20)]
    result = rl.lookup(records, "Reagent")
    assert len(result["results"]) <= rl.MAX_RESULTS


# --------------------------------------------------------------------------- #
# load_reagents
# --------------------------------------------------------------------------- #

def test_load_reagents_missing_file():
    rows = rl.load_reagents(Path("/tmp/nonexistent_reagents_xyz.jsonl"))
    assert rows == []

def test_load_reagents_reads_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({"canonical": "EGF"}) + "\n")
        fname = Path(f.name)
    try:
        rows = rl.load_reagents(fname)
        assert len(rows) == 1
    finally:
        fname.unlink()
