#!/usr/bin/env python3
"""
Relabel organoid_type using the discovery vocabulary.

The tier-1 extractor historically only knew 8 specific organoid systems (the rest fell
to "other"), so a broad corpus collapsed ~37% of papers to OTHER — losing the type the
discovery harvester already knew (it matched a tuned phrase query, e.g. "cardiac
organoid" -> cardiac). This relabels every record whose extractor type is "other" to its
discovery type, leaving extractor-specific calls untouched (the text-derived label is
trusted over the query match).

Operates on the curated corpus (data/corpus/corpus.tsv) and the local predictions
(data/predictions/local/*.json), re-validating each prediction against the (now expanded)
OrganoidProtocol schema. Idempotent. Predictions are git-ignored; corpus.tsv is committed.

Run:
  python pipeline/relabel_organoid_type.py            # apply
  python pipeline/relabel_organoid_type.py --dry-run  # report only
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "organoid_demo"))
from schema import OrganoidProtocol, OrganoidType  # noqa: E402

CORPUS = REPO / "data" / "corpus" / "corpus.tsv"
PRED_DIR = REPO / "data" / "predictions" / "local"
INCOMING = REPO / "data" / "corpus" / "incoming"

VALID = {t.value for t in OrganoidType}
# discovery vocab terms that don't match an enum value 1:1
ALIASES = {"hepatic": "liver", "hepatobiliary": "liver"}


def map_discovery(dtype: str) -> str | None:
    """Map a discovery organoid_type to a valid OrganoidType value, or None if unknown."""
    d = (dtype or "").strip().lower()
    d = ALIASES.get(d, d)
    return d if d in VALID else None


def resolve_type(extractor_type: str, discovery_type: str) -> str:
    """The label to keep: normalize aliases first, then trust a specific extractor call;
    rescue 'other' from discovery."""
    et = (extractor_type or "").strip().lower()
    et = ALIASES.get(et, et)                  # normalize legacy aliases (hepatic→liver)
    if et and et != "other" and et in VALID:
        return et                              # text-derived specific (normalised) label wins
    return map_discovery(discovery_type) or (et or "other")


def discovery_map() -> dict[str, str]:
    """pmcid (upper) -> discovery organoid_type, from every candidate pool."""
    m: dict[str, str] = {}
    for pool in sorted(INCOMING.glob("organoid_corpus_candidates_*.csv")):
        for row in csv.DictReader(open(pool)):
            pmcid = (row.get("pmcid") or "").strip().upper()
            dt = (row.get("organoid_type") or "").strip()
            if pmcid and dt and pmcid not in m:
                m[pmcid] = dt
    return m


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    dmap = discovery_map()
    print(f"discovery type map: {len(dmap)} pmcids", flush=True)

    # ---- corpus.tsv ----
    rows = list(csv.DictReader(open(CORPUS), delimiter="\t"))
    fieldnames = list(rows[0].keys()) if rows else []
    corpus_changes = Counter()
    for r in rows:
        pmcid = (r.get("pmcid") or "").strip().upper()
        new = resolve_type(r.get("organoid_type", ""), dmap.get(pmcid, ""))
        if new != (r.get("organoid_type") or ""):
            corpus_changes[(r.get("organoid_type"), new)] += 1
            r["organoid_type"] = new
    if not args.dry_run and corpus_changes:
        with open(CORPUS, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
            w.writeheader()
            w.writerows(rows)

    # ---- predictions ----
    pred_changes = Counter()
    pred_errors = 0
    for pf in glob.glob(str(PRED_DIR / "*.json")):
        pmcid = Path(pf).stem.upper()
        try:
            d = json.loads(open(pf).read())
        except Exception:  # noqa: BLE001
            pred_errors += 1
            continue
        new = resolve_type(d.get("organoid_type", ""), dmap.get(pmcid, ""))
        if new != (d.get("organoid_type") or ""):
            pred_changes[(d.get("organoid_type"), new)] += 1
            d["organoid_type"] = new
            if not args.dry_run:
                try:
                    proto = OrganoidProtocol.model_validate(d)
                    Path(pf).write_text(proto.model_dump_json(indent=2))
                except Exception as e:  # noqa: BLE001
                    pred_errors += 1
                    print(f"  ! validate {pmcid}: {e}", flush=True)

    print(f"\ncorpus relabeled: {sum(corpus_changes.values())} rows "
          f"({'DRY-RUN' if args.dry_run else 'written'})")
    for (old, new), n in corpus_changes.most_common(20):
        print(f"  {old} -> {new}: {n}")
    print(f"predictions relabeled: {sum(pred_changes.values())} "
          f"(errors {pred_errors})")


if __name__ == "__main__":
    main()
