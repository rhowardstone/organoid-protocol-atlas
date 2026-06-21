#!/usr/bin/env python3
"""
S-quality: evidence-span FIDELITY validation (Starling-style judge pass, adapted to
protocol intelligence).

Starling validates extracted biomedical facts with a frontier-model judge and reports
a rejection rate. We do the analogue for wet-lab protocol records: for a stratified
sample of extracted reagent records that carry BOTH a concentration and an evidence
quote, a frontier judge decides whether the cited quote actually supports the
(reagent name, concentration value, unit, role) tuple — catching reagent→dose
misbinding, unit drift, and unsupported numbers.

This is a QUALITY-CONTROL signal, NOT the accuracy metric: S3 gold (human-verified)
remains the ground-truth eval. Here the judge is an LLM (frontier), so we label it as
such and never claim it as human gold. Output is a GENERATED artifact (no hand-typed
numbers): outputs/validation/evidence_fidelity.json.

Stage 1 (this module): deterministically sample records to judge ->
outputs/validation/sample.jsonl. Stage 2: judges emit verdicts ->
outputs/validation/verdicts.jsonl. Stage 3: aggregate() -> evidence_fidelity.json.

Run:  python pipeline/validate_evidence.py --n 120   # writes the sample
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REAGENTS = REPO / "exports" / "public" / "reagents.jsonl"
OUT = REPO / "outputs" / "validation"

# fields the judge needs to assess reagent->dose->evidence binding
SAMPLE_FIELDS = ("id", "name", "canonical", "value", "unit", "role",
                 "organoid_type", "pmcid", "doi", "evidence_quote")


def eligible(row: dict) -> bool:
    """A record is judgeable iff it carries a concentration AND an evidence quote."""
    return bool((row.get("evidence_quote") or "").strip()) and row.get("value") is not None


def _key(row: dict) -> str:
    """Stable per-record hash for deterministic, seed-free ordering (no RNG → resumable)."""
    return hashlib.sha1(str(row.get("id", row.get("pmcid", "") + (row.get("name") or ""))).encode()).hexdigest()


def sample_records(rows, n: int):
    """Deterministic, organoid-type-STRATIFIED sample of eligible records: round-robin
    across types (each type ordered by stable hash) until n are taken. No randomness,
    so the sample is reproducible and the artifact auditable."""
    by_type = defaultdict(list)
    for r in rows:
        if eligible(r):
            by_type[r["organoid_type"]].append(r)
    for t in by_type:
        by_type[t].sort(key=_key)
    order = sorted(by_type)  # deterministic type order
    out, i = [], 0
    while len(out) < n and any(by_type[t][i:] for t in order):
        for t in order:
            if i < len(by_type[t]) and len(out) < n:
                out.append(by_type[t][i])
        i += 1
    return [{k: r.get(k) for k in SAMPLE_FIELDS} for r in out]


def aggregate(verdicts):
    """Aggregate judge verdicts into the fidelity metric. verdicts: list of
    {id, verdict in {supported,partial,unsupported}, reason}. Returns generated counts."""
    c = {"total": len(verdicts), "supported": 0, "partial": 0, "unsupported": 0, "invalid": 0}
    for v in verdicts:
        c[v.get("verdict") if v.get("verdict") in ("supported", "partial", "unsupported") else "invalid"] += 1
    scored = c["supported"] + c["partial"] + c["unsupported"]
    c["fidelity_supported_rate"] = round(c["supported"] / scored, 4) if scored else 0.0
    c["fidelity_supported_or_partial_rate"] = round((c["supported"] + c["partial"]) / scored, 4) if scored else 0.0
    c["flagged_unsupported"] = [v["id"] for v in verdicts if v.get("verdict") == "unsupported"]
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=120, help="sample size to judge")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(l) for l in REAGENTS.read_text().splitlines() if l.strip()]
    sample = sample_records(rows, args.n)
    (OUT / "sample.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in sample) + "\n")
    n_elig = sum(1 for r in rows if eligible(r))
    print(f"eligible records (conc + evidence): {n_elig}")
    print(f"wrote {len(sample)} sampled records -> {(OUT / 'sample.jsonl').relative_to(REPO)}")
    from collections import Counter
    print("by organoid_type:", dict(Counter(r["organoid_type"] for r in sample)))


if __name__ == "__main__":
    main()
