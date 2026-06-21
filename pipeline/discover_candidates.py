#!/usr/bin/env python3
"""
Candidate discovery — pull new organoid-protocol paper candidates from Europe PMC.

Goal: scale the corpus past the current handful of papers by surfacing several
hundred open-access, full-text organoid-protocol candidates that downstream
Tier-0 JATS extraction can actually fetch (i.e. they have a PMCID and are in
Europe PMC full text).

What it does
------------
  - Runs one tuned query per organoid type across a BROAD set of well-established
    human/mammalian organoid systems (see TYPE_QUERIES) so the organoid_type
    column can be assigned from the query that found a paper.
  - Restricts to OPEN_ACCESS:Y AND HAS_FT:Y AND IN_EPMC:Y and keeps only rows
    that carry a PMCID — those are the ones Tier 0 can pull JATS for.
  - Paginates each type via cursorMark, politely.
  - DEDUPES against the existing corpus (data/corpus/corpus.tsv) AND the
    already-curated candidate pool (organoid_corpus_candidates_180.csv), by
    BOTH pmcid and doi. Only genuinely new candidates are emitted.
  - DEDUPES ACROSS the (now overlapping) type queries within a single run: a
    paper that matches more than one type is emitted ONCE, labelled with the
    FIRST type whose query surfaced it. TYPE_QUERIES is an ordered mapping with
    more-specific / higher-value types listed before broader synonym queries, so
    "first match wins" == "most-specific type wins". See assign_type().
  - Writes data/corpus/incoming/organoid_corpus_candidates_generated.csv with
    the exact 18-column candidate header.

has_methods is set HEURISTICALLY to "yes" (flag "epmc-ft") when the paper is in
Europe PMC full text with a PMCID — Europe PMC `core` does not expose a real
methods flag, and the downstream orchestrator re-checks methods length anyway.

No LLM. Pure stdlib + requests (already a repo dependency).

Run:
    python pipeline/discover_candidates.py                       # default caps
    python pipeline/discover_candidates.py --limit-per-type 100
    python pipeline/discover_candidates.py --max-total 500
"""

from __future__ import annotations

import argparse
import csv
import time
from collections import Counter
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "data" / "corpus" / "corpus.tsv"
POOL_180 = REPO / "data" / "corpus" / "incoming" / "organoid_corpus_candidates_180.csv"
OUT = REPO / "data" / "corpus" / "incoming" / "organoid_corpus_candidates_generated.csv"

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
UA = "organoid-protocol-atlas/0.1 (research; mailto:19674552+rhowardstone@users.noreply.github.com)"

# Exact 18-column candidate header (matches the curated pools).
HEADER = [
    "organoid_type", "doi", "pmcid", "first_author", "year", "journal", "species",
    "source_cell_type", "license", "has_methods", "has_supplement", "gold_candidate",
    "flags", "notes", "pmid", "title", "cited_by", "in_current_corpus",
]

# Common filter applied to every type query: open access, full text, in Europe PMC.
_OA = '(OPEN_ACCESS:Y AND HAS_FT:Y AND IN_EPMC:Y)'

# The protocol/method clause shared by every type query. It restricts hits to
# method-bearing papers (protocols, differentiation, culture, generation, etc.)
# rather than generic mentions, keeping quality high as we broaden coverage.
_METHOD = ('(protocol OR "differentiation protocol" OR "step-by-step" '
           'OR differentiation OR culture OR generation OR establishment OR derivation)')


def _q(*terms: str) -> str:
    """Build a type query: (organoid synonyms) AND (method clause).

    `terms` are the organoid-specific synonyms; each is OR-ed together. They
    should be specific organoid terminology (e.g. '"cardiac organoid"') so hits
    are real organoid-protocol papers, not generic cell culture.
    """
    syn = " OR ".join(terms)
    return f'(({syn}) AND {_METHOD})'


