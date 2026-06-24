"""Guards the build_kg -> export_public stages[] carry-through seam (#178 / #226 / #228).

build_kg stores stages[] as JSON text in protocols.stages; export_public must re-parse it
to a real array so the recipe renderer (#228) sees `p.stages` as a list. Absent stages must
emit [] (so the renderer degrades to the timeline fallback) — no regression on pre-stages data.
"""
import json
import sqlite3


def _emit_row(r: sqlite3.Row) -> dict:
    """Mirror the export_public.py emission transform for the stages columns."""
    row = {k: r[k] for k in r.keys()}
    if "stages" in row:
        try:
            row["stages"] = json.loads(row["stages"]) if row["stages"] else []
        except (TypeError, ValueError):
            row["stages"] = []
    if "is_generation_protocol" in row and row["is_generation_protocol"] is not None:
        row["is_generation_protocol"] = bool(row["is_generation_protocol"])
    return row


def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE protocols(pmcid TEXT, stages TEXT, is_generation_protocol INTEGER)")
    return con


def test_stages_roundtrip_to_array():
    stage = [{"name": "Seeding", "start_day": 0, "end_day": 5,
              "reagents": [{"name": "dorsomorphin", "concentration": 2.5, "unit": "µM", "role": "inhibitor"}],
              "transition": "Day 7: add microglia"}]
    con = _db()
    con.execute("INSERT INTO protocols VALUES (?,?,?)", ("PMC1", json.dumps(stage), 1))
    row = _emit_row(next(iter(con.execute("SELECT * FROM protocols"))))
    assert isinstance(row["stages"], list) and len(row["stages"]) == 1
    assert row["stages"][0]["reagents"][0]["name"] == "dorsomorphin"
    assert row["is_generation_protocol"] is True
    # the emitted row must be valid JSONL the renderer can read p.stages from
    assert json.loads(json.dumps(row))["stages"][0]["start_day"] == 0


def test_absent_stages_emit_empty_no_regression():
    con = _db()
    con.execute("INSERT INTO protocols VALUES (?,?,?)", ("PMC2", None, None))
    row = _emit_row(next(iter(con.execute("SELECT * FROM protocols"))))
    assert row["stages"] == []                      # renderer falls back to timeline
    assert row["is_generation_protocol"] is None


def test_malformed_stages_degrade_safely():
    con = _db()
    con.execute("INSERT INTO protocols VALUES (?,?,?)", ("PMC3", "{not json", 0))
    row = _emit_row(next(iter(con.execute("SELECT * FROM protocols"))))
    assert row["stages"] == []
    assert row["is_generation_protocol"] is False
