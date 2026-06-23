"""
Offline tests for the marathon driver's pool selection (marathon_ingest.load_pool):
public-license filtering + newest-first ordering. No orchestrator, no network.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import marathon_ingest as mi  # noqa: E402


def _write(tmp_path, rows):
    p = tmp_path / "cand.csv"
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["pmcid", "license", "year"])
        w.writeheader()
        w.writerows(rows)
    return p


def test_cc_only_keeps_public_licenses(tmp_path):
    p = _write(tmp_path, [
        {"pmcid": "A", "license": "CC-BY", "year": "2021"},
        {"pmcid": "B", "license": "CC-BY-NC", "year": "2022"},
        {"pmcid": "C", "license": "CC0", "year": "2020"},
        {"pmcid": "D", "license": "unknown", "year": "2023"},
    ])
    ids = [r["pmcid"] for r in mi.load_pool(p, cc_only=True)]
    assert set(ids) == {"A", "C"}                 # NC and unknown dropped


def test_all_licenses_keeps_everything(tmp_path):
    p = _write(tmp_path, [
        {"pmcid": "A", "license": "CC-BY", "year": "2021"},
        {"pmcid": "B", "license": "CC-BY-NC", "year": "2022"},
    ])
    assert len(mi.load_pool(p, cc_only=False)) == 2


def test_newest_first_ordering(tmp_path):
    p = _write(tmp_path, [
        {"pmcid": "old", "license": "CC-BY", "year": "2015"},
        {"pmcid": "new", "license": "CC-BY", "year": "2025"},
        {"pmcid": "mid", "license": "CC-BY", "year": "2020"},
        {"pmcid": "blank", "license": "CC-BY", "year": ""},   # unknown year sorts last
    ])
    ids = [r["pmcid"] for r in mi.load_pool(p, cc_only=True)]
    assert ids == ["new", "mid", "old", "blank"]
