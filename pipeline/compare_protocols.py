#!/usr/bin/env python3
"""
Protocol comparison engine: diff two organoid protocols across reagents,
concentrations, timeline, failure modes, and lineage.

Data sources (tried in order):
  1. data/predictions/local/{pmcid}.json  -- full v0.4 prediction (local-only)
  2. exports/public/protocols.jsonl        -- summary-level fallback (no reagents)

Usage:
  python pipeline/compare_protocols.py PMC1234567 PMC9876543
  python pipeline/compare_protocols.py PMC1234567 PMC9876543 --output path/out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
PRED_DIR = REPO / "data" / "predictions" / "local"
PROTOCOLS_JSONL = REPO / "exports" / "public" / "protocols.jsonl"
OUT_DIR = REPO / "outputs" / "comparison"

# Fields compared as plain scalars (value may differ between protocols)
SCALAR_FIELDS = [
    "organoid_type",
    "species",
    "source_cell_type",
    "matrix",
    "base_media",
    "passaging",
]


# --------------------------------------------------------------------------- #
# Pure diff logic (fully offline-testable)
# --------------------------------------------------------------------------- #

def _reagent_key(r: dict) -> str:
    """Stable identity key for a reagent: canonical_name > name, lowercased."""
    name = (r.get("canonical_name") or r.get("name") or "").strip().lower()
    return name


def diff_reagent_lists(
    a: list[dict], b: list[dict]
) -> dict[str, Any]:
    """
    Diff two reagent lists.
    Returns {added, removed, concentration_changed} where each item carries
    the reagent name and concentration detail.
    """
    a_map = {_reagent_key(r): r for r in a if _reagent_key(r)}
    b_map = {_reagent_key(r): r for r in b if _reagent_key(r)}

    only_a = set(a_map) - set(b_map)
    only_b = set(b_map) - set(a_map)
    both = set(a_map) & set(b_map)

    conc_changed = []
    for key in sorted(both):
        ca = _extract_concentration(a_map[key])
        cb = _extract_concentration(b_map[key])
        if ca != cb:
            conc_changed.append({
                "name": key,
                "a": ca,
                "b": cb,
            })

    return {
        "added_in_b": [_reagent_summary(b_map[k]) for k in sorted(only_b)],
        "removed_in_b": [_reagent_summary(a_map[k]) for k in sorted(only_a)],
        "concentration_changed": conc_changed,
    }


def _extract_concentration(r: dict) -> dict | None:
    c = r.get("concentration")
    if not c:
        return None
    return {
        "value": c.get("value"),
        "unit": c.get("canonical_unit") or c.get("unit"),
        "raw": c.get("raw"),
    }


def _reagent_summary(r: dict) -> dict:
    return {
        "name": r.get("name", ""),
        "canonical_name": r.get("canonical_name"),
        "role": r.get("role"),
        "concentration": _extract_concentration(r),
    }


def diff_scalar_fields(a: dict, b: dict, fields: list[str]) -> dict[str, dict]:
    """
    Compare named scalar fields between two flat dicts.
    Returns {field: {a: val, b: val}} for fields that differ.
    """
    out: dict[str, dict] = {}
    for f in fields:
        va = a.get(f)
        vb = b.get(f)
        if va != vb:
            out[f] = {"a": va, "b": vb}
    return out


def diff_timeline(a: list[dict], b: list[dict]) -> dict[str, Any]:
    """
    Diff timeline stage lists by stage name (positional labels when names missing).
    """
    def _stage_key(s: dict, idx: int) -> str:
        return (s.get("name") or s.get("stage") or str(idx)).strip().lower()

    a_map = {_stage_key(s, i): s for i, s in enumerate(a)}
    b_map = {_stage_key(s, i): s for i, s in enumerate(b)}

    only_a = sorted(set(a_map) - set(b_map))
    only_b = sorted(set(b_map) - set(a_map))
    both = set(a_map) & set(b_map)

    duration_changed = []
    for key in sorted(both):
        da = a_map[key].get("duration") or a_map[key].get("duration_days")
        db = b_map[key].get("duration") or b_map[key].get("duration_days")
        if da != db:
            duration_changed.append({"stage": key, "a": da, "b": db})

    return {
        "added_in_b": [b_map[k] for k in only_b],
        "removed_in_b": [a_map[k] for k in only_a],
        "duration_changed": duration_changed,
    }


def diff_text_list(a: list[str], b: list[str], label: str) -> dict[str, list[str]]:
    """
    Diff two lists of strings (failure mode descriptions, assay endpoints, etc.)
    using set semantics on lowercased values.
    """
    a_set = {v.strip().lower() for v in a if v}
    b_set = {v.strip().lower() for v in b if v}
    return {
        f"added_in_b": sorted(b_set - a_set),
        f"removed_in_b": sorted(a_set - b_set),
    }


def diff_failure_modes(a: list[dict], b: list[dict]) -> dict[str, list]:
    """
    Diff failure mode lists by description (lowercased set membership).
    """
    a_descs = {(fm.get("description") or "").strip().lower(): fm for fm in a}
    b_descs = {(fm.get("description") or "").strip().lower(): fm for fm in b}
    only_a = sorted(set(a_descs) - set(b_descs))
    only_b = sorted(set(b_descs) - set(a_descs))
    return {
        "added_in_b": [b_descs[k] for k in only_b],
        "removed_in_b": [a_descs[k] for k in only_a],
    }


def diff_modifications(a: list[dict], b: list[dict]) -> dict[str, list]:
    """
    Diff ProtocolModification lists by change_description (set membership).
    """
    def _key(m: dict) -> str:
        return (m.get("change_description") or "").strip().lower()

    a_map = {_key(m): m for m in a}
    b_map = {_key(m): m for m in b}
    return {
        "added_in_b": [b_map[k] for k in sorted(set(b_map) - set(a_map))],
        "removed_in_b": [a_map[k] for k in sorted(set(a_map) - set(b_map))],
    }


def compare_protocols(pa: dict, pb: dict, pmcid_a: str, pmcid_b: str) -> dict:
    """
    Master diff function. Accepts two protocol dicts (full or summary).
    Returns structured comparison JSON.
    """
    result: dict[str, Any] = {
        "pmcid_a": pmcid_a,
        "pmcid_b": pmcid_b,
        "source_a": pa.get("_source", "unknown"),
        "source_b": pb.get("_source", "unknown"),
        "schema_version_a": pa.get("schema_version"),
        "schema_version_b": pb.get("schema_version"),
    }

    # Flatten nested scalar fields for comparison
    flat_a = _flatten(pa)
    flat_b = _flatten(pb)

    result["metadata_diff"] = diff_scalar_fields(flat_a, flat_b, SCALAR_FIELDS)

    # Reagent diffs (only available in full predictions)
    for section in ("signaling_factors", "media_supplements", "small_molecules"):
        la = pa.get(section) or []
        lb = pb.get(section) or []
        result[f"{section}_diff"] = diff_reagent_lists(la, lb)

    # Timeline
    tl_a = pa.get("timeline") or []
    tl_b = pb.get("timeline") or []
    if isinstance(tl_a, str):
        tl_a = []  # summary-level is a string description, not a list
    if isinstance(tl_b, str):
        tl_b = []
    result["timeline_diff"] = diff_timeline(tl_a, tl_b)

    # Failure modes (v0.4+)
    result["failure_modes_diff"] = diff_failure_modes(
        pa.get("failure_modes") or [], pb.get("failure_modes") or []
    )

    # Protocol modifications / lineage
    result["modifications_diff"] = diff_modifications(
        pa.get("modifications") or [], pb.get("modifications") or []
    )

    # Assay endpoints (list of strings in full predictions, pipe-delimited string in summary)
    ep_a = _to_str_list(pa.get("assay_endpoints"))
    ep_b = _to_str_list(pb.get("assay_endpoints"))
    result["assay_endpoints_diff"] = diff_text_list(ep_a, ep_b, "assay_endpoints")

    # Summary counts
    result["summary"] = _build_summary(result)
    return result


def _flatten(p: dict) -> dict:
    """Pull nested scalar fields up for uniform comparison."""
    flat = dict(p)
    sc = p.get("source_cells") or {}
    if isinstance(sc, dict):
        flat.setdefault("species", sc.get("species"))
        flat.setdefault("source_cell_type", sc.get("cell_type"))
    mat = p.get("matrix") or {}
    if isinstance(mat, dict):
        flat["matrix"] = mat.get("name") or mat.get("matrix")
    bm = p.get("base_media") or {}
    if isinstance(bm, dict):
        flat["base_media"] = bm.get("name") or bm.get("base_media")
    pa = p.get("passaging") or {}
    if isinstance(pa, dict):
        flat["passaging"] = pa.get("method") or pa.get("passaging")
    return flat


def _to_str_list(val: Any) -> list[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(v) for v in val]
    # pipe-delimited summary string
    return [s.strip() for s in str(val).split("·") if s.strip()]


def _build_summary(result: dict) -> dict:
    counts: dict[str, int] = {}
    for section in (
        "signaling_factors_diff", "media_supplements_diff", "small_molecules_diff"
    ):
        d = result.get(section, {})
        counts[f"{section}_added"] = len(d.get("added_in_b", []))
        counts[f"{section}_removed"] = len(d.get("removed_in_b", []))
        counts[f"{section}_conc_changed"] = len(d.get("concentration_changed", []))
    fm = result.get("failure_modes_diff", {})
    counts["failure_modes_added"] = len(fm.get("added_in_b", []))
    counts["failure_modes_removed"] = len(fm.get("removed_in_b", []))
    tl = result.get("timeline_diff", {})
    counts["timeline_stages_added"] = len(tl.get("added_in_b", []))
    counts["timeline_stages_removed"] = len(tl.get("removed_in_b", []))
    counts["metadata_fields_differ"] = len(result.get("metadata_diff", {}))
    counts["total_differences"] = sum(counts.values())
    return counts


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

def load_protocol(pmcid: str) -> dict:
    """Load a protocol from local predictions or public summary fallback."""
    local_path = PRED_DIR / f"{pmcid}.json"
    if local_path.exists():
        p = json.loads(local_path.read_text())
        p["_source"] = "local_prediction"
        return p

    # Fallback: search protocols.jsonl by PMCID
    if PROTOCOLS_JSONL.exists():
        for line in PROTOCOLS_JSONL.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("pmcid", "").upper() == pmcid.upper():
                rec["_source"] = "public_summary"
                return rec

    raise FileNotFoundError(
        f"No prediction found for {pmcid}. "
        f"Run: python pipeline/tier1_extract.py   (requires Gemma3/Ollama)\n"
        f"Checked: {local_path}\n"
        f"Fallback: {PROTOCOLS_JSONL}"
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(description="Diff two organoid protocols")
    ap.add_argument("pmcid_a", help="First PMCID (e.g. PMC1234567)")
    ap.add_argument("pmcid_b", help="Second PMCID (e.g. PMC9876543)")
    ap.add_argument("--output", "-o", help="Output JSON path (default: outputs/comparison/)")
    ap.add_argument("--pretty", action="store_true", default=True,
                    help="Pretty-print JSON (default: on)")
    args = ap.parse_args()

    pmcid_a = args.pmcid_a.upper()
    pmcid_b = args.pmcid_b.upper()

    try:
        pa = load_protocol(pmcid_a)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        pb = load_protocol(pmcid_b)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    result = compare_protocols(pa, pb, pmcid_a, pmcid_b)
    indent = 2 if args.pretty else None
    out_json = json.dumps(result, indent=indent)

    if args.output:
        out_path = Path(args.output)
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUT_DIR / f"{pmcid_a}_vs_{pmcid_b}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(out_json)
    print(f"Comparison written → {out_path}")

    s = result["summary"]
    print(f"\nSummary ({pmcid_a} vs {pmcid_b}):")
    print(f"  Metadata differences:   {s['metadata_fields_differ']}")
    print(f"  Signaling factors:      +{s['signaling_factors_diff_added']} / -{s['signaling_factors_diff_removed']} / ~{s['signaling_factors_diff_conc_changed']}")
    print(f"  Media supplements:      +{s['media_supplements_diff_added']} / -{s['media_supplements_diff_removed']} / ~{s['media_supplements_diff_conc_changed']}")
    print(f"  Small molecules:        +{s['small_molecules_diff_added']} / -{s['small_molecules_diff_removed']} / ~{s['small_molecules_diff_conc_changed']}")
    print(f"  Timeline stages:        +{s['timeline_stages_added']} / -{s['timeline_stages_removed']}")
    print(f"  Failure modes:          +{s['failure_modes_added']} / -{s['failure_modes_removed']}")
    print(f"  Total differences:      {s['total_differences']}")


if __name__ == "__main__":
    main()
