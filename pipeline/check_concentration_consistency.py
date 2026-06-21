#!/usr/bin/env python3
"""
Cross-paper reagent concentration consistency check (number reconciliation).

Groups reagents by (canonical_name, canonical_unit), computes the median
concentration per group, and flags records where value is >10x or <0.1x
the median. These are likely unit normalisation errors (ng/mL vs µg/mL) or
wrong-reagent dose mis-binding.

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
EVIDENCE_SNIPPET_MAX = 120


# --------------------------------------------------------------------------- #
# Pure functions (testable without filesystem)
# --------------------------------------------------------------------------- #

def _median(vals: list[float]) -> float:
    """Sample median of a non-empty list of floats."""
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def group_reagents(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """
    Group reagent records by (canonical_name, canonical_unit).

    Eligible records must have a canonical name, a canonical_unit, and
    a positive numeric value. Skips records missing any of these.

    Returns: {(canonical, unit): [record, ...]}
    """
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
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
            "evidence_quote": (r.get("evidence_quote") or "")[:EVIDENCE_SNIPPET_MAX],
        })
    return dict(groups)


def find_outliers(
    groups: dict[tuple[str, str], list[dict]],
    threshold: float = OUTLIER_THRESHOLD,
) -> tuple[list[dict], list[dict]]:
    """
    Find concentration outliers within each (canonical, unit) group.

    A record is an outlier if its value / group_median > threshold or
    < 1/threshold. Groups with fewer than 2 records are skipped.

    Returns: (group_stats, flagged_outliers)
      group_stats: per-group summary (canonical, unit, n, median, min, max, n_outliers)
      flagged_outliers: individual flagged records with ratio_to_median and median
    """
    flagged: list[dict] = []
    group_stats: list[dict] = []

    for (canon, unit), members in sorted(groups.items()):
        vals = [m["value"] for m in members]
        if len(vals) < 2:
            continue
        med = _median(vals)
        if med == 0:
            continue  # degenerate; skip
        outliers = []
        for m in members:
            ratio = m["value"] / med
            if ratio > threshold or ratio < (1 / threshold):
                outliers.append({
                    **m,
                    "canonical": canon,
                    "unit": unit,
                    "ratio_to_median": round(ratio, 3),
                    "median": med,
                })
        group_stats.append({
            "canonical": canon,
            "unit": unit,
            "n": len(members),
            "median": med,
            "min": min(vals),
            "max": max(vals),
            "n_outliers": len(outliers),
        })
        flagged.extend(outliers)

    return group_stats, flagged


def build_report(
    group_stats: list[dict],
    flagged: list[dict],
    threshold: float = OUTLIER_THRESHOLD,
) -> dict:
    """
    Assemble the final consistency report dict.
    Pure function — no I/O.
    """
    n_records = sum(g["n"] for g in group_stats)
    return {
        "method": "cross-paper concentration consistency (median ±{:.0f}x threshold); "
                  "records grouped by (canonical, canonical_unit); groups with <2 records skipped".format(threshold),
        "n_groups": len(group_stats),
        "n_records_with_concentration": n_records,
        "n_flagged_outliers": len(flagged),
        "outlier_rate": round(len(flagged) / max(1, n_records), 4),
        "threshold": threshold,
        "groups": sorted(group_stats, key=lambda g: -g["n_outliers"]),
        "flagged": sorted(flagged, key=lambda f: -abs(math.log10(max(f["ratio_to_median"], 1e-9)))),
    }


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #

def load_reagents(path: Path | None = None) -> list[dict]:
    p = path or REAGENTS
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
    rows = load_reagents()
    if not rows:
        print(f"No reagent data at {REAGENTS}")
        return

    groups = group_reagents(rows)
    group_stats, flagged = find_outliers(groups)
    result = build_report(group_stats, flagged)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2))
    print(f"Groups: {result['n_groups']}, Records: {result['n_records_with_concentration']}")
    print(f"Flagged outliers: {result['n_flagged_outliers']} ({result['outlier_rate']:.1%})")
    if flagged:
        print("Top flagged (by deviation):")
        for f in result["flagged"][:5]:
            print(
                f"  [{f['canonical']} {f['unit']}] pmcid={f['pmcid']} "
                f"val={f['value']} (median={f['median']}, ratio={f['ratio_to_median']}x)"
            )


if __name__ == "__main__":
    main()
