#!/usr/bin/env python3
"""
Aggregate the multi-modal silver-gold adjudications (outputs/validation/silver/*.json,
each written by an independent Claude reviewer that read a paper's methods + tables +
figure images and scored the pipeline extraction) into one measured summary.

This is the extraction-ACCURACY layer the auto fidelity audit could not provide: the
auto check only verifies a value matches ITS OWN quote (~99%); a reviewer reading the
whole source catches wrong-quote, cross-protocol contamination, cell-type mislabels
(precision) AND values stated only in tables/figures that the extractor missed (recall).

Silver (Claude-adjudicated vs source), not human-gold — but reproducible and honest.

Run: python pipeline/aggregate_silver_gold.py
"""

from __future__ import annotations

import glob
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SILVER = REPO / "outputs" / "validation" / "silver"
OUT = REPO / "outputs" / "validation" / "silver_gold_summary.json"


def classify(entry: dict) -> str:
    s = (f"{entry.get('field','')} {entry.get('source_says','')} "
         f"{entry.get('extracted','')}").lower()
    if any(k in s for k in ("esc", "ipsc", "hesc", "psc")):
        return "cell_type_ESC_vs_iPSC"
    if any(k in s for k in ("fabricat", "absent", "no source", "not in source", "hallucinat")):
        return "fabrication"
    if any(k in s for k in ("medium", "media", "rpmi", "dmem", "mtesr")):
        return "media_conflation"
    if any(k in s for k in ("species", "mouse", "human", "mus musculus")):
        return "species"
    return "other_value_unit_name"


def main() -> None:
    recs = []
    for f in sorted(glob.glob(str(SILVER / "*.json"))):
        try:
            recs.append(json.loads(Path(f).read_text()))
        except Exception:  # noqa: BLE001
            continue
    n = len(recs)
    checked = sum(r.get("n_fields_checked", 0) for r in recs)
    correct = sum(r.get("n_correct", 0) for r in recs)
    incorrect = [e for r in recs for e in r.get("incorrect", [])]
    misses = [m for r in recs for m in r.get("recall_misses", [])]
    tax = Counter(classify(e) for e in incorrect)

    def loc_bucket(m):
        s = str(m.get("source_loc", "")).lower()
        if "table" in s:
            return "table"
        if "figure" in s or "fig" in s or "schematic" in s:
            return "figure"
        if "suppl" in s:
            return "supplementary"
        return "methods/body_text"
    miss_loc = Counter(loc_bucket(m) for m in misses)

    summary = {
        "method": "multi-modal silver-gold: independent Claude reviewer per paper reads "
                  "methods+tables+figure images, scores extraction precision (vs full "
                  "source) + recall (items only in tables/figures). Silver, not human-gold.",
        "n_papers": n,
        "n_multimodal": sum(1 for r in recs if r.get("multimodal")),
        "field_precision": round(correct / checked, 4) if checked else None,
        "n_fields_checked": checked,
        "n_correct": correct,
        "n_incorrect": len(incorrect),
        "recall_misses_total": len(misses),
        "recall_misses_per_paper": round(len(misses) / n, 2) if n else None,
        "recall_miss_location": dict(miss_loc),
        "verdicts": dict(Counter(r.get("verdict") for r in recs)),
        "correctness_error_taxonomy": dict(tax.most_common()),
        "papers": sorted(r.get("pmcid") for r in recs if r.get("pmcid")),
        "note": "Precision here (~full-source) is the honest extraction-accuracy number; "
                "it is LOWER than the value-in-quote auto-proxy because it catches wrong-"
                "quote / cross-protocol / cell-type errors. Recall is the dominant gap "
                "(timeline, media, supplement doses, table-only values).",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2))
    print(f"silver-gold: {n} papers ({summary['n_multimodal']} multimodal) | "
          f"precision {summary['field_precision']:.1%} ({correct}/{checked}) | "
          f"recall misses {len(misses)} ({summary['recall_misses_per_paper']}/paper)")
    print(f"verdicts {summary['verdicts']} | errors {summary['correctness_error_taxonomy']}")
    print(f"-> {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
