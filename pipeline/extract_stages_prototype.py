#!/usr/bin/env python3
"""
PROTOTYPE: stage-aware (recipe) extraction for GitHub #178.

Extracts an ordered `stages[]` array per protocol — the ordered, reagent-linked PROCEDURE
that turns the atlas from "bag of ingredients + consensus %" into an actual recipe. Runs
the same local model (gemma3:12b via ollama) the production tier1 uses, with a stage-
structured prompt + JSON-constrained decoding, so the head-to-head with tier1 is apples-to-
apples. Seed set = the 3 primary-source papers in #178 (tumor / intestinal / cerebral).

Output: outputs/eval/stages_prototype/<pmcid>.json  + a console quality summary.
This is a PROTOTYPE to (a) give QA a concrete gold-set target and (b) give the Supervisor
evidence before the stages[] schema is folded into the vLLM batched re-extraction. Run:
  python pipeline/extract_stages_prototype.py
  python pipeline/extract_stages_prototype.py --only PMC10005775
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUNDLES = REPO / "data" / "evidence_bundles" / "local"
OUT = REPO / "outputs" / "eval" / "stages_prototype"
OLLAMA = "http://localhost:11434/api/generate"
MODEL = "gemma3:12b"
SEEDS = ["PMC10000618", "PMC10001859", "PMC10005775"]  # tumor / intestinal / cerebral (#178)

# Mirror the schema proposed in #178 exactly so QA can score against it.
PROMPT = """You are extracting a reproducible STEP-BY-STEP PROTOCOL (a recipe) from an organoid methods section.

Return ONLY a JSON object: {{"stages": [ ... ]}}.

A protocol is an ORDERED sequence of named stages. For EACH stage, in order, emit:
- "name": short stage name (e.g. "EB aggregation", "neural induction", "maturation")
- "start_day": integer day the stage starts (absolute, Day 0 = protocol start), or null
- "end_day": integer day the stage ends, or null
- "culture_vessel": plate/vessel/format used in this stage, or null
- "medium_base": base medium for this stage (e.g. "DMEM/F12", "E6"), or null
- "reagents": list of {{"name","concentration","unit","role"}} for factors ADDED in this
  stage (signaling factors, small molecules, supplements). concentration numeric or null;
  unit like "ng/mL","µM","%"; role like "BMP inhibitor","WNT activator" or null.
- "transition": what triggers the move to the next stage (e.g. "Day 6: switch to ..."), or null

Rules:
- Preserve ORDER. Stages must be sequential as performed.
- Only include reagents explicitly stated for that stage. Do not invent doses.
- If a reagent is removed at a stage, you may note it in "transition".
- Use absolute days when stated; if only relative ("after 2 days") infer start/end if possible, else null.

METHODS TEXT:
{evidence}
"""

# v2 — addresses the prototype findings: scope to the GENERATION procedure only (exclude
# characterization assays + upstream maintenance), add a real-protocol gate, and capture
# assays separately so they don't pollute stages[].
PROMPT_V2 = """You extract a reproducible organoid GENERATION PROTOCOL (a recipe) as JSON.

Return ONLY: {{"is_generation_protocol": bool, "source_cells": str|null,
"final_organoid": str|null, "assay_endpoints": [str], "stages": [ ... ]}}.

SCOPE — stages[] is ONLY the culture procedure that BUILDS the organoid: the ordered
sequence from seeding/aggregating the source cells through differentiation to the mature
organoid. STRICTLY EXCLUDE (these are NOT stages):
- characterization / readout assays: Western blot, ELISA, qPCR/RT-PCR, immunofluorescence/
  histology, imaging, sequencing, viability/MTT, TEER measurement, flow cytometry. Put their
  names in "assay_endpoints" instead.
- routine maintenance/expansion of the source cell line BEFORE the protocol starts
  (record it in "source_cells", not as a stage).
- downstream drug treatments / functional perturbations / disease modeling.
If the paper is NOT primarily an organoid generation protocol (e.g. it only uses organoids
as one assay in a drug study), set "is_generation_protocol": false and return stages: [] .

For EACH generation stage, in order:
- "name": short stage name (e.g. "EB aggregation", "neural induction", "maturation")
- "start_day"/"end_day": integer absolute day (Day 0 = protocol start) or null. MANY real
  protocols are condition-keyed, not day-keyed — null days are fine; never invent days.
- "culture_vessel", "medium_base": or null
- "reagents": [{{"name","concentration","unit","role"}}] ADDED in this stage; numeric conc or null
- "transition": trigger to the next stage (e.g. "Day 6: switch medium", "TEER > 150"), or null

Rules: preserve ORDER; only reagents explicitly stated for that stage; never invent doses/days.

METHODS TEXT:
{evidence}
"""


def call_ollama(prompt: str) -> dict:
    req = urllib.request.Request(
        OLLAMA,
        data=json.dumps({"model": MODEL, "prompt": prompt, "format": "json", "stream": False,
                         "options": {"temperature": 0, "num_ctx": 16384, "num_predict": 6144}}).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = json.load(urllib.request.urlopen(req, timeout=600))["response"]
    return json.loads(resp)


def summarize(pmcid: str, data: dict) -> str:
    stages = data.get("stages") or []
    hdr = f"\n=== {pmcid}: {len(stages)} stages ==="
    if "is_generation_protocol" in data:
        hdr += (f" | gen_protocol={data.get('is_generation_protocol')}"
                f" | source={data.get('source_cells')!r} -> {data.get('final_organoid')!r}"
                f" | endpoints={len(data.get('assay_endpoints') or [])}")
    lines = [hdr]
    for i, s in enumerate(stages, 1):
        days = f"d{s.get('start_day')}-{s.get('end_day')}"
        reg = ", ".join(f"{r.get('name')} {r.get('concentration')}{r.get('unit') or ''}".strip()
                        for r in (s.get("reagents") or [])[:6])
        lines.append(f"  {i}. {s.get('name')} ({days}) [{s.get('medium_base') or '?'}] "
                     f"-> {reg or '(no reagents)'}")
        if s.get("transition"):
            lines.append(f"       ⟶ {s['transition']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", default="", help="single PMCID (default: all 3 seeds)")
    ap.add_argument("--v2", action="store_true", help="use the scoped v2 prompt (gen-protocol gate)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    keys = [args.only] if args.only else SEEDS
    prompt_tmpl = PROMPT_V2 if args.v2 else PROMPT
    suffix = ".v2" if args.v2 else ""

    for pmcid in keys:
        bp = BUNDLES / f"{pmcid}.json"
        if not bp.exists():
            print(f"{pmcid}: MISSING bundle", file=sys.stderr)
            continue
        methods = (json.loads(bp.read_text()).get("methods_text") or "")[:24000]
        print(f"[{pmcid}] extracting stages ({len(methods)} chars){suffix}...", flush=True)
        try:
            data = call_ollama(prompt_tmpl.format(evidence=methods))
        except Exception as e:  # noqa: BLE001
            print(f"{pmcid}: ERROR {type(e).__name__}: {e}", file=sys.stderr)
            continue
        (OUT / f"{pmcid}{suffix}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(summarize(pmcid, data), flush=True)
    print(f"\n-> prototypes in {OUT.relative_to(REPO)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
