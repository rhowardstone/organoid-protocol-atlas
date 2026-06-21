#!/usr/bin/env python3
"""
Cross-corpus reagent lookup: search all reagent records from reagents.jsonl
by canonical or raw name, aggregate usage statistics, and return concentration
summaries with evidence quotes.

Input:  exports/public/reagents.jsonl  (5,000+ reagent-paper pairs)
Output: stdout (human) or --json

Run:
  python pipeline/reagent_lookup.py CHIR99021
  python pipeline/reagent_lookup.py "EGF" --json
  python pipeline/reagent_lookup.py "R-spondin" --type intestinal
  python pipeline/reagent_lookup.py Matrigel --min-papers 3
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
REAGENTS_JSONL = REPO / "exports" / "public" / "reagents.jsonl"

MAX_EXAMPLES = 5  # evidence quotes per result
MAX_RESULTS = 10  # max distinct canonical names returned when query is ambiguous


# --------------------------------------------------------------------------- #
# Pure search and aggregation logic (no I/O)
# --------------------------------------------------------------------------- #

def _matches(text: str | None, query: str) -> bool:
    """Case-insensitive substring match."""
    if not text:
        return False
    return query.lower() in text.lower()


def search_reagents(
    records: list[dict],
    query: str,
    organoid_type: str | None = None,
) -> list[dict]:
    """
    Filter reagent records matching query (case-insensitive substring on
    canonical or name field), optionally further filtered by organoid_type.
    """
    query = query.strip()
    hits = [
        r for r in records
        if _matches(r.get("canonical"), query) or _matches(r.get("name"), query)
    ]
    if organoid_type:
        otype = organoid_type.strip().lower()
        hits = [r for r in hits if (r.get("organoid_type") or "").lower() == otype]
    return hits


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    if n % 2 == 0:
        return (s[n // 2 - 1] + s[n // 2]) / 2.0
    return s[n // 2]


def aggregate_reagent_hits(hits: list[dict]) -> dict:
    """
    Given a list of reagent records (all matching one canonical), produce a
    summary dict. Pure function — no I/O.
    """
    if not hits:
        return {"n_records": 0}

    pmcids = set()
    types_counter: Counter = Counter()
    kind_counter: Counter = Counter()
    values: list[float] = []
    unit_counter: Counter = Counter()
    canonical_counter: Counter = Counter()
    evidence_examples: list[dict] = []
    seen_pmcid_for_examples: set = set()
    grounded_count = 0
    figure_confirmed_count = 0

    for r in hits:
        pmcid = r.get("pmcid") or ""
        if pmcid:
            pmcids.add(pmcid)

        otype = (r.get("organoid_type") or "unknown").lower()
        types_counter[otype] += 1

        kind = r.get("kind") or "unknown"
        kind_counter[kind] += 1

        canon = r.get("canonical") or ""
        if canon:
            canonical_counter[canon] += 1

        val = r.get("value")
        if val is not None:
            try:
                values.append(float(val))
                u = r.get("canonical_unit") or r.get("unit")
                if u:
                    unit_counter[u] += 1
            except (TypeError, ValueError):
                pass

        if r.get("grounded"):
            grounded_count += 1
        if r.get("figure_confirmed"):
            figure_confirmed_count += 1

        # Collect one evidence example per paper (up to MAX_EXAMPLES)
        if pmcid and pmcid not in seen_pmcid_for_examples and len(evidence_examples) < MAX_EXAMPLES:
            quote = r.get("evidence_quote")
            if quote:
                evidence_examples.append({
                    "pmcid": pmcid,
                    "organoid_type": otype,
                    "quote": quote[:300],
                    "value": val,
                    "unit": r.get("canonical_unit") or r.get("unit"),
                })
                seen_pmcid_for_examples.add(pmcid)

    # Most common canonical name
    most_common_canonical = canonical_counter.most_common(1)[0][0] if canonical_counter else None

    # Concentration stats
    conc_stats: dict[str, Any] = {"n_with_value": len(values)}
    if values:
        med = _median(values)
        conc_stats.update({
            "min": min(values),
            "max": max(values),
            "median": round(med, 4) if med is not None else None,
            "dominant_unit": unit_counter.most_common(1)[0][0] if unit_counter else None,
            "unit_distribution": dict(unit_counter.most_common()),
        })
        if len(values) >= 2:
            mean = sum(values) / len(values)
            sample_var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
            sample_std = math.sqrt(sample_var)
            cv = sample_std / mean if mean != 0 else None
            conc_stats["cv"] = round(cv, 4) if cv is not None else None
            conc_stats["high_variability"] = (cv is not None and cv > 1.0)

    return {
        "n_records": len(hits),
        "n_papers": len(pmcids),
        "n_organoid_types": len(types_counter),
        "most_common_canonical": most_common_canonical,
        "usage_by_type": dict(types_counter.most_common()),
        "kind_distribution": dict(kind_counter.most_common()),
        "grounding_rate": round(grounded_count / len(hits), 4) if hits else None,
        "figure_confirmed_count": figure_confirmed_count,
        "concentration": conc_stats,
        "evidence_examples": evidence_examples,
    }


def group_by_canonical(hits: list[dict]) -> dict[str, list[dict]]:
    """Group a list of matching records by their canonical name."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in hits:
        canon = r.get("canonical") or r.get("name") or "unknown"
        groups[canon].append(r)
    return dict(groups)


