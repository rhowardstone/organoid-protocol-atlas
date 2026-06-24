"""
Scorer for stage-aware extraction (#178) — predicted `stages[]` vs HUMAN-verified gold.

Four metrics, each isolating one failure mode so we know *what* an extractor got wrong
(mirrors the design posted to #178 and the conventions in pipeline/eval_gold.py):

  1. stage segmentation  — match pred↔gold stages, report precision/recall/F1.
       A pred matches a gold stage if their day ranges overlap (IoU >= 0.5) OR their
       names normalise equal. Catches over-/under-splitting (the v2 prototype's empty
       "Dissociation"/"Medium Refresh" stages would tank precision here).
  2. stage count error   — |n_pred - n_gold|.
  3. per-stage reagent P/R/F1 — over matched stage pairs, set overlap on reagent names.
       Catches "right reagent, wrong stage".
  4. stage-attribution accuracy — of gold reagents the pred found *anywhere*, the
       fraction it placed in the correct (matched) stage. Cleanly separates
       "found the reagent" (already measured by the flat harness) from "knew when".

This module is QA-owned (tests/). It does NOT author gold — the gold-scoring test is
skipped until human-verified gold exists under gold/verified/<pmcid>.stages.json with a
real `verified_by`. The synthetic self-tests below prove the scorer itself is correct.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GOLD_VERIFIED = REPO / "gold" / "verified"
FIXTURES = REPO / "tests" / "fixtures" / "stages_prototype"


# --------------------------------------------------------------------------- #
# Scorer
# --------------------------------------------------------------------------- #

def _norm(s) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _day_iou(a: dict, b: dict) -> float | None:
    """Interval IoU on [start_day, end_day]; None if either lacks both days."""
    if not all(isinstance(x.get(k), int) for x in (a, b) for k in ("start_day", "end_day")):
        return None
    a0, a1, b0, b1 = a["start_day"], a["end_day"], b["start_day"], b["end_day"]
    inter = max(0, min(a1, b1) - max(a0, b0))
    union = (a1 - a0) + (b1 - b0) - inter
    return inter / union if union > 0 else (1.0 if a0 == b0 else 0.0)


def _stage_matches(pred: dict, gold: dict) -> bool:
    iou = _day_iou(pred, gold)
    if iou is not None and iou >= 0.5:
        return True
    return _norm(pred.get("name")) == _norm(gold.get("name")) and bool(_norm(gold.get("name")))


def _match_stages(pred_stages: list[dict], gold_stages: list[dict]) -> list[tuple[int, int]]:
    """Greedy 1:1 matching pred->gold. Returns list of (pred_idx, gold_idx)."""
    pairs, used_gold = [], set()
    for pi, ps in enumerate(pred_stages):
        for gi, gs in enumerate(gold_stages):
            if gi in used_gold:
                continue
            if _stage_matches(ps, gs):
                pairs.append((pi, gi))
                used_gold.add(gi)
                break
    return pairs


def _prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * p * r / (p + r)) if (p + r) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4)}


def _reagent_names(stage: dict) -> set[str]:
    return {_norm(r.get("name")) for r in stage.get("reagents", []) if _norm(r.get("name"))}


def score_stages(pred: dict, gold: dict) -> dict:
    _gold_body = gold.get("gold", gold)  # support nested {gold:{stages}} or flat {stages}
    ps, gs = pred.get("stages", []), _gold_body.get("stages", [])
    pairs = _match_stages(ps, gs)
    matched_pred = {pi for pi, _ in pairs}
    matched_gold = {gi for _, gi in pairs}

    segmentation = _prf(tp=len(pairs), fp=len(ps) - len(matched_pred), fn=len(gs) - len(matched_gold))

    # per-stage reagent overlap, summed over matched pairs
    rtp = rfp = rfn = 0
    attr_correct = attr_total_found = 0
    gold_to_pred = {gi: pi for pi, gi in pairs}
    all_pred_reagents = set().union(*[_reagent_names(s) for s in ps]) if ps else set()
    for pi, gi in pairs:
        gset, pset = _reagent_names(gs[gi]), _reagent_names(ps[pi])
        rtp += len(gset & pset)
        rfp += len(pset - gset)
        rfn += len(gset - pset)
    # stage-attribution: for each gold reagent found anywhere in pred, was it in the matched stage?
    for gi, gstage in enumerate(gs):
        pi = gold_to_pred.get(gi)
        pset = _reagent_names(ps[pi]) if pi is not None else set()
        for name in _reagent_names(gstage):
            if name in all_pred_reagents:
                attr_total_found += 1
                if name in pset:
                    attr_correct += 1

    return {
        "stage_count_pred": len(ps),
        "stage_count_gold": len(gs),
        "stage_count_error": abs(len(ps) - len(gs)),
        "segmentation": segmentation,
        "reagent_linkage": _prf(rtp, rfp, rfn),
        "stage_attribution_accuracy": round(attr_correct / attr_total_found, 4) if attr_total_found else None,
    }


# --------------------------------------------------------------------------- #
# Self-tests — prove the scorer is correct on synthetic data
# --------------------------------------------------------------------------- #

def _stage(name, sd=None, ed=None, reagents=()):
    return {"name": name, "start_day": sd, "end_day": ed, "culture_vessel": None,
            "medium_base": None, "transition": None,
            "reagents": [{"name": n, "concentration": 1, "unit": "uM", "role": "x"} for n in reagents]}


def test_perfect_match_scores_one():
    doc = {"stages": [_stage("EB", 0, 5, ["SB431542", "dorsomorphin"]), _stage("Neural", 6, 24, ["EGF"])]}
    s = score_stages(doc, doc)
    assert s["segmentation"]["f1"] == 1.0
    assert s["reagent_linkage"]["f1"] == 1.0
    assert s["stage_attribution_accuracy"] == 1.0
    assert s["stage_count_error"] == 0


def test_over_segmentation_hurts_precision():
    gold = {"stages": [_stage("EB", 0, 5, ["SB431542"])]}
    pred = {"stages": [_stage("EB", 0, 5, ["SB431542"]), _stage("Empty refresh", None, None, [])]}
    s = score_stages(pred, gold)
    assert s["segmentation"]["recall"] == 1.0
    assert s["segmentation"]["precision"] == 0.5  # one spurious stage
    assert s["stage_count_error"] == 1


def test_right_reagent_wrong_stage_caught_by_attribution():
    gold = {"stages": [_stage("EB", 0, 5, ["SB431542"]), _stage("Neural", 6, 24, ["EGF"])]}
    # pred finds both reagents but puts EGF in the EB stage
    pred = {"stages": [_stage("EB", 0, 5, ["SB431542", "EGF"]), _stage("Neural", 6, 24, [])]}
    s = score_stages(pred, gold)
    assert s["stage_attribution_accuracy"] == 0.5  # SB431542 right, EGF misattributed
    assert s["reagent_linkage"]["fp"] == 1  # EGF in wrong stage counts as a linkage FP


def test_name_match_when_days_absent():
    gold = {"stages": [_stage("Colonoid expansion", None, None, ["Y-27632"])]}
    pred = {"stages": [_stage("colonoid  expansion", None, None, ["Y-27632"])]}
    assert score_stages(pred, gold)["segmentation"]["f1"] == 1.0


# --------------------------------------------------------------------------- #
# Gold-gated real scoring — dormant until human gold exists (QA must not author gold)
# --------------------------------------------------------------------------- #

def _verified_gold_stage_files():
    if not GOLD_VERIFIED.exists():
        return []
    out = []
    for p in GOLD_VERIFIED.glob("*.stages.json"):
        try:
            g = json.loads(p.read_text())
        except Exception:
            continue
        vb = (g.get("verified_by") or "").strip().lower()
        if vb and vb not in {"tbd", "none", "null"}:
            out.append(p)
    return out


_GOLD = _verified_gold_stage_files()


@pytest.mark.skipif(not _GOLD, reason="no human-verified gold/verified/*.stages.json yet (see #178 annotation guide)")
@pytest.mark.parametrize("gold_path", _GOLD, ids=lambda p: p.name)
def test_extractor_meets_gold_thresholds(gold_path):
    """Score the committed extractor output for a paper against its human gold.
    Thresholds are intentionally modest for v0.2 and will tighten as the prompt matures."""
    gold = json.loads(gold_path.read_text())
    pmcid = gold.get("pmcid") or gold_path.name.split(".")[0]
    pred_path = FIXTURES / f"{pmcid}.v2.json"
    if not pred_path.exists():
        pytest.skip(f"no extractor output vendored for {pmcid}")
    s = score_stages(json.loads(pred_path.read_text()), gold)
    assert s["segmentation"]["f1"] >= 0.6, f"{pmcid} stage segmentation F1 {s['segmentation']['f1']} < 0.6: {s}"
    assert s["reagent_linkage"]["f1"] >= 0.5, f"{pmcid} reagent-linkage F1 {s['reagent_linkage']['f1']} < 0.5: {s}"