# One tuned query per organoid type, across a broad set of well-established
# human/mammalian organoid systems. ORDER MATTERS: more-specific / higher-value
# types come first, so when a paper matches several queries the first (most
# specific) type wins — see assign_type() and the module docstring.
#
# Each value restricts to the organ-specific organoid vocabulary so organoid_type
# can be assigned from the query that found the paper.
TYPE_QUERIES = {
    # --- original high-value types (now with broadened synonyms) ---
    "cardiac": _q('"cardiac organoid"', '"heart organoid"', '"cardiac organoids"',
                  '"cardiac microtissue"', 'cardioid'),
    "intestinal": _q('"intestinal organoid"', '"gut organoid"', '"intestinal organoids"',
                     'enteroid', 'colonoid', '"small intestinal organoid"'),
    "cerebral": _q('"cerebral organoid"', '"brain organoid"', '"neural organoid"',
                   '"cortical organoid"', '"midbrain organoid"', '"cerebellar organoid"',
                   '"forebrain organoid"', '"neural organoids"'),
    "retinal": _q('"retinal organoid"', '"optic cup organoid"', '"optic vesicle organoid"',
                  '"retinal organoids"', '"eye organoid"'),
    # cholangiocyte (bile-duct) is more specific than hepatic — list it FIRST so a
    # paper matching both is labelled cholangiocyte (assign_type takes the first match).
    "cholangiocyte": _q('"cholangiocyte organoid"', '"bile duct organoid"',
                        '"biliary organoid"', '"intrahepatic cholangiocyte organoid"'),
    "hepatic": _q('"liver organoid"', '"hepatic organoid"', '"hepatobiliary organoid"',
                  '"liver organoids"', '"hepatocyte organoid"'),
    "kidney": _q('"kidney organoid"', '"renal organoid"', '"nephron organoid"',
                 '"kidney organoids"', '"renal organoids"'),
    "lung": _q('"lung organoid"', '"airway organoid"', '"alveolar organoid"',
               '"lung organoids"', '"bronchial organoid"', '"lung bud organoid"'),
    "gastric": _q('"gastric organoid"', '"stomach organoid"', '"gastric organoids"',
                  '"antral organoid"', '"fundic organoid"'),
    "pancreatic": _q('"pancreatic organoid"', '"pancreas organoid"', '"islet organoid"',
                     '"pancreatic organoids"'),

    # --- newly added organoid systems ---
    "tumor": _q('tumoroid', '"tumor organoid"', '"tumour organoid"',
                '"patient-derived organoid"', '"patient derived organoid"',
                '"cancer organoid"'),
    "vascular": _q('"vascular organoid"', '"blood vessel organoid"',
                   '"blood-vessel organoid"', '"vascularized organoid"'),
    "blood-brain-barrier": _q('"blood-brain barrier organoid"', '"blood brain barrier organoid"',
                              '"BBB organoid"', '"neurovascular organoid"'),
    "thyroid": _q('"thyroid organoid"', '"thyroid follicular organoid"'),
    "salivary-gland": _q('"salivary gland organoid"', '"salivary organoid"',
                         '"submandibular gland organoid"'),
    "prostate": _q('"prostate organoid"', '"prostatic organoid"'),
    "endometrial": _q('"endometrial organoid"', '"uterine organoid"',
                      '"endometrium organoid"'),
    "mammary": _q('"mammary organoid"', '"breast organoid"', '"mammary gland organoid"'),
    "inner-ear": _q('"inner ear organoid"', '"otic organoid"', '"inner-ear organoid"',
                    '"cochlear organoid"'),
    "esophageal": _q('"esophageal organoid"', '"oesophageal organoid"',
                     '"esophagus organoid"'),
    "bladder": _q('"bladder organoid"', '"urothelial organoid"',
                  '"urinary bladder organoid"'),
    "skin": _q('"skin organoid"', '"epidermal organoid"', '"hair follicle organoid"'),
    "bone": _q('"bone organoid"', '"skeletal organoid"', '"osteogenic organoid"',
               '"bone marrow organoid"'),
    "neuromuscular": _q('"neuromuscular organoid"', '"muscle organoid"',
                        '"skeletal muscle organoid"', '"myogenic organoid"'),
    "fallopian-tube": _q('"fallopian tube organoid"', '"oviduct organoid"',
                         '"fallopian-tube organoid"'),
}


