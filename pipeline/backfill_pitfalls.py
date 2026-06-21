#!/usr/bin/env python3
"""
Backfill failure_modes + modifications into existing Tier-1 predictions.

The corpus's 800+ predictions were extracted before the failure_modes / modifications
fields were wired into the OrganoidProtocol constructor (they only ever reached the
summary rows, never the prediction files), so /analytics/failure-modes and
/analytics/lineage were empty. This pass re-asks the local model for ONLY those two
fields per paper and MERGES the gated results into the existing prediction JSON,
leaving every other (already-validated) field untouched -- no re-grounding, no QC
churn, no public-corpus cascade.

Gating is identical to tier1_extract (shared build_failure_modes / build_modifications):
failure_modes need a description (evidence attached only when the quote is verbatim);
modifications need a change_description and keep cited_doi ONLY when it is a real DOI
appearing verbatim in the source -- so no bare reference indices or parroted example
DOIs become fabricated lineage edges.

Idempotent: re-running re-derives the same gated fields. Predictions are git-ignored
(regenerated); the committed artifact is outputs/analysis/pitfalls_backfill_summary.json.

Run:
  python pipeline/backfill_pitfalls.py --workers 6          # all predictions
  python pipeline/backfill_pitfalls.py --only PMC123,PMC456 # targeted
  python pipeline/backfill_pitfalls.py --limit 5            # smoke test
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
sys.path.insert(0, str(REPO / "organoid_demo"))

import tier1_extract as t1  # noqa: E402
from schema import OrganoidProtocol  # noqa: E402

PRED_DIR = REPO / "data" / "predictions" / "local"
BUNDLES = REPO / "data" / "evidence_bundles" / "local"
OUT_PATH = REPO / "outputs" / "analysis" / "pitfalls_backfill_summary.json"


def backfill_one(pred_path: Path) -> dict:
    """Re-extract failure_modes + modifications for one paper and merge them into its
    prediction file. Returns a per-paper result row (never raises)."""
    pmcid = pred_path.stem
    try:
        pred = json.loads(pred_path.read_text())
    except Exception as e:  # noqa: BLE001
        return {"pmcid": pmcid, "error": f"pred read: {type(e).__name__}: {e}"}
    bundle_path = BUNDLES / f"{pmcid}.json"
    if not bundle_path.exists():
        return {"pmcid": pmcid, "error": "no evidence bundle"}
    try:
        bundle = json.loads(bundle_path.read_text())
        evidence = t1.build_evidence_text(bundle)
        doi = pred.get("source_doi") or bundle.get("source_doi") or pmcid
        m = t1.call_ollama(t1.PROMPT.format(evidence=evidence))
    except Exception as e:  # noqa: BLE001
        return {"pmcid": pmcid, "error": f"extract: {type(e).__name__}: {e}"}

    fms = t1.build_failure_modes(m, doi, evidence)
    mods = t1.build_modifications(m, doi, evidence)
    pred["failure_modes"] = [f.model_dump(mode="json") for f in fms]
    pred["modifications"] = [x.model_dump(mode="json") for x in mods]
    try:
        proto = OrganoidProtocol.model_validate(pred)        # guarantee schema validity
    except Exception as e:  # noqa: BLE001
        return {"pmcid": pmcid, "error": f"validate: {type(e).__name__}: {e}"}
    pred_path.write_text(proto.model_dump_json(indent=2))
    return {
        "pmcid": pmcid,
        "n_failure_modes": len(fms),
        "n_modifications": len(mods),
        "n_modifications_with_doi": sum(1 for x in mods if x.cited_doi),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", default="", help="comma-separated PMCIDs")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    preds = sorted(PRED_DIR.glob("*.json"))
    if args.only:
        keep = {s.strip() for s in args.only.split(",") if s.strip()}
        preds = [p for p in preds if p.stem in keep]
    if args.limit:
        preds = preds[: args.limit]
    print(f"backfilling failure_modes + modifications for {len(preds)} predictions "
          f"({args.workers} workers)", flush=True)

    rows: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(backfill_one, p): p for p in preds}
        for fut in as_completed(futs):
            rows.append(fut.result())
            done += 1
            if done % 25 == 0 or done == len(preds):
                print(f"  {done}/{len(preds)}", flush=True)

    ok = [r for r in rows if "error" not in r]
    errs = [r for r in rows if "error" in r]
    summary = {
        "method": "backfill failure_modes + modifications into existing predictions via "
                  f"{t1.MODEL} (gated: FM needs description; modification cited_doi must be "
                  "a real DOI verbatim in source)",
        "n_predictions": len(preds),
        "n_ok": len(ok),
        "n_errors": len(errs),
        "papers_with_failure_modes": sum(1 for r in ok if r["n_failure_modes"]),
        "papers_with_modifications": sum(1 for r in ok if r["n_modifications"]),
        "papers_with_grounded_doi_edge": sum(1 for r in ok if r.get("n_modifications_with_doi")),
        "total_failure_modes": sum(r["n_failure_modes"] for r in ok),
        "total_modifications": sum(r["n_modifications"] for r in ok),
        "total_grounded_doi_edges": sum(r.get("n_modifications_with_doi", 0) for r in ok),
        "errors": errs[:50],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, indent=2))
    print(f"\npapers w/ failure_modes: {summary['papers_with_failure_modes']}  "
          f"papers w/ modifications: {summary['papers_with_modifications']}  "
          f"grounded DOI edges: {summary['total_grounded_doi_edges']}  "
          f"errors: {summary['n_errors']}")
    print(f"summary -> {OUT_PATH.relative_to(REPO)}")


if __name__ == "__main__":
    main()
