#!/usr/bin/env python3
"""
PROTOTYPE: decomposed multi-pass structured extraction (v1.0 target, #178).

Tests the architecture the team agreed on: the LLM extracts SCOPED MENTIONS + evidence per
entity type in SEPARATE passes (never model-authored cross-reference IDs); deterministic
code would then assign IDs and resolve references. Run on the hardest case in the corpus —
the iAssembloid CRISPRi paper (BIORXIV_2023.04.26.538498), currently MISLABELED "cerebral".

If the inventory pass correctly (a) classifies model_class=assembloid / not-strict,
(b) separates layer-3 perturbations+assays from the layer-2 protocol, and (c) decomposes the
distinct cell_populations and protocol_variants, the decomposed approach holds and the only
remaining job is code-side ID resolution. Brings real output as evidence, like stages[] v1->v2.

Passes: (A) inventory/classify, (B) steps for the primary assembly variant.
Output: outputs/eval/structured_prototype/<pmcid>.{inventory,steps}.json. Run:
  python pipeline/extract_structured_prototype.py            # iAssembloid seed
  python pipeline/extract_structured_prototype.py --only PMCxxxxxxx
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUNDLES = REPO / "data" / "evidence_bundles" / "local"
OUT = REPO / "outputs" / "eval" / "structured_prototype"
OLLAMA = "http://localhost:11434/api/generate"
MODEL = "gemma3:12b"
DEFAULT = "BIORXIV_2023.04.26.538498"  # iAssembloid CRISPRi paper (mislabeled cerebral)

# PASS A — inventory: classification + the three layers as scoped mentions (NO IDs).
INVENTORY = """You are cataloguing a 3D biological-model methods paper. Return ONLY JSON.

Separate THREE LAYERS and never merge them:
  L1 biological model (what is grown), L2 executable protocol variants (how it is grown),
  L3 experiments performed on the model (what was done with it).

{{
 "model_class": "organoid|assembloid|spheroid|organ_on_chip|2D_monoculture|3D_monoculture|co_culture|other",
 "is_organoid_strict": bool,   // true ONLY if self-organized through developmental patterning,
 "classification_reason": "one sentence",
 "tissue_or_system": str, "species": str, "cell_source_type": str,
 "disease_context": [str],
 "cell_populations": [          // L1 — each separately-derived input population (MENTIONS, no ids)
   {{"label": str, "cell_type": str, "source": str,
     "differentiation_method": str|null, "engineered_features": [str], "markers": [str]}}],
 "protocol_variants": [         // L2 — each comparable executable recipe / experimental branch
   {{"label": str, "purpose": "culture_generation|assembly|differentiation|perturbation_screen|assay_preparation|validation"}}],
 "perturbations": [             // L3 — NOT protocol steps
   {{"label": str, "type": str}}],
 "assays": [                    // L3 — characterization/readouts, NOT protocol steps
   {{"label": str, "type": str}}]
}}

Rules: list EVERY distinct cell population separately (e.g. serum-free vs serum-based astrocytes,
APOE3 vs APOE4 are DISTINCT). Comparable experimental branches are distinct protocol_variants.
CRISPRi/CROP-seq/screens are perturbations; MEA/snRNA-seq/imaging/ELISA are assays — never steps.

METHODS:
{evidence}
"""

# PASS B — steps for ONE named variant (scoped mentions; code binds to populations/media later).
STEPS = """Extract the ORDERED steps of ONLY this protocol variant: "{variant}".
Return ONLY JSON {{"steps":[...]}}. EXCLUDE characterization assays and upstream cell-line
maintenance. Each step:
{{"order_index": int, "day": int|null, "phase": str, "action": str,
  "inputs": [{{"cell_population_label": str, "quantity": number|null, "unit": str|null}}],
  "ratio": str|null, "device": str|null, "media": str|null,
  "reagents_added": [{{"name": str, "concentration": number|null, "unit": str|null}}],
  "transition": str|null}}
Preserve order; null days allowed; never invent values.

METHODS:
{evidence}
"""


def call(prompt: str) -> dict:
    req = urllib.request.Request(
        OLLAMA,
        data=json.dumps({"model": MODEL, "prompt": prompt, "format": "json", "stream": False,
                         "options": {"temperature": 0, "num_ctx": 16384, "num_predict": 6144}}).encode(),
        headers={"Content-Type": "application/json"})
    return json.loads(json.load(urllib.request.urlopen(req, timeout=600))["response"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", default=DEFAULT)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    bp = BUNDLES / f"{args.only}.json"
    if not bp.exists():
        print(f"{args.only}: MISSING bundle", file=sys.stderr)
        return 1
    methods = (json.loads(bp.read_text()).get("methods_text") or "")[:24000]

    print(f"[{args.only}] PASS A inventory ({len(methods)} chars)...", flush=True)
    inv = call(INVENTORY.format(evidence=methods))
    (OUT / f"{args.only}.inventory.json").write_text(json.dumps(inv, ensure_ascii=False, indent=2))
    print(f"  model_class={inv.get('model_class')} strict={inv.get('is_organoid_strict')}"
          f" | reason: {inv.get('classification_reason')}")
    print(f"  cell_populations={len(inv.get('cell_populations') or [])}:"
          f" {[c.get('label') for c in (inv.get('cell_populations') or [])]}")
    print(f"  protocol_variants={len(inv.get('protocol_variants') or [])}:"
          f" {[(v.get('label'), v.get('purpose')) for v in (inv.get('protocol_variants') or [])]}")
    print(f"  perturbations(L3)={len(inv.get('perturbations') or [])} | assays(L3)={len(inv.get('assays') or [])}")

    variants = inv.get("protocol_variants") or []
    # prefer the assembly/generation variant (the interesting recipe), in priority order
    target = None
    for pref in ("assembly", "culture_generation", "differentiation"):
        target = next((v["label"] for v in variants if v.get("purpose") == pref), None)
        if target:
            break
    target = target or (variants[0]["label"] if variants else "assembly protocol")
    print(f"\n[{args.only}] PASS B steps for variant {target!r}...", flush=True)
    steps = call(STEPS.format(variant=target, evidence=methods))
    (OUT / f"{args.only}.steps.json").write_text(json.dumps(steps, ensure_ascii=False, indent=2))
    for s in (steps.get("steps") or []):
        reg = ", ".join(f"{r.get('name')} {r.get('concentration') or ''}{r.get('unit') or ''}".strip()
                        for r in (s.get("reagents_added") or [])[:5])
        inp = ", ".join(f"{i.get('cell_population_label')}({i.get('quantity')})" for i in (s.get("inputs") or []))
        print(f"  {s.get('order_index')}. d{s.get('day')} {s.get('phase')}/{s.get('action')}"
              f" [{s.get('device') or s.get('media') or '?'}] inputs:[{inp}] {reg}")
    print(f"\n-> {OUT.relative_to(REPO)}/{args.only}.{{inventory,steps}}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
