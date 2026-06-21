#!/usr/bin/env python3
"""
Per-paper protocol quality scorer.

Computes a composite quality score for each paper in the public corpus,
combining evidence of extraction completeness and grounding quality.

Score components (each 0–1, equal weight):
  grounding_quality  = grounding_rate (directly from field)
  reagent_coverage   = min(reagents_total / 5, 1.0)   [5+ reagents = full]
  context_richness   = 0.25 each for: has_timeline, has_base_media,
                                       has_matrix, has_passaging
  assay_coverage     = 0 or 1 (has assay_endpoints)
  figure_support     = min(n_figure_confirmed / 3, 1.0)  [3+ = full]

Final score = mean of 5 components. Ranges 0–1.

Quality tiers:
  gold   ≥ 0.80 — high completeness, well-grounded
  silver ≥ 0.55 — moderate completeness
  bronze  < 0.55 — sparse extraction

Input:  exports/public/protocols.jsonl
Output: outputs/analysis/protocol_quality_scores.json

Run:
  python pipeline/score_protocol_quality.py
  python pipeline/score_protocol_quality.py --top 20
  python pipeline/score_protocol_quality.py --type intestinal
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
PROTOCOLS_JSONL = REPO / "exports" / "public" / "protocols.jsonl"
OUT_PATH = REPO / "outputs" / "analysis" / "protocol_quality_scores.json"

GOLD_THRESHOLD = 0.80
SILVER_THRESHOLD = 0.55

_FALSY = frozenset({
    "", "null", "none", "not_reported", "not_extracted",
    "not_applicable", "tbd",
})


# --------------------------------------------------------------------------- #
# Pure scoring logic (no I/O)
# --------------------------------------------------------------------------- #

def _has_field(val: Any) -> bool:
    """Return True if field is present and non-empty/non-null."""
    if val is None:
        return False
    return str(val).strip().lower() not in _FALSY


def score_protocol(p: dict) -> dict:
    """
    Compute quality score for a single protocol dict.
    Pure function — no I/O.

    Returns the input dict augmented with:
      quality_score     (float 0–1)
      quality_tier      ("gold" | "silver" | "bronze")
      score_components  (dict of individual component values)
    """
    # Component 1: grounding quality
    gr = p.get("grounding_rate")
    try:
        grounding_quality = max(0.0, min(1.0, float(gr))) if gr is not None else 0.0
    except (TypeError, ValueError):
        grounding_quality = 0.0

    # Component 2: reagent coverage (≥5 reagents = full)
    rt = p.get("reagents_total")
    try:
        reagent_coverage = min(int(rt) / 5.0, 1.0) if rt is not None else 0.0
    except (TypeError, ValueError):
        reagent_coverage = 0.0

    # Component 3: context richness (0.25 per present field)
    context_richness = sum([
        0.25 if _has_field(p.get("timeline")) else 0.0,
        0.25 if _has_field(p.get("base_media")) else 0.0,
        0.25 if _has_field(p.get("matrix")) else 0.0,
        0.25 if _has_field(p.get("passaging")) else 0.0,
    ])

    # Component 4: assay coverage
    assay_coverage = 1.0 if _has_field(p.get("assay_endpoints")) else 0.0

    # Component 5: figure support (≥3 figure-confirmed reagents = full)
    nfc = p.get("n_figure_confirmed")
    try:
        figure_support = min(int(nfc) / 3.0, 1.0) if nfc is not None else 0.0
    except (TypeError, ValueError):
        figure_support = 0.0

    components = {
        "grounding_quality": round(grounding_quality, 4),
        "reagent_coverage": round(reagent_coverage, 4),
        "context_richness": round(context_richness, 4),
        "assay_coverage": round(assay_coverage, 4),
        "figure_support": round(figure_support, 4),
    }

    score = round(sum(components.values()) / len(components), 4)

    if score >= GOLD_THRESHOLD:
        tier = "gold"
    elif score >= SILVER_THRESHOLD:
        tier = "silver"
    else:
        tier = "bronze"

    return {
        "pmcid": p.get("pmcid"),
        "organoid_type": p.get("organoid_type"),
        "doi": p.get("doi"),
        "year": p.get("year"),
        "quality_score": score,
        "quality_tier": tier,
        "score_components": components,
    }


def score_all_protocols(protocols: list[dict]) -> dict:
    """
    Score all protocols and produce a corpus-wide quality report.
    Pure function — no I/O.

    Returns:
      scores: [{pmcid, quality_score, quality_tier, score_components, ...}] sorted desc
      summary: {n_gold, n_silver, n_bronze, avg_score, by_organoid_type}
    """
    scored = [score_protocol(p) for p in protocols]
    scored.sort(key=lambda r: -r["quality_score"])

    n_gold = sum(1 for r in scored if r["quality_tier"] == "gold")
    n_silver = sum(1 for r in scored if r["quality_tier"] == "silver")
    n_bronze = sum(1 for r in scored if r["quality_tier"] == "bronze")

    avg_score = (
        round(sum(r["quality_score"] for r in scored) / len(scored), 4)
        if scored else None
    )

    # Per-type summary
    by_type: dict[str, dict] = {}
    from collections import defaultdict
    type_scores: dict[str, list[float]] = defaultdict(list)
    type_tiers: dict[str, dict[str, int]] = defaultdict(lambda: {"gold": 0, "silver": 0, "bronze": 0})

    for r in scored:
        otype = (r.get("organoid_type") or "unknown").lower()
        type_scores[otype].append(r["quality_score"])
        type_tiers[otype][r["quality_tier"]] += 1

    for otype in sorted(type_scores.keys()):
        vals = type_scores[otype]
        by_type[otype] = {
            "n_papers": len(vals),
            "avg_score": round(sum(vals) / len(vals), 4),
            "n_gold": type_tiers[otype]["gold"],
            "n_silver": type_tiers[otype]["silver"],
            "n_bronze": type_tiers[otype]["bronze"],
        }

    return {
        "n_total": len(scored),
        "n_gold": n_gold,
        "n_silver": n_silver,
        "n_bronze": n_bronze,
        "avg_score": avg_score,
        "gold_threshold": GOLD_THRESHOLD,
        "silver_threshold": SILVER_THRESHOLD,
        "by_organoid_type": by_type,
        "scores": scored,
    }


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #

def load_protocols(path: Path | None = None) -> list[dict]:
    p = path or PROTOCOLS_JSONL
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Score protocol extraction quality per paper")
    ap.add_argument("--top", type=int, default=10, help="Show top N papers (default 10)")
    ap.add_argument("--type", dest="organoid_type", default=None,
                    help="Filter by organoid type")
    ap.add_argument("--output", "-o", default=None, help="Output JSON path")
    ap.add_argument("--json", action="store_true", help="Output full JSON to stdout")
    args = ap.parse_args()

    protocols = load_protocols()
    if not protocols:
        print(f"No protocols at {PROTOCOLS_JSONL}", file=sys.stderr)
        sys.exit(1)

    if args.organoid_type:
        otype = args.organoid_type.lower()
        protocols = [p for p in protocols
                     if (p.get("organoid_type") or "").lower() == otype]
        if not protocols:
            print(f"No protocols found for type: {args.organoid_type}", file=sys.stderr)
            sys.exit(1)

    report = score_all_protocols(protocols)

    if args.json:
        print(json.dumps(report, indent=2))
        return

    out_path = Path(args.output) if args.output else OUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))

    n = report["n_total"]
    print(f"Quality scores → {out_path}")
    print(f"Papers: {n}  |  avg score: {report['avg_score']:.3f}")
    print(f"  Gold   (≥{GOLD_THRESHOLD}): {report['n_gold']:4d} ({100*report['n_gold']/n:.0f}%)")
    print(f"  Silver (≥{SILVER_THRESHOLD}): {report['n_silver']:4d} ({100*report['n_silver']/n:.0f}%)")
    print(f"  Bronze  (<{SILVER_THRESHOLD}): {report['n_bronze']:4d} ({100*report['n_bronze']/n:.0f}%)")

    print(f"\nTop {args.top} papers by quality:")
    for r in report["scores"][:args.top]:
        c = r["score_components"]
        print(
            f"  {r['pmcid']:15s} [{r['organoid_type']:20s}] "
            f"score={r['quality_score']:.3f} [{r['quality_tier']}]  "
            f"gr={c['grounding_quality']:.2f} "
            f"re={c['reagent_coverage']:.2f} "
            f"cx={c['context_richness']:.2f} "
            f"as={c['assay_coverage']:.0f} "
            f"fig={c['figure_support']:.2f}"
        )


if __name__ == "__main__":
    main()
