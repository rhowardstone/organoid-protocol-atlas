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
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Deterministic non-reagent guard: the model occasionally lists lab equipment,
# software, or imaging systems as "signaling factors" (they appear verbatim in
# methods, so substring-grounding alone won't catch them). Drop names that are
# clearly instruments/software, not culture reagents. Conservative — matches only
# unambiguous equipment/software tokens, never real reagents.
NON_REAGENT_RE = re.compile(
    r"(confocal|microscop|imaging (?:software|system)|\bsoftware\b|NIS[- ]?Elements|"
    r"ImageJ|\bFIJI\b|FlowJo|cytometer|spectrophotomet|centrifuge|\bincubator\b|"
    r"\bNikon\b|\bZeiss\b|\bLeica\b|\bOlympus\b|scanner|workstation|GraphPad|"
    r"\bPrism\b|microplate reader|hemocytometer|water bath|biosafety|\bPPE\b|"
    r"forceps|scalpel|\bpipette\b|thermocycler|\bcamera\b)", re.I)


def is_non_reagent(name: str | None) -> bool:
    return bool(name) and bool(NON_REAGENT_RE.search(name))


# Pathway / signaling-family context guard: bare family names without a specific
# isoform number/letter are pathway-context prose, not actionable culture reagents.
# "WNT signaling" ≠ "WNT3A" or "CHIR99021". Also catches any name that explicitly
# qualifies itself with "signaling / pathway / axis / cascade / family / regulation".
# Conservative: only matches when NO isoform suffix (digit or letter run) follows
# the base name — so "BMP4", "FGF2", "TGF-β1", "EGF" are never blocked.
PATHWAY_CONTEXT_RE = re.compile(
    # bare family names (no trailing digit / letter suffix → isoform):
    r"^\s*(?:wnt|bmp|tgf(?:[\s\-]?(?:beta|α|β|alpha))?|sonic[\s+]hedgehog|shh"
    r"|notch|pdgf|vegf|hippo|hedgehog)\s*$"
    r"|"
    # any name that declares itself as signaling / pathway / etc.:
    r"\b(?:wnt|bmp|fgf|tgf|egf|shh|notch|hedgehog|pdgf|vegf)\s+"
    r"(?:signaling?|pathway|activity|axis|cascade|family|regulation"
    r"|ligand|superfamily|inhibition|inhibitor|activation|response)\b",
    re.I,
)


def is_pathway_context(name: str | None) -> bool:
    return bool(name) and bool(PATHWAY_CONTEXT_RE.search(name))


sys.path.insert(0, str(REPO / "organoid_demo"))

from schema import (  # noqa: E402
    BaseMedia, Concentration, CultureConditions, Evidence, FailureMode, Matrix,
    OrganoidProtocol, OrganoidType, Passaging, ProtocolModification, Reagent, Reporting,
    SourceCells, SourceCellType, TimelineStage,
)

# A real DOI ("10.<registrant>/<suffix>"). The model frequently emits a bare reference
# index (e.g. "21") for a cited prior protocol; those must NOT become lineage edges.
DOI_RE = re.compile(r"10\.\d{4,9}/\S+")

BUNDLES = REPO / "data" / "evidence_bundles" / "local"
PRED_DIR = REPO / "data" / "predictions" / "local"
OUT_DIR = REPO / "outputs" / "tier1"
OLLAMA = "http://localhost:11434/api/generate"
MODEL = "gemma3:12b"

MAX_RETRIES = 3
RETRY_DELAY_S = 5


