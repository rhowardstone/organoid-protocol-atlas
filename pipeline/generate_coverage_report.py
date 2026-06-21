#!/usr/bin/env python3
"""
Corpus coverage report: per-organoid-type quality statistics across the public corpus.

Answers: "Where is the corpus well-covered? Where is it sparse?"

Metrics per type:
  n_papers, avg_grounding_rate, n_with_signaling_factors, n_with_timeline,
  n_with_base_media, n_with_matrix, n_with_passaging, n_with_assay_endpoints,
  n_figure_confirmed_total, n_species, top_species, n_source_cell_types,
  year_range, grounding_distribution, completeness_score

Input:  exports/public/protocols.jsonl
Output: outputs/analysis/coverage_report.json

Run:
  python pipeline/generate_coverage_report.py
  python pipeline/generate_coverage_report.py --min-papers 5
  python pipeline/generate_coverage_report.py --output path/to/report.json
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
PROTOCOLS_JSONL = REPO / "exports" / "public" / "protocols.jsonl"
OUT_PATH = REPO / "outputs" / "analysis" / "coverage_report.json"

GROUNDING_BUCKETS = [
    (0.0, 0.5, "poor_lt50"),
    (0.5, 0.8, "moderate_50_80"),
    (0.8, 1.0, "good_80_100"),
    (1.0, 1.001, "perfect_100"),
]


# --------------------------------------------------------------------------- #
# Pure aggregation logic (fully offline-testable, no I/O)
# --------------------------------------------------------------------------- #

def _is_truthy(val: Any) -> bool:
    if val is None:
        return False
    s = str(val).strip().lower()
    return s not in ("", "null", "none", "not_reported", "not_extracted",
                     "not_applicable", "tbd", "0")


def compute_type_coverage(protocols: list[dict]) -> dict:
    """
    Compute coverage metrics for a list of protocols sharing the same organoid_type.
    Pure function — no I/O.
    """
    n = len(protocols)
    if n == 0:
        return {"n_papers": 0, "completeness_score": 0.0}

    grounding_rates: list[float] = []
    n_with_signaling = 0
    n_with_timeline = 0
    n_with_base_media = 0
    n_with_matrix = 0
    n_with_passaging = 0
    n_with_assay_endpoints = 0
    figure_confirmed_total = 0
    species_counts: Counter = Counter()
    source_type_counts: Counter = Counter()
    years: list[int] = []
    reagents_grounded_total = 0
    reagents_total_sum = 0

    for p in protocols:
        # Grounding rate
        gr = p.get("grounding_rate")
        if gr is not None:
            try:
                grounding_rates.append(float(gr))
            except (TypeError, ValueError):
                pass

        # Reagent totals
        rg = p.get("reagents_grounded")
        rt = p.get("reagents_total")
        try:
            if rg is not None:
                reagents_grounded_total += int(rg)
            if rt is not None:
                reagents_total_sum += int(rt)
        except (TypeError, ValueError):
            pass

        # Signaling factors
        nsf = p.get("n_signaling_factors") or 0
        try:
            if int(nsf) > 0:
                n_with_signaling += 1
        except (TypeError, ValueError):
            pass

        # Figure confirmed
        nfc = p.get("n_figure_confirmed") or 0
        try:
            figure_confirmed_total += int(nfc)
        except (TypeError, ValueError):
            pass

        # Presence checks
        if _is_truthy(p.get("timeline")):
            n_with_timeline += 1
        if _is_truthy(p.get("base_media")):
            n_with_base_media += 1
        if _is_truthy(p.get("matrix")):
            n_with_matrix += 1
        if _is_truthy(p.get("passaging")):
            n_with_passaging += 1
        if _is_truthy(p.get("assay_endpoints")):
            n_with_assay_endpoints += 1

        # Species
        sp = (p.get("species") or "").strip().lower()
        if sp and sp not in ("tbd", "null", "none"):
            species_counts[sp] += 1

        # Source cell type
        st = (p.get("source_cell_type") or "").strip().lower()
        if st and st not in ("tbd", "null", "none", "other"):
            source_type_counts[st] += 1

        # Year — stored as string in exports
        yr = p.get("year")
        if yr:
            try:
                years.append(int(yr))
            except (TypeError, ValueError):
                pass

    avg_gr = round(sum(grounding_rates) / len(grounding_rates), 4) if grounding_rates else None
    min_year = min(years) if years else None
    max_year = max(years) if years else None

    gr_dist: dict[str, int] = {}
    for lo, hi, label in GROUNDING_BUCKETS:
        gr_dist[label] = sum(1 for r in grounding_rates if lo <= r < hi)

    pooled_gr = (
        round(reagents_grounded_total / reagents_total_sum, 4)
        if reagents_total_sum > 0 else None
    )

    return {
        "n_papers": n,
        "avg_grounding_rate": avg_gr,
        "pooled_grounding_rate": pooled_gr,
        "reagents_grounded_total": reagents_grounded_total,
        "reagents_total_sum": reagents_total_sum,
        "n_with_signaling_factors": n_with_signaling,
        "n_with_timeline": n_with_timeline,
        "n_with_base_media": n_with_base_media,
        "n_with_matrix": n_with_matrix,
        "n_with_passaging": n_with_passaging,
        "n_with_assay_endpoints": n_with_assay_endpoints,
        "n_figure_confirmed_total": figure_confirmed_total,
        "n_species": len(species_counts),
        "top_species": [{"species": s, "count": c} for s, c in species_counts.most_common(3)],
        "n_source_cell_types": len(source_type_counts),
        "source_cell_types": [{"type": t, "count": c} for t, c in source_type_counts.most_common()],
        "year_range": [min_year, max_year] if min_year is not None else None,
        "grounding_distribution": gr_dist,
        "completeness_score": _completeness_score(
            n, avg_gr, n_with_signaling, n_with_base_media, n_with_matrix
        ),
    }


def _completeness_score(
    n: int,
    avg_gr: float | None,
    n_with_sf: int,
    n_with_bm: int,
    n_with_mx: int,
) -> float:
    """
    Composite 0–1 score: rewards coverage breadth × extraction quality.
    Not an objective metric — a proxy for 'how useful is this type's data?'

    Components:
      - grounding quality (avg_gr, 0–1)
      - signaling factor extraction coverage (n_with_sf / n)
      - base media extraction coverage (n_with_bm / n)
      - matrix extraction coverage (n_with_mx / n)
      - breadth bonus: log10(n) / 2, capped at 1.0 (10 papers ≈ 0.5, 100 ≈ 1.0)

    Mean of 5 components, all in [0, 1].
    """
    if n == 0:
        return 0.0
    breadth = min(1.0, math.log10(max(n, 1)) / 2.0)
    grounding = avg_gr if avg_gr is not None else 0.0
    sf_cov = n_with_sf / n
    bm_cov = n_with_bm / n
    mx_cov = n_with_mx / n
    return round((grounding + sf_cov + bm_cov + mx_cov + breadth) / 5.0, 4)


def generate_coverage_report(
    protocols: list[dict],
    min_papers: int = 1,
) -> dict:
    """
    Compute coverage report across all organoid types.
    Filters types with fewer than min_papers.
    Returns full report dict.
    """
    by_type: dict[str, list[dict]] = defaultdict(list)
    for p in protocols:
        otype = (p.get("organoid_type") or "unknown").strip().lower()
        by_type[otype].append(p)

    type_coverage: dict[str, dict] = {}
    for otype, ps in sorted(by_type.items()):
        if len(ps) < min_papers:
            continue
        type_coverage[otype] = compute_type_coverage(ps)

    total_n = sum(v["n_papers"] for v in type_coverage.values())
    all_grs = [v["avg_grounding_rate"] for v in type_coverage.values()
               if v.get("avg_grounding_rate") is not None]
    overall_avg_gr = round(sum(all_grs) / len(all_grs), 4) if all_grs else None

    # Pool reagent counts for a corpus-wide grounding rate
    total_rg = sum(v.get("reagents_grounded_total", 0) for v in type_coverage.values())
    total_rt = sum(v.get("reagents_total_sum", 0) for v in type_coverage.values())
    corpus_pooled_gr = round(total_rg / total_rt, 4) if total_rt > 0 else None

    ranked = sorted(
        [{"organoid_type": t, **v} for t, v in type_coverage.items()],
        key=lambda x: -x.get("completeness_score", 0.0),
    )

    return {
        "n_total_papers": total_n,
        "n_organoid_types": len(type_coverage),
        "overall_avg_grounding_rate": overall_avg_gr,
        "corpus_pooled_grounding_rate": corpus_pooled_gr,
        "types_by_completeness": ranked,
        "by_organoid_type": type_coverage,
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
    ap = argparse.ArgumentParser(description="Generate per-type corpus coverage report")
    ap.add_argument("--min-papers", type=int, default=1,
                    help="Min papers per type to include in report (default 1)")
    ap.add_argument("--output", "-o", default=None, help="Output JSON path")
    args = ap.parse_args()

    protocols = load_protocols()
    if not protocols:
        print(f"No protocols found at {PROTOCOLS_JSONL}", file=sys.stderr)
        sys.exit(1)

    report = generate_coverage_report(protocols, args.min_papers)
    out_path = Path(args.output) if args.output else OUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))

    print(f"Coverage report → {out_path}")
    print(f"Total papers:      {report['n_total_papers']}")
    print(f"Organoid types:    {report['n_organoid_types']}")
    if report["overall_avg_grounding_rate"] is not None:
        print(f"Overall avg grounding: {report['overall_avg_grounding_rate']:.1%}")
    if report["corpus_pooled_grounding_rate"] is not None:
        print(f"Corpus pooled grounding: {report['corpus_pooled_grounding_rate']:.1%}")
    print("\nTop 8 types by completeness score:")
    for item in report["types_by_completeness"][:8]:
        print(
            f"  {item['organoid_type']:25s} "
            f"n={item['n_papers']:4d}  "
            f"gr={item['avg_grounding_rate'] or 0:.2f}  "
            f"score={item['completeness_score']:.3f}"
        )


if __name__ == "__main__":
    main()
