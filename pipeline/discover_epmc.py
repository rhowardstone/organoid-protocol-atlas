#!/usr/bin/env python3
"""
Europe PMC OA discovery — find CC-licensed full-text papers for a topic, OpenAlex-free.

OpenAlex discovery (discover_openalex.py) is great for OA status + license but rate-limits
hard on big sweeps and needs a per-DOI EPMC round-trip to find the PMCID. For PMC-indexed
literature we can skip all that: Europe PMC's own search returns PMCID + license + CC filter
in one paged query, and tier0 already fetches JATS by PMCID. EPMC has ~24k CC organoid
full-text papers vs our ~5k corpus — large headroom, reachable without OpenAlex.

Writes the SAME candidate-CSV schema discover_openalex.py emits (route=epmc_jats, pmcid
filled, license normalized, in_current_corpus flagged), so fetch_openalex_jats.py and
accept_ingest_to_corpus.py consume it unchanged.

cursorMark pagination, crash-safe (flush per page), polite. Run:
  python pipeline/discover_epmc.py --topic organoid --cc-only
  python pipeline/discover_epmc.py --query '"organ-on-a-chip" AND OPEN_ACCESS:Y AND IN_EPMC:Y' --slug ooc
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "data" / "corpus" / "corpus.tsv"
OUTDIR = REPO / "data" / "corpus" / "incoming"
SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

COLS = ["topic", "doi", "pmcid", "title", "year", "oa_status", "license", "oa_url",
        "route", "in_current_corpus"]
# EPMC license strings are lowercase ("cc by", "cc0", "cc by-nc"); map to corpus convention.
LIC_MAP = {"cc by": "CC-BY", "cc-by": "CC-BY", "cc0": "CC0", "cc by-sa": "CC-BY-SA",
           "cc by-nc": "CC-BY-NC", "cc by-nc-nd": "CC-BY-NC-ND", "cc by-nc-sa": "CC-BY-NC-SA",
           "cc by-nd": "CC-BY-ND"}


def norm_doi(d: str | None) -> str:
    return (d or "").replace("https://doi.org/", "").strip().lower()


def norm_license(lic: str | None) -> str:
    s = (lic or "").strip().lower()
    return LIC_MAP.get(s, s.upper() if s else "")


def corpus_keys() -> tuple[set, set]:
    pmcids, dois = set(), set()
    if CORPUS.exists():
        for r in csv.DictReader(CORPUS.open(), delimiter="\t"):
            if r.get("pmcid"):
                pmcids.add(r["pmcid"])
            d = norm_doi(r.get("doi"))
            if d:
                dois.add(d)
    return pmcids, dois


def _get(url: str, tries: int = 6) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": "organoid-protocol-atlas/1.0 (academic research)"})
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=60).read())
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            code = getattr(e, "code", None)
            if code is not None and 400 <= code < 500 and code != 429:
                raise
            if i == tries - 1:
                raise
            time.sleep((10 * (i + 1)) if code == 429 else (2 * (i + 1)))
    raise RuntimeError(f"unreachable: {url}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topic", default="organoid", help="search term (used in query + slug)")
    ap.add_argument("--query", default="", help="full EPMC query (overrides --topic default)")
    ap.add_argument("--slug", default="", help="output filename slug (default from topic)")
    ap.add_argument("--cc-only", action="store_true", help="restrict to CC-BY/CC0 licenses")
    ap.add_argument("--max", type=int, default=0, help="cap candidates (0 = all)")
    args = ap.parse_args()

    if args.query:
        query = args.query
    else:
        query = f'{args.topic} AND OPEN_ACCESS:Y AND IN_EPMC:Y AND HAS_FT:Y'
        if args.cc_only:
            query += ' AND (LICENSE:"cc by" OR LICENSE:"cc0")'
    slug = args.slug or args.topic.replace(" ", "_").replace('"', "")
    out_csv = OUTDIR / f"epmc_candidates_{slug}.csv"
    OUTDIR.mkdir(parents=True, exist_ok=True)
    pmcids, dois = corpus_keys()

    cursor = "*"
    n = n_new = n_incorpus = n_nopmc = 0
    seen_pmcid: set[str] = set()
    f = out_csv.open("w", newline="")
    w = csv.DictWriter(f, fieldnames=COLS)
    w.writeheader()
    print(f"EPMC discovery query={query!r}", flush=True)
    while True:
        p = {"query": query, "format": "json", "pageSize": 1000, "cursorMark": cursor,
             "resultType": "core"}
        try:
            d = _get(f"{SEARCH}?{urllib.parse.urlencode(p)}")
        except Exception as e:  # noqa: BLE001
            print(f"  [paging stopped at {n}] {type(e).__name__}: {e}", flush=True)
            break
        res = d.get("resultList", {}).get("result", [])
        if not res:
            break
        for r in res:
            pmcid = r.get("pmcid") or ""
            if not pmcid:
                n_nopmc += 1
                continue
            if pmcid in seen_pmcid:
                continue
            seen_pmcid.add(pmcid)
            n += 1
            doi = norm_doi(r.get("doi"))
            in_corpus = pmcid in pmcids or (doi and doi in dois)
            if in_corpus:
                n_incorpus += 1
            else:
                n_new += 1
            w.writerow({
                "topic": args.topic, "doi": doi, "pmcid": pmcid,
                "title": (r.get("title") or "")[:300], "year": r.get("pubYear") or "",
                "oa_status": "oa", "license": norm_license(r.get("license")), "oa_url": "",
                "route": "epmc_jats", "in_current_corpus": "1" if in_corpus else "0"})
            if args.max and n >= args.max:
                break
        f.flush()
        if args.max and n >= args.max:
            break
        nxt = d.get("nextCursorMark")
        if not nxt or nxt == cursor:
            break
        cursor = nxt
        if n % 5000 < 1000:
            print(f"  ...{n} candidates ({n_new} new)", flush=True)
        time.sleep(0.2)
    f.close()

    print(f"\nEPMC discovery {args.topic!r}: {n} full-text candidates | in corpus {n_incorpus} | "
          f"NEW {n_new} | no-pmcid skipped {n_nopmc}\n-> {out_csv.relative_to(REPO)}\n"
          f"   next: fetch_openalex_jats --candidates {out_csv.relative_to(REPO)} [--public-only]", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