def assign_type(matched_types: list[str]) -> str | None:
    """Given the types whose queries matched a paper (in TYPE_QUERIES order),
    return the single type to label it with: the FIRST (most-specific) one.

    Returns None if the list is empty. This is the across-query dedup rule made
    explicit and unit-testable; the driver enforces it implicitly by iterating
    TYPE_QUERIES in order and skipping papers already emitted under an earlier
    type.
    """
    return matched_types[0] if matched_types else None


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested offline)
# --------------------------------------------------------------------------- #

# Europe PMC license strings are lowercase, space-separated (e.g. "cc by",
# "cc by-nc", "cc0"). Normalize to the corpus conventions.
def normalize_license(raw: str | None) -> str:
    """Map a Europe PMC license string to corpus conventions."""
    if not raw:
        return "unknown"
    s = raw.strip().lower().replace("_", " ").replace("-", " ")
    s = " ".join(s.split())
    if "cc0" in s or "public domain" in s:
        return "CC0"
    if "cc by" in s or s == "ccby":
        # Distinguish the NC variant; SA/ND still fall under CC-BY family here.
        if "nc" in s.split():
            return "CC-BY-NC"
        return "CC-BY"
    return "unknown"


def first_author_lastname(result: dict) -> str:
    """Last name of the first author, falling back to authorString parsing."""
    al = (result.get("authorList") or {}).get("author") or []
    if al:
        a = al[0]
        ln = (a.get("lastName") or "").strip()
        if ln:
            return ln
        full = (a.get("fullName") or "").strip()
        if full:
            return full.split()[0]
    # fallback: "Smith J, Doe A" -> "Smith"
    s = (result.get("authorString") or "").strip()
    if s:
        first = s.split(",")[0].strip()
        return first.split()[0] if first else ""
    return ""


def journal_title(result: dict) -> str:
    return (((result.get("journalInfo") or {}).get("journal") or {}).get("title") or "").strip()


def build_row(result: dict, organoid_type: str) -> dict | None:
    """Build a candidate row dict from a Europe PMC core result.

    Returns None if the result is unusable (no PMCID, or not full-text in EPMC).
    """
    pmcid = (result.get("pmcid") or "").strip()
    if not pmcid:
        return None
    in_epmc = (result.get("inEPMC") or "").strip().upper() == "Y"
    is_oa = (result.get("isOpenAccess") or "").strip().upper() == "Y"
    if not (in_epmc and is_oa):
        return None

    cited = result.get("citedByCount")
    return {
        "organoid_type": organoid_type,
        "doi": (result.get("doi") or "").strip(),
        "pmcid": pmcid,
        "first_author": first_author_lastname(result),
        "year": (result.get("pubYear") or "").strip(),
        "journal": journal_title(result),
        "species": "tbd",
        "source_cell_type": "tbd",
        "license": normalize_license(result.get("license")),
        # heuristic: full text in EPMC with a PMCID -> methods very likely fetchable.
        "has_methods": "yes",
        "has_supplement": "tbd",
        "gold_candidate": "no",
        "flags": "epmc-ft",
        "notes": f"europepmc discover {organoid_type}",
        "pmid": (result.get("pmid") or "").strip(),
        "title": (result.get("title") or "").strip().rstrip("."),
        "cited_by": str(cited) if cited is not None else "",
        "in_current_corpus": "no",
    }


