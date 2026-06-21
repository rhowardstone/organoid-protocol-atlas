#!/usr/bin/env python3
"""
Cross-paper reagent concentration consistency check (Starling-style QC).

Groups reagents by (canonical, canonical_unit), computes median concentration
per group, and flags records where value is >10x or <0.1x the median.
These are likely unit normalization errors (e.g. ng/mL vs ug/mL) or
wrong-reagent dose misbinding.

Output: outputs/validation/concentration_consistency.json
Run: python pipeline/check_concentration_consistency.py
"""
from __future__ import annotations
import json
import math
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REAGENTS = REPO / "exports" / "public" / "reagents.jsonl"
OUT = REPO / "outputs" / "validation" / "concentration_consistency.json"
OUTLIER_THRESHOLD = 10.0  # flag if value/median > threshold or < 1/threshold


def median(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    return (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)


def main():
    rows = [json.loads(l) for l in REAGENTS.read_text().splitlines() if l.strip()]

    # Group eligible rows: must have canonical, value (float), canonical_unit
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        canon = (r.get("canonical") or "").strip()
        unit = (r.get("canonical_unit") or "").strip()
        val = r.get("value")
        if not canon or not unit or val is None:
            continue
        try:
            fval = float(val)
        except (ValueError, TypeError):
            continue
        if fval <= 0:
            continue
        groups[(canon, unit)].append({
            "id": r.get("id"),
            "pmcid": r.get("pmcid"),
            "organoid_type": r.get("organoid_type"),
            "name": r.get("name"),
            "value": fval,
            "evidence_quote": (r.get("evidence_quote") or "")[:120],
        })

    flagged = []
    group_stats = []
    for (canon, unit), members in sorted(groups.items()):
        vals = [m["value"] for m in members]
        if len(vals) < 2:
            continue
        med = median(vals)
        outliers = []
        for m in members:
            ratio = m["value"] / med
            if ratio > OUTLIER_THRESHOLD or ratio < (1 / OUTLIER_THRESHOLD):
                outliers.append({**m, "ratio_to_median": round(ratio, 3), "median": med})
        group_stats.append({
            "canonical": canon, "unit": unit, "n": len(members),
            "median": med, "min": min(vals), "max": max(vals),
            "n_outliers": len(outliers),
        })
        flagged.extend(outliers)

    result = {
        "method": "cross-paper concentration consistency (median ±10x threshold)",
        "n_groups": len(group_stats),
        "n_records_with_concentration": sum(g["n"] for g in group_stats),
        "n_flagged_outliers": len(flagged),
        "outlier_rate": round(len(flagged) / max(1, sum(g["n"] for g in group_stats)), 4),
        "threshold": OUTLIER_THRESHOLD,
        "groups": sorted(group_stats, key=lambda g: -g["n_outliers"]),
        "flagged": sorted(flagged, key=lambda f: -abs(math.log10(f["ratio_to_median"]))),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2))
    print(f"Groups: {result['n_groups']}, Records: {result['n_records_with_concentration']}")
    print(f"Flagged outliers: {result['n_flagged_outliers']} ({result['outlier_rate']:.1%})")
    if flagged:
        print("Top flagged (by deviation):")
        for f in result['flagged'][:5]:
            print(f"  [{f['canonical']} {f['unit']}] id={f['id']} pmcid={f['pmcid']} val={f['value']} (median={f['median']}, ratio={f['ratio_to_median']}x)")

if __name__ == "__main__":
    main()
