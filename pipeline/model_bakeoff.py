#!/usr/bin/env python3
"""
Extractor model bake-off — head-to-head on the 6 HUMAN-VERIFIED gold papers.

Question (Rye, 2026-06-22): we extract with gemma3:12b, a GENERAL 12B model. Does a
biomedical model, or a higher-quality >=12B general model, extract better? Run the
SAME prompt + SAME evidence bundle through each candidate and score the raw output
against the verified gold with the exact S3 scorer (pipeline/eval_gold.score_paper).

Controlled: identical prompt (tier1_extract.PROMPT), identical evidence window
(build_evidence_text), identical decoding (temp 0, num_ctx 16384), identical scorer.
The only variable is the model. Raw model JSON is scored (pre-grounding filter) so
all candidates are on equal footing — this isolates MODEL quality, not the pipeline.

Writes outputs/eval/model_bakeoff.json. Every number computed here, none hand-typed.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
import tier1_extract as t1  # noqa: E402
import eval_gold as eg      # noqa: E402

GOLD_DIR = REPO / "gold" / "verified"
BUNDLE_DIR = REPO / "data" / "evidence_bundles" / "local"
OUT = REPO / "outputs" / "eval" / "model_bakeoff.json"

# candidates: (model, label, note)
MODELS = [
    ("gemma3:12b", "gemma3:12b", "baseline — general 12B (production extractor)"),
    ("phi4:14b", "phi4:14b", "general 14B — the >=12B 'equal or higher quality' test"),
    ("meditron:latest", "meditron-7b", "BIOMEDICAL but 7B Llama-2-based (below 12B bar)"),
]


def extract_one(model: str, bundle: dict) -> dict:
    """Run one model over one bundle with the production prompt/decoding. Returns raw JSON."""
    t1.MODEL = model  # the call_ollama global the pipeline reads
    evidence = t1.build_evidence_text(bundle)
    return t1.with_retry(t1.call_ollama, t1.PROMPT.format(evidence=evidence))


def main() -> int:
    golds = {p.stem: json.loads(p.read_text()) for p in sorted(GOLD_DIR.glob("*.json"))}
    bundles = {pmcid: json.loads((BUNDLE_DIR / f"{pmcid}.json").read_text()) for pmcid in golds}
    print(f"gold papers: {len(golds)} | candidates: {[m[0] for m in MODELS]}\n")

    results = {}
    for model, label, note in MODELS:
        print(f"== {label} ({note}) ==")
        paper_scores, timings, errors = {}, [], []
        for pmcid, gold in golds.items():
            t0 = time.time()
            try:
                m = extract_one(model, bundles[pmcid])
                paper_scores[pmcid] = eg.score_paper(gold, m)
                dt = time.time() - t0
                timings.append(dt)
                print(f"  {pmcid}: ok ({dt:.0f}s)")
            except Exception as e:  # noqa: BLE001
                errors.append({"pmcid": pmcid, "error": repr(e)})
                print(f"  {pmcid}: ERROR {e!r}")
        agg = eg.aggregate(paper_scores) if paper_scores else {}
        results[label] = {
            "model": model, "note": note, "papers_scored": len(paper_scores),
            "errors": errors, "median_sec": round(sorted(timings)[len(timings) // 2], 1) if timings else None,
            "aggregate": agg,
        }
        if agg:
            sf = agg["set_fields"]["signaling_factors"]["micro"]
            sc = agg["scalar_fields"]
            print(f"  -> signaling F1={sf['f1']} (P={sf['precision']} R={sf['recall']}) | "
                  f"cell_type acc={sc['source_cells.cell_type']['accuracy']} | "
                  f"matrix acc={sc['matrix']['accuracy']} | "
                  f"base_media acc={sc['base_media']['accuracy']}\n")

    artifact = {
        "generator": "pipeline/model_bakeoff.py",
        "question": "Does a biomedical or higher-quality >=12B model extract better than gemma3:12b?",
        "method": "same prompt + evidence + decoding (temp0/num_ctx16384); raw model JSON "
                  "scored vs 6 human-verified gold via eval_gold.score_paper. Only the model varies.",
        "gold_papers": sorted(golds),
        "results": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(artifact, indent=2))

    print("=" * 64)
    print(f"{'model':<16}{'sig F1':>9}{'sig P':>8}{'sig R':>8}{'cell':>7}{'matrix':>8}{'media':>8}")
    for label, r in results.items():
        a = r.get("aggregate")
        if not a:
            print(f"{label:<16}  (no scores)")
            continue
        sf = a["set_fields"]["signaling_factors"]["micro"]
        sc = a["scalar_fields"]
        print(f"{label:<16}{sf['f1']:>9}{sf['precision']:>8}{sf['recall']:>8}"
              f"{sc['source_cells.cell_type']['accuracy']:>7}"
              f"{sc['matrix']['accuracy']:>8}{sc['base_media']['accuracy']:>8}")
    print(f"\nwrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