def with_retry(fn, *args, max_retries=MAX_RETRIES, delay=RETRY_DELAY_S, **kwargs):
    """Retry fn on TimeoutError or ConnectionError (transient failures). Other errors propagate."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except (TimeoutError, ConnectionError, OSError) as e:
            last_exc = e
            if attempt < max_retries - 1:
                print(f"  retrying ({attempt+1}/{max_retries}) after {delay}s: {e}", flush=True)
                time.sleep(delay)
    raise last_exc


UNIT_CANON = {
    "ng/ml": "ng/mL", "ng/mleg": "ng/mL", "ug/ml": "ug/mL", "µg/ml": "ug/mL",
    "um": "uM", "µm": "uM", "uM": "uM", "µM": "uM", "nm": "nM", "nM": "nM",
    "mm": "mM", "mM": "mM", "%": "%",
}


def norm_unit(u: str | None) -> str | None:
    if not u:
        return None
    return UNIT_CANON.get(u.strip().lower(), u.strip())


def build_evidence_text(bundle: dict, cap: int = 24000) -> str:
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
organoid_type (intestinal|gastric|cerebral|kidney|liver|lung|retinal|pancreatic|tumor|cardiac|vascular|cholangiocyte|skin|mammary|endometrial|bone|prostate|inner-ear|salivary-gland|bladder|neuromuscular|esophageal|blood-brain-barrier|thyroid|fallopian-tube|other),
source_cells: {{cell_type (iPSC|ESC|adult_stem_cell|primary_tissue|other), species, line_name, rrid}},
matrix: {{name}}, base_media: {{name}},
culture_conditions: {{temperature_c, co2_pct, o2_pct, evidence_quote}},
signaling_factors: [{{name, role, value, unit, evidence_quote}}],
media_supplements: [{{name}}],
passaging: {{method, split_ratio, interval_days}},
timeline: [{{name, day_start, day_end}}],
assay_endpoints: [string],
failure_modes: [{{description, condition, evidence_quote}}],
modifications: [{{cited_doi, change_description, evidence_quote}}],
publication_type ("primary_methods" | "review" | "other"): "review" if this text summarizes findings from multiple other papers' protocols; "primary_methods" if it presents one new original culture procedure.
RULES:
- evidence_quote MUST be copied verbatim (exact substring) from the text.
- culture_conditions: numeric temperature_c / co2_pct / o2_pct ONLY if the text states them
  (e.g. "37 °C, 5% CO2"); evidence_quote = the verbatim span containing those numbers; null if
  not stated. Do NOT assume 37C/5%CO2 — extract only what is written.
- source_cells.line_name = the cell line as named (e.g. H9, WTC-11); rrid = an RRID/Cellosaurus
  accession (e.g. CVCL_9773) ONLY if it appears verbatim; null otherwise.
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
- failure_modes: list any explicit warnings, failure conditions, or critical steps the paper warns about (e.g. "temperature above 37°C reduces efficiency", "avoid repeated freeze-thaw"). evidence_quote = the verbatim span stating it. Empty [] if none stated.
- modifications: if the paper explicitly says it modified a prior protocol, capture the prior protocol's DOI (cited_doi = the full DOI string ONLY if it appears verbatim in THIS text; null otherwise — never a bare reference number, never invented) and what changed; evidence_quote = the verbatim span. Empty [] if this is an original protocol or no modifications are stated.

TEXT:
{evidence}"""


def detect_publication_type(bundle: dict, model_out: dict) -> str:
    """Determine article type: prefer deterministic JATS attribute, fall back to model."""
    jats_at = bundle.get("article_type", "").lower()
    if "review" in jats_at:
        return "review"
    mp = str(model_out.get("publication_type", "")).lower().strip('"').strip()
    if mp in ("review", "primary_methods", "other"):
        return mp
    return "primary_methods"


