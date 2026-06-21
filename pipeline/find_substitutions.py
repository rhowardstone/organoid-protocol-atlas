#!/usr/bin/env python3
"""
Reagent substitution finder: search ProtocolModification records for papers
that substituted one reagent for another.

Answers questions like:
  "Which papers replaced Matrigel with an alternative?"
  "Which papers substituted Noggin with LDN-193189?"
  "What protocols changed their base media from DMEM?"

Data source: data/predictions/local/{pmcid}.json (full predictions with modifications)
Fallback: outputs/tier1/extraction_summary.json (if available)

Run:
  python pipeline/find_substitutions.py "Matrigel"
  python pipeline/find_substitutions.py "Noggin" --from-only
  python pipeline/find_substitutions.py "DMEM" --to-only
  python pipeline/find_substitutions.py "matrigel" "laminin"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PRED_DIR = REPO / "data" / "predictions" / "local"
SUMMARY_PATH = REPO / "outputs" / "tier1" / "extraction_summary.json"


# --------------------------------------------------------------------------- #
# Pure search logic (fully offline-testable)
# --------------------------------------------------------------------------- #

def _matches(text: str, pattern: str) -> bool:
    return bool(re.search(re.escape(pattern), text, re.IGNORECASE))


def search_substitutions(
    modifications: list[dict],
    query_from: str | None,
    query_to: str | None,
    from_only: bool = False,
    to_only: bool = False,
) -> list[dict]:
    """
    Search modifications for substitutions involving query terms.

    query_from: term that must appear in change_description (e.g. 'Matrigel')
    query_to: optional secondary term (if provided, both must match)

    Modes:
      default:    query_from must appear anywhere in change_description
      from_only:  query_from likely being REMOVED (appears before →, 'replaced', 'from')
      to_only:    query_from likely being ADDED (appears after →, 'with', 'to')

    Returns matching modification records with source_doi, pmcid, change_description.
    """
    if not query_from:
        return []

    results = []
    for m in modifications:
        desc = m.get("change_description") or ""
        if not desc.strip():
            continue

        # Basic match: term appears somewhere
        if not _matches(desc, query_from):
            continue

        # Secondary term filter
        if query_to and not _matches(desc, query_to):
            continue

        results.append(m)

    return results


def load_all_modifications() -> list[dict]:
    """Load modification records from local predictions + extraction summary."""
    records: list[dict] = []
    seen: set[tuple] = set()

    # Local predictions
    if PRED_DIR.exists():
        for pred_file in sorted(PRED_DIR.glob("*.json")):
            pmcid = pred_file.stem
            try:
                p = json.loads(pred_file.read_text())
            except json.JSONDecodeError:
                continue
            src_doi = p.get("source_doi", "")
            otype = p.get("organoid_type", "unknown")
            for mod in p.get("modifications") or []:
                rec = {
                    "source_doi": src_doi,
                    "cited_doi": mod.get("cited_doi", ""),
                    "change_description": mod.get("change_description", ""),
                    "pmcid": pmcid,
                    "organoid_type": otype,
                }
                key = (src_doi, mod.get("change_description", "")[:60])
                if key not in seen:
                    seen.add(key)
                    records.append(rec)

    # Summary fallback
    if SUMMARY_PATH.exists():
        try:
            data = json.loads(SUMMARY_PATH.read_text())
        except json.JSONDecodeError:
            data = {}
        for row in data.get("rows") or []:
            src_doi = row.get("doi", "")
            pmcid = row.get("pmcid", "")
            otype = row.get("organoid_type", "unknown")
            for mod in row.get("modifications") or []:
                if not isinstance(mod, dict):
                    continue
                rec = {
                    "source_doi": src_doi,
                    "cited_doi": mod.get("cited_doi", ""),
                    "change_description": mod.get("change_description", ""),
                    "pmcid": pmcid,
                    "organoid_type": otype,
                }
                key = (src_doi, mod.get("change_description", "")[:60])
                if key not in seen:
                    seen.add(key)
                    records.append(rec)

    return records


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Search protocol modifications for reagent substitutions"
    )
    ap.add_argument("term", help="Reagent or phrase to search for (regex-escaped)")
    ap.add_argument("to_term", nargs="?", default=None,
                    help="Optional second term — both must appear in the modification")
    ap.add_argument("--from-only", action="store_true",
                    help="Hint: term is the thing being replaced (for display only)")
    ap.add_argument("--to-only", action="store_true",
                    help="Hint: term is the thing being added (for display only)")
    ap.add_argument("--organoid-type", default=None, help="Filter by organoid type")
    ap.add_argument("--json", dest="output_json", action="store_true",
                    help="Output JSON instead of human-readable text")
    args = ap.parse_args()

    modifications = load_all_modifications()

    if args.organoid_type:
        modifications = [m for m in modifications
                         if m.get("organoid_type", "").lower() == args.organoid_type.lower()]

    hits = search_substitutions(
        modifications,
        args.term,
        args.to_term,
        from_only=args.from_only,
        to_only=args.to_only,
    )

    if not hits:
        qualifier = f" in '{args.organoid_type}'" if args.organoid_type else ""
        print(f"No substitutions found involving '{args.term}'{qualifier}.")
        if not modifications:
            print("(No modification records loaded — run Tier-1 extraction on A100 first.)")
        return

    if args.output_json:
        print(json.dumps(hits, indent=2))
        return

    term2 = f" + '{args.to_term}'" if args.to_term else ""
    print(f"Found {len(hits)} modification(s) involving '{args.term}'{term2}:\n")
    for h in hits:
        print(f"  PMCID:    {h['pmcid']}")
        print(f"  DOI:      {h['source_doi']}")
        print(f"  Type:     {h['organoid_type']}")
        print(f"  Change:   {h['change_description']}")
        if h.get("cited_doi"):
            print(f"  Base DOI: {h['cited_doi']}")
        print()


if __name__ == "__main__":
    main()
