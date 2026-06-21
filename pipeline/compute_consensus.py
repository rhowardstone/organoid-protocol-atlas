#!/usr/bin/env python3
"""
Protocol consensus engine: for a given organoid type, aggregate all corpus protocols
to compute consensus concentrations, top reagents, base media, matrix, timeline,
and divergence signals.

This answers questions like:
  "What concentration of EGF do intestinal organoid protocols typically use?"
  "What's the consensus base media for cerebral organoid differentiation?"
  "Which signaling factors are near-universal vs highly variable?"

Data sources (tried in order per paper):
  1. data/predictions/local/{pmcid}.json  -- full v0.4 predictions (local-only)
  2. exports/public/protocols.jsonl + exports/public/reagents.jsonl  -- summary fallback

Output:
  outputs/analysis/consensus_{organoid_type}.json

Run:
  python pipeline/compute_consensus.py intestinal
  python pipeline/compute_consensus.py intestinal --min-papers 3
  python pipeline/compute_consensus.py --all        # all types
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
PRED_DIR = REPO / "data" / "predictions" / "local"
PROTOCOLS_JSONL = REPO / "exports" / "public" / "protocols.jsonl"
OUT_DIR = REPO / "outputs" / "analysis"

# Reagent sections to aggregate across
REAGENT_SECTIONS = ("signaling_factors", "media_supplements", "small_molecules")


# --------------------------------------------------------------------------- #
# Pure aggregation logic (fully offline-testable)
# --------------------------------------------------------------------------- #

def _reagent_key(r: dict) -> str:
    return (r.get("canonical_name") or r.get("name") or "").strip().lower()


def _concentration_value(r: dict) -> float | None:
    c = r.get("concentration")
    if not c:
        return None
    return c.get("value")


def _concentration_unit(r: dict) -> str | None:
    c = r.get("concentration")
    if not c:
        return None
    return c.get("canonical_unit") or c.get("unit")


def median(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return float("nan")
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def compute_reagent_consensus(
    protocols: list[dict],
    section: str,
) -> list[dict]:
    """
    For a reagent section across all protocols, compute:
    - occurrence count (n_papers using it)
    - prevalence (fraction of papers)
    - median concentration + unit + spread (min, max, stddev)
    - consensus_unit (most common unit)

    Returns list sorted by prevalence descending.
    """
    n_total = len(protocols)
    if n_total == 0:
        return []

    # Per-key: list of (value, unit) pairs from papers that report it
    key_values: dict[str, list[tuple[float, str]]] = defaultdict(list)
    key_names: dict[str, str] = {}  # canonical key → display name
    key_papers: dict[str, set] = defaultdict(set)

    for p in protocols:
        pmcid = p.get("pmcid", p.get("source_doi", "unknown"))
        for r in p.get(section) or []:
            k = _reagent_key(r)
            if not k:
                continue
            key_papers[k].add(pmcid)
            if k not in key_names:
                key_names[k] = r.get("canonical_name") or r.get("name") or k
            v = _concentration_value(r)
            u = _concentration_unit(r) or ""
            if v is not None and v > 0:
                key_values[k].append((v, u))

    result = []
    for k, papers in key_papers.items():
        n = len(papers)
        prevalence = round(n / n_total, 4)
        vals_units = key_values.get(k, [])
        vals = [v for v, u in vals_units]

        # Consensus unit = most common non-empty unit
        units_nonempty = [u for _, u in vals_units if u]
        consensus_unit = Counter(units_nonempty).most_common(1)[0][0] if units_nonempty else None

        conc_summary: dict | None = None
        if vals:
            med = median(vals)
            mean = sum(vals) / len(vals)
            stddev = math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) if len(vals) > 1 else 0.0
            cv = (stddev / mean) if mean > 0 else None  # coefficient of variation
            conc_summary = {
                "median": round(med, 4),
                "min": round(min(vals), 4),
                "max": round(max(vals), 4),
                "stddev": round(stddev, 4),
                "cv": round(cv, 3) if cv is not None else None,
                "unit": consensus_unit,
                "n_with_concentration": len(vals),
            }
            # Flag high variability (CV > 1.0 = standard deviation exceeds mean)
            if cv is not None and cv > 1.0:
                conc_summary["high_variability"] = True

        result.append({
            "name": key_names[k],
            "canonical_key": k,
            "n_papers": n,
            "prevalence": prevalence,
            "section": section,
            "concentration": conc_summary,
        })

    return sorted(result, key=lambda r: (-r["prevalence"], r["canonical_key"]))


def compute_scalar_consensus(
    protocols: list[dict],
    field: str,
) -> dict:
    """
    Consensus for a categorical field (base_media, matrix, source_cell_type, etc.)
    Returns frequency distribution + top value.
    """
    counts: Counter = Counter()
    for p in protocols:
        val = p.get(field)
        if val and val not in ("not_reported", "not_extracted", "not_applicable", None):
            counts[str(val).strip()] += 1
    total = sum(counts.values())
    if total == 0:
        return {"top": None, "distribution": [], "n_reported": 0}
    distribution = [
        {"value": v, "count": c, "fraction": round(c / total, 3)}
        for v, c in counts.most_common(10)
    ]
    return {
        "top": counts.most_common(1)[0][0],
        "distribution": distribution,
        "n_reported": total,
        "n_missing": len(protocols) - total,
    }


def compute_timeline_consensus(protocols: list[dict]) -> dict:
    """
    Aggregate timeline stage durations across protocols.
    Groups stages by name (lowercased), computes median duration per stage.
    """
    stage_durations: dict[str, list[float]] = defaultdict(list)
    stage_counts: Counter = Counter()

    for p in protocols:
        tl = p.get("timeline") or []
        if isinstance(tl, str):
            continue  # summary-level string, skip
        for stage in tl:
            name = (stage.get("name") or stage.get("stage") or "").strip().lower()
            if not name:
                continue
            stage_counts[name] += 1
            dur = stage.get("duration") or stage.get("duration_days")
            if dur is not None:
                try:
                    stage_durations[name].append(float(dur))
                except (TypeError, ValueError):
                    pass

    n_total = len(protocols)
    stages = []
    for name, count in stage_counts.most_common():
        durs = stage_durations.get(name, [])
        stages.append({
            "stage": name,
            "n_papers": count,
            "prevalence": round(count / n_total, 3),
            "median_duration": round(median(durs), 2) if durs else None,
            "min_duration": min(durs) if durs else None,
            "max_duration": max(durs) if durs else None,
        })
    return {"n_protocols_with_timeline": sum(1 for p in protocols if p.get("timeline")), "stages": stages}


def compute_consensus(protocols: list[dict], organoid_type: str) -> dict:
    """
    Master consensus computation for a set of protocols of a given type.
    """
    n = len(protocols)
    result: dict[str, Any] = {
        "organoid_type": organoid_type,
        "n_protocols": n,
    }

    if n == 0:
        return result

    # Scalar fields
    result["base_media"] = compute_scalar_consensus(protocols, "base_media")
    result["matrix"] = compute_scalar_consensus(protocols, "matrix")
    result["source_cell_type"] = compute_scalar_consensus(protocols, "source_cell_type")
    result["species"] = compute_scalar_consensus(protocols, "species")

    # Reagents
    for section in REAGENT_SECTIONS:
        result[section] = compute_reagent_consensus(protocols, section)

    # Timeline
    result["timeline"] = compute_timeline_consensus(protocols)

    # High-universality reagents (prevalence > 0.7 across all sections)
    all_reagents = []
    for section in REAGENT_SECTIONS:
        all_reagents.extend(result[section])
    result["universal_reagents"] = [
        r for r in all_reagents if r["prevalence"] >= 0.7
    ]

    # Highly variable reagents (reported by ≥2 papers, CV > 1.0)
    result["high_variability_reagents"] = [
        r for r in all_reagents
        if r.get("concentration") and r["concentration"].get("high_variability")
        and r["n_papers"] >= 2
    ]

    return result


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

def _flatten_local(p: dict) -> dict:
    """Flatten nested schema fields for uniform consensus computation."""
    flat = dict(p)
    sc = p.get("source_cells") or {}
    if isinstance(sc, dict):
        flat["source_cell_type"] = sc.get("cell_type")
        flat["species"] = sc.get("species")
    mat = p.get("matrix") or {}
    if isinstance(mat, dict):
        flat["matrix"] = mat.get("name")
    bm = p.get("base_media") or {}
    if isinstance(bm, dict):
        flat["base_media"] = bm.get("name")
    return flat


def load_protocols_by_type(
    organoid_type: str | None,
    min_papers: int = 1,
) -> dict[str, list[dict]]:
    """
    Load all protocols grouped by organoid_type.
    Returns {organoid_type: [protocol_dict, ...]}
    """
    by_type: dict[str, list[dict]] = defaultdict(list)

    # 1. Local predictions (full detail)
    if PRED_DIR.exists():
        for pred_file in sorted(PRED_DIR.glob("*.json")):
            try:
                p = json.loads(pred_file.read_text())
            except json.JSONDecodeError:
                continue
            otype = (p.get("organoid_type") or "unknown").lower()
            if organoid_type and otype != organoid_type.lower():
                continue
            flat = _flatten_local(p)
            flat["pmcid"] = pred_file.stem
            by_type[otype].append(flat)

    # 2. Public summary fallback (summary-level only, no reagent detail)
    seen_pmcids: set[str] = {p.get("pmcid", "") for plist in by_type.values() for p in plist}
    if PROTOCOLS_JSONL.exists():
        for line in PROTOCOLS_JSONL.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            pmcid = rec.get("pmcid", "")
            if pmcid in seen_pmcids:
                continue
            otype = (rec.get("organoid_type") or "unknown").lower()
            if organoid_type and otype != organoid_type.lower():
                continue
            by_type[otype].append(rec)

    # Filter types with fewer than min_papers
    return {t: ps for t, ps in by_type.items() if len(ps) >= min_papers}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(description="Compute consensus protocol for organoid type(s)")
    ap.add_argument("organoid_type", nargs="?", default=None,
                    help="Organoid type to compute (e.g. intestinal). Omit with --all.")
    ap.add_argument("--all", action="store_true", help="Compute consensus for all types")
    ap.add_argument("--min-papers", type=int, default=2,
                    help="Min papers per type (default 2)")
    ap.add_argument("--output", "-o", default=None, help="Output JSON path (default: outputs/analysis/)")
    args = ap.parse_args()

    if not args.all and not args.organoid_type:
        ap.error("Specify an organoid_type or use --all")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    target_type = args.organoid_type
    by_type = load_protocols_by_type(target_type, args.min_papers)

    if not by_type:
        print(
            f"No protocols found for type={target_type!r} with min_papers={args.min_papers}.\n"
            "Run: python pipeline/tier1_extract.py  (requires Gemma3/Ollama on A100)",
            file=sys.stderr,
        )
        return

    results = []
    for otype, protocols in sorted(by_type.items()):
        print(f"[{otype}] {len(protocols)} protocols ...", flush=True)
        result = compute_consensus(protocols, otype)
        results.append(result)

        if args.output and not args.all:
            out_path = Path(args.output)
        else:
            out_path = OUT_DIR / f"consensus_{otype}.json"
        out_path.write_text(json.dumps(result, indent=2))
        print(f"  → {out_path}")

        # Print brief summary
        sf = result.get("signaling_factors", [])
        bm = result.get("base_media", {}).get("top")
        mat = result.get("matrix", {}).get("top")
        univ = result.get("universal_reagents", [])
        print(f"  Base media: {bm}  Matrix: {mat}")
        if univ:
            print(f"  Universal (≥70%): {', '.join(r['name'] for r in univ[:5])}")
        if sf:
            top = sf[0]
            conc = top.get("concentration")
            conc_str = f" @ {conc['median']} {conc['unit']}" if conc else ""
            print(f"  Top signaling factor: {top['name']} ({top['prevalence']:.0%}){conc_str}")

    if args.all:
        combined_path = OUT_DIR / "consensus_all.json"
        combined_path.write_text(json.dumps(results, indent=2))
        print(f"\nAll types → {combined_path}")


if __name__ == "__main__":
    main()
