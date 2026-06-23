#!/usr/bin/env python3
"""
Tier 2 — Vision extraction on protocol-schematic figures (LOCAL, A100).

Organoid papers put the *protocol* in a figure: a Day-0..Day-N timeline with the
reagents added at each stage and their concentrations. That information is often
incomplete or absent in the methods prose, so Tier-1 (text) misses it. Tier 2
runs a local vision model (gemma3:12b via ollama) on the figures the router
flags as schematics, then GROUNDS the result against the paper text.

Router (cost guardrail): we do NOT caption-OCR every figure. We run vision only
on figures whose caption matches a schematic/timeline cue, and only for
license-clean papers whose images we are allowed to cache (see fetch_figures.py).
This keeps the expensive tier a small fraction of figures.

Grounding (missing evidence beats false evidence): a vision-extracted stage name
or reagent is kept only if it also appears (case-insensitive substring) in the
paper body text or the figure caption. Ungrounded items are reported, not stored
as fact. Concentrations are kept only when their reagent grounds AND the figure
caption/body corroborates the value, else flagged unverified.

Run:
    python pipeline/tier2_vision.py                 # all license-clean papers
    python pipeline/tier2_vision.py PMC6906116      # one paper
"""

from __future__ import annotations

import base64
import io
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import CONC_OK, canon_unit, canonical_or_none  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
BUNDLES = REPO / "data" / "evidence_bundles" / "local"
FIG_DIR = REPO / "data" / "figures" / "local"
PRED1 = REPO / "data" / "predictions" / "local"
PRED2 = REPO / "data" / "predictions" / "local" / "tier2"
OUT = REPO / "outputs" / "tier2"
OLLAMA = "http://localhost:11434/api/generate"
MODEL = "gemma3:12b"

# hour-scale vs day/week/passage-scale stage labels (model sometimes maps "4h" -> day 0)
HOUR_RE = re.compile(r"\b\d+\s*h(?:ours?|rs?)?\b", re.I)
DAY_RE = re.compile(r"\bday\b|\bweek\b|\bw\d|\bd\d|\bp\d", re.I)

# router cue: a caption that promises a protocol/timeline schematic
SCHEMATIC_RE = re.compile(
    r"\b(schematic|scheme|timeline|time[- ]?course|protocol|workflow|overview|"
    r"differentiation|stepwise|strategy|pipeline|generat\w+ of|day ?\d)\b", re.I)

PROMPT = """You are reading ONE figure from an organoid–biology paper.
Figure label: {label}
Caption (ground truth for what the figure is): {caption}

Return ONLY JSON:
{{
 "is_protocol_schematic": true|false,
 "timeline_stages": [{{"name": "...", "day_start": int|null, "day_end": int|null}}],
 "reagents_in_figure": [{{"name": "...", "value": number|null, "unit": "..."|null}}],
 "verbatim_labels": ["exact text strings you can READ printed in the image"]
}}
RULES:
- Only report what is VISUALLY present in THIS image. Do not use outside knowledge.
- timeline_stages: ordered culture/differentiation phases drawn on a time axis,
  with day numbers if printed. [] if the figure is not a timeline/schematic.
- reagents_in_figure: growth factors / small molecules / morphogens written in the
  figure (e.g. EGF, Noggin, CHIR99021, FGF2, SB431542), with dose if printed.
- verbatim_labels: copy text EXACTLY as printed (used to verify you actually read it).
- If this is a results/microscopy figure with no protocol, set is_protocol_schematic
  false and return empty lists."""


def clean_concentration(value, unit):
    """Sanitize a vision-read dose. Keep a unit only if it's a real concentration unit
    (drops e.g. an abbreviation the model dropped in the unit field: 'ACTA'); drop a
    value that then has no valid unit (a bare number — often part of the name like
    'laminin 111' — is not a usable concentration). Returns (value, canonical_unit)."""
    cu = canon_unit(unit) if unit else None
    if cu not in CONC_OK:
        cu = None
    if value is not None and cu is None:
        value = None
    return value, cu