def lookup(
    records: list[dict],
    query: str,
    organoid_type: str | None = None,
    min_papers: int = 1,
) -> dict:
    """
    Top-level lookup: search, group by canonical, aggregate each group.
    Returns result dict ready for serialisation.
    """
    hits = search_reagents(records, query, organoid_type)
    if not hits:
        return {
            "query": query,
            "organoid_type": organoid_type,
            "n_hits": 0,
            "results": [],
        }

    by_canonical = group_by_canonical(hits)
    results = []
    for canonical, recs in sorted(
        by_canonical.items(),
        key=lambda kv: -len(set(r.get("pmcid") for r in kv[1]))
    ):
        agg = aggregate_reagent_hits(recs)
        if agg["n_papers"] < min_papers:
            continue
        results.append({"canonical": canonical, **agg})

    return {
        "query": query,
        "organoid_type": organoid_type,
        "n_hits": len(hits),
        "n_distinct_canonicals": len(results),
        "results": results[:MAX_RESULTS],
    }


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #

def load_reagents(path: Path | None = None) -> list[dict]:
    p = path or REAGENTS_JSONL
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
    ap = argparse.ArgumentParser(
        description="Cross-corpus reagent lookup from reagents.jsonl"
    )
    ap.add_argument("query", help="Reagent name or fragment to search (case-insensitive)")
    ap.add_argument("--type", dest="organoid_type", default=None,
                    help="Filter by organoid type (e.g. intestinal)")
    ap.add_argument("--min-papers", type=int, default=1,
                    help="Min papers using this reagent (default 1)")
    ap.add_argument("--json", action="store_true", help="Output raw JSON")
    args = ap.parse_args()

    records = load_reagents()
    if not records:
        print(f"No reagent records found at {REAGENTS_JSONL}", file=sys.stderr)
        sys.exit(1)

    result = lookup(records, args.query, args.organoid_type, args.min_papers)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    q = result["query"]
    n_hits = result["n_hits"]
    n_canon = result.get("n_distinct_canonicals", 0)
    otype = result.get("organoid_type")
    filter_note = f" [{otype}]" if otype else ""

    print(f"\nReagent lookup: {q!r}{filter_note}")
    print(f"  {n_hits} record matches → {n_canon} distinct canonical names\n")

    for r in result["results"]:
        conc = r.get("concentration", {})
        n_with_v = conc.get("n_with_value", 0)
        med = conc.get("median")
        unit = conc.get("dominant_unit", "")
        conc_str = f"  median={med} {unit}" if med is not None else "  (no concentrations)"
        cv = conc.get("cv")
        cv_str = f"  CV={cv:.2f}" if cv is not None else ""
        hv = "  [HIGH VARIABILITY]" if conc.get("high_variability") else ""

        print(f"  {r['canonical']}")
        print(f"    {r['n_papers']} papers · {r['n_organoid_types']} types · "
              f"gr={r['grounding_rate']:.0%}")
        print(f"    types: " + ", ".join(
            f"{t}({c})" for t, c in list(r["usage_by_type"].items())[:5]
        ))
        if n_with_v:
            print(f"    conc: {n_with_v} records{conc_str}  [{conc.get('min')}, {conc.get('max')}]{cv_str}{hv}")
        if r["evidence_examples"]:
            ex = r["evidence_examples"][0]
            snippet = ex["quote"][:100].strip()
            print(f"    evidence: \"{snippet}…\" [{ex['pmcid']}]")
        print()


if __name__ == "__main__":
    main()
