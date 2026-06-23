#!/usr/bin/env python3
"""
Bake-off addendum — a BIOMEDICAL INSTRUCT model served via vLLM.

Rye asked: did we try a biomedically-tuned model on vLLM? The first bake-off used
ollama and meditron (a 7B Llama-2 *chat* model that couldn't follow the JSON schema).
This adds aaditya/Llama3-OpenBioLLM-8B — Llama-3-8B-INSTRUCT fine-tuned on biomedical
text, the leading open biomedical instruct model — served on vLLM's OpenAI-compatible
endpoint. Same prompt + evidence + decoding + scorer; only the model/engine differ.

Merges its column into outputs/eval/model_bakeoff.json (-> model_bakeoff_full.json).
Every number computed here, none hand-typed.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
import tier1_extract as t1  # noqa: E402
import eval_gold as eg      # noqa: E402

GOLD_DIR = REPO / "gold" / "verified"
BUNDLE_DIR = REPO / "data" / "evidence_bundles" / "local"
PRIOR = REPO / "outputs" / "eval" / "model_bakeoff.json"
OUT = REPO / "outputs" / "eval" / "model_bakeoff_full.json"

# OpenBioLLM-8B's tokenizer defines NO chat template, so /v1/chat/completions 400s
# (transformers >=4.44 refuses a default). Use /v1/completions with the Llama-3 instruct
# format applied manually — this also mirrors how ollama templated gemma3/phi4.
VLLM_URL = "http://localhost:8001/v1/completions"
MODEL = "aaditya/Llama3-OpenBioLLM-8B"
LABEL = "OpenBioLLM-8B"
NOTE = "BIOMEDICAL instruct (Llama-3-8B-Instruct FT), served via vLLM, /v1/completions + Llama-3 template"

_SYS = ("You are a precise biomedical information extraction engine. "
        "Respond with a single JSON object only.")


def call_vllm(prompt: str) -> dict:
    templated = (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
        f"{_SYS}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
        f"{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    )
    body = json.dumps({
        "model": MODEL,
        "prompt": templated,
        "temperature": 0,
        "max_tokens": 2048,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(VLLM_URL, data=body,
                                headers={"Content-Type": "application/json"})
    resp = json.load(urllib.request.urlopen(req, timeout=300))
    return json.loads(resp["choices"][0]["text"])


def main() -> int:
    golds = {p.stem: json.loads(p.read_text()) for p in sorted(GOLD_DIR.glob("*.json"))}
    bundles = {k: json.loads((BUNDLE_DIR / f"{k}.json").read_text()) for k in golds}
    print(f"== {LABEL} ({NOTE}) ==")
    paper_scores, timings, errors = {}, [], []
    for pmcid, gold in golds.items():
        t0 = time.time()
        try:
            # OpenBioLLM-8B caps at 8192 ctx (vs 16k for gemma3/phi4) — trim evidence to
            # ~4.5k tokens so prompt+output fit. A genuine handicap, noted in the artifact.
            ev = t1.build_evidence_text(bundles[pmcid], cap=18000)
            m = call_vllm(t1.PROMPT.format(evidence=ev))
            paper_scores[pmcid] = eg.score_paper(gold, m)
            dt = time.time() - t0
            timings.append(dt)
            print(f"  {pmcid}: ok ({dt:.0f}s)")
        except Exception as e:  # noqa: BLE001
            errors.append({"pmcid": pmcid, "error": repr(e)})
            print(f"  {pmcid}: ERROR {e!r}")
    agg = eg.aggregate(paper_scores) if paper_scores else {}

    col = {"model": MODEL, "note": NOTE, "engine": "vllm", "papers_scored": len(paper_scores),
           "errors": errors,
           "median_sec": round(sorted(timings)[len(timings) // 2], 1) if timings else None,
           "aggregate": agg}

    prior = json.loads(PRIOR.read_text()) if PRIOR.exists() else {"results": {}}
    prior["results"][LABEL] = col
    prior["generator"] = "pipeline/model_bakeoff.py + pipeline/bakeoff_vllm.py"
    OUT.write_text(json.dumps(prior, indent=2))

    print("\n" + "=" * 64)
    print(f"{'model':<16}{'sig F1':>9}{'sig P':>8}{'sig R':>8}{'cell':>7}{'matrix':>8}{'media':>8}")
    for lab, r in prior["results"].items():
        a = r.get("aggregate")
        if not a:
            print(f"{lab:<16}  (no scores)")
            continue
        sf = a["set_fields"]["signaling_factors"]["micro"]
        sc = a["scalar_fields"]
        print(f"{lab:<16}{sf['f1']:>9}{sf['precision']:>8}{sf['recall']:>8}"
              f"{sc['source_cells.cell_type']['accuracy']:>7}"
              f"{sc['matrix']['accuracy']:>8}{sc['base_media']['accuracy']:>8}")
    print(f"\nwrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