def call_ollama(prompt: str) -> dict:
    req = urllib.request.Request(
        OLLAMA,
        # num_ctx must be set explicitly — ollama's default context (~4k) silently
        # truncates long protocol papers (e.g. Broda 40k methods), losing the
        # concentrations stated in later steps. 16k tokens covers the 24k-char window.
        data=json.dumps({"model": MODEL, "prompt": prompt, "format": "json",
                         "stream": False,
                         "options": {"temperature": 0, "num_ctx": 16384}}).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = json.load(urllib.request.urlopen(req, timeout=600))["response"]
    return json.loads(resp)


def _enum(cls, val, default):
    try:
        return cls(val)
    except (ValueError, TypeError):
        return default


def build_failure_modes(m: dict, doi: str, evidence: str) -> list[FailureMode]:
    """Failure modes the model reported. Keep any with a non-empty description; attach a
    verbatim Evidence quote when the model supplied one that is a real substring of the
    source (a quote that is NOT verbatim is dropped, never stored as false evidence)."""
    out = []
    for fm in (m.get("failure_modes") or []):
        if not isinstance(fm, dict):
            continue
        desc = str(fm.get("description") or "").strip()
        if not desc:
            continue
        q = (fm.get("evidence_quote") or "").strip()
        ev = Evidence(source_doi=doi, quote=q, section="Methods", confidence=0.0) \
            if (q and q in evidence) else None
        cond = (fm.get("condition") or "").strip() or None
        out.append(FailureMode(description=desc, condition=cond, evidence=ev))
    return out


def build_modifications(m: dict, doi: str, evidence: str) -> list[ProtocolModification]:
    """Protocol modifications the model reported. Require a change_description; keep
    cited_doi ONLY if it is a real DOI (a bare reference index like "21" is dropped so
    it cannot become a fabricated lineage edge)."""
    out = []
    for mod in (m.get("modifications") or []):
        if not isinstance(mod, dict):
            continue
        change = str(mod.get("change_description") or "").strip()
        if not change:
            continue
        # cited_doi must be a real DOI AND appear verbatim in the source — this kills both
        # bare reference indices ("21") and example DOIs parroted from the prompt.
        cd = str(mod.get("cited_doi") or "").strip()
        cited = cd if (DOI_RE.fullmatch(cd) and cd in evidence) else None
        q = (mod.get("evidence_quote") or "").strip()
        ev = Evidence(source_doi=doi, quote=q, section="Methods", confidence=0.0) \
            if (q and q in evidence) else None
        out.append(ProtocolModification(cited_doi=cited, change_description=change, evidence=ev))
    return out


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

    # v0.3 culture_conditions — grounded numerics only. Keep a value iff the model's
    # quote is verbatim AND the number string appears in that quote (no assumed 37C/5%).
    def _num(x):
        try:
            return float(x)
        except (ValueError, TypeError):
            return None
    cc_in = m.get("culture_conditions") or {}
    cq = (cc_in.get("evidence_quote") or "").strip()
    cq_ok = bool(cq) and cq in evidence

    def _grounded_num(key):
        v = _num(cc_in.get(key))
        if v is None or not cq_ok:
            return None
        # the numeric must appear in the quote as a WHOLE number, not digits embedded
        # in a larger one (else co2=7 would ground against "37 °C"). #7 review fix.
        forms = {str(int(v)) if v == int(v) else None, str(v), f"{v:g}"} - {None}
        return v if any(re.search(r"(?<![\d.])" + re.escape(f) + r"(?![\d.])", cq)
                        for f in forms) else None
    temp, co2, o2 = _grounded_num("temperature_c"), _grounded_num("co2_pct"), _grounded_num("o2_pct")
    has_cc = any(x is not None for x in (temp, co2, o2))
    culture_conditions = CultureConditions(
        temperature_c=temp, co2_pct=co2, o2_pct=o2,
        reporting=Reporting.REPORTED if has_cc else Reporting.NOT_EXTRACTED,
        evidence=Evidence(source_doi=doi, quote=cq, section="Methods", confidence=0.0) if has_cc else None)

    # v0.3 cell-line identity — require EXACT (case-sensitive) substring grounding so the
    # stored Evidence quote is genuinely verbatim ("h9" is dropped if the source says "H9").
    # RRID must not be an ungrounded convenience field (PR #4 + #7 review notes).
    ln = (sc.get("line_name") or "").strip() or None
    rrid = (sc.get("rrid") or "").strip() or None
    ln = ln if (ln and ln in evidence) else None
    rrid = rrid if (rrid and rrid in evidence) else None
    sc_ev = Evidence(source_doi=doi, quote=(rrid or ln), section="Methods", confidence=0.0) \
        if (ln or rrid) else None

    proto = OrganoidProtocol(
        source_doi=doi,
        extractor_version=f"tier1_local::{MODEL}",
        organoid_type=_enum(OrganoidType, m.get("organoid_type"), OrganoidType.OTHER),
        source_cells=SourceCells(
            cell_type=_enum(SourceCellType, sc.get("cell_type"), SourceCellType.OTHER),
            species=sc.get("species"), line_name=ln, rrid=rrid, evidence=sc_ev),
        culture_conditions=culture_conditions,
        matrix=Matrix(name=mx.get("name")),
        base_media=BaseMedia(name=bm.get("name"),
                             reporting=Reporting.REPORTED if bm.get("name") else Reporting.NOT_REPORTED),
        signaling_factors=[reagent(d) for d in (m.get("signaling_factors") or [])
                           if d.get("name") and not is_non_reagent(d.get("name"))
                           and not is_pathway_context(d.get("name"))],
        media_supplements=[Reagent(name=str(s.get("name") if isinstance(s, dict) else s).strip())
                           for s in (m.get("media_supplements") or []) if s],
        passaging=passaging,
        timeline=timeline,
        assay_endpoints=endpoints,
        failure_modes=build_failure_modes(m, doi, evidence),
        modifications=build_modifications(m, doi, evidence),
    )
    return proto, {"reagents": total, "grounded": grounded}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="comma-separated PMCIDs (incremental extraction)")
    ap.add_argument("--retry-errors", action="store_true",
                    help="Re-extract only rows with 'error' in the existing summary")
    args = ap.parse_args()
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    only = {p.strip() for p in args.only.split(",") if p.strip()}
    bundles = sorted(BUNDLES.glob("*.json"))
    if only:
        bundles = [b for b in bundles if b.stem in only]
    elif args.limit:
        bundles = bundles[: args.limit]

    summary_path = OUT_DIR / "extraction_summary.json"
    if args.retry_errors and summary_path.exists():
        existing = json.loads(summary_path.read_text())
        error_pmcids = {s["pmcid"] for s in existing.get("rows", []) if "error" in s}
        bundles = [b for b in bundles if b.stem in error_pmcids]
        print(f"Retrying {len(bundles)} error records: {sorted(error_pmcids)}")

    summary = []
    for i, bp in enumerate(bundles, 1):
        bundle = json.loads(bp.read_text())
        doi, pmcid = bundle["doi"], bundle["pmcid"]
        print(f"[{i}/{len(bundles)}] {pmcid} ({bundle['organoid_type']}) ...", flush=True)
        evidence = build_evidence_text(bundle)
        try:
            m = with_retry(call_ollama, PROMPT.format(evidence=evidence))
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
        pred_dict = json.loads(proto.model_dump_json(indent=2))
        pred_dict["publication_type"] = detect_publication_type(bundle, m)
        (PRED_DIR / f"{pmcid}.json").write_text(json.dumps(pred_dict, indent=2))
        rate = round(g["grounded"] / g["reagents"], 3) if g["reagents"] else None
        # mirror the GATED values stored on the prediction (DOI-checked, evidence-grounded)
        failure_modes = [
            {"description": fm.description, "condition": fm.condition}
            for fm in proto.failure_modes
        ]
        modifications = [
            {"cited_doi": mod.cited_doi, "change_description": mod.change_description}
            for mod in proto.modifications
        ]
        summary.append({
            "pmcid": pmcid, "doi": doi, "organoid_type": proto.organoid_type.value,
            "model": MODEL, "n_signaling_factors": len(proto.signaling_factors),
            "n_supplements": len(proto.media_supplements),
            "matrix": proto.matrix.name, "base_media": proto.base_media.name,
            "reagents_grounded": g["grounded"], "reagents_total": g["reagents"],
            "grounding_rate": rate,
            "failure_modes": failure_modes,
            "modifications": modifications,
            "publication_type": pred_dict.get("publication_type"),
        })

    # incremental (--only): merge fresh rows into the existing summary, keeping the rest
    if only and summary_path.exists():
        prior = json.loads(summary_path.read_text()).get("rows", [])
        done = {s["pmcid"] for s in summary}
        summary = [s for s in prior if s["pmcid"] not in done] + summary
    summary_path.write_text(json.dumps({
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
