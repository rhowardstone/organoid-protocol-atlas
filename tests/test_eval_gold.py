"""
S3 gold-eval tests — OFFLINE, inline fake gold+pred dicts only. No network, no
disk fixtures. These pin the honesty contract: only human-verified gold is ever
scored, and the pure scoring functions return the exact P/R/F1 we expect.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import eval_gold  # noqa: E402


# --------------------------------------------------------------------------- #
# is_verified
# --------------------------------------------------------------------------- #
def test_is_verified_true_only_for_real_human():
    assert eval_gold.is_verified({"verified_by": "RHS"}) is True
    assert eval_gold.is_verified({"verified_by": "Jane Doe"}) is True


def test_is_verified_false_for_missing_empty_and_sentinels():
    assert eval_gold.is_verified({}) is False
    assert eval_gold.is_verified({"verified_by": None}) is False
    assert eval_gold.is_verified({"verified_by": ""}) is False
    assert eval_gold.is_verified({"verified_by": "   "}) is False
    assert eval_gold.is_verified({"verified_by": "tbd"}) is False
    assert eval_gold.is_verified({"verified_by": "TBD"}) is False
    assert eval_gold.is_verified({"verified_by": "pending"}) is False
    assert eval_gold.is_verified({"verified_by": "none"}) is False


# --------------------------------------------------------------------------- #
# score_set_field
# --------------------------------------------------------------------------- #
def test_set_field_perfect_match():
    gold = [{"name": "Activin A"}, {"name": "R-Spondin1"}]
    pred = [{"name": "activin a"}, {"name": "r spondin1"}]  # normalize-equal
    s = eval_gold.score_set_field(gold, pred)
    assert (s["tp"], s["fp"], s["fn"]) == (2, 0, 0)
    assert s["precision"] == 1.0 and s["recall"] == 1.0 and s["f1"] == 1.0


def test_set_field_one_miss_and_one_spurious():
    # gold has A,B,C ; pred has A,B (miss C) and D (spurious)
    gold = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    pred = [{"name": "A"}, {"name": "B"}, {"name": "D"}]
    s = eval_gold.score_set_field(gold, pred)
    assert (s["tp"], s["fp"], s["fn"]) == (2, 1, 1)
    assert s["precision"] == round(2 / 3, 4)
    assert s["recall"] == round(2 / 3, 4)
    assert s["f1"] == round(2 / 3, 4)


def test_set_field_empty_inputs_no_zero_division():
    assert eval_gold.score_set_field([], []) == {
        "tp": 0, "fp": 0, "fn": 0, "precision": 0.0, "recall": 0.0, "f1": 0.0
    }
    s = eval_gold.score_set_field([{"name": "X"}], [])
    assert (s["tp"], s["fp"], s["fn"]) == (0, 0, 1)
    assert s["precision"] == 0.0 and s["recall"] == 0.0
    s = eval_gold.score_set_field([], [{"name": "X"}])
    assert (s["tp"], s["fp"], s["fn"]) == (0, 1, 0)


def test_set_field_collapses_duplicate_predictions():
    gold = [{"name": "EGF"}]
    pred = [{"name": "EGF"}, {"name": "egf"}, {"name": ""}]  # dup + blank
    s = eval_gold.score_set_field(gold, pred)
    assert (s["tp"], s["fp"], s["fn"]) == (1, 0, 0)


# --------------------------------------------------------------------------- #
# score_scalar_field
# --------------------------------------------------------------------------- #
def test_scalar_statuses():
    assert eval_gold.score_scalar_field("Matrigel", "matrigel")["status"] == "correct"
    assert eval_gold.score_scalar_field("Matrigel", "Cultrex")["status"] == "incorrect"
    assert eval_gold.score_scalar_field("Matrigel", None)["status"] == "missing"
    assert eval_gold.score_scalar_field(None, "Matrigel")["status"] == "not_in_gold"


# --------------------------------------------------------------------------- #
# score_paper — small mixed example with known numbers
# --------------------------------------------------------------------------- #
def _mixed_gold():
    return {
        "verified_by": "RHS",
        "gold": {
            "source_cells": {"cell_type": "ESC"},
            "matrix": {"name": "Matrigel"},
            "base_media": {"value": "Advanced DMEM/F12"},
            "signaling_factors": [{"name": "Activin A"}, {"name": "FGF4"}, {"name": "EGF"}],
            "small_molecules": [{"name": "CHIR99021"}],
        },
    }


def _mixed_pred():
    return {
        "source_cells": {"cell_type": "ESC"},          # correct
        "matrix": {"name": "Cultrex"},                  # incorrect
        "base_media": {"name": None},                   # missing
        # factors: Activin A + FGF4 hit, EGF missed, Wnt3a spurious
        "signaling_factors": [{"name": "activin a"}, {"name": "FGF4"}, {"name": "Wnt3a"}],
        "small_molecules": [{"name": "CHIR99021"}],     # perfect
    }


def test_score_paper_known_numbers():
    res = eval_gold.score_paper(_mixed_gold(), _mixed_pred())

    sf = res["set_fields"]["signaling_factors"]
    assert (sf["tp"], sf["fp"], sf["fn"]) == (2, 1, 1)
    assert sf["precision"] == round(2 / 3, 4) and sf["recall"] == round(2 / 3, 4)

    sm = res["set_fields"]["small_molecules"]
    assert (sm["tp"], sm["fp"], sm["fn"]) == (1, 0, 0)
    assert sm["f1"] == 1.0

    scal = res["scalar_fields"]
    assert scal["source_cells.cell_type"]["status"] == "correct"
    assert scal["matrix"]["status"] == "incorrect"
    assert scal["base_media"]["status"] == "missing"


def test_aggregate_micro_and_macro():
    scores = {"P1": eval_gold.score_paper(_mixed_gold(), _mixed_pred())}
    agg = eval_gold.aggregate(scores)
    assert agg["papers_scored"] == 1
    sf = agg["set_fields"]["signaling_factors"]
    assert sf["micro"]["tp"] == 2 and sf["micro"]["fp"] == 1 and sf["micro"]["fn"] == 1
    assert sf["macro"]["papers_with_support"] == 1
    assert agg["scalar_fields"]["source_cells.cell_type"]["accuracy"] == 1.0
    assert agg["scalar_fields"]["matrix"]["accuracy"] == 0.0


# --------------------------------------------------------------------------- #
# runner SKIPS unverified gold and never counts it
# --------------------------------------------------------------------------- #
def test_run_eval_skips_unverified(tmp_path):
    gold_dir = tmp_path / "gold"
    pred_dir = tmp_path / "pred"
    gold_dir.mkdir()
    pred_dir.mkdir()

    import json
    # one verified, one unverified — both have predictions present
    (gold_dir / "PMC1.json").write_text(json.dumps(_mixed_gold()))
    unver = _mixed_gold()
    unver["verified_by"] = None
    (gold_dir / "PMC2.json").write_text(json.dumps(unver))
    (pred_dir / "PMC1.json").write_text(json.dumps(_mixed_pred()))
    (pred_dir / "PMC2.json").write_text(json.dumps(_mixed_pred()))

    art = eval_gold.run_eval(gold_dir, pred_dir)
    assert art["provenance"]["verified_count"] == 1
    assert art["provenance"]["skipped_unverified_count"] == 1
    assert art["is_real_metric"] is True
    assert [v["pmcid"] for v in art["verified_gold_scored"]] == ["PMC1"]
    assert [s["pmcid"] for s in art["skipped_unverified"]] == ["PMC2"]
    # PMC2 must NOT appear anywhere in the scored numbers
    assert set(art["per_paper"].keys()) == {"PMC1"}


def test_run_eval_zero_verified_is_not_real_metric(tmp_path):
    gold_dir = tmp_path / "gold"
    pred_dir = tmp_path / "pred"
    gold_dir.mkdir()
    pred_dir.mkdir()
    import json
    unver = _mixed_gold()
    unver["verified_by"] = None
    (gold_dir / "PMC1.json").write_text(json.dumps(unver))
    (pred_dir / "PMC1.json").write_text(json.dumps(_mixed_pred()))

    art = eval_gold.run_eval(gold_dir, pred_dir)
    assert art["is_real_metric"] is False
    assert art["provenance"]["verified_count"] == 0
    assert art["aggregate"]["papers_scored"] == 0
