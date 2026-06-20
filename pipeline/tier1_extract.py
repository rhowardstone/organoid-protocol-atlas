#!/usr/bin/env python3
"""
Tier 1 — Structured extraction with a LOCAL model (A100, via ollama).

Reads each Tier-0 evidence bundle (methods + figure captions + table text +
inline supplement text), prompts a local LLM to fill the OrganoidProtocol
schema, validates the JSON, and enforces evidence grounding: a reagent's
Evidence is kept ONLY if its quote is a verbatim substring of the input
(missing evidence beats false evidence). Grounding rate is reported.

Zero marginal cost (local inference). No API. No schema changes.

Full predictions (carry short evidence quotes) are written local-only
(git-ignored, like the bundles); a metadata summary is committed.

Run:
    python pipeline/tier1_extract.py --limit 3
    python pipeline/tier1_extract.py            # whole corpus
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "organoid_demo"))

from schema import (  # noqa: E402
    BaseMedia, Concentration, Evidence, Matrix, OrganoidProtocol,
    OrganoidType, Passaging, Reagent, Reporting, SourceCells, SourceCellType,
    TimelineStage,
)

BUNDLES = REPO / "data" / "evidence_bundles" / "local"
PRED_DIR = REPO / "data" / "predictions" / "local"
OUT_DIR = REPO / "outputs" / "tier1"
OLLAMA = "http://localhost:11434/api/generate"
MODEL = "gemma3:12b"

UNIT_CANON = {
    "ng/ml": "ng/mL", "ng/mleg": "ng/mL", "ug/ml": "ug/mL", "µg/ml": "ug/mL",
    "um": "uM", "µm": "uM", "uM": "uM", "µM": "uM", "nm": "nM", "nM": "nM",
    "mm": "mM", "mM": "mM", "%": "%",
}


def norm_unit(u: str | None) -> str | None:
    if not u:
        return None
    return UNIT_CANON.get(u.strip().lower(), u.strip())


def build_evidence_text(bundle: dict, cap: int = 9000) -> str:
    parts = [bundle.get("methods_text", "")]
    for f in bundle.get("figures", []):
        if f.get("caption"):
            parts.append(f"[FIGURE {f.get('label','')}] {f['caption']}")
    for t in bundle.get("tables", []):
        if t.get("text"):
            parts.append(f"[TABLE {t.get('label','')}] {t['text']}")
    if bundle.get("supplementary_text"):
        parts.append("[SUPPLEMENT] " + bundle["supplementary_text"])
    txt = "\n".join(p for p in parts if p)
    if len(txt) < 400:  # fall back to full body if methods were thin
        txt = bundle.get("body_text", txt)
    return txt[:cap]


PROMPT = """You extract an organoid culture protocol from the text into JSON.
Return ONLY JSON with keys:
organoid_type (intestinal|gastric|cerebral|kidney|liver|lung|retinal|pancreatic|other),
source_cells: {{cell_type (iPSC|ESC|adult_stem_cell|primary_tissue|other), species}},
matrix: {{name}}, base_media: {{name}},
signaling_factors: [{{name, role, value, unit, evidence_quote}}],
media_supplements: [{{name}}],
passaging: {{method, split_ratio, interval_days}},
timeline: [{{name, day_start, day_end}}],
assay_endpoints: [string].
RULES:
- evidence_quote MUST be copied verbatim (exact substring) from the text.
- Extract ONLY items explicitly stated in THIS text. Never copy example wording, never fill
  from background knowledge. If a field/list is not stated, use null or [] — do not invent.
- passaging: method/split_ratio/interval_days only if the text states them (interval_days = integer).
- timeline = ordered culture/differentiation stages NAMED IN THIS TEXT, with day_start/day_end
  if the text gives them (integers); [] if the text does not describe staged timing.
- assay_endpoints = validation readouts/markers THIS paper actually reports; [] if none stated.
- signaling_factors = morphogens / growth factors / pathway agonists or inhibitors
  (e.g. EGF, Noggin, R-spondin, Wnt3a, FGF4, FGF9, ActivinA, CHIR99021, SB431542, Y-27632).
- viability supplements (B27, N2, FBS, nicotinamide, N-acetylcysteine, Pen/Strep) go in
  media_supplements, NOT signaling_factors.
- treat R-spondin / R-spondin1 / RSPO1 as ONE entity (list once).
- if a field is not stated, omit it; never invent a value.

