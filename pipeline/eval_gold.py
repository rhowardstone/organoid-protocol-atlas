"""
S3 gold evaluation — score Tier-1 LLM predictions against HUMAN-VERIFIED gold.

This is the third Tier-S pillar (issue #8: S1 grounding -> S2 KGX -> S3 gold eval).
It is the *honest* metric: a model prediction is only ever graded against a gold
annotation that a human has signed off on. We NEVER grade model-vs-model. If gold
is unverified, it is excluded from the real metric and any preview is labelled
"UNVERIFIED — not a real metric".

WHAT COUNTS AS SCORABLE GOLD
----------------------------
A gold file is scorable ONLY if `is_verified(gold)` is True, i.e. it has a truthy
`verified_by` field carrying a human's name/initials. Missing / empty / "tbd" /
"pending" (case-insensitive) all mean UNVERIFIED -> skipped, with the reason
recorded in the artifact. The 6 candidate drafts in gold/candidate/ are all
unverified by design; the harness reports 0 verified and warns rather than
fabricating a number.

GOLD FILE SHAPE (gold/candidate/*.json)
---------------------------------------
  {
    "pmcid": "PMC3033971",
    "verified_by": null | "RHS",          # <- the gate
    "gold": {
      "source_cells": {"cell_type": "ESC", ...},
      "matrix":       {"name": "Matrigel", ...},
      "base_media":   {"value": "Advanced DMEM/F12", ...},   # note: 'value', not 'name'
      "signaling_factors": [{"name": ...}, ...],
      "small_molecules":   [{"name": ...}, ...]  # often absent -> treated as []
    }
  }

PREDICTION SHAPE (data/predictions/local/<pmcid>.json) — OrganoidProtocol schema:
  {
    "source_cells": {"cell_type": "iPSC", ...},
    "matrix":       {"name": "Matrigel", ...},
    "base_media":   {"name": "mTesR1", ...},                 # note: 'name'
    "signaling_factors": [{"name": ...}, ...],
    "small_molecules":   [{"name": ...}, ...]
  }

Matching is by filename stem (pmcid): gold/<pmcid>.json <-> predictions/<pmcid>.json.

MATCHING RULES (explicit)
-------------------------
All matching is on the NORMALIZED surface form via ground._norm (lowercase,
greek-fold, strip every non-alphanumeric char). So "R-Spondin1" == "r spondin1",
"ActivinA" == "Activin A", "TGF-β" == "tgfbeta".

Set-valued fields (signaling_factors, small_molecules):
  - Build the normalized name set of gold items and of predicted items
    (duplicates collapse — a set, so a model repeating a synonym is not double
    counted, and an empty/blank name is dropped).
  - tp = |gold_norms ∩ pred_norms|
  - fp = |pred_norms − gold_norms|   (predicted but not in gold)
  - fn = |gold_norms − pred_norms|   (in gold but missed)
  - precision = tp/(tp+fp), recall = tp/(tp+fn), f1 = 2PR/(P+R)
  - Every denominator guards against zero: when there is nothing to score we
    return 0.0 (and the {tp,fp,fn} make that visible) rather than dividing by 0.
    NB: empty gold AND empty pred yields tp=fp=fn=0 -> P=R=F1=0.0, but support=0,
    so the aggregator can choose to ignore it.

Scalar fields (source_cells.cell_type, matrix, base_media):
  - Exact match AFTER normalization -> one of:
      "correct"  gold present, pred present, normalized-equal
      "incorrect" gold present, pred present, normalized-different
      "missing"  gold present, pred absent/blank
    A scalar where gold itself is absent/blank is "not_in_gold" and not scored.
  - Per-field scalar accuracy aggregates correct / scorable.

AGGREGATION
-----------
For each set field we report BOTH:
  - micro P/R/F1: pool tp/fp/fn across all papers then divide once.
  - macro P/R/F1: mean of the per-paper P/R/F1 (papers with support only).

Writes outputs/eval/gold_eval.json — every number computed here, none hand-typed.
Prints a summary; exits NONZERO (or prints a WARNING banner with --no-fail) when
zero verified gold files are found, so CI cannot be tricked into a green pass.

Run:
    python pipeline/eval_gold.py                       # gold-dir defaults to gold/
    python pipeline/eval_gold.py --gold-dir gold/candidate
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
import ground  # noqa: E402  (reuse the canonical normalizer)

DEFAULT_GOLD_DIR = REPO / "gold"
DEFAULT_PRED_DIR = REPO / "data" / "predictions" / "local"
DEFAULT_OUT = REPO / "outputs" / "eval" / "gold_eval.json"

# verified_by values that mean "not actually verified by a human yet".
_UNVERIFIED_SENTINELS = {"", "tbd", "pending", "none", "null", "n/a", "na"}

# The set-valued fields we score (name-keyed lists of reagents).
SET_FIELDS = ("signaling_factors", "small_molecules")
# Scalar fields: (output_name, gold_accessor, pred_accessor).
# Gold base_media uses 'value'; prediction base_media uses 'name' — hence the
# separate accessors. cell_type/matrix line up on the same key in both.
SCALAR_FIELDS = ("source_cells.cell_type", "matrix", "base_media")


# --------------------------------------------------------------------------- #
# Pure, testable core
# --------------------------------------------------------------------------- #
def _norm(s) -> str:
    """Normalized surface form, delegating to the canonical pipeline normalizer."""
    return ground._norm(s if isinstance(s, str) else (str(s) if s is not None else None))


def is_verified(gold: dict) -> bool:
    """True only when `verified_by` carries a real (human) value.

    False for missing key, None, "", or any sentinel (tbd/pending/...). The value
    is compared case-insensitively after stripping whitespace.
    """
    v = gold.get("verified_by")
    if v is None:
        return False
    if not isinstance(v, str):
        # any non-empty, non-string truthy value (unlikely) counts as a name.
        return bool(v)
    return v.strip().lower() not in _UNVERIFIED_SENTINELS


def _gold_payload(gold: dict) -> dict:
    """Gold annotations live under the 'gold' key; tolerate flat files too."""
    return gold.get("gold", gold)


def _name_set(items, key: str = "name") -> set[str]:
    """Normalized, de-duplicated set of names from a list of reagent dicts."""
    out: set[str] = set()
    for it in items or []:
        if isinstance(it, dict):
            n = _norm(it.get(key))
        else:
            n = _norm(it)
        if n:
            out.add(n)
    return out


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def score_set_field(gold_items, pred_items, key: str = "name") -> dict:
    """Set-overlap P/R/F1 for one name-keyed list field. See module docstring.

    Returns {tp, fp, fn, precision, recall, f1}. No division by zero: empty
    gold and/or empty pred yields zeros, never an exception.
    """
    g = _name_set(gold_items, key)
    p = _name_set(pred_items, key)
    tp = len(g & p)
    fp = len(p - g)
    fn = len(g - p)
    return _prf(tp, fp, fn)


def _gold_scalar(payload: dict, field: str):
    if field == "source_cells.cell_type":
        sc = payload.get("source_cells") or {}
        return sc.get("cell_type")
    if field == "matrix":
        m = payload.get("matrix") or {}
        return m.get("name")
    if field == "base_media":
        bm = payload.get("base_media") or {}
        # gold uses 'value'; fall back to 'name' for robustness.
        return bm.get("value", bm.get("name"))
    raise ValueError(f"unknown scalar field {field!r}")


def _pred_scalar(pred: dict, field: str):
    if field == "source_cells.cell_type":
        sc = pred.get("source_cells") or {}
        return sc.get("cell_type")
    if field == "matrix":
        m = pred.get("matrix") or {}
        return m.get("name")
    if field == "base_media":
        bm = pred.get("base_media") or {}
        return bm.get("name", bm.get("value"))
    raise ValueError(f"unknown scalar field {field!r}")


def score_scalar_field(gold_val, pred_val) -> dict:
    """Exact-after-normalize scalar verdict.

    -> {"status": correct|incorrect|missing|not_in_gold, "gold":..., "pred":...}
    """
    g = _norm(gold_val)
    p = _norm(pred_val)
    if not g:
        status = "not_in_gold"
    elif not p:
        status = "missing"
    elif g == p:
        status = "correct"
    else:
        status = "incorrect"
    return {"status": status, "gold": gold_val, "pred": pred_val}


def score_paper(gold: dict, pred: dict) -> dict:
    """Score one (gold, prediction) pair across all set + scalar fields."""
    payload = _gold_payload(gold)
    set_scores = {
        f: score_set_field(payload.get(f), pred.get(f), key="name") for f in SET_FIELDS
    }
    scalar_scores = {
        f: score_scalar_field(_gold_scalar(payload, f), _pred_scalar(pred, f))
        for f in SCALAR_FIELDS
    }
    return {"set_fields": set_scores, "scalar_fields": scalar_scores}


def aggregate(paper_scores: dict) -> dict:
    """Aggregate per-paper scores into micro + macro P/R/F1 and scalar accuracy.

    `paper_scores` maps pmcid -> score_paper(...) output.
    """
    set_agg = {}
    for f in SET_FIELDS:
        micro_tp = micro_fp = micro_fn = 0
        macro_p = macro_r = macro_f1 = 0.0
        n_support = 0
        for ps in paper_scores.values():
            s = ps["set_fields"][f]
            micro_tp += s["tp"]
            micro_fp += s["fp"]
            micro_fn += s["fn"]
            # a paper "supports" macro averaging only if it has gold or pred items
            if s["tp"] + s["fp"] + s["fn"] > 0:
                macro_p += s["precision"]
                macro_r += s["recall"]
                macro_f1 += s["f1"]
                n_support += 1
        micro = _prf(micro_tp, micro_fp, micro_fn)
        macro = {
            "precision": round(macro_p / n_support, 4) if n_support else 0.0,
            "recall": round(macro_r / n_support, 4) if n_support else 0.0,
            "f1": round(macro_f1 / n_support, 4) if n_support else 0.0,
            "papers_with_support": n_support,
        }
        set_agg[f] = {"micro": micro, "macro": macro}

    scalar_agg = {}
    for f in SCALAR_FIELDS:
        counts = {"correct": 0, "incorrect": 0, "missing": 0, "not_in_gold": 0}
        for ps in paper_scores.values():
            counts[ps["scalar_fields"][f]["status"]] += 1
        scorable = counts["correct"] + counts["incorrect"] + counts["missing"]
        scalar_agg[f] = {
            **counts,
            "scorable": scorable,
            "accuracy": round(counts["correct"] / scorable, 4) if scorable else 0.0,
        }

    return {
        "papers_scored": len(paper_scores),
        "set_fields": set_agg,
        "scalar_fields": scalar_agg,
    }


# --------------------------------------------------------------------------- #
# IO / runner
# --------------------------------------------------------------------------- #
def _unverified_reason(gold: dict) -> str:
    v = gold.get("verified_by")
    if "verified_by" not in gold:
        return "no verified_by field"
    if v is None:
        return "verified_by is null"
    if isinstance(v, str) and v.strip().lower() in _UNVERIFIED_SENTINELS:
        return f"verified_by is {v.strip()!r} (sentinel, not a human)"
    return "verified_by empty/falsy"


def load_json(path: Path) -> dict:
    with path.open() as fh:
        return json.load(fh)


def run_eval(gold_dir: Path, pred_dir: Path) -> dict:
    """Load gold + predictions, score every verified pair, build the artifact dict."""
    gold_files = sorted(gold_dir.glob("*.json"))

    verified_scored = []
    skipped_unverified = []
    skipped_no_pred = []
    paper_scores = {}
    per_paper_artifact = {}

    for gpath in gold_files:
        pmcid = gpath.stem
        gold = load_json(gpath)
        if not is_verified(gold):
            skipped_unverified.append(
                {"pmcid": pmcid, "file": str(gpath), "reason": _unverified_reason(gold)}
            )
            continue
        ppath = pred_dir / f"{pmcid}.json"
        if not ppath.exists():
            skipped_no_pred.append(
                {"pmcid": pmcid, "file": str(gpath), "reason": f"no prediction at {ppath}"}
            )
            continue
        pred = load_json(ppath)
        score = score_paper(gold, pred)
        paper_scores[pmcid] = score
        per_paper_artifact[pmcid] = score
        verified_scored.append(
            {"pmcid": pmcid, "gold_file": str(gpath), "pred_file": str(ppath),
             "verified_by": gold.get("verified_by")}
        )

    agg = aggregate(paper_scores) if paper_scores else {
        "papers_scored": 0, "set_fields": {}, "scalar_fields": {},
    }

    artifact = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "pipeline/eval_gold.py",
        "honesty": (
            "Only HUMAN-VERIFIED gold (truthy verified_by) is scored; "
            "unverified gold is skipped and never counted. No model-vs-model."
        ),
        "provenance": {
            "gold_dir": str(gold_dir),
            "pred_dir": str(pred_dir),
            "gold_files_found": len(gold_files),
            "gold_pmcids": [g.stem for g in gold_files],
            "verified_count": len(verified_scored),
            "skipped_unverified_count": len(skipped_unverified),
            "skipped_no_prediction_count": len(skipped_no_pred),
        },
        "match_rules": {
            "name_normalizer": "ground._norm (lowercase, greek-fold, strip non-alnum)",
            "set_fields": list(SET_FIELDS),
            "scalar_fields": list(SCALAR_FIELDS),
            "set_match": "normalized set overlap; duplicates collapsed",
            "scalar_match": "exact after normalize -> correct/incorrect/missing/not_in_gold",
        },
        "verified_gold_scored": verified_scored,
        "skipped_unverified": skipped_unverified,
        "skipped_no_prediction": skipped_no_pred,
        "is_real_metric": len(verified_scored) > 0,
        "aggregate": agg,
        "per_paper": per_paper_artifact,
    }
    return artifact


def _print_summary(artifact: dict) -> None:
    prov = artifact["provenance"]
    real = artifact["is_real_metric"]
    print("== S3 gold evaluation ==\n")
    print(f"  gold dir:        {prov['gold_dir']}")
    print(f"  pred dir:        {prov['pred_dir']}")
    print(f"  gold files:      {prov['gold_files_found']}")
    print(f"  VERIFIED+scored: {prov['verified_count']}")
    print(f"  skipped (unverified): {prov['skipped_unverified_count']}")
    print(f"  skipped (no prediction): {prov['skipped_no_prediction_count']}")

    if not real:
        print("\n" + "!" * 64)
        print("!! WARNING: 0 human-verified gold files. NO REAL METRIC PRODUCED. !!")
        print("!! Candidate drafts need a human `verified_by` to be scorable.   !!")
        print("!" * 64)
        if artifact["skipped_unverified"]:
            print("\n  Unverified gold (excluded):")
            for s in artifact["skipped_unverified"]:
                print(f"    - {s['pmcid']}: {s['reason']}")
        return

    agg = artifact["aggregate"]
    print(f"\n  papers scored: {agg['papers_scored']}\n")
    for f, sc in agg["set_fields"].items():
        mi, ma = sc["micro"], sc["macro"]
        print(f"  [{f}]")
        print(f"    micro  P={mi['precision']} R={mi['recall']} F1={mi['f1']} "
              f"(tp={mi['tp']} fp={mi['fp']} fn={mi['fn']})")
        print(f"    macro  P={ma['precision']} R={ma['recall']} F1={ma['f1']} "
              f"(n={ma['papers_with_support']})")
    for f, sc in agg["scalar_fields"].items():
        print(f"  [{f}] accuracy={sc['accuracy']} "
              f"(correct={sc['correct']} incorrect={sc['incorrect']} "
              f"missing={sc['missing']} of scorable={sc['scorable']})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Score Tier-1 predictions vs verified gold.")
    ap.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD_DIR,
                    help="Directory of gold *.json (default: gold/; use gold/candidate for drafts).")
    ap.add_argument("--pred-dir", type=Path, default=DEFAULT_PRED_DIR,
                    help="Directory of prediction *.json (default: data/predictions/local).")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="Artifact output path (default: outputs/eval/gold_eval.json).")
    ap.add_argument("--no-fail", action="store_true",
                    help="Do not exit nonzero when zero verified gold is found (still warns).")
    args = ap.parse_args(argv)

    artifact = run_eval(args.gold_dir, args.pred_dir)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as fh:
        json.dump(artifact, fh, indent=2)

    _print_summary(artifact)
    print(f"\n  wrote {args.out}")

    if not artifact["is_real_metric"] and not args.no_fail:
        print("\n  EXIT 1: no real metric (no verified gold). This is the honest gate.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
