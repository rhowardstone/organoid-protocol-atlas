#!/usr/bin/env python3
"""
Build SAMPLE cookbook-protocol records for the frontend /protocols/<pmcid> page (#178).

Composes the eventual recipe-page data contract for the 3 seed papers by merging:
  - corpus.tsv          -> citation (author/year/journal), license
  - flat tier1 pred     -> materials (reagents w/ doses), matrix, base_media, source_cells
  - stages[] v2 proto   -> ordered stages w/ per-stage reagents, assay_endpoints, gate

Output: exports/sample/cookbook_sample.json (list of records) + exports/sample/README.md
(the field contract). This is SAMPLE/contract data so the frontend can build the page now,
before the production vLLM batched re-extraction emits stages[] corpus-wide.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PRED = REPO / "data" / "predictions" / "local"
STAGES = REPO / "outputs" / "eval" / "stages_prototype"
CORPUS = REPO / "data" / "corpus" / "corpus.tsv"
OUT = REPO / "exports" / "sample"
SEEDS = ["PMC10005775", "PMC10001859", "PMC10000618"]  # cerebral / intestinal / tumor


def corpus_meta() -> dict:
    return {r["pmcid"]: r for r in csv.DictReader(CORPUS.open(), delimiter="\t")}


def _reagent_rows(pred: dict) -> list:
    """Flatten the flat-schema reagents into a materials table (name/dose/unit/role/kind)."""
    out = []
    for kind in ("signaling_factors", "small_molecules", "media_supplements"):
        for r in (pred.get(kind) or []):
            conc = r.get("concentration") or {}
            out.append({"name": r.get("name"), "value": conc.get("value"),
                        "unit": conc.get("unit"), "role": r.get("role"), "kind": kind})
    return out


def build(pmcid: str, meta: dict) -> dict:
    pred = json.loads((PRED / f"{pmcid}.json").read_text())
    st = json.loads((STAGES / f"{pmcid}.v2.json").read_text())
    cm = meta.get(pmcid, {})
    sc = pred.get("source_cells") or {}
    return {
        "pmcid": pmcid,
        "doi": pred.get("source_doi") or cm.get("doi"),
        "citation": {"first_author": cm.get("first_author"), "year": cm.get("year"),
                     "journal": cm.get("journal"), "doi": cm.get("doi")},
        "license": cm.get("license"),
        "organoid_type": cm.get("organoid_type") or pred.get("organoid_type"),
        "is_generation_protocol": st.get("is_generation_protocol"),
        "source_cells": {"cell_type": sc.get("cell_type"), "line_name": sc.get("line_name"),
                         "species": sc.get("species")},
        "final_organoid": st.get("final_organoid"),
        "matrix": (pred.get("matrix") or {}).get("name"),
        "base_media": (pred.get("base_media") or {}).get("name"),
        "materials": _reagent_rows(pred),
        "stages": st.get("stages") or [],
        "assay_endpoints": st.get("assay_endpoints") or pred.get("assay_endpoints") or [],
    }


README = """# Sample cookbook-protocol records (frontend contract, #178)

`cookbook_sample.json` — a list of 3 protocol records (cerebral / intestinal / tumor),
the data contract for the `/protocols/<pmcid>` recipe page. SAMPLE data: flat fields are
production-real (from tier1), `stages[]` is from the v2 prototype (will be production once
the vLLM batched re-extraction lands). Per-record fields:

- `pmcid`, `doi`, `citation{first_author,year,journal,doi}`, `license` — page header + attribution
- `organoid_type`, `is_generation_protocol` (gate; false ⇒ render as "uses organoids as assay")
- `source_cells{cell_type,line_name,species}`, `final_organoid` — "from X → Y"
- `matrix`, `base_media` — header chips
- `materials[]` — `{name,value,unit,role,kind}` table (kind ∈ signaling_factors|small_molecules|media_supplements)
- `stages[]` — ORDERED. each: `{name,start_day,end_day,culture_vessel,medium_base,
  reagents[{name,concentration,unit,role}],transition}`. Render as the numbered recipe;
  `start_day/end_day` may be null (condition-keyed protocols) — fall back to `transition` text.
- `assay_endpoints[]` — characterization readouts (NOT culture stages); render as an "Endpoints" section.

Render order suggestion: header → source→organoid → materials table → numbered stages
(group each stage's reagents under it) → endpoints → citation. Cerebral is the richest
day-keyed example; intestinal is condition-keyed (null days); tumor exercises the
is_generation_protocol gate (1 culture stage + many endpoints).
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    meta = corpus_meta()
    records = [build(k, meta) for k in SEEDS]
    (OUT / "cookbook_sample.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))
    (OUT / "README.md").write_text(README)
    for r in records:
        print(f"{r['pmcid']:14} {r['organoid_type']:11} | {len(r['stages'])} stages | "
              f"{len(r['materials'])} materials | {len(r['assay_endpoints'])} endpoints | "
              f"gen={r['is_generation_protocol']}")
    print(f"-> {(OUT / 'cookbook_sample.json').relative_to(REPO)} (+ README.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