TEXT:
{evidence}"""


def call_ollama(prompt: str) -> dict:
    req = urllib.request.Request(
        OLLAMA,
        data=json.dumps({"model": MODEL, "prompt": prompt, "format": "json",
                         "stream": False, "options": {"temperature": 0}}).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = json.load(urllib.request.urlopen(req, timeout=600))["response"]
    return json.loads(resp)


def _enum(cls, val, default):
    try:
        return cls(val)
    except (ValueError, TypeError):
        return default


def to_protocol(doi: str, m: dict, evidence: str) -> tuple[OrganoidProtocol, dict]:
    """Map model JSON -> OrganoidProtocol; ground evidence by verbatim-substring check."""
    grounded = total = 0

    def reagent(d: dict) -> Reagent:
        nonlocal grounded, total
        total += 1
        q = (d.get("evidence_quote") or "").strip()
        ev = None
        if q and q in evidence:           # missing evidence beats false evidence
            grounded += 1
            ev = Evidence(source_doi=doi, quote=q, section="Methods", confidence=0.0)
        val = d.get("value")
        try:
            val = float(val)
        except (ValueError, TypeError):
            val = None
        unit = d.get("unit")
        conc = Concentration(value=val, unit=unit, canonical_unit=norm_unit(unit),
                             raw=f"{d.get('value','')} {unit or ''}".strip()) if (val or unit) else None
        return Reagent(name=str(d.get("name", "")).strip(), role=d.get("role"),
                       concentration=conc, evidence=ev)

    def _int(x):
        try:
            return int(x)
        except (ValueError, TypeError):
            return None

    sc = m.get("source_cells") or {}
    mx = m.get("matrix") or {}
    bm = m.get("base_media") or {}
    pg = m.get("passaging") or {}
    passaging = Passaging(
        method=pg.get("method"), split_ratio=pg.get("split_ratio"),
        interval_days=_int(pg.get("interval_days")),
        reporting=(Reporting.REPORTED if (pg.get("method") or pg.get("split_ratio")
                   or pg.get("interval_days")) else Reporting.NOT_REPORTED))
    timeline = [TimelineStage(name=str(t["name"]).strip(), day_start=_int(t.get("day_start")),
                              day_end=_int(t.get("day_end")))
                for t in (m.get("timeline") or []) if isinstance(t, dict) and t.get("name")]
    endpoints = [str(x).strip() for x in (m.get("assay_endpoints") or []) if x]
    # deterministic anti-hallucination: keep only stage names / endpoints that actually
    # appear (verbatim, case-insensitive) in the source text. Kills prompt-example parroting.
    el = evidence.lower()
    timeline = [t for t in timeline if t.name and t.name.lower() in el]
    endpoints = [x for x in endpoints if x.lower() in el]

    proto = OrganoidProtocol(
        source_doi=doi,
        extractor_version=f"tier1_local::{MODEL}",
        organoid_type=_enum(OrganoidType, m.get("organoid_type"), OrganoidType.OTHER),
        source_cells=SourceCells(
            cell_type=_enum(SourceCellType, sc.get("cell_type"), SourceCellType.OTHER),
            species=sc.get("species")),
        matrix=Matrix(name=mx.get("name")),
        base_media=BaseMedia(name=bm.get("name"),
                             reporting=Reporting.REPORTED if bm.get("name") else Reporting.NOT_REPORTED),
        signaling_factors=[reagent(d) for d in (m.get("signaling_factors") or []) if d.get("name")],
        media_supplements=[Reagent(name=str(s.get("name") if isinstance(s, dict) else s).strip())
                           for s in (m.get("media_supplements") or []) if s],
        passaging=passaging,
        timeline=timeline,
        assay_endpoints=endpoints,
    )
    return proto, {"reagents": total, "grounded": grounded}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    bundles = sorted(BUNDLES.glob("*.json"))
    if args.limit:
        bundles = bundles[: args.limit]

    summary = []
    for i, bp in enumerate(bundles, 1):
        bundle = json.loads(bp.read_text())
        doi, pmcid = bundle["doi"], bundle["pmcid"]
        print(f"[{i}/{len(bundles)}] {pmcid} ({bundle['organoid_type']}) ...", flush=True)
        evidence = build_evidence_text(bundle)
        try:
            m = call_ollama(PROMPT.format(evidence=evidence))
            proto, g = to_protocol(doi, m, evidence)
            # organoid_type is curated in the corpus manifest (baked into the bundle) ->
            # trust it, not the LLM's guess.
            try:
                proto.organoid_type = OrganoidType(bundle["organoid_type"])
            except (ValueError, KeyError):
                pass
        except Exception as e:  # noqa: BLE001
            summary.append({"pmcid": pmcid, "doi": doi, "error": f"{type(e).__name__}: {e}"})
            continue
        (PRED_DIR / f"{pmcid}.json").write_text(proto.model_dump_json(indent=2))
        rate = round(g["grounded"] / g["reagents"], 3) if g["reagents"] else None
        summary.append({
            "pmcid": pmcid, "doi": doi, "organoid_type": proto.organoid_type.value,
            "model": MODEL, "n_signaling_factors": len(proto.signaling_factors),
            "n_supplements": len(proto.media_supplements),
            "matrix": proto.matrix.name, "base_media": proto.base_media.name,
            "reagents_grounded": g["grounded"], "reagents_total": g["reagents"],
            "grounding_rate": rate,
        })

    (OUT_DIR / "extraction_summary.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL, "papers": len(summary), "rows": summary,
    }, indent=2))
    ok = [s for s in summary if "error" not in s]
    tot_g = sum(s["reagents_grounded"] for s in ok)
    tot_r = sum(s["reagents_total"] for s in ok)
    print(f"\n{len(ok)}/{len(summary)} extracted | "
          f"corpus grounding {tot_g}/{tot_r} = {round(tot_g/tot_r,3) if tot_r else 'n/a'}")
    print(f"predictions (local-only): {PRED_DIR} | summary: {OUT_DIR}/extraction_summary.json")


if __name__ == "__main__":
    main()