def load_existing_keys() -> tuple[set[str], set[str]]:
    """Return (pmcids, dois) already present in the corpus or the curated pool."""
    pmcids: set[str] = set()
    dois: set[str] = set()

    def _add(pmcid: str, doi: str):
        if pmcid:
            pmcids.add(pmcid.strip().upper())
        if doi:
            dois.add(doi.strip().lower())

    if CORPUS.exists():
        with open(CORPUS, newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                _add(row.get("pmcid", ""), row.get("doi", ""))
    if POOL_180.exists():
        with open(POOL_180, newline="") as f:
            for row in csv.DictReader(f):
                _add(row.get("pmcid", ""), row.get("doi", ""))
    return pmcids, dois


def is_new(row: dict, seen_pmcids: set[str], seen_dois: set[str]) -> bool:
    """True if neither the pmcid nor the (non-empty) doi has been seen.

    Comparison is normalized on both sides (pmcid case-insensitive, doi
    case-insensitive) so it is robust to how the seen sets were populated.
    """
    pmcid = row["pmcid"].strip().upper()
    doi = row["doi"].strip().lower()
    norm_pmcids = {p.strip().upper() for p in seen_pmcids}
    norm_dois = {d.strip().lower() for d in seen_dois}
    if pmcid and pmcid in norm_pmcids:
        return False
    if doi and doi in norm_dois:
        return False
    return True


# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #

def epmc_page(query: str, cursor: str, page_size: int) -> dict:
    """One Europe PMC search page. Retries once on error/timeout."""
    params = {
        "query": query,
        "format": "json",
        "pageSize": page_size,
        "resultType": "core",
        "cursorMark": cursor,
    }
    last_err = None
    for attempt in range(2):
        try:
            r = requests.get(EPMC, params=params, timeout=40, headers={"User-Agent": UA})
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt == 0:
                time.sleep(2.0)
    raise RuntimeError(f"Europe PMC request failed after retry: {last_err}")


def search_type(query: str, organoid_type: str, limit: int, page_size: int,
                sleep: float) -> list[dict]:
    """Pull up to `limit` candidate rows for one type, paginating via cursorMark."""
    rows: list[dict] = []
    cursor = "*"
    while len(rows) < limit:
        data = epmc_page(query, cursor, page_size)
        results = (data.get("resultList") or {}).get("result") or []
        if not results:
            break
        for res in results:
            row = build_row(res, organoid_type)
            if row is not None:
                rows.append(row)
                if len(rows) >= limit:
                    break
        next_cursor = data.get("nextCursorMark")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
        time.sleep(sleep)
    return rows


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description="Discover organoid-protocol candidates from Europe PMC")
    ap.add_argument("--limit-per-type", type=int, default=60,
                    help="max kept rows pulled per organoid type (default 60)")
    ap.add_argument("--max-total", type=int, default=0,
                    help="cap on total unique new candidates emitted (0 = no cap)")
    ap.add_argument("--page-size", type=int, default=100, help="Europe PMC page size (default 100)")
    ap.add_argument("--sleep", type=float, default=0.34, help="delay between pages (politeness)")
    args = ap.parse_args()

    seen_pmcids, seen_dois = load_existing_keys()
    print(f"Dedup baseline: {len(seen_pmcids)} pmcids, {len(seen_dois)} dois "
          f"(corpus + curated pool)\n", flush=True)

    emitted: list[dict] = []
    per_type: Counter = Counter()

    for organoid_type, query in TYPE_QUERIES.items():
        print(f"[{organoid_type}] querying Europe PMC ...", flush=True)
        try:
            candidates = search_type(query, organoid_type, args.limit_per_type,
                                     args.page_size, args.sleep)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {organoid_type} failed: {e}", flush=True)
            continue

        new_for_type = 0
        for row in candidates:
            if not is_new(row, seen_pmcids, seen_dois):
                continue
            # also dedupe within this run
            emitted.append(row)
            seen_pmcids.add(row["pmcid"].strip().upper())
            if row["doi"]:
                seen_dois.add(row["doi"].strip().lower())
            per_type[organoid_type] += 1
            new_for_type += 1
            if args.max_total and len(emitted) >= args.max_total:
                break
        print(f"  {len(candidates)} fetched, {new_for_type} new unique", flush=True)
        if args.max_total and len(emitted) >= args.max_total:
            print("  reached --max-total cap", flush=True)
            break

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(emitted)

    # summary
    lic = Counter(r["license"] for r in emitted)
    print("\n=== Summary ===")
    print(f"Total unique NEW candidates: {len(emitted)}")
    print("Per-type:")
    for t in TYPE_QUERIES:
        print(f"  {t:12s} {per_type.get(t, 0)}")
    print("License distribution:")
    for k, v in lic.most_common():
        print(f"  {k:10s} {v}")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
