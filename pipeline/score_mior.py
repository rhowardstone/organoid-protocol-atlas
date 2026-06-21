#!/usr/bin/env python3
"""
MIOR (Minimum Information About an Organoid Research) completeness scorer.

Maps extracted protocol fields to the MIOR community reporting standard modules
and scores each paper's reporting completeness.

MIOR modules (based on Lancaster & Bhatt 2019 + Nature Protocols guidance):
  M1  Source material         species, organoid_type, source_cell_type
  M2  Culture system          base_media, matrix, passaging, n_supplements + n_signaling_factors
  M3  Protocol timeline       timeline
  M4  Endpoint characterisation  assay_endpoints
  M5  Reproducibility / QC    n_figure_confirmed, evidence grounding

Each item is scored:
  present       — field is extracted and not null/not_reported/empty
  not_reported  — field value is explicitly "not_reported" or equivalent
  not_extracted — field is null/missing (we couldn't determine if it was reported)

MIOR completeness = (n_present) / (n_present + n_not_reported)
  Only counts items where reporting status is known (present or explicitly not_reported).
  Not_extracted items neither help nor hurt the score.

This score reflects how well the SOURCE PAPER reports the minimum required information,
not how well we extracted it.

Output: outputs/analysis/mior_completeness.json

Run:
  python pipeline/score_mior.py
  python pipeline/score_mior.py --type intestinal
  python pipeline/score_mior.py --top 10
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, NamedTuple

REPO = Path(__file__).resolve().parent.parent
PROTOCOLS_JSONL = REPO / "exports" / "public" / "protocols.jsonl"
OUT_PATH = REPO / "outputs" / "analysis" / "mior_completeness.json"

# --------------------------------------------------------------------------- #
# MIOR module definitions
# --------------------------------------------------------------------------- #

class MiorItem(NamedTuple):
    module: str
    item_id: str
    label: str
    field: str          # protocol field name, or "COMPUTED" for derived items
    required: bool      # True = core MIOR, False = recommended


MIOR_ITEMS: list[MiorItem] = [
    # M1 — Source material
    MiorItem("M1_source_material", "M1.1", "Species",          "species",          required=True),
    MiorItem("M1_source_material", "M1.2", "Tissue / organ type", "organoid_type", required=True),
    MiorItem("M1_source_material", "M1.3", "Source cell type", "source_cell_type", required=True),

    # M2 — Culture system
    MiorItem("M2_culture_system", "M2.1", "Base media",        "base_media",       required=True),
    MiorItem("M2_culture_system", "M2.2", "Extracellular matrix / scaffold", "matrix", required=True),
    MiorItem("M2_culture_system", "M2.3", "Signaling factors present", "n_signaling_factors", required=True),
    MiorItem("M2_culture_system", "M2.4", "Media supplements present", "n_supplements", required=False),
    MiorItem("M2_culture_system", "M2.5", "Passaging method",  "passaging",        required=False),

    # M3 — Protocol timeline
    MiorItem("M3_timeline",        "M3.1", "Culture timeline", "timeline",         required=True),

    # M4 — Endpoint characterisation
    MiorItem("M4_endpoints",       "M4.1", "Validation / assay endpoints", "assay_endpoints", required=True),

    # M5 — Reproducibility / QC
    MiorItem("M5_reproducibility", "M5.1", "Figure-confirmed reagents", "n_figure_confirmed", required=False),
    MiorItem("M5_reproducibility", "M5.2", "Reagent grounding rate",    "grounding_rate",    required=False),
]

# Values that indicate explicit "not reported" by the paper
_NOT_REPORTED = frozenset({
    "not_reported", "not_extracted", "not_applicable", "tbd",
    "null", "none", "", "0",
})

# Numeric fields where 0 means "not reported" (no signaling factors = none extracted)
_NUMERIC_FIELDS = frozenset({"n_signaling_factors", "n_supplements", "n_figure_confirmed"})


# --------------------------------------------------------------------------- #
# Pure scoring logic
# --------------------------------------------------------------------------- #

def _field_status(val: Any, field: str) -> str:
    """
    Classify a field value as: 'present', 'not_reported', or 'not_extracted'.

    - 'present'      : value clearly exists and is informative
    - 'not_reported' : value is explicitly absent (null with meaning: "we know the paper didn't say")
    - 'not_extracted': we couldn't determine either way (None / missing)
    """
    if val is None:
        return "not_extracted"

    str_val = str(val).strip().lower()

    if str_val in _NOT_REPORTED:
        return "not_reported"

    if field in _NUMERIC_FIELDS:
        try:
            n = int(val)
            return "present" if n > 0 else "not_reported"
        except (TypeError, ValueError):
            return "not_extracted"

    if field == "grounding_rate":
        try:
            f = float(val)
            return "present" if f >= 0 else "not_extracted"
        except (TypeError, ValueError):
            return "not_extracted"

    return "present"


def score_mior(p: dict) -> dict:
    """
    Score a single protocol record against all MIOR items.
    Pure function — no I/O.

    Returns dict with:
      pmcid, organoid_type, items (list of per-item results),
      mior_completeness (0–1), required_completeness (0–1),
      n_present, n_not_reported, n_not_extracted
    """
    item_results = []
    for item in MIOR_ITEMS:
        val = p.get(item.field)
        status = _field_status(val, item.field)
        item_results.append({
            "module": item.module,
            "item_id": item.item_id,
            "label": item.label,
            "field": item.field,
            "required": item.required,
            "status": status,
            "value_summary": _summarize(val),
        })

    n_present = sum(1 for r in item_results if r["status"] == "present")
    n_not_reported = sum(1 for r in item_results if r["status"] == "not_reported")
    n_not_extracted = sum(1 for r in item_results if r["status"] == "not_extracted")
    n_known = n_present + n_not_reported

    mior_completeness = round(n_present / n_known, 4) if n_known > 0 else None

    required = [r for r in item_results if r["required"]]
    req_present = sum(1 for r in required if r["status"] == "present")
    req_not_reported = sum(1 for r in required if r["status"] == "not_reported")
    req_known = req_present + req_not_reported
    required_completeness = round(req_present / req_known, 4) if req_known > 0 else None

    return {
        "pmcid": p.get("pmcid"),
        "organoid_type": p.get("organoid_type"),
        "doi": p.get("doi"),
        "year": p.get("year"),
        "mior_completeness": mior_completeness,
        "required_completeness": required_completeness,
        "n_present": n_present,
        "n_not_reported": n_not_reported,
        "n_not_extracted": n_not_extracted,
        "n_items": len(item_results),
        "items": item_results,
    }


def _summarize(val: Any) -> str | None:
    """Short summary of a value for display (never full text)."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in _NOT_REPORTED:
        return None
    return s[:60] + "…" if len(s) > 60 else s


