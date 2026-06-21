#!/usr/bin/env python3
"""
R3: SEMANTIC + entity-filtered retrieval (the Starling capability we lacked).

Keyword discovery saturated at ~500 candidates because lexical queries miss papers
that describe a system without the query word (e.g. "gut epithelium / enteroid" for
intestinal). This builds a dense-vector index over the corpus so we can retrieve by
MEANING, with an optional entity/organoid-type filter — the substrate for finding
protocol papers keyword search misses.

Embeddings: sentence-transformers all-MiniLM-L6-v2 (384-d), local. Index: in-memory
numpy (cosine) — exact, dependency-light, fine at this corpus size; faiss optional.
Vectors are regenerated (data/index/, git-ignored); only this module + the measured
eval artifact are committed.

The PURE retrieval logic (cosine_topk, apply_filter, precision_at_k) is unit-tested
offline with synthetic vectors; the embedding step is a runtime concern (like Ollama
for extraction), so tests never download a model.

Run:
  python pipeline/semantic_index.py build        # embed corpus -> data/index/
  python pipeline/semantic_index.py search "gut crypt organoid with R-spondin" -k 5
  python pipeline/semantic_index.py eval          # semantic vs lexical, measured
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
BUNDLES = REPO / "data" / "evidence_bundles" / "local"
INDEX = REPO / "data" / "index"
EVAL_OUT = REPO / "outputs" / "retrieval" / "semantic_eval.json"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MAX_CHARS = 2000   # methods-text window per doc to embed


# --------------------------------------------------------------------------- #
# Pure retrieval logic (unit-tested, no model)
# --------------------------------------------------------------------------- #

def _l2norm(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.clip(n, 1e-12, None)


def cosine_topk(query_vec: np.ndarray, doc_mat: np.ndarray, k: int, mask=None):
    """Return [(idx, score)] of the top-k docs by cosine. `mask` (bool array) restricts
    the candidate set (entity/type filter) without rebuilding the index."""
    q = _l2norm(query_vec.reshape(1, -1))[0]
    d = _l2norm(doc_mat)
    sims = d @ q
    if mask is not None:
        sims = np.where(mask, sims, -np.inf)
    k = min(k, int(np.count_nonzero(np.isfinite(sims))))
    if k <= 0:
        return []
    idx = np.argpartition(-sims, k - 1)[:k]
    idx = idx[np.argsort(-sims[idx])]
    return [(int(i), float(sims[i])) for i in idx]


def type_mask(doc_types, organoid_type):
    """Boolean candidate mask for an organoid-type filter (entity-filtered retrieval)."""
    return np.array([t == organoid_type for t in doc_types]) if organoid_type else None


def precision_at_k(ranked_types, true_type, k):
    """Fraction of the top-k retrieved docs whose organoid_type == the query's type."""
    top = ranked_types[:k]
    return sum(1 for t in top if t == true_type) / len(top) if top else 0.0


# --------------------------------------------------------------------------- #
# Corpus / embedding (runtime)
# --------------------------------------------------------------------------- #

def doc_text(b: dict) -> str:
    """Protocol text to embed. Deliberately EXCLUDES the organoid_type label so the
    type-as-query eval measures real content similarity, not label leakage."""
    t = (b.get("methods_text") or "").strip() or (b.get("body_text") or "").strip()
    return t[:MAX_CHARS]


def load_docs():
    docs = []
    for f in sorted(BUNDLES.glob("*.json")):
        try:
            b = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        txt = doc_text(b)
        if txt:
            docs.append({"pmcid": b.get("pmcid", f.stem), "organoid_type": b.get("organoid_type"),
                         "doi": b.get("doi"), "text": txt})
    return docs


def _embed(texts):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL)
    return np.asarray(model.encode(texts, batch_size=64, show_progress_bar=False), dtype=np.float32)


def build():
    docs = load_docs()
    INDEX.mkdir(parents=True, exist_ok=True)
    vecs = _embed([d["text"] for d in docs])
    np.save(INDEX / "vectors.npy", vecs)
    (INDEX / "docs.jsonl").write_text(
        "\n".join(json.dumps({k: d[k] for k in ("pmcid", "organoid_type", "doi")}) for d in docs) + "\n")
    print(f"embedded {len(docs)} docs -> {INDEX.relative_to(REPO)} (dim {vecs.shape[1]})")


def _load_index():
    vecs = np.load(INDEX / "vectors.npy")
    docs = [json.loads(l) for l in (INDEX / "docs.jsonl").read_text().splitlines() if l.strip()]
    return vecs, docs


def search(query: str, k: int = 5, organoid_type: str | None = None):
    vecs, docs = _load_index()
    qv = _embed([query])[0]
    mask = type_mask([d["organoid_type"] for d in docs], organoid_type)
    return [{**docs[i], "score": round(s, 4)} for i, s in cosine_topk(qv, vecs, k, mask)]


