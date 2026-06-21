#!/usr/bin/env python3
"""
Failure mode aggregator: group FailureMode records across all corpus papers,
cluster by keyword, and emit a ranked summary per organoid_type.

Input sources (tried in order per paper):
  1. data/predictions/local/{pmcid}.json  -- full v0.4 prediction
  2. outputs/tier1/extraction_summary.json -- failure_modes field if present

Output:
  outputs/analysis/failure_mode_summary.json

Run:
  python pipeline/aggregate_failure_modes.py
  python pipeline/aggregate_failure_modes.py --organoid-type intestinal
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PRED_DIR = REPO / "data" / "predictions" / "local"
SUMMARY_PATH = REPO / "outputs" / "tier1" / "extraction_summary.json"
PROTOCOLS_JSONL = REPO / "exports" / "public" / "protocols.jsonl"
OUT_PATH = REPO / "outputs" / "analysis" / "failure_mode_summary.json"

# Keyword clusters: label → regex patterns (case-insensitive OR)
KEYWORD_CLUSTERS: dict[str, list[str]] = {
    "matrix_gelation": [r"matrigel", r"gel.*solidif", r"matrix.*not.*set", r"polymeriz"],
    "contamination": [r"contaminat", r"bacterial", r"mycoplasma", r"fungal"],
    "organoid_collapse": [r"collaps", r"disintegrat", r"fall.*apart", r"disrupt"],
    "growth_arrest": [r"growth.*arrest", r"stop.*growing", r"proliferat.*fail", r"no.*growth"],
    "low_efficiency": [r"low.*efficienc", r"poor.*yield", r"few.*organoid", r"sparse"],
    "concentration_critical": [r"concentrat", r"dose.*critical", r"too.*high", r"too.*low"],
    "reagent_quality": [r"reagent.*quality", r"lot.*variation", r"batch.*variab"],
    "timing_critical": [r"timing", r"passag.*interval", r"too.*early", r"too.*late"],
    "crypt_failure": [r"crypt", r"budding.*fail", r"no.*crypt"],
    "differentiation_failure": [r"differenti.*fail", r"fail.*to.*differenti", r"remain.*undiff"],
    "passage_failure": [r"passag.*fail", r"fail.*to.*passage", r"dissociat.*fail"],
}


# --------------------------------------------------------------------------- #
# Pure logic (fully offline-testable)
# --------------------------------------------------------------------------- #

def assign_cluster(description: str, clusters: dict[str, list[str]]) -> list[str]:
    """
    Assign a failure mode description to zero or more keyword clusters.
    Returns list of matching cluster labels (multiple allowed).
    """
    matched: list[str] = []
    desc_lower = description.lower()
    for label, patterns in clusters.items():
        if any(re.search(p, desc_lower) for p in patterns):
            matched.append(label)
    return matched if matched else ["other"]


def aggregate_failure_modes(
    records: list[dict],  # each has: pmcid, organoid_type, description, condition
    clusters: dict[str, list[str]],
) -> dict:
    """
    Group failure modes by organoid_type and keyword cluster.
    Returns aggregation result dict.
    """
    by_type: dict[str, dict] = defaultdict(lambda: {"total": 0, "clusters": defaultdict(list)})

    for rec in records:
        otype = (rec.get("organoid_type") or "unknown").strip().lower()
        desc = (rec.get("description") or "").strip()
        if not desc:
            continue
        labels = assign_cluster(desc, clusters)
        by_type[otype]["total"] += 1
        for label in labels:
            by_type[otype]["clusters"][label].append({
                "pmcid": rec.get("pmcid", ""),
                "description": desc,
                "condition": rec.get("condition"),
                "source_doi": rec.get("source_doi"),
            })

    # Convert defaultdicts to plain dicts and sort clusters by count desc
    result_by_type = {}
    for otype, data in sorted(by_type.items()):
        clusters_sorted = sorted(
            [
                {
                    "cluster": label,
                    "count": len(items),
                    "examples": items[:5],  # cap at 5 examples per cluster per type
                }
                for label, items in data["clusters"].items()
            ],
            key=lambda x: -x["count"],
        )
        result_by_type[otype] = {
            "total_failure_modes": data["total"],
            "clusters": clusters_sorted,
        }

    total = sum(v["total_failure_modes"] for v in result_by_type.values())

    # Global cluster frequency across all types
    global_counts: dict[str, int] = defaultdict(int)
    for data in result_by_type.values():
        for c in data["clusters"]:
            global_counts[c["cluster"]] += c["count"]

    return {
        "total_failure_modes": total,
        "n_organoid_types": len(result_by_type),
        "global_cluster_ranking": sorted(
            [{"cluster": k, "count": v} for k, v in global_counts.items()],
            key=lambda x: -x["count"],
        ),
        "by_organoid_type": result_by_type,
    }


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

def _load_from_local_predictions(filter_type: str | None) -> list[dict]:
    """Load failure modes from data/predictions/local/*.json."""
    records: list[dict] = []
    if not PRED_DIR.exists():
        return records
    for pred_file in sorted(PRED_DIR.glob("*.json")):
        pmcid = pred_file.stem
        try:
            p = json.loads(pred_file.read_text())
        except json.JSONDecodeError:
            continue
        otype = p.get("organoid_type", "unknown")
        if filter_type and otype.lower() != filter_type.lower():
            continue
        for fm in p.get("failure_modes") or []:
            records.append({
                "pmcid": pmcid,
                "organoid_type": otype,
                "description": fm.get("description", ""),
                "condition": fm.get("condition"),
                "source_doi": p.get("source_doi"),
            })
    return records


def _load_from_extraction_summary(filter_type: str | None) -> list[dict]:
    """Load failure modes from outputs/tier1/extraction_summary.json rows."""
    if not SUMMARY_PATH.exists():
        return []
    try:
        data = json.loads(SUMMARY_PATH.read_text())
    except json.JSONDecodeError:
        return []
    records: list[dict] = []
    for row in data.get("rows") or []:
        otype = row.get("organoid_type", "unknown")
        if filter_type and otype.lower() != filter_type.lower():
            continue
        pmcid = row.get("pmcid", "")
        doi = row.get("doi", "")
        for fm in row.get("failure_modes") or []:
            if isinstance(fm, dict):
                desc = fm.get("description", "")
                cond = fm.get("condition")
            elif isinstance(fm, str):
                desc = fm
                cond = None
            else:
                continue
            records.append({
                "pmcid": pmcid,
                "organoid_type": otype,
                "description": desc,
                "condition": cond,
                "source_doi": doi,
            })
    return records


def load_all_failure_modes(filter_type: str | None) -> list[dict]:
    """
    Load failure modes from all available sources.
    Local predictions take precedence; extraction summary fills gaps.
    """
    local = _load_from_local_predictions(filter_type)
    summary = _load_from_extraction_summary(filter_type)

    # Deduplicate by (pmcid, description) — prefer local source
    seen: set[tuple] = set()
    merged: list[dict] = []
    for rec in local + summary:
        key = (rec.get("pmcid", ""), rec.get("description", "").lower()[:80])
        if key not in seen:
            seen.add(key)
            merged.append(rec)
    return merged


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(description="Aggregate failure modes across corpus papers")
    ap.add_argument("--organoid-type", default=None,
                    help="Filter to a single organoid type (e.g. intestinal)")
    ap.add_argument("--output", "-o", default=None, help="Output JSON path")
    ap.add_argument("--min-count", type=int, default=1,
                    help="Only include clusters with at least this many examples (default 1)")
    args = ap.parse_args()

    records = load_all_failure_modes(args.organoid_type)

    if not records:
        print(
            "No failure modes found. "
            "Run tier1 extraction on A100 first: python pipeline/tier1_extract.py",
            file=sys.stderr,
        )
        # Write empty result rather than failing
        result = {
            "total_failure_modes": 0,
            "n_organoid_types": 0,
            "global_cluster_ranking": [],
            "by_organoid_type": {},
        }
    else:
        result = aggregate_failure_modes(records, KEYWORD_CLUSTERS)
        if args.min_count > 1:
            for otype_data in result["by_organoid_type"].values():
                otype_data["clusters"] = [
                    c for c in otype_data["clusters"] if c["count"] >= args.min_count
                ]

    out_path = Path(args.output) if args.output else OUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(f"Failure mode summary → {out_path}")
    print(f"Total failure modes: {result['total_failure_modes']}")
    print(f"Organoid types: {result['n_organoid_types']}")
    if result["global_cluster_ranking"]:
        print("Top clusters:")
        for c in result["global_cluster_ranking"][:5]:
            print(f"  {c['cluster']:30s} {c['count']}")


if __name__ == "__main__":
    main()
