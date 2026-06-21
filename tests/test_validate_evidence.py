"""
Offline tests for the evidence-fidelity validator harness (pipeline/validate_evidence.py).
Pure functions only — the LLM judging step is out of scope (its output is the committed
verdicts artifact).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import validate_evidence as ve  # noqa: E402


def _row(id, t, q="100 ng/mL X", v=100.0):
    return {"id": id, "name": "X", "value": v, "unit": "ng/mL", "role": "signaling",
            "organoid_type": t, "pmcid": f"PMC{id}", "doi": "", "evidence_quote": q}


def test_eligible_requires_quote_and_value():
    assert ve.eligible(_row(1, "gut"))
    assert not ve.eligible({**_row(1, "gut"), "value": None})
    assert not ve.eligible({**_row(1, "gut"), "evidence_quote": "  "})


def test_sample_is_deterministic_and_eligible_only():
    rows = [_row(i, ["a", "b", "c"][i % 3]) for i in range(30)]
    rows.append({**_row(99, "a"), "value": None})  # ineligible
    s1 = ve.sample_records(rows, 9)
    s2 = ve.sample_records(rows, 9)
    assert [r["id"] for r in s1] == [r["id"] for r in s2]  # deterministic
    assert 99 not in {r["id"] for r in s1}                 # ineligible excluded
    assert len(s1) == 9


def test_sample_is_stratified_round_robin():
    rows = [_row(i, ["a", "b", "c"][i % 3]) for i in range(30)]
    s = ve.sample_records(rows, 6)
    from collections import Counter
    c = Counter(r["organoid_type"] for r in s)
    assert set(c) == {"a", "b", "c"} and all(v == 2 for v in c.values())  # even across types


def test_sample_returns_only_judge_fields():
    s = ve.sample_records([_row(1, "a")], 1)
    assert set(s[0]) == set(ve.SAMPLE_FIELDS)


def test_aggregate_counts_rates_and_flags():
    verdicts = [
        {"id": 1, "verdict": "supported"}, {"id": 2, "verdict": "supported"},
        {"id": 3, "verdict": "partial"}, {"id": 4, "verdict": "unsupported", "reason": "wrong reagent"},
        {"id": 5, "verdict": "garbage"},  # invalid bucket
    ]
    a = ve.aggregate(verdicts)
    assert a["total"] == 5 and a["supported"] == 2 and a["partial"] == 1
    assert a["unsupported"] == 1 and a["invalid"] == 1
    # rates computed over scored (supported+partial+unsupported = 4)
    assert a["fidelity_supported_rate"] == round(2 / 4, 4)
    assert a["fidelity_supported_or_partial_rate"] == round(3 / 4, 4)
    assert a["flagged_unsupported"] == [4]


def test_aggregate_empty_no_zero_division():
    a = ve.aggregate([])
    assert a["total"] == 0 and a["fidelity_supported_rate"] == 0.0
