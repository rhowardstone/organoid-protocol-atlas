"""
Schema-conformance for the stage-aware protocol model (issue #178, `stages-gold/v0.2`).

This is the *structural* contract for any `stages[]` document — whether emitted by the
A100 extractor (`pipeline/extract_stages_prototype.py`) or hand-verified as gold. It
deliberately checks STRUCTURE and a few hard invariants only; *correctness* of an
extraction (did it find the right stages/reagents/days) is scored separately against
human gold by test_stages_eval.py. Keeping the two apart means a structurally-valid but
wrong extraction fails the scorer, not the schema — which is the honest split.

Field names track the production extractor's output verbatim (A100 asked QA to align so
conformance scoring is direct):

    doc:
      is_generation_protocol : bool                       (the scope gate, finding #3)
      source_cells           : str | null
      final_organoid         : str | null
      assay_endpoints        : list[str]                  (readouts live here, NOT in stages)
      stages                 : list[stage]

    stage:
      name          : non-empty str
      start_day     : int | null                          (null is VALID — procedure-keyed
      end_day       : int | null                           protocols use transitions, not days)
      culture_vessel: str | null
      medium_base   : str | null
      reagents      : list[reagent]
      transition    : str | null                          (what triggers the next stage)

    reagent:
      name          : non-empty str
      concentration : number | null
      unit          : str | null
      role          : str | null

Hard invariants beyond types:
  - when BOTH start_day and end_day are present, start_day <= end_day
  - stages with both days present must be non-overlapping and in ascending order
  - a stage name must not be a characterization assay (finding #1: Western/ELISA/MTT/
    IncuCyte/clonogenic/qPCR etc. belong in assay_endpoints, not stages)
  - if is_generation_protocol is true, stages must be non-empty
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "stages_prototype"

# Assay / readout terms that must never appear as a *stage* name (finding #1 scope creep).
ASSAY_TERMS = (
    "western", "elisa", "incucyte", "clonogenic", "qpcr", "rt-pcr", "rt pcr",
    "immunofluoresc", "immunohisto", "histolog", "mtt", "flow cytometry",
    "facs", "sequencing", "rna extraction", "statistical analysis", "teer measurement",
)

_NUM = (int, float)


def validate_stages_doc(doc: dict) -> list[str]:
    """Return a list of human-readable conformance violations. Empty list == conforms."""
    v: list[str] = []

    if not isinstance(doc, dict):
        return [f"doc is {type(doc).__name__}, expected object"]

    if not isinstance(doc.get("is_generation_protocol"), bool):
        v.append("is_generation_protocol must be a bool")

    for f in ("source_cells", "final_organoid"):
        if doc.get(f) is not None and not isinstance(doc.get(f), str):
            v.append(f"{f} must be str or null")

    ae = doc.get("assay_endpoints")
    if not isinstance(ae, list) or any(not isinstance(x, str) for x in ae or []):
        v.append("assay_endpoints must be a list[str]")

    stages = doc.get("stages")
    if not isinstance(stages, list):
        return v + ["stages must be a list"]

    if doc.get("is_generation_protocol") is True and not stages:
        v.append("is_generation_protocol is true but stages is empty")

    day_intervals: list[tuple[int, int, int]] = []  # (start, end, index)
    for i, s in enumerate(stages):
        where = f"stages[{i}]"
        if not isinstance(s, dict):
            v.append(f"{where} is not an object")
            continue

        name = s.get("name")
        if not isinstance(name, str) or not name.strip():
            v.append(f"{where}.name must be a non-empty str")
        elif any(term in name.lower() for term in ASSAY_TERMS):
            v.append(f"{where}.name {name!r} looks like an assay/readout — belongs in assay_endpoints (finding #1)")

        for f in ("start_day", "end_day"):
            val = s.get(f)
            if val is not None and not isinstance(val, int):
                v.append(f"{where}.{f} must be int or null, got {type(val).__name__}")

        for f in ("culture_vessel", "medium_base", "transition"):
            if s.get(f) is not None and not isinstance(s.get(f), str):
                v.append(f"{where}.{f} must be str or null")

        sd, ed = s.get("start_day"), s.get("end_day")
        if isinstance(sd, int) and isinstance(ed, int):
            if sd > ed:
                v.append(f"{where} start_day {sd} > end_day {ed}")
            else:
                day_intervals.append((sd, ed, i))

        reagents = s.get("reagents")
        if not isinstance(reagents, list):
            v.append(f"{where}.reagents must be a list")
            continue
        for j, r in enumerate(reagents):
            rwhere = f"{where}.reagents[{j}]"
            if not isinstance(r, dict):
                v.append(f"{rwhere} is not an object")
                continue
            if not isinstance(r.get("name"), str) or not r.get("name").strip():
                v.append(f"{rwhere}.name must be a non-empty str")
            if r.get("concentration") is not None and not isinstance(r.get("concentration"), _NUM):
                v.append(f"{rwhere}.concentration must be a number or null")
            for f in ("unit", "role"):
                if r.get(f) is not None and not isinstance(r.get(f), str):
                    v.append(f"{rwhere}.{f} must be str or null")

    # Ordering / non-overlap on the day-keyed stages only (procedure-keyed nulls are exempt).
    ordered = sorted(day_intervals, key=lambda t: (t[0], t[1]))
    if [t[2] for t in day_intervals] != [t[2] for t in ordered]:
        v.append("day-keyed stages are not in ascending day order")
    for a, b in zip(ordered, ordered[1:]):
        if b[0] < a[1]:
            v.append(f"day-keyed stages overlap: stages[{a[2]}] [{a[0]},{a[1]}] vs stages[{b[2]}] [{b[0]},{b[1]}]")

    return v


# --------------------------------------------------------------------------- #
# The committed prototype outputs must be STRUCTURALLY valid (not necessarily
# correct — that's the scorer's job).
# --------------------------------------------------------------------------- #

_FIXTURES = sorted(FIXTURES.glob("*.json")) if FIXTURES.exists() else []

# Known non-conformance in the v2 prototype (d662cf3), reported to A100 on #178.
# strict=True: when A100 fixes the extractor these XPASS and the suite goes red,
# forcing us to drop the marker — i.e. the marker is a live tracker, not a mute.
# Same discipline as the #171 strict-xfail.
_KNOWN_NONCONFORMANT = {
    "PMC10000618.v2.json": "v2 emits reagent.concentration as strings ('10','1×') not numbers — #178 finding A",
    "PMC10005775.v2.json": "v2 emits overlapping/inconsistent stage day-ranges (stage 'Days 1-10' carries [6,16], overlaps [5,10]) — #178 finding B",
}


def _mark(path):
    reason = _KNOWN_NONCONFORMANT.get(path.name)
    marks = [pytest.mark.xfail(reason=reason, strict=True)] if reason else []
    return pytest.param(path, id=path.name, marks=marks)


@pytest.mark.parametrize("path", [_mark(p) for p in _FIXTURES])
def test_prototype_outputs_are_structurally_conformant(path):
    doc = json.loads(path.read_text())
    violations = validate_stages_doc(doc)
    assert not violations, f"{path.name} conformance violations:\n  " + "\n  ".join(violations)


def test_fixtures_present():
    """Guard against the fixtures being dropped — the conformance suite is meaningless empty."""
    assert len(_FIXTURES) >= 3, f"expected >=3 vendored prototype fixtures, found {len(_FIXTURES)}"


# --------------------------------------------------------------------------- #
# Targeted invariant tests (synthetic docs — prove the validator has teeth).
# --------------------------------------------------------------------------- #

def _ok_doc(**over):
    doc = {
        "is_generation_protocol": True,
        "source_cells": "iPSC",
        "final_organoid": "cerebral",
        "assay_endpoints": ["Western Blot"],
        "stages": [
            {"name": "EB aggregation", "start_day": 0, "end_day": 5, "culture_vessel": "96-well",
             "medium_base": "E6", "transition": "neural diff",
             "reagents": [{"name": "SB431542", "concentration": 10, "unit": "uM", "role": "inhibitor"}]},
            {"name": "Neural differentiation", "start_day": 6, "end_day": 24, "culture_vessel": None,
             "medium_base": None, "transition": None, "reagents": []},
        ],
    }
    doc.update(over)
    return doc


def test_clean_doc_conforms():
    assert validate_stages_doc(_ok_doc()) == []


def test_procedure_keyed_null_days_conform():
    """Null days are valid (intestinal/TEER-keyed protocols) — must NOT be flagged."""
    doc = _ok_doc(stages=[
        {"name": "Colonoid expansion", "start_day": None, "end_day": None, "culture_vessel": "24-well",
         "medium_base": None, "transition": "TEER > 150 Ohm/cm2",
         "reagents": [{"name": "Y-27632", "concentration": 10, "unit": "uM", "role": "proliferation"}]},
    ])
    assert validate_stages_doc(doc) == []


def test_assay_named_stage_is_flagged():
    doc = _ok_doc(stages=[{"name": "Western Blot Analysis", "start_day": None, "end_day": None,
                           "culture_vessel": None, "medium_base": None, "transition": None, "reagents": []}])
    assert any("assay" in x for x in validate_stages_doc(doc))


def test_overlapping_day_stages_flagged():
    doc = _ok_doc(stages=[
        {"name": "A", "start_day": 0, "end_day": 10, "culture_vessel": None, "medium_base": None,
         "transition": None, "reagents": []},
        {"name": "B", "start_day": 5, "end_day": 15, "culture_vessel": None, "medium_base": None,
         "transition": None, "reagents": []},
    ])
    assert any("overlap" in x for x in validate_stages_doc(doc))


def test_inverted_day_range_flagged():
    doc = _ok_doc(stages=[{"name": "A", "start_day": 10, "end_day": 2, "culture_vessel": None,
                           "medium_base": None, "transition": None, "reagents": []}])
    assert any("start_day" in x and ">" in x for x in validate_stages_doc(doc))


def test_generation_protocol_requires_stages():
    assert any("stages is empty" in x for x in validate_stages_doc(_ok_doc(stages=[])))


def test_reagent_missing_name_flagged():
    doc = _ok_doc(stages=[{"name": "A", "start_day": None, "end_day": None, "culture_vessel": None,
                           "medium_base": None, "transition": None,
                           "reagents": [{"name": "", "concentration": 1, "unit": "uM", "role": "x"}]}])
    assert any("name must be a non-empty str" in x for x in validate_stages_doc(doc))
