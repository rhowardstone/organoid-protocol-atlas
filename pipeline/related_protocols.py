#!/usr/bin/env python3
"""
Related protocols by canonical-reagent similarity — the "related recipes" sidebar (#178).

No ML, no GPU: each protocol is a binary vector over its canonical reagent names; cosine
similarity gives a defensible "protocols that use a similar reagent set" ranking. This is
the immediately-buildable stopgap before the order-aware stage/graph embedding (which needs
stages[] corpus-wide). Reads the committed public export so it matches what's live.

Output: data/analysis/related_protocols.json
  { "<pmcid>": [ {pmcid, score, organoid_type, first_author, year, n_shared} , ... top-K ] }
Regenerate after any corpus/export change (like the consensus_*.json analytics). Run:
  python pipeline/related_protocols.py [--topk 8]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import sparse

REPO = Path(__file__).resolve().parent.parent
PROTOCOLS = REPO / "exports" / "public" / "protocols.jsonl"
REAGENTS = REPO / "exports" / "public" / "reagents.jsonl"
OUT = REPO / "data" / "analysis" / "related_protocols.json"


def _rows(path: Path):
    for ln in path.read_text().splitlines():
        if ln.strip():
            yield json.loads(ln)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topk", type=int, default=8)
    ap.add_argument("--min-shared", type=int, default=2,
                    help="drop neighbors sharing fewer than this many reagents")
    args = ap.parse_args()

    meta = {r["pmcid"]: r for r in _rows(PROTOCOLS)}
    pmcids = sorted(meta)
    idx = {p: i for i, p in enumerate(pmcids)}

    # protocol -> set of canonical reagent names
    feats: dict[str, set] = defaultdict(set)
    vocab: dict[str, int] = {}
    for r in _rows(REAGENTS):
        p = r.get("pmcid")
        name = (r.get("canonical") or r.get("name") or "").strip().lower()
        if p in idx and name:
            feats[p].add(name)
            vocab.setdefault(name, len(vocab))

    # sparse binary protocol x reagent matrix
    rows, cols = [], []
    for p in pmcids:
        for name in feats.get(p, ()):
            rows.append(idx[p]); cols.append(vocab[name])
    X = sparse.csr_matrix((np.ones(len(rows), dtype=np.float32), (rows, cols)),
                          shape=(len(pmcids), max(len(vocab), 1)))
    # L2-normalize rows -> cosine = X @ X.T
    norms = np.sqrt(np.asarray(X.multiply(X).sum(axis=1)).ravel())
    norms[norms == 0] = 1.0
    Xn = sparse.diags(1.0 / norms) @ X
    counts = np.asarray(X.sum(axis=1)).ravel()  # reagents per protocol (for n_shared)

    related = {}
    K = args.topk
    for i, p in enumerate(pmcids):
        if counts[i] == 0:
            continue
        sims = (Xn[i] @ Xn.T).toarray().ravel()
        sims[i] = -1.0  # exclude self
        # candidate top-K by cosine
        top = np.argpartition(sims, -min(K * 4, len(sims) - 1))[-(K * 4):]
        top = top[np.argsort(sims[top])[::-1]]
        out = []
        for j in top:
            if sims[j] <= 0:
                continue
            # shared reagents = intersection size
            shared = len(feats[p] & feats[pmcids[j]])
            if shared < args.min_shared:
                continue
            m = meta[pmcids[j]]
            out.append({"pmcid": pmcids[j], "score": round(float(sims[j]), 4),
                        "organoid_type": m.get("organoid_type"),
                        "first_author": m.get("first_author"), "year": m.get("year"),
                        "n_shared": shared})
            if len(out) >= K:
                break
        if out:
            related[p] = out

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(related, ensure_ascii=False, indent=2))
    covered = len(related)
    avg = round(sum(len(v) for v in related.values()) / max(covered, 1), 1)
    print(f"related_protocols: {len(pmcids)} protocols | {len(vocab)} reagent vocab | "
          f"{covered} with >=1 neighbor (avg {avg} each) -> {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
