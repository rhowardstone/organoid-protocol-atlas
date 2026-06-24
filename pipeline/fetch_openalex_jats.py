#!/usr/bin/env python3
"""
Fetch JATS evidence bundles for OpenAlex discovery candidates on the epmc_jats route.

discover_openalex.py tags each OA candidate with a fetch route. For route=epmc_jats the
DOI resolves to a Europe PMC full-text record, so we can reuse the existing tier0 fetch
(fetch_xml -> parse_jats) with NO new extraction code — the same path the organoid corpus
uses. This turns the ~2,652 epmc_jats organ-on-chip candidates into tier1-ready bundles
keyed by their real PMCID, exactly like the journal corpus.

Bundles carry the OpenAlex license (normalized) so the downstream public-export gate keeps
only CC0/CC-BY; NC/ND/unknown are mined locally but not redistributed. organoid_type is left
blank (curated by the LLM at tier1 — organ-on-chip papers aren't in the hand-curated manifest).

Resumable (skips PMCIDs whose bundle already exists), network-only, polite. Run:
  python pipeline/fetch_openalex_jats.py --candidates data/corpus/incoming/openalex_candidates_organ-on-a-chip.csv
  python pipeline/fetch_openalex_jats.py --candidates <csv> --public-only   # CC0/CC-BY rows only
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
import tier0_extract as t0  # noqa: E402  (reuse fetch_xml + parse_jats)
from export_public import is_public_license  # noqa: E402

BUNDLES = REPO / "data" / "evidence_bundles" / "local"
OUT = REPO / "outputs" / "ingest" / "openalex_jats_fetch_summary.json"

# normalize OpenAlex license strings to the corpus convention (export_public re-filters)
LIC_MAP = {"cc-by": "CC-BY", "cc-by-sa": "CC-BY-SA", "cc0": "CC0", "public-domain": "CC0",
           "cc-by-nc": "CC-BY-NC", "cc-by-nc-nd": "CC-BY-NC-ND", "cc-by-nc-sa": "CC-BY-NC-SA",
           "cc-by-nd": "CC-BY-ND"}


def norm_license(lic: str) -> str:
    s = (lic or "").strip().lower()
    return LIC_MAP.get(s, "openalex-oa" if s in ("", "other-oa") else s.upper())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--public-only", action="store_true",
                    help="fetch only CC0/CC-BY rows (skip NC/ND/unknown)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.34)
    args = ap.parse_args()

    BUNDLES.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(open(args.candidates)))
    todo = [r for r in rows if r.get("route") == "epmc_jats"
            and r.get("in_current_corpus") == "0" and r.get("pmcid")]
    if args.public_only:
        todo = [r for r in todo if is_public_license(norm_license(r.get("license")))]
    if args.limit:
        todo = todo[: args.limit]
    existing = {p.stem for p in BUNDLES.glob("PMC*.json")}
    print(f"fetch_openalex_jats: {len(todo)} epmc_jats candidates (existing bundles: {len(existing)})",
          flush=True)

    n_ok, n_thin, n_fail, n_skip = 0, 0, 0, 0
    for i, r in enumerate(todo, 1):
        pmcid = r["pmcid"]
        if not pmcid.startswith("PMC"):
            pmcid = "PMC" + pmcid
        if pmcid in existing:
            n_skip += 1
            continue
        route, xml, note = t0.fetch_xml(pmcid)
        if xml is None:
            n_fail += 1
            time.sleep(args.sleep)
            continue
        try:
            parsed = t0.parse_jats(xml)
        except Exception as e:  # noqa: BLE001
            print(f"  [parse-fail] {pmcid}: {type(e).__name__}", flush=True)
            n_fail += 1
            time.sleep(args.sleep)
            continue
        if len((parsed.get("methods_text") or "")) < 400:
            n_thin += 1
            time.sleep(args.sleep)
            continue
        bundle = {"doi": r.get("doi", ""), "pmcid": pmcid, "organoid_type": "",
                  "license": norm_license(r.get("license")), "source_route": route,
                  "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "discovery": "openalex:organ-on-a-chip", **parsed}
        (BUNDLES / f"{pmcid}.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2))
        n_ok += 1
        if i % 200 == 0:
            print(f"  [{i}/{len(todo)}] ok={n_ok} thin={n_thin} fail={n_fail} skip={n_skip}", flush=True)
        time.sleep(args.sleep)

    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "candidates": args.candidates, "epmc_jats_considered": len(todo),
        "new_bundles": n_ok, "thin": n_thin, "fetch_or_parse_fail": n_fail, "skipped_existing": n_skip},
        indent=2))
    print(f"\nfetch_openalex_jats: {n_ok} new bundles | {n_thin} thin | {n_fail} fail | {n_skip} skip\n"
          f"   next: tier1 extract the new PMC* bundles, then accept_ingest_to_corpus.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