def score_all_protocols(protocols: list[dict]) -> dict:
    """
    Score all protocols and produce corpus-wide MIOR completeness report.
    Pure function — no I/O.
    """
    scored = [score_mior(p) for p in protocols]
    scored.sort(key=lambda r: -(r["mior_completeness"] or 0))

    completeness_vals = [r["mior_completeness"] for r in scored if r["mior_completeness"] is not None]
    avg_completeness = round(sum(completeness_vals) / len(completeness_vals), 4) if completeness_vals else None

    req_vals = [r["required_completeness"] for r in scored if r["required_completeness"] is not None]
    avg_required = round(sum(req_vals) / len(req_vals), 4) if req_vals else None

    # Per-module stats across corpus
    module_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"present": 0, "not_reported": 0, "not_extracted": 0})
    for r in scored:
        for item in r["items"]:
            module_stats[item["module"]][item["status"]] += 1

    # Per-item stats across corpus
    item_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"present": 0, "not_reported": 0, "not_extracted": 0})
    for r in scored:
        for item in r["items"]:
            item_stats[item["item_id"]][item["status"]] += 1

    item_reporting_rates = {}
    for item in MIOR_ITEMS:
        counts = item_stats[item.item_id]
        n_known = counts["present"] + counts["not_reported"]
        rate = round(counts["present"] / n_known, 4) if n_known > 0 else None
        item_reporting_rates[item.item_id] = {
            "label": item.label,
            "module": item.module,
            "required": item.required,
            "present": counts["present"],
            "not_reported": counts["not_reported"],
            "not_extracted": counts["not_extracted"],
            "reporting_rate": rate,
        }

    # Per-type summary
    by_type: dict[str, dict] = {}
    type_scores: dict[str, list[float]] = defaultdict(list)
    for r in scored:
        otype = (r.get("organoid_type") or "unknown").lower()
        if r["mior_completeness"] is not None:
            type_scores[otype].append(r["mior_completeness"])

    for otype, vals in sorted(type_scores.items()):
        by_type[otype] = {
            "n_papers": len(vals),
            "avg_mior_completeness": round(sum(vals) / len(vals), 4),
        }

    # Tiers: full ≥ 0.80, partial ≥ 0.50, sparse < 0.50
    n_full = sum(1 for r in scored if (r["mior_completeness"] or 0) >= 0.80)
    n_partial = sum(1 for r in scored if 0.50 <= (r["mior_completeness"] or 0) < 0.80)
    n_sparse = sum(1 for r in scored if (r["mior_completeness"] or 0) < 0.50)

    return {
        "n_total": len(scored),
        "avg_mior_completeness": avg_completeness,
        "avg_required_completeness": avg_required,
        "n_full": n_full,
        "n_partial": n_partial,
        "n_sparse": n_sparse,
        "full_threshold": 0.80,
        "partial_threshold": 0.50,
        "mior_version": "1.0",
        "n_mior_items": len(MIOR_ITEMS),
        "n_required_items": sum(1 for i in MIOR_ITEMS if i.required),
        "item_reporting_rates": item_reporting_rates,
        "module_stats": {k: dict(v) for k, v in module_stats.items()},
        "by_organoid_type": by_type,
        "scores": [
            {k: v for k, v in r.items() if k != "items"}
            for r in scored
        ],
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
    ap = argparse.ArgumentParser(description="MIOR completeness scorer for organoid protocols")
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
    print(f"MIOR completeness → {out_path}")
    print(f"Papers: {n}  |  avg completeness: {report['avg_mior_completeness']:.1%}")
    print(f"  Full   (≥80%): {report['n_full']:4d} ({100*report['n_full']/n:.0f}%)")
    print(f"  Partial(≥50%): {report['n_partial']:4d} ({100*report['n_partial']/n:.0f}%)")
    print(f"  Sparse ( <50%): {report['n_sparse']:4d} ({100*report['n_sparse']/n:.0f}%)")
    print()
    print("  Per-item reporting rate (known = present + not_reported):")
    for iid, stats in sorted(report["item_reporting_rates"].items()):
        rate = stats["reporting_rate"]
        rate_str = f"{rate:.0%}" if rate is not None else "n/a"
        req_flag = "[R]" if stats["required"] else "   "
        print(f"    {req_flag} {iid}  {stats['label']:<40s}  {rate_str}")
    print()
    print(f"  Top {args.top} papers by MIOR completeness:")
    for r in report["scores"][:args.top]:
        c = r["mior_completeness"]
        print(
            f"  {r['pmcid']:15s} [{(r.get('organoid_type') or ''):20s}] "
            f"mior={c:.1%}  req={r['required_completeness']:.1%}"
        )


if __name__ == "__main__":
    main()
