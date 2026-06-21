#!/usr/bin/env python3
"""
Citation Graph Expansion — discover new organoid-protocol candidates via cited references.

For each paper already in corpus.tsv, fetches its reference list from Europe PMC and
surfaces new open-access candidates that have not yet been ingested. This leverages
the "wisdom" of known-good corpus papers: papers they cite are likely to be relevant.

Europe PMC APIs used:
  References: GET /rest/{pmcid}/references?source=PMC&format=json&pageSize=100
  Search:     GET /rest/search?query=EXT_ID:{id}+AND+SRC:{source}&resultType=core&format=json

Output:
  data/corpus/incoming/citation_expansion_candidates.csv  (18-col HEADER format)
  outputs/validation/citation_expansion_stats.json

Run:
    python pipeline/citation_expand.py
    python pipeline/citation_expand.py --limit-per-paper 50 --max-total 200
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))

from discover_candidates import (  # noqa: E402
    HEADER,
    first_author_lastname,
    journal_title,
    load_existing_keys,
    normalize_license,
)

CORPUS = REPO / "data" / "corpus" / "corpus.tsv"
OUT_CSV = REPO / "data" / "corpus" / "incoming" / "citation_expansion_candidates.csv"
OUT_STATS = REPO / "outputs" / "validation" / "citation_expansion_stats.json"

EPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
UA = "organoid-protocol-atlas/0.1 (research; mailto:19674552+rhowardstone@users.noreply.github.com)"

SLEEP_BETWEEN_PAPERS = 0.5  # polite rate limiting


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def fetch_references(pmcid: str, session: requests.Session) -> list[dict]:
    """Fetch reference list for one corpus paper from Europe PMC.

    Returns list of reference dicts (may be empty on error or no references).
    Each dict has keys like: id, source, title, authorString, pubYear, etc.
    """
    url = f"{EPMC_BASE}/{pmcid}/references"
    params = {"source": "PMC", "format": "json", "pageSize": 100}
    try:
        resp = session.get(url, params=params, timeout=30, headers={"User-Agent": UA})
        resp.raise_for_status()
        data = resp.json()
        refs = (data.get("referenceList") or {}).get("reference") or []
        return list(refs)
    except Exception as e:  # noqa: BLE001
        print(f"  ! fetch_references({pmcid}) failed: {e}", flush=True)
        return []


def enrich_reference(ref: dict, session: requests.Session) -> dict | None:
    """Look up a reference in Europe PMC to get pmcid, license, OA status.

    First checks if the reference dict already carries pmcid + OA info (from the
    references endpoint). If not, calls the search API.

    Returns a Europe PMC core result dict (with pmcid, isOpenAccess, license, etc.)
    or None if not found, not OA, or not in EPMC with a PMCID.
    """
    # Fast path: reference already has pmcid and OA status
    if ref.get("pmcid") and (ref.get("isOpenAccess") or "").upper() == "Y":
        return ref

    ref_id = (ref.get("id") or "").strip()
    source = (ref.get("source") or "MED").strip()
    if not ref_id:
        return None

    query = f"EXT_ID:{ref_id} AND SRC:{source}"
    params = {"query": query, "resultType": "core", "format": "json", "pageSize": 1}
    try:
        resp = session.get(
            f"{EPMC_BASE}/search", params=params, timeout=30, headers={"User-Agent": UA}
        )
        resp.raise_for_status()
        data = resp.json()
        results = (data.get("resultList") or {}).get("result") or []
        if not results:
            return None
        result = results[0]
        # Must be open access and in EPMC with a PMCID
        is_oa = (result.get("isOpenAccess") or "").upper() == "Y"
        in_epmc = (result.get("inEPMC") or "").upper() == "Y"
        has_pmcid = bool((result.get("pmcid") or "").strip())
        if is_oa and in_epmc and has_pmcid:
            return result
        return None
    except Exception as e:  # noqa: BLE001
        print(f"  ! enrich_reference({ref_id}) failed: {e}", flush=True)
        return None


def _build_row(result: dict, source_pmcid: str) -> dict:
    """Build a candidate row from an enriched Europe PMC result dict."""
    return {
        "organoid_type": "tbd",
        "doi": (result.get("doi") or "").strip(),
        "pmcid": (result.get("pmcid") or "").strip(),
        "first_author": first_author_lastname(result),
        "year": (result.get("pubYear") or result.get("year") or "").strip(),
        "journal": journal_title(result),
        "species": "tbd",
        "source_cell_type": "tbd",
        "license": normalize_license(result.get("license")),
        "has_methods": "yes",  # heuristic: full text in EPMC with PMCID
        "has_supplement": "tbd",
        "gold_candidate": "no",
        "flags": "citation-expansion",
        "notes": f"cited by {source_pmcid}",
        "pmid": (result.get("pmid") or "").strip(),
        "title": (result.get("title") or "").strip().rstrip("."),
        "cited_by": str(result.get("citedByCount", "")),
        "in_current_corpus": "no",
    }


def expand_corpus(
    corpus_pmcids: list[str],
    existing_pmcids: set,
    existing_dois: set,
    session: requests.Session,
    limit_per_paper: int = 50,
) -> list[dict]:
    """For each corpus paper, fetch references, enrich, filter to new OA candidates.

    Deduplicates across papers (a paper cited by multiple corpus papers appears once).
    Returns list of candidate row dicts using the 18-column HEADER format.
    """
    seen_pmcids = {p.strip().upper() for p in existing_pmcids}
    seen_dois = {d.strip().lower() for d in existing_dois}
    new_candidates: list[dict] = []

    for source_pmcid in corpus_pmcids:
        print(f"[{source_pmcid}] fetching references ...", flush=True)
        refs = fetch_references(source_pmcid, session)
        print(f"  {len(refs)} references found", flush=True)

        enriched_count = 0
        new_for_paper = 0
        for ref in refs:
            if enriched_count >= limit_per_paper:
                break
            result = enrich_reference(ref, session)
            enriched_count += 1
            if result is None:
                continue

            pmcid = (result.get("pmcid") or "").strip().upper()
            doi = (result.get("doi") or "").strip().lower()

            # Skip if already in corpus or seen this run
            if pmcid and pmcid in seen_pmcids:
                continue
            if doi and doi in seen_dois:
                continue

            row = _build_row(result, source_pmcid)
            new_candidates.append(row)
            if pmcid:
                seen_pmcids.add(pmcid)
            if doi:
                seen_dois.add(doi)
            new_for_paper += 1

        print(f"  {new_for_paper} new unique OA candidates", flush=True)
        time.sleep(SLEEP_BETWEEN_PAPERS)

    return new_candidates


# ---------------------------------------------------------------------------
# Corpus reader
# ---------------------------------------------------------------------------

def read_corpus_pmcids(corpus_path: Path) -> list[str]:
    """Return list of PMCIDs from corpus TSV (non-empty only)."""
    if not corpus_path.exists():
        return []
    with open(corpus_path, newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return [r["pmcid"].strip() for r in rows if r.get("pmcid", "").strip()]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Citation graph expansion via Europe PMC references")
    ap.add_argument(
        "--limit-per-paper",
        type=int,
        default=50,
        help="Max references to enrich per corpus paper (default: 50)",
    )
    ap.add_argument(
        "--max-total",
        type=int,
        default=200,
        help="Cap on total new candidates emitted (0 = no cap, default: 200)",
    )
    ap.add_argument(
        "--corpus",
        type=Path,
        default=CORPUS,
        help="Corpus TSV path (default: data/corpus/corpus.tsv)",
    )
    args = ap.parse_args()

    # Load existing keys for dedup
    existing_pmcids, existing_dois = load_existing_keys()
    corpus_pmcids = read_corpus_pmcids(args.corpus)

    print(f"Corpus papers to expand: {len(corpus_pmcids)}")
    print(f"Dedup baseline: {len(existing_pmcids)} pmcids, {len(existing_dois)} dois\n")

    session = requests.Session()

    candidates = expand_corpus(
        corpus_pmcids,
        existing_pmcids,
        existing_dois,
        session,
        limit_per_paper=args.limit_per_paper,
    )

    # Apply max-total cap
    if args.max_total and len(candidates) > args.max_total:
        candidates = candidates[: args.max_total]
        print(f"\nCapped to --max-total {args.max_total}")

    # Write output CSV
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(candidates)
    print(f"\nWrote {len(candidates)} candidates to {OUT_CSV}")

    # Write stats
    OUT_STATS.parent.mkdir(parents=True, exist_ok=True)
    stats = {
        "corpus_papers_expanded": len(corpus_pmcids),
        "new_candidates_found": len(candidates),
        "limit_per_paper": args.limit_per_paper,
        "max_total": args.max_total,
        "output_csv": str(OUT_CSV),
    }
    OUT_STATS.write_text(json.dumps(stats, indent=2))
    print(f"Wrote stats to {OUT_STATS}")


if __name__ == "__main__":
    main()
