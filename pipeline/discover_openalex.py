#!/usr/bin/env python3
"""
OpenAlex OA discovery — find open-access works for a topic and emit ingest candidates.

The journal corpus is discovered via Europe PMC with organoid-only queries, so whole
adjacent literatures (notably organ-on-a-chip / microphysiological systems: ~6,680 OA
works, 0 captured) are missing. OpenAlex indexes them with authoritative OA status +
license, which Europe PMC search alone does not give cleanly. We page OpenAlex for a
topic, keep OA works, and write candidates tagged with the cheapest viable fetch route:

  - route=epmc_jats : the DOI resolves to a Europe PMC full-text record -> reuse the
                      existing tier0 JATS fetch (clean, CC-redistributable, no new code).
  - route=pdf       : OA only as a publisher/repository PDF -> needs the pymupdf PDF->text
                      adapter (separate, the one genuinely new capability).
  - route=none      : OA flagged but no usable full-text location found.

Empirically ~78% of CC organ-on-chip DOIs are in EPMC (epmc_jats), ~21% pdf-only.

License is taken from OpenAlex (primary_location.license / oa_status); the corpus's
existing is_public_license gate decides public-redistribution downstream. DOIs already
in data/corpus/corpus.tsv are tagged in_current_corpus=1 so the ingest can skip them.

Network-only, resumable (cursor + idempotent CSV). Run:
  python pipeline/discover_openalex.py --topic "organ-on-a-chip"
  python pipeline/discover_openalex.py --topic organoid --max 0   # 0 = all
  python pipeline/discover_openalex.py --topic "organ-on-a-chip" --resolve-epmc --max 1500
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
EMAIL = "rhowardstone@gmail.com"  # OpenAlex polite pool
OA_API = "https://api.openalex.org/works"
EPMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

COLS = ["topic", "doi", "pmcid", "title", "year", "oa_status", "license", "oa_url",
        "route", "in_current_corpus"]


def _get(url: str, timeout: int = 60, tries: int = 6) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": "organoid-protocol-atlas/1.0 (academic research; mailto:%s)" % EMAIL})
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            code = getattr(e, "code", None)
            if code is not None and 400 <= code < 500 and code != 429:
                raise
            if i == tries - 1:
                raise
            # 429 (rate limit) gets a much longer backoff than transient 5xx/timeouts
            time.sleep((10 * (i + 1)) if code == 429 else (2 * (i + 1)))
    raise RuntimeError(f"unreachable: {url}")


def norm_doi(d: str | None) -> str:
    return (d or "").replace("https://doi.org/", "").replace("http://doi.org/", "").strip().lower()


def corpus_dois() -> set[str]:
    if not CORPUS.exists():
        return set()
    out = set()
    for r in csv.DictReader(CORPUS.open(), delimiter="\t"):
        d = norm_doi(r.get("doi"))
        if d:
            out.add(d)
    return out


def epmc_lookup(doi: str) -> tuple[str | None, bool]:
    """Return (pmcid, in_epmc_fulltext) for a DOI via Europe PMC, else (None, False)."""
    q = urllib.parse.quote(f'DOI:"{doi}"')
    try:
        r = _get(f"{EPMC_API}?query={q}&format=json&resultType=core", timeout=30)
        res = r.get("resultList", {}).get("result", [])
        if not res:
            return None, False
        x = res[0]
        return x.get("pmcid"), (x.get("inEPMC") == "Y")
    except Exception:  # noqa: BLE001
        return None, False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topic", required=True, help="title_and_abstract.search term")
    ap.add_argument("--max", type=int, default=2000, help="cap works (0 = all)")
    ap.add_argument("--resolve-epmc", action="store_true",
                    help="resolve each DOI against Europe PMC to set route (slower, ~0.15s/DOI)")
    args = ap.parse_args()

    OUTDIR.mkdir(parents=True, exist_ok=True)
    slug = args.topic.replace(" ", "_").replace("/", "_")
    out_csv = OUTDIR / f"openalex_candidates_{slug}.csv"
    have = corpus_dois()

    filt = f"title_and_abstract.search:{args.topic},is_oa:true"
    select = "doi,ids,open_access,primary_location,publication_year,title"
    cursor = "*"
    rows, n, n_epmc, n_pdf, n_none, n_incorpus = [], 0, 0, 0, 0, 0
    print(f"OpenAlex discovery topic={args.topic!r} (resolve_epmc={args.resolve_epmc})", flush=True)
    while True:
        p = {"filter": filt, "mailto": EMAIL, "per-page": 200, "cursor": cursor, "select": select}
        try:
            d = _get(f"{OA_API}?{urllib.parse.urlencode(p)}")
        except Exception as e:  # noqa: BLE001
            # crash-safe: keep whatever we paged so far rather than losing the whole crawl
            print(f"  [paging stopped at {n} works] {type(e).__name__}: {e}", flush=True)
            break
        res = d.get("results", [])
        if not res:
            break
        for w in res:
            doi = norm_doi(w.get("doi"))
            if not doi:
                continue
            n += 1
            oa = w.get("open_access") or {}
            pl = w.get("primary_location") or {}
            oa_url = oa.get("oa_url") or ""
            lic = pl.get("license") or ""
            pmcid = (w.get("ids") or {}).get("pmcid") or ""
            in_corpus = doi in have
            if in_corpus:
                n_incorpus += 1
            route = "none"
            if args.resolve_epmc and not in_corpus:
                epmc_pmcid, in_ft = epmc_lookup(doi)
                if epmc_pmcid:
                    pmcid = epmc_pmcid.split("/")[-1] if epmc_pmcid else pmcid
                route = "epmc_jats" if in_ft else ("pdf" if oa_url else "none")
                time.sleep(0.15)
            elif not args.resolve_epmc:
                route = "epmc_jats?" if not oa_url else "pdf?"  # unresolved guess
            if route.startswith("epmc"):
                n_epmc += 1
            elif route.startswith("pdf"):
                n_pdf += 1
            else:
                n_none += 1
            rows.append({"topic": args.topic, "doi": doi, "pmcid": pmcid,
                         "title": (w.get("title") or "")[:300], "year": w.get("publication_year") or "",
                         "oa_status": oa.get("oa_status") or "", "license": lic, "oa_url": oa_url,
                         "route": route, "in_current_corpus": "1" if in_corpus else "0"})
            if args.max and n >= args.max:
                break
        if args.max and n >= args.max:
            break
        cursor = d["meta"].get("next_cursor")
        if not cursor:
            break
        if n % 1000 < 200:
            print(f"  ...{n} works", flush=True)
        time.sleep(0.3)

    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)

    print(f"\nOpenAlex discovery {args.topic!r}: {n} OA works | already in corpus {n_incorpus} | "
          f"new: epmc_jats {n_epmc}, pdf {n_pdf}, none {n_none}\n-> {out_csv.relative_to(REPO)}\n"
          f"   next: ingest route=epmc_jats via tier0 (no new code); route=pdf needs pymupdf adapter.",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