def tier1_reagent_canon(pmcid: str) -> set:
    """Canonical reagent names this paper's Tier-1 (text) extraction found — the set
    vision is allowed to CONFIRM. Vision never originates a reagent absent from text."""
    p = PRED1 / f"{pmcid}.json"
    if not p.exists():
        return set()
    try:
        d = json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return set()
    out = set()
    for k in ("signaling_factors", "media_supplements", "small_molecules"):
        for r in d.get(k) or []:
            n = r.get("name") if isinstance(r, dict) else r
            c = canonical_or_none(n)
            if c:
                out.add(c)
    return out


def confirm_reagents(vision_reagents, tier1_canon: set):
    """Keep only vision reagents whose canonical resolves AND is in the paper's Tier-1
    reagent set — vision CONFIRMS text, never originates. Each kept record carries
    figure_confirmed=True and the verbatim figure text it was read from."""
    out = []
    for r in vision_reagents or []:
        if not isinstance(r, dict):
            continue
        name = (r.get("name") or "").strip()
        canon = canonical_or_none(name)
        if not canon or canon not in tier1_canon:
            continue
        value, unit = clean_concentration(r.get("value"), r.get("unit"))
        out.append({"name": name, "canonical": canon, "value": value, "unit": unit,
                    "figure_confirmed": True, "evidence_figure_text": name})
    return out


def clean_stages(stages):
    """Dedup timeline stages and null day numbers on hour-scale labels ('4h' is not
    day 0). Preserves order."""
    seen = set()
    out = []
    for s in stages or []:
        if not isinstance(s, dict):
            continue
        name = (s.get("name") or "").strip()
        if not name:
            continue
        ds, de = s.get("day_start"), s.get("day_end")
        if HOUR_RE.search(name) and not DAY_RE.search(name):
            ds = de = None  # hour-scale label: the day axis is unreliable
        key = (name.lower(), ds, de)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "day_start": ds, "day_end": de})
    return out


def call_vision(img_b64: str, label: str, caption: str) -> dict:
    body = json.dumps({
        "model": MODEL,
        "prompt": PROMPT.format(label=label, caption=(caption or "")[:600]),
        "images": [img_b64], "format": "json", "stream": False,
        "options": {"temperature": 0},
    }).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    resp = json.load(urllib.request.urlopen(req, timeout=600))["response"]
    return json.loads(resp)


def load_image_b64(path: Path, max_side: int = 1280) -> str:
    im = Image.open(path).convert("RGB")
    if max(im.size) > max_side:
        s = max_side / max(im.size)
        im = im.resize((int(im.width * s), int(im.height * s)))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


