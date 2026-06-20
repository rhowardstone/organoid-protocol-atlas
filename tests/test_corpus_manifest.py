import csv
from collections import Counter
from pathlib import Path


def test_verified_seed_manifest_counts():
    path = Path(__file__).resolve().parent.parent / "data" / "corpus" / "organoid_corpus_seed_verified_28.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))

    assert len(rows) == 28
    assert len({r["pmcid"] for r in rows}) == 28
    assert Counter(r["organoid_type"] for r in rows) == {
        "intestinal": 3,
        "gastric": 3,
        "cerebral": 5,
        "kidney": 3,
        "liver": 4,
        "lung": 4,
        "pancreatic": 3,
        "retinal": 3,
    }
    assert Counter(r["priority_tier"] for r in rows) == {
        "gold_candidate": 13,
        "dev_seed": 15,
    }


def test_incoming_candidates_are_not_accepted_corpus():
    path = Path(__file__).resolve().parent.parent / "data" / "corpus" / "incoming" / "organoid_corpus_candidates_180.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))

    assert len(rows) == 180
    assert len({r["pmcid"] for r in rows}) == 180
    assert Counter(r["organoid_type"] for r in rows) == {
        "cardiac": 18,
        "cerebral": 18,
        "gastric": 18,
        "intestinal": 18,
        "kidney": 18,
        "liver": 18,
        "lung": 18,
        "pancreatic": 18,
        "retinal": 18,
        "vascular": 18,
    }
    assert {r["in_current_corpus"] for r in rows} == {"yes", "no"}

