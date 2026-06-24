#!/usr/bin/env python3
"""
bioRxiv preprint ingester — pull organoid-protocol PREPRINTS into the same pipeline.

The journal corpus is PMC open-access only; this adds bioRxiv preprints (often the
earliest public version of a protocol, months ahead of the journal). bioRxiv's native
API (api.biorxiv.org) is the only reliable bioRxiv full-text source — it exposes a
`jatsxml` URL per preprint — but it has NO keyword search, so we crawl a date window
and filter title for organoid terms, then fetch + parse the JATS exactly like tier0.

Reuse: tier0.parse_jats does the JATS → evidence-bundle parse, so a fetched preprint
becomes a bundle tier1 can extract with zero new extraction code. Output:
  - data/evidence_bundles/local/BIORXIV_<slug>.json   (tier1-ready bundle)
  - data/corpus/incoming/organoid_corpus_candidates_preprints.csv  (append, deduped)
  - outputs/ingest/biorxiv_ingest_summary.json

License: bioRxiv authors pick a license; we tag it. CC0/CC-BY/CC-BY-NC are public-safe;
"cc_no"/none are kept local-only (the public export already filters to CC0/CC-BY).

Resumable: skips preprints whose bundle already exists. Network-only (no GPU). Run:
  python pipeline/ingest_biorxiv.py                     # last 120 days
  python pipeline/ingest_biorxiv.py --from 2023-01-01 --to 2023-12-31
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
import tier0_extract as t0  # noqa: E402  (reuse parse_jats)

BUNDLES = REPO / "data" / "evidence_bundles" / "local"
CAND = REPO / "data" / "corpus" / "incoming" / "organoid_corpus_candidates_preprints.csv"
OUT = REPO / "outputs" / "ingest" / "biorxiv_ingest_summary.json"
API = "https://api.biorxiv.org/details/biorxiv"

# title filter — broad organoid terms (title-only keeps precision high; abstract isn't
# always in the details feed). "organoid"/"organoids"/"assembloid"/"gastruloid".
TERMS = ("organoid", "assembloid", "gastruloid", "organ-on")
CC_PUBLIC = {"cc_by", "cc_by_nc", "cc0", "cc_by_nd", "cc_by_nc_nd"}  # tagged; public export re-filters

CAND_COLS = ["organoid_type", "doi", "pmcid", "first_author", "year", "journal", "species",
             "source_cell_type", "license", "has_methods", "has_supplement", "gold_candidate",
             "flags", "notes", "pmid", "title", "cited_by", "in_current_corpus"]


def _get(url: str, timeout: int = 30, tries: int = 4) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": "organoid-protocol-atlas/1.0 (academic research)"})
    for i in range(tries):
        try:
            return urllib.request.urlopen(req, timeout=timeout).read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            code = getattr(e, "code", None)
            if code is not None and 400 <= code < 500 and code != 429:
                raise
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"unreachable: {url}")


def slug(doi: str) -> str:
    return "BIORXIV_" + doi.split("/")[-1]


def crawl(date_from: str, date_to: str):
    """Yield bioRxiv records (latest version each) in [from,to] whose title matches TERMS."""
    cursor = 0
    seen_doi = set()
    while True:
        try:
            d = json.loads(_get(f"{API}/{date_from}/{date_to}/{cursor}"))
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] page cursor={cursor}: {e}", flush=True)
            break
        coll = d.get("collection", [])
        if not coll:
            break
        for r in coll:
            title = (r.get("title") or "").lower()
            if any(term in title for term in TERMS):
                doi = r.get("doi")
                if doi and doi not in seen_doi:
                    seen_doi.add(doi)
                    yield r  # latest version wins (API returns versions in order)
        msg = d.get("messages", [{}])[0]
        total = int(msg.get("total", 0))
        cursor += len(coll)
        if cursor >= total:
            break
        time.sleep(0.3)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    today = datetime.now(timezone.utc).date()
    ap.add_argument("--from", dest="dfrom", default=str(today - timedelta(days=120)))
    ap.add_argument("--to", dest="dto", default=str(today))
    ap.add_argument("--limit", type=int, default=0, help="cap matches processed (0=all)")
    args = ap.parse_args()

    BUNDLES.mkdir(parents=True, exist_ok=True)
    CAND.parent.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in BUNDLES.glob("BIORXIV_*.json")}
    print(f"bioRxiv organoid ingest {args.dfrom}..{args.dto} (existing bundles: {len(existing)})", flush=True)

    new_rows, n_match, n_ft, n_skip, n_fail = [], 0, 0, 0, 0
    for r in crawl(args.dfrom, args.dto):
        n_match += 1
        doi = r["doi"]
        key = slug(doi)
        if key in existing:
            n_skip += 1
            continue
        jx = r.get("jatsxml")
        if not jx:
            n_fail += 1
            continue
        try:
            xml = _get(jx, timeout=40)
            parsed = t0.parse_jats(xml)
        except Exception as e:  # noqa: BLE001
            print(f"  [fail] {key}: {type(e).__name__}: {e}", flush=True)
            n_fail += 1
            continue
        if len((parsed.get("methods_text") or "")) < 400:  # need real methods to extract
            n_fail += 1
            continue
        lic = (r.get("license") or "").strip().lower() or "preprint"
        bundle = {"doi": doi, "pmcid": key, "organoid_type": "",
                  "license": lic, "source_route": "biorxiv_api", "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  **parsed}
        (BUNDLES / f"{key}.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2))
        n_ft += 1
        new_rows.append({c: "" for c in CAND_COLS} | {
            "organoid_type": "", "doi": doi, "pmcid": key,
            "first_author": (r.get("authors") or "").split(";")[0][:40],
            "year": (r.get("date") or "")[:4], "journal": "bioRxiv",
            "license": lic, "has_methods": "1",
            "has_supplement": "1" if (parsed.get("supplementary_text")) else "0",
            "title": r.get("title", ""), "notes": "biorxiv preprint ingest",
            "in_current_corpus": "0",
        })
        if args.limit and n_ft >= args.limit:
            break

    # append candidates (create header if new)
    if new_rows:
        new = not CAND.exists()
        with CAND.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CAND_COLS)
            if new:
                w.writeheader()
            w.writerows(new_rows)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "window": [args.dfrom, args.dto], "title_terms": list(TERMS),
               "title_matches": n_match, "new_bundles": n_ft, "skipped_existing": n_skip,
               "no_fulltext_or_thin": n_fail, "candidates_csv": str(CAND.relative_to(REPO))}
    OUT.write_text(json.dumps(summary, indent=2))
    print(f"\nbioRxiv ingest: {n_match} title-matches | {n_ft} new bundles | {n_skip} skipped | "
          f"{n_fail} no-fulltext/thin\n-> bundles in {BUNDLES.relative_to(REPO)}; candidates {CAND.relative_to(REPO)}\n"
          f"   next: tier1 extract the new BIORXIV_* keys (after current GPU job), then QC into corpus.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