def main():
    PRED2.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    subset = bool(sys.argv[1:])
    targets = sys.argv[1:] or [p.name for p in sorted(FIG_DIR.iterdir()) if p.is_dir()]

    summary = []
    for pmcid in targets:
        figdir = FIG_DIR / pmcid
        bpath = BUNDLES / f"{pmcid}.json"
        if not figdir.exists() or not bpath.exists():
            continue
        b = json.loads(bpath.read_text())
        body_l = (b.get("body_text", "") or "").lower()
        doi = b.get("doi")
        t1_canon = tier1_reagent_canon(pmcid)   # reagents vision is allowed to confirm

        flagged = []
        for f in b.get("figures", []):
            cap = f.get("caption", "") or ""
            href = f.get("graphic_href")
            if href and SCHEMATIC_RE.search(cap) and (figdir / href).exists():
                flagged.append((f.get("label", ""), cap, figdir / href))

        fig_records = []
        for label, cap, fp in flagged:
            cap_l = cap.lower()
            try:
                v = call_vision(load_image_b64(fp), label, cap)
            except Exception as e:  # noqa: BLE001
                fig_records.append({"label": label, "file": fp.name, "error": f"{type(e).__name__}: {e}"})
                continue

            def grounds(name: str | None) -> bool:
                n = (name or "").strip().lower()
                return bool(n) and (n in body_l or n in cap_l)

            stages = clean_stages([s for s in (v.get("timeline_stages") or [])
                                    if isinstance(s, dict) and grounds(s.get("name"))])
            reagents = [r for r in (v.get("reagents_in_figure") or [])
                        if isinstance(r, dict) and grounds(r.get("name"))]
            # CONFIRM-don't-originate: keep only figure reagents whose canonical is in
            # THIS paper's Tier-1 (text) reagent set. Drops markers / reporters / panel
            # labels / assay compounds vision read but text never extracted, and fixes
            # value/unit parse noise. These figure_confirmed items are merge-eligible.
            figure_confirmed = confirm_reagents(v.get("reagents_in_figure") or [], t1_canon)
            raw_stage_n = len(v.get("timeline_stages") or [])
            raw_reag_n = len(v.get("reagents_in_figure") or [])
            fig_records.append({
                "label": label, "file": fp.name, "doi": doi,
                "is_protocol_schematic": bool(v.get("is_protocol_schematic")),
                "timeline_stages": stages, "reagents_in_figure": reagents,
                "figure_confirmed_reagents": figure_confirmed,
                "verbatim_labels": v.get("verbatim_labels") or [],
                "raw_stages": raw_stage_n, "raw_reagents": raw_reag_n,
                "grounded_stages": len(stages), "grounded_reagents": len(reagents),
                "confirmed_reagents": len(figure_confirmed),
            })
            print(f"  [{pmcid}] {label}: schematic={fig_records[-1]['is_protocol_schematic']} "
                  f"stages {len(stages)}/{raw_stage_n} reagents {len(reagents)}/{raw_reag_n} "
                  f"figure-confirmed {len(figure_confirmed)}", flush=True)

        rec = {"pmcid": pmcid, "doi": doi, "model": MODEL,
               "n_flagged": len(flagged), "figures": fig_records}
        (PRED2 / f"{pmcid}.json").write_text(json.dumps(rec, indent=2))
        gs = sum(f.get("grounded_stages", 0) for f in fig_records)
        gr = sum(f.get("grounded_reagents", 0) for f in fig_records)
        rs = sum(f.get("raw_stages", 0) for f in fig_records)
        rr = sum(f.get("raw_reagents", 0) for f in fig_records)
        cf = sum(f.get("confirmed_reagents", 0) for f in fig_records)
        summary.append({"pmcid": pmcid, "n_flagged": len(flagged),
                        "grounded_stages": gs, "raw_stages": rs,
                        "grounded_reagents": gr, "raw_reagents": rr,
                        "confirmed_reagents": cf})
        print(f"[{pmcid}] flagged {len(flagged)} figs | grounded stages {gs}/{rs} "
              f"reagents {gr}/{rr} | figure-confirmed {cf}", flush=True)

    # incremental (subset) run: merge fresh rows into the existing summary so the
    # committed artifact reflects the whole CC-paper set, not just what was re-run.
    out_path = OUT / "vision_summary.json"
    if subset and out_path.exists():
        prior = json.loads(out_path.read_text()).get("rows", [])
        done = {s["pmcid"] for s in summary}
        summary = [s for s in prior if s["pmcid"] not in done] + summary

    g_st = sum(s["grounded_stages"] for s in summary)
    r_st = sum(s["raw_stages"] for s in summary)
    g_rg = sum(s["grounded_reagents"] for s in summary)
    r_rg = sum(s["raw_reagents"] for s in summary)
    cfac = sum(s.get("confirmed_reagents", s.get("culture_factors", 0)) for s in summary)
    (OUT / "vision_summary.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL, "papers": len(summary),
        "grounding": {"stages_grounded": g_st, "stages_raw": r_st,
                      "reagents_grounded": g_rg, "reagents_raw": r_rg,
                      "figure_confirmed_reagents": cfac},
        "rows": summary,
    }, indent=2))
    print(f"\nTier-2 vision: {len(summary)} papers | "
          f"timeline stages grounded {g_st}/{r_st} | reagents grounded {g_rg}/{r_rg} "
          f"| figure-confirmed reagents {cfac}")
    print(f"predictions (local-only): {PRED2} | summary: {OUT}/vision_summary.json")


if __name__ == "__main__":
    main()
