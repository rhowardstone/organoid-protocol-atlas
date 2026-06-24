#!/usr/bin/env python3
"""
QC + dedup + corpus-append for newly-ingested bioRxiv / protocols.io predictions.

The bioRxiv (BIORXIV_*) and protocols.io (PROTOCOLSIO_*) ingesters write tier1-ready
bundles; tier1_extract then writes data/predictions/local/<key>.json for each. But a
prediction only becomes a *public* protocol once it has a row in data/corpus/corpus.tsv
(build_kg reads license/journal/year/first_author from there; export_public filters to
CC0/CC-BY). This script promotes accepted predictions into the corpus:

  1. QC gate   — drop predictions that extracted no real recipe (need >=2 reagents and
                 >=1 grounded reagent), so junk doesn't pollute the KG.
  2. DEDUP     — (a) skip if the bundle DOI already appears in the corpus (exact);
                 (b) skip bioRxiv preprints whose bioRxiv `published` field names a
                     journal DOI already in the corpus (authoritative preprint->published
                     dedup; the journal corpus is PMC-OA so the published version may
                     already be present); (c) collapse duplicate DOIs among the new set.
  3. APPEND    — write a corpus.tsv row (organoid_type from the LLM extraction since these
                 sources aren't hand-curated; license normalized so protocols.io -> CC-BY
                 and bioRxiv cc_by/cc0 stay public; species from the extraction).

Idempotent: rows whose pmcid already exists in corpus.tsv are never re-added. Network is
used only for the bioRxiv published-DOI check (skippable with --no-published-check).

Run:  python pipeline/accept_ingest_to_corpus.py            # QC+dedup+append, report
      python pipeline/accept_ingest_to_corpus.py --dry-run  # report only, no write
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PRED = REPO / "data" / "predictions" / "local"
BUNDLES = REPO / "data" / "evidence_bundles" / "local"
CORPUS = REPO / "data" / "corpus" / "corpus.tsv"
CAND_PRE = REPO / "data" / "corpus" / "incoming" / "organoid_corpus_candidates_preprints.csv"
CAND_PIO = REPO / "data" / "corpus" / "incoming" / "organoid_corpus_candidates_protocols_io.csv"
INCOMING = REPO / "data" / "corpus" / "incoming"
BIORXIV_DETAILS = "https://api.biorxiv.org/details/biorxiv"

CORPUS_COLS = ["organoid_type", "doi", "pmcid", "first_author", "year", "journal",
               "species", "source_cell_type", "license", "has_methods", "has_supplement",
               "gold_candidate", "flags", "notes"]


def norm_doi(d: str | None) -> str:
    d = (d or "").strip().lower()
    for p in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(p):
            d = d[len(p):]
    return d.strip("/ ")


def norm_license(lic: str | None, source: str) -> str:
    """Map a raw bundle license to a corpus license string export_public understands.
    protocols.io public protocols are CC-BY 4.0; bioRxiv authors pick one (tagged as-is)."""
    s = (lic or "").strip().lower()
    if source == "protocols_io":
        return "CC-BY"  # protocols.io public protocols default CC-BY 4.0
    # bioRxiv: cc_by / cc_by_nc / cc0 / cc_by_nd / cc_no / preprint(none)
    mapping = {
        "cc_by": "CC-BY", "cc-by": "CC-BY", "cc0": "CC0", "cc_by_sa": "CC-BY-SA",
        "cc_by_nc": "CC-BY-NC", "cc_by_nc_nd": "CC-BY-NC-ND", "cc_by_nd": "CC-BY-ND",
    }
    if source == "openalex":
        # fetch_openalex_jats already normalized the license (CC-BY / CC0 / CC-BY-NC / ...);
        # pass it through so is_public_license can gate it directly.
        return (lic or "").strip() or "openalex-oa"
    return mapping.get(s, "preprint-no-redistribution" if s in ("", "preprint", "cc_no", "none") else s.upper())


def _pmc(k: str) -> str:
    k = (k or "").strip()
    return k if k.startswith("PMC") or not k else "PMC" + k


def load_candidate_meta() -> dict:
    """pmcid -> candidate row, across preprint/protocols.io and every openalex_candidates_*.csv."""
    meta = {}
    paths = ([CAND_PRE, CAND_PIO] + sorted(INCOMING.glob("openalex_candidates_*.csv"))
             + sorted(INCOMING.glob("epmc_candidates_*.csv")))
    for path in paths:
        if not path.exists():
            continue
        for r in csv.DictReader(path.open()):
            meta[_pmc(r.get("pmcid", ""))] = r
    return meta


def qc_ok(pred: dict) -> tuple[bool, str]:
    sf = pred.get("signaling_factors") or []
    sup = pred.get("media_supplements") or []
    grounded = sum(1 for r in sf + sup if (r.get("evidence") or {}).get("quote"))
    if len(sf) + len(sup) < 2:
        return False, "thin(<2 reagents)"
    if grounded < 1:
        return False, "ungrounded(0 quotes)"
    return True, "ok"


def biorxiv_published_doi(preprint_doi: str, cache: dict) -> str | None:
    """Return the journal DOI bioRxiv records for a published preprint, else None."""
    if preprint_doi in cache:
        return cache[preprint_doi]
    out = None
    try:
        d = json.loads(urllib.request.urlopen(
            f"{BIORXIV_DETAILS}/{preprint_doi}", timeout=20).read())
        coll = d.get("collection") or []
        pub = (coll[-1].get("published") if coll else "") or ""
        if pub and pub.upper() != "NA":
            out = norm_doi(pub)
    except Exception:  # noqa: BLE001
        out = None
    cache[preprint_doi] = out
    time.sleep(0.2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-published-check", action="store_true",
                    help="skip the bioRxiv published-DOI dedup network call")
    args = ap.parse_args()

    # existing corpus state
    corpus_rows = list(csv.DictReader(CORPUS.open(), delimiter="\t"))
    corpus_pmcids = {r["pmcid"] for r in corpus_rows}
    corpus_dois = {norm_doi(r.get("doi")) for r in corpus_rows if norm_doi(r.get("doi"))}
    cand = load_candidate_meta()

    # OpenAlex PMC-keyed bundles are identified by their "discovery" field (set by
    # fetch_openalex_jats); only those PMC predictions are new ingest (others are corpus).
    openalex_pmc = set()
    for p in PRED.glob("PMC*.json"):
        if p.stem in corpus_pmcids:
            continue
        bp = BUNDLES / f"{p.stem}.json"
        if bp.exists():
            try:
                if str(json.loads(bp.read_text()).get("discovery", "")).startswith("openalex"):
                    openalex_pmc.add(p.stem)
            except Exception:  # noqa: BLE001
                pass

    keys = sorted([p.stem for p in PRED.glob("BIORXIV_*.json")]
                  + [p.stem for p in PRED.glob("PROTOCOLSIO_*.json")]
                  + list(openalex_pmc))
    keys = [k for k in keys if k not in corpus_pmcids]  # idempotent

    accepted, rej = [], {"thin(<2 reagents)": 0, "ungrounded(0 quotes)": 0,
                         "dup_doi_in_corpus": 0, "dup_published_in_corpus": 0,
                         "dup_within_new": 0, "no_bundle": 0}
    seen_new_dois: set[str] = set()
    pub_cache: dict = {}
    counts = {"biorxiv": {"seen": 0, "acc": 0}, "protocols_io": {"seen": 0, "acc": 0},
              "openalex": {"seen": 0, "acc": 0}}

    for k in keys:
        source = ("biorxiv" if k.startswith("BIORXIV_")
                  else "protocols_io" if k.startswith("PROTOCOLSIO_") else "openalex")
        counts[source]["seen"] += 1
        bp = BUNDLES / f"{k}.json"
        if not bp.exists():
            rej["no_bundle"] += 1
            continue
        bundle = json.loads(bp.read_text())
        pred = json.loads((PRED / f"{k}.json").read_text())

        ok, why = qc_ok(pred)
        if not ok:
            rej[why] += 1
            continue

        doi = norm_doi(bundle.get("doi"))
        if doi and doi in corpus_dois:
            rej["dup_doi_in_corpus"] += 1
            continue
        if doi and doi in seen_new_dois:
            rej["dup_within_new"] += 1
            continue
        if source == "biorxiv" and not args.no_published_check and doi:
            pub = biorxiv_published_doi(bundle.get("doi"), pub_cache)
            if pub and pub in corpus_dois:
                rej["dup_published_in_corpus"] += 1
                continue

        if doi:
            seen_new_dois.add(doi)
        cm = cand.get(k, {})
        sc = pred.get("source_cells") or {}
        row = {
            "organoid_type": pred.get("organoid_type") or "other",
            "doi": bundle.get("doi") or "",
            "pmcid": k,
            "first_author": cm.get("first_author", ""),
            "year": cm.get("year", ""),
            "journal": cm.get("journal") or {"biorxiv": "bioRxiv", "protocols_io": "protocols.io",
                                              "openalex": "organ-on-chip (OA)"}.get(source, ""),
            "species": sc.get("species") or cm.get("species", ""),
            "source_cell_type": sc.get("cell_type") or "",
            "license": norm_license(bundle.get("license"), source),
            "has_methods": "yes",
            "has_supplement": "yes" if (bundle.get("supplementary_text")) else "no",
            "gold_candidate": "no",
            "flags": source,
            "notes": f"{source} ingest 2026-06",
        }
        accepted.append(row)
        counts[source]["acc"] += 1

    # report
    print("=== QC + dedup + corpus-append ===")
    print(f"candidates considered: {len(keys)} (not already in corpus)")
    print(f"ACCEPTED: {len(accepted)}  "
          f"[bioRxiv {counts['biorxiv']['acc']}/{counts['biorxiv']['seen']}, "
          f"protocols.io {counts['protocols_io']['acc']}/{counts['protocols_io']['seen']}, "
          f"openalex {counts['openalex']['acc']}/{counts['openalex']['seen']}]")
    print("REJECTED:", {k: v for k, v in rej.items() if v})
    pub_n = sum(1 for r in accepted
                if r["license"].upper().startswith(("CC-BY", "CC0"))
                and "NC" not in r["license"].upper() and "ND" not in r["license"].upper())
    print(f"of accepted, public-redistributable (CC0/CC-BY, no NC/ND): {pub_n}")

    if args.dry_run:
        print("\n[dry-run] no rows written.")
        return 0

    if accepted:
        with CORPUS.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CORPUS_COLS, delimiter="\t")
            w.writerows(accepted)
        print(f"\nappended {len(accepted)} rows -> {CORPUS.relative_to(REPO)} "
              f"(now {len(corpus_rows) + len(accepted)} papers)")
    else:
        print("\nnothing accepted; corpus unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
