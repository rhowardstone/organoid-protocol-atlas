"""
S1 -> S2 handoff: produce grounded sidecar records for Tier-1 predictions.

For every prediction in data/predictions/local/*.json this writes
data/predictions/local/grounded/<pmcid>.json containing the per-entity grounding
{query, kind, field, curie, biolink_category, label, grounding_status, flags} for
each signaling factor, small molecule, and source cell line. This is the frozen
A->B contract: Agent B's KGX/Biolink/TRAPI layer consumes these sidecars.

Grounding is network-bound (SRI Name Resolver + Node Normalizer + Cellosaurus via
pipeline/ground.py), so it parallelizes across the box's many CPUs while the GPU is
busy with extraction. We ground each UNIQUE (name, kind) pair once, in a thread
pool, then assemble per-paper sidecars from that map -- polite to SRI and fast.

Honest by construction: grounding_status is the 4-state value from ground.py
(resolved|needs_review|not_found|not_attempted); CURIEs are never fabricated.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
import ground  # noqa: E402

PRED_DIR = REPO / "data" / "predictions" / "local"
OUT_DIR = PRED_DIR / "grounded"


def collect_entities(pred: dict):
    """Yield (name, kind, field) for every groundable entity in a prediction."""
    for r in pred.get("signaling_factors") or []:
        nm = (r.get("name") or "").strip()
        if nm:
            yield nm, "reagent", "signaling_factors"
    for r in pred.get("small_molecules") or []:
        nm = (r.get("name") or "").strip()
        if nm:
            yield nm, "reagent", "small_molecules"
    sc = pred.get("source_cells") or {}
    line = (sc.get("line_name") or "").strip()
    if line:
        yield line, "cell_line", "source_cells.line_name"


def ground_one(name: str, kind: str, offline: bool) -> dict:
    if kind == "cell_line":
        return ground.ground_cell_line(name, offline=offline)
    return ground.ground_entity(name, kind=kind, offline=offline)


def coverage(entities):
    c = {"total": len(entities), "resolved": 0, "needs_review": 0,
         "not_found": 0, "not_attempted": 0}
    for e in entities:
        c[e["grounding_status"]] = c.get(e["grounding_status"], 0) + 1
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=24, help="parallel grounding threads")
    ap.add_argument("--offline", action="store_true", help="cached fixtures only, no network")
    ap.add_argument("--force", action="store_true", help="re-ground even if sidecar exists")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    preds = sorted(PRED_DIR.glob("*.json"))
    if not preds:
        print("no predictions in", PRED_DIR)
        return
    loaded = []
    for p in preds:
        out = OUT_DIR / p.name
        if out.exists() and not args.force:
            continue
        try:
            loaded.append((p.stem, json.loads(p.read_text())))
        except Exception as e:  # noqa: BLE001
            print(f"  skip {p.name}: {type(e).__name__}")
    if not loaded:
        print(f"all {len(preds)} predictions already have sidecars (use --force to redo)")
        return

    # Dedupe unique (name, kind) across ALL papers -> ground each once in parallel.
    uniq = {(n, k) for _, pred in loaded for n, k, _ in collect_entities(pred)}
    print(f"{len(loaded)} predictions, {len(uniq)} unique entities -> grounding "
          f"with {args.workers} workers{' (offline)' if args.offline else ''}...", flush=True)

    grounded = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(ground_one, n, k, args.offline): (n, k) for n, k in uniq}
        done = 0
        for fut in as_completed(futs):
            n, k = futs[fut]
            try:
                grounded[(n, k)] = fut.result()
            except Exception as e:  # noqa: BLE001
                grounded[(n, k)] = {"query": n, "kind": k, "grounding_status": "not_attempted",
                                    "curie": None, "label": None, "biolink_category": None,
                                    "flags": [f"error:{type(e).__name__}"]}
            done += 1
            if done % 50 == 0:
                print(f"  grounded {done}/{len(uniq)}", flush=True)

    totals = {"resolved": 0, "needs_review": 0, "not_found": 0, "not_attempted": 0}
    for pmcid, pred in loaded:
        ents = []
        for n, k, field in collect_entities(pred):
            g = dict(grounded[(n, k)])
            g["field"] = field
            ents.append(g)
        cov = coverage(ents)
        for s in totals:
            totals[s] += cov[s]
        sidecar = {"pmcid": pmcid, "source_doi": pred.get("source_doi"),
                   "organoid_type": pred.get("organoid_type"),
                   "grounded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "grounder": "pipeline/ground.py (SRI Name Resolver + Node Normalizer + Cellosaurus)",
                   "coverage": cov, "entities": ents}
        (OUT_DIR / f"{pmcid}.json").write_text(json.dumps(sidecar, ensure_ascii=False, indent=2))

    n_ent = sum(totals.values())
    print(f"\nwrote {len(loaded)} sidecars -> {OUT_DIR.relative_to(REPO)}")
    print(f"entities: {n_ent} | " + " ".join(f"{k}={v}" for k, v in totals.items()))
    if n_ent:
        print(f"resolved rate: {totals['resolved']/n_ent:.3f}")


if __name__ == "__main__":
    main()