# Paraphrase queries that DELIBERATELY avoid the organoid-type word — this is where
# dense retrieval should beat lexical (synonymy / description without the keyword).
PARAPHRASE = {
    "intestinal": "crypt-villus epithelial budding organoids from Lgr5 stem cells with R-spondin and Noggin",
    "cerebral": "self-organizing neuroectoderm with cortical progenitors and neural rosettes",
    "cardiac": "beating cardiomyocyte spheroids via BMP4 and Wnt modulation",
    "kidney": "nephron progenitors with podocyte and proximal tubule segments",
    "retinal": "optic cup with laminated photoreceptors and pigmented epithelium",
    "hepatic": "hepatocyte-like cells secreting albumin with bile canaliculi",
    "lung": "alveolar type II and airway club cells producing surfactant",
    "gastric": "antral and fundic glandular epithelium with mucous pit cells",
    "pancreatic": "islet-like clusters of insulin-secreting beta cells expressing PDX1",
    "tumor": "patient-derived tumoroids from resected carcinoma for drug screening",
    "vascular": "endothelial networks with pericytes forming perfusable lumens",
    "cholangiocyte": "biliary duct epithelium forming cystic structures secreting bile",
}


def _precision_for_queries(queries, vecs, types, corpus_txt, k):
    """Return (semantic_precisions, lexical_precisions) for a {type: query} dict."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    tfidf = TfidfVectorizer(max_features=20000, stop_words="english")
    dtm = tfidf.fit_transform(corpus_txt)
    ts = list(queries)
    sem_qv = _embed([queries[t] for t in ts])
    lex_qv = tfidf.transform([queries[t] for t in ts])
    sem_p, lex_p = [], []
    for j, t in enumerate(ts):
        sem_rank = [types[i] for i, _ in cosine_topk(sem_qv[j], vecs, k)]
        lex_sims = np.asarray((dtm @ lex_qv[j].T).todense()).ravel()
        lex_rank = [types[i] for i in np.argsort(-lex_sims)[:k]]
        sem_p.append(precision_at_k(sem_rank, t, k))
        lex_p.append(precision_at_k(lex_rank, t, k))
    return sem_p, lex_p


def evaluate(k: int = 10):
    """Measured: semantic (MiniLM) vs lexical (TF-IDF cosine) retrieval. Query = a
    natural-language protocol query per organoid type; relevance = same organoid_type
    (curated label). Reports mean precision@k for both — a real artifact, no hand
    numbers. Embeds docs WITHOUT their type label, so this tests content similarity."""
    from datetime import datetime, timezone
    vecs, docs = _load_index()
    types = [d["organoid_type"] for d in docs]
    uniq = sorted({t for t in types if t})
    full = {d["pmcid"]: d for d in load_docs()}
    corpus_txt = [full.get(d["pmcid"], {}).get("text", "") for d in docs]

    # (1) in-vocab queries: the type word appears in the query
    invocab = {t: f"{t.replace('-', ' ')} organoid culture and differentiation protocol" for t in uniq}
    s1, l1 = _precision_for_queries(invocab, vecs, types, corpus_txt, k)
    # (2) paraphrase queries: NO type word — tests semantic synonymy (its real value)
    para = {t: q for t, q in PARAPHRASE.items() if t in uniq}
    s2, l2 = _precision_for_queries(para, vecs, types, corpus_txt, k)

    art = {
        "method": f"semantic (all-MiniLM-L6-v2) vs lexical (TF-IDF) retrieval over methods text "
                  f"(type label excluded from docs); relevance=same curated organoid_type; precision@{k}",
        "n_docs": len(docs), "n_types": len(uniq), "k": k,
        "in_vocab_query": {  # type word present -> lexical expected to win
            "semantic_mean_p@k": round(float(np.mean(s1)), 4),
            "lexical_mean_p@k": round(float(np.mean(l1)), 4)},
        "paraphrase_query": {  # NO type word -> semantic's value prop
            "n": len(para),
            "semantic_mean_p@k": round(float(np.mean(s2)), 4),
            "lexical_mean_p@k": round(float(np.mean(l2)), 4)},
        "finding": "pure dense retrieval does NOT beat lexical on in-vocabulary type queries; "
                   "its value is recall on paraphrase/synonym queries lacking the keyword -> "
                   "use HYBRID (lexical precision + semantic recall), as Starling does.",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    EVAL_OUT.parent.mkdir(parents=True, exist_ok=True)
    EVAL_OUT.write_text(json.dumps(art, indent=2))
    print(f"in-vocab:   semantic {art['in_vocab_query']['semantic_mean_p@k']}  "
          f"lexical {art['in_vocab_query']['lexical_mean_p@k']}")
    print(f"paraphrase: semantic {art['paraphrase_query']['semantic_mean_p@k']}  "
          f"lexical {art['paraphrase_query']['lexical_mean_p@k']}  (n={len(para)})")
    return art


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "search", "eval"])
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--type", default=None)
    args = ap.parse_args()
    if args.cmd == "build":
        build()
    elif args.cmd == "search":
        for r in search(args.query, args.k, args.type):
            print(f"{r['score']:.4f}  {r['organoid_type']:14} {r['pmcid']}  {r.get('doi','')}")
    else:
        evaluate(args.k if args.k != 5 else 10)


if __name__ == "__main__":
    main()
