#!/usr/bin/env python3
"""
Scaled corpus-ingestion orchestrator — discover → fetch → extract → QC → stage.

Reads the Europe PMC candidate pool (data/corpus/incoming/*.csv), dedups against the
current corpus, and for each NEW candidate runs the existing Tier-0 (fetch+parse) and
Tier-1 (local-LLM extraction) pipeline, then applies deterministic QC gates so quality
holds at scale without hand-checking every paper:

  ACCEPT  iff full text fetched, methods captured, >=1 grounded signaling factor, and
              grounding_rate >= --min-grounding, and not a duplicate.
  REJECT  otherwise, with a logged reason (no_full_text / no_methods / no_signaling /
              low_grounding / parse_error / extract_error).

Accepted: bundle + prediction written LOCAL-ONLY; the curated manifest row is appended
to data/corpus/corpus.tsv. A GENERATED batch report (outputs/ingest/batch_*.json) records
counts + per-paper reasons + grounding (no hand-typed metrics). The corpus diff + report
are the review artifact for the supervisor (codex) gate — nothing auto-merges to master.

Run:
    python pipeline/ingest_orchestrator.py --limit 5 --dry-run   # QC only, no writes
    python pipeline/ingest_orchestrator.py --limit 5             # measured batch
    python pipeline/ingest_orchestrator.py --limit 20 --cc-only  # public-eligible only
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
from tier0_extract import LOCAL_DIR, fetch_xml, parse_jats  # noqa: E402
from tier1_extract import (  # noqa: E402
    MODEL, PRED_DIR, PROMPT, build_evidence_text, call_ollama, to_protocol,
)

CORPUS = REPO / "data" / "corpus" / "corpus.tsv"
CANDIDATES = REPO / "data" / "corpus" / "incoming" / "organoid_corpus_candidates_180.csv"
OUT = REPO / "outputs" / "ingest"
MIN_METHODS = 400
CORPUS_COLS = ["organoid_type", "doi", "pmcid", "first_author", "year", "journal", "species",
               "source_cell_type", "license", "has_methods", "has_supplement", "gold_candidate",
               "flags", "notes"]


def existing_corpus():
    rows = list(csv.DictReader(open(CORPUS), delimiter="\t"))
    return ({r["pmcid"] for r in rows},
            {(r.get("doi") or "").lower() for r in rows if r.get("doi")})


def process_one(cand: dict) -> dict:
    """Fetch + extract one candidate; return a QC verdict dict."""
    pmcid, doi = cand["pmcid"], cand.get("doi", "")
    route, xml, note = fetch_xml(pmcid)
    if xml is None:
        return {"pmcid": pmcid, "reason": "no_full_text", "note": note}
    try:
        parsed = parse_jats(xml)
    except Exception as e:  # noqa: BLE001
        return {"pmcid": pmcid, "reason": f"parse_error:{type(e).__name__}"}
    if len(parsed.get("methods_text", "")) < MIN_METHODS and len(parsed.get("body_text", "")) < MIN_METHODS:
        return {"pmcid": pmcid, "reason": "no_methods"}
    bundle = {"doi": doi, "pmcid": pmcid, "organoid_type": cand.get("organoid_type"),
              "license": cand.get("license"), "source_route": route,
              "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **parsed}
    evidence = build_evidence_text(bundle)
    try:
        m = call_ollama(PROMPT.format(evidence=evidence))
        proto, _ = to_protocol(doi, m, evidence)
    except Exception as e:  # noqa: BLE001
        return {"pmcid": pmcid, "reason": f"extract_error:{type(e).__name__}"}
    nsig = len(proto.signaling_factors)
    grounded = sum(1 for r in proto.signaling_factors if r.evidence)
    gr = round(grounded / nsig, 3) if nsig else 0.0
    return {"pmcid": pmcid, "doi": doi, "organoid_type": cand.get("organoid_type"),
            "n_signaling": nsig, "grounded": grounded, "grounding_rate": gr,
            "methods_chars": len(parsed["methods_text"]), "bundle": bundle, "proto": proto, "cand": cand}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--min-grounding", type=float, default=0.5)
    ap.add_argument("--cc-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="QC only; do not write bundles/preds/corpus")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    have_pmc, have_doi = existing_corpus()

    cands = [c for c in csv.DictReader(open(CANDIDATES))
             if c.get("pmcid") and c["pmcid"] not in have_pmc
             and (c.get("doi", "").lower() not in have_doi)
             and c.get("has_methods") == "yes"]
    if args.cc_only:
        cands = [c for c in cands if (c.get("license") or "").upper().startswith("CC")]
    cands = cands[: args.limit]

    accepted, rejected, new_rows = [], [], []
    for c in cands:
        r = process_one(c)
        reason = None
        if "reason" in r:
            reason = r["reason"]
        elif r["n_signaling"] < 1:
            reason = "no_signaling"
        elif r["grounding_rate"] < args.min_grounding:
            reason = f"low_grounding={r['grounding_rate']}"
        if reason:
            rejected.append({"pmcid": r["pmcid"], "reason": reason})
            print(f"  REJECT {r['pmcid']}: {reason}", flush=True)
            continue
        if not args.dry_run:
            LOCAL_DIR.mkdir(parents=True, exist_ok=True)
            PRED_DIR.mkdir(parents=True, exist_ok=True)
            (LOCAL_DIR / f"{r['pmcid']}.json").write_text(json.dumps(r["bundle"], ensure_ascii=False, indent=2))
            (PRED_DIR / f"{r['pmcid']}.json").write_text(r["proto"].model_dump_json(indent=2))
            cd = r["cand"]
            new_rows.append({**{k: "" for k in CORPUS_COLS},
                             "organoid_type": cd.get("organoid_type"), "doi": cd.get("doi"),
                             "pmcid": cd.get("pmcid"), "first_author": cd.get("first_author"),
                             "year": cd.get("year"), "journal": cd.get("journal"),
                             "species": cd.get("species") or "tbd",
                             "source_cell_type": cd.get("source_cell_type") or "tbd",
                             "license": cd.get("license"), "has_methods": "yes",
                             "has_supplement": "tbd", "gold_candidate": "no", "flags": "auto-ingested",
                             "notes": f"orchestrator batch; grounding {r['grounding_rate']}"})
        accepted.append({k: r[k] for k in ("pmcid", "doi", "organoid_type", "n_signaling",
                                           "grounded", "grounding_rate", "methods_chars")})
        print(f"  ACCEPT {r['pmcid']} ({r['organoid_type']}): {r['n_signaling']} sig, "
              f"grounding {r['grounding_rate']}", flush=True)

    if new_rows:
        with open(CORPUS, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CORPUS_COLS, delimiter="\t")
            for row in new_rows:
                w.writerow(row)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "model": MODEL, "candidates_considered": len(cands),
              "accepted": len(accepted), "rejected": len(rejected),
              "min_grounding": args.min_grounding, "cc_only": args.cc_only, "dry_run": args.dry_run,
              "accepted_papers": accepted, "rejected_papers": rejected}
    (OUT / f"batch_{stamp}.json").write_text(json.dumps(report, indent=2))
    print(f"\nbatch: {len(accepted)} accepted / {len(rejected)} rejected of {len(cands)} "
          f"considered{' (dry-run)' if args.dry_run else ''} -> outputs/ingest/batch_{stamp}.json")


if __name__ == "__main__":
    main()
