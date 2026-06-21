#!/usr/bin/env python3
"""
R3b: Hybrid candidate discovery = lexical (Europe PMC) + semantic re-ranking.

discover_candidates.py saturates at ~500 papers because keyword queries miss papers
that describe the same organoid biology without the exact type-word ("enteroid" vs
"intestinal organoid"). R3b re-ranks the lexical hits by cosine similarity to the
centroid of already-indexed corpus papers of the same type — surfaces the most
biology-similar candidates first and sinks incidental keyword matches.

Algorithm per organoid type:
  1. Fetch candidates from Europe PMC (same TYPE_QUERIES as discover_candidates.py)
  2. Deduplicate against corpus + curated pools (same is_new logic)
  3. If the semantic index exists: embed title+abstract with all-MiniLM-L6-v2,
     score each candidate by cosine(embed, type_centroid), sort descending
  4. Emit ranked candidates with sem_score and lex_rank columns added

Graceful fallback: if `data/index/` is not built, or sentence-transformers is not
installed, falls back to lexical-only order with sem_score=0.0 and a warning.

Requires:
  python pipeline/semantic_index.py build     # one-time index build
  pip install sentence-transformers           # embedding model

Run:
  python pipeline/hybrid_discover.py
  python pipeline/hybrid_discover.py --limit-per-type 100
  python pipeline/hybrid_discover.py --no-semantic    # force lexical-only
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))

from discover_candidates import (  # noqa: E402
    HEADER, TYPE_QUERIES, build_row, epmc_page, is_new, load_existing_keys,
)

_INDEX = REPO / "data" / "index"
OUT = REPO / "data" / "corpus" / "incoming" / "organoid_corpus_candidates_hybrid.csv"
HYBRID_HEADER = HEADER + ["sem_score", "lex_rank"]
_MAX_TEXT = 2000   # title + abstract chars to embed per candidate


# --------------------------------------------------------------------------- #
# Pure logic (unit-tested offline, no model)
# --------------------------------------------------------------------------- #

def type_centroids(index_dir: Path) -> tuple[np.ndarray, list[dict], dict[str, np.ndarray]] | None:
    """Load the semantic index and compute an L2-normalised centroid per organoid type.

    Returns (vecs, docs, centroids) or None if the index has not been built yet.
    Centroids are unit vectors so cosine_to_centroid reduces to a dot product.
    """
    vp = index_dir / "vectors.npy"
    dp = index_dir / "docs.jsonl"
    if not (vp.exists() and dp.exists()):
        return None
    vecs = np.load(vp)
    docs = [json.loads(line) for line in dp.read_text().splitlines() if line.strip()]
    doc_types = [d.get("organoid_type") for d in docs]
    centroids: dict[str, np.ndarray] = {}
    for t in set(t for t in doc_types if t):
        mask = np.array([dt == t for dt in doc_types])
        subset = vecs[mask]
        if len(subset) == 0:
            continue
        c = subset.mean(axis=0)
        norm = np.linalg.norm(c)
        centroids[t] = c / max(float(norm), 1e-12)
    return vecs, docs, centroids


def cosine_to_centroid(vec: np.ndarray, centroid: np.ndarray) -> float:
    """Cosine similarity of vec to a pre-normalised centroid vector."""
    norm = np.linalg.norm(vec)
    if norm < 1e-12:
        return 0.0
    return float(np.dot(vec / norm, centroid))


# --------------------------------------------------------------------------- #
# Embedding (runtime, lazy-imports sentence-transformers)
# --------------------------------------------------------------------------- #

def embed_texts(texts: list[str]) -> np.ndarray | None:
    """Embed texts with all-MiniLM-L6-v2. Returns None if dep unavailable."""
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        return np.asarray(
            model.encode(texts, batch_size=64, show_progress_bar=False),
            dtype=np.float32,
        )
    except ImportError:
        warnings.warn(
            "sentence-transformers not installed — pip install sentence-transformers. "
            "Falling back to lexical-only ranking.",
            stacklevel=2,
        )
        return None


# --------------------------------------------------------------------------- #
# Europe PMC fetch (captures abstract for semantic scoring)
# --------------------------------------------------------------------------- #

def _candidate_text(result: dict) -> str:
    """Title + abstract, truncated, for embedding."""
    title = (result.get("title") or "").strip().rstrip(".")
    abstract = (result.get("abstractText") or "").strip()
    body = f"{title}. {abstract}" if abstract else title
    return body[:_MAX_TEXT]


def search_with_text(
    query: str, organoid_type: str, limit: int, page_size: int, sleep: float
) -> list[tuple[dict, str]]:
    """Paginate Europe PMC and return (candidate_row, embed_text) pairs."""
    out: list[tuple[dict, str]] = []
    cursor = "*"
    while len(out) < limit:
        data = epmc_page(query, cursor, page_size)
        results = (data.get("resultList") or {}).get("result") or []
        if not results:
            break
        for res in results:
            row = build_row(res, organoid_type)
            if row is None:
                continue
            out.append((row, _candidate_text(res)))
            if len(out) >= limit:
                break
        next_cursor = data.get("nextCursorMark")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
        time.sleep(sleep)
    return out


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Hybrid (lexical + semantic) organoid-protocol candidate discovery"
    )
    ap.add_argument("--limit-per-type", type=int, default=60,
                    help="max Europe PMC results fetched per type (default 60)")
    ap.add_argument("--max-total", type=int, default=0,
                    help="cap on total unique candidates emitted (0 = no cap)")
    ap.add_argument("--page-size", type=int, default=100)
    ap.add_argument("--sleep", type=float, default=0.34, help="politeness delay between pages")
    ap.add_argument("--no-semantic", action="store_true",
                    help="skip semantic scoring, emit in lexical order")
    args = ap.parse_args()

    # ── Semantic index ──────────────────────────────────────────────────────
    sem_available = False
    centroids: dict[str, np.ndarray] = {}
    if not args.no_semantic:
        idx = type_centroids(_INDEX)
        if idx is None:
            warnings.warn(
                f"Semantic index not found at {_INDEX}. "
                "Run `python pipeline/semantic_index.py build` first. "
                "Falling back to lexical-only.",
                stacklevel=1,
            )
        else:
            _, _, centroids = idx
            sem_available = True
            print(f"Loaded semantic index: {len(centroids)} type centroids", flush=True)

    # ── Dedup baseline ──────────────────────────────────────────────────────
    seen_pmcids, seen_dois = load_existing_keys()
    print(
        f"Dedup baseline: {len(seen_pmcids)} pmcids, {len(seen_dois)} dois "
        f"(corpus + curated pool)\n",
        flush=True,
    )

    emitted: list[dict] = []

    for organoid_type, query in TYPE_QUERIES.items():
        print(f"[{organoid_type}] querying Europe PMC ...", flush=True)
        try:
            raw = search_with_text(
                query, organoid_type, args.limit_per_type, args.page_size, args.sleep
            )
        except Exception as e:  # noqa: BLE001
            print(f"  ! {organoid_type} failed: {e}", flush=True)
            continue

        # filter to genuinely new candidates
        new_pairs = [
            (row, text) for row, text in raw
            if is_new(row, seen_pmcids, seen_dois)
        ]

        if sem_available and new_pairs and organoid_type in centroids:
            vecs = embed_texts([text for _, text in new_pairs])
            centroid = centroids[organoid_type]
            if vecs is not None:
                for i, (row, _) in enumerate(new_pairs):
                    row["sem_score"] = round(cosine_to_centroid(vecs[i], centroid), 4)
                    row["lex_rank"] = i + 1
                new_pairs.sort(key=lambda pair: -pair[0]["sem_score"])
            else:
                for i, (row, _) in enumerate(new_pairs):
                    row["sem_score"] = 0.0
                    row["lex_rank"] = i + 1
        else:
            for i, (row, _) in enumerate(new_pairs):
                row["sem_score"] = 0.0
                row["lex_rank"] = i + 1

        added = 0
        for row, _ in new_pairs:
            emitted.append(row)
            seen_pmcids.add(row["pmcid"].strip().upper())
            if row["doi"]:
                seen_dois.add(row["doi"].strip().lower())
            added += 1
            if args.max_total and len(emitted) >= args.max_total:
                break
        print(
            f"  {len(raw)} fetched, {added} new "
            f"(semantic={'on' if (sem_available and organoid_type in centroids) else 'off'})",
            flush=True,
        )
        if args.max_total and len(emitted) >= args.max_total:
            break

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HYBRID_HEADER, extrasaction="ignore")
        w.writeheader()
        w.writerows(emitted)

    print(f"\nTotal: {len(emitted)} new candidates → {OUT}")
    if sem_available and emitted:
        scored = [r for r in emitted if r.get("sem_score", 0.0) > 0.0]
        if scored:
            print("Top-5 by semantic score:")
            for r in sorted(scored, key=lambda r: -r["sem_score"])[:5]:
                print(
                    f"  [{r['organoid_type']:16s}] sem={r['sem_score']:.3f} "
                    f"lex_rank={r['lex_rank']:3d}  {r['pmcid']}  "
                    f"{r.get('title', '')[:55]}"
                )


if __name__ == "__main__":
    main()
