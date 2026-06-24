#!/usr/bin/env python3
"""
Render the cookbook-sample records into a real, self-contained recipe page (demo for #178).

The live site has no /protocols/<pmcid> cookbook route yet (404) — this proves our extracted
data IS recipe-grade by rendering it as an actual "materials + numbered steps" page, and
doubles as a reference render for the Frontend engineer. Reads exports/sample/cookbook_sample.json,
writes a single self-contained HTML (no server, no JS deps). Run:
  python pipeline/build_recipe_demo.py  ->  outputs/eval/recipe_demo.html
"""
from __future__ import annotations

import html
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SAMPLE = REPO / "exports" / "sample" / "cookbook_sample.json"
OUT = REPO / "outputs" / "eval" / "recipe_demo.html"


def esc(x) -> str:
    return html.escape(str(x)) if x is not None else ""


def dose(r: dict) -> str:
    v, u = r.get("concentration", r.get("value")), r.get("unit")
    return f"{esc(v)}&nbsp;{esc(u)}" if v not in (None, "") else ('<span class="na">not reported</span>')


def render(rec: dict) -> str:
    c = rec.get("citation") or {}
    sc = rec.get("source_cells") or {}
    src = " ".join(x for x in [sc.get("cell_type"), sc.get("line_name"), f"({sc.get('species')})" if sc.get("species") else ""] if x)
    mats = "".join(
        f"<tr><td>{esc(m.get('name'))}</td><td class='d'>{dose(m)}</td>"
        f"<td>{esc(m.get('role'))}</td><td class='k'>{esc((m.get('kind') or '').replace('_',' '))}</td></tr>"
        for m in (rec.get("materials") or []))
    stages = []
    for i, s in enumerate(rec.get("stages") or [], 1):
        d0, d1 = s.get("start_day"), s.get("end_day")
        days = (f"Day {d0}–{d1}" if d0 is not None and d1 is not None
                else f"Day {d0}+" if d0 is not None else "")
        regs = "".join(f"<li>{esc(r.get('name'))} &mdash; {dose(r)}"
                       f"{(' <em>('+esc(r.get('role'))+')</em>') if r.get('role') else ''}</li>"
                       for r in (s.get("reagents") or []))
        regs = f"<ul class='reg'>{regs}</ul>" if regs else "<p class='na'>no reagents added this stage</p>"
        meta = " &middot; ".join(x for x in [esc(s.get("medium_base")), esc(s.get("culture_vessel"))] if x)
        trans = f"<p class='trans'>→ {esc(s.get('transition'))}</p>" if s.get("transition") else ""
        stages.append(
            f"<li><div class='sh'><span class='sn'>{i}</span><b>{esc(s.get('name'))}</b>"
            f"<span class='day'>{days}</span></div>"
            f"{('<div class=meta>'+meta+'</div>') if meta else ''}{regs}{trans}</li>")
    endpoints = "".join(f"<span class='ep'>{esc(e)}</span>" for e in (rec.get("assay_endpoints") or []))
    gate = "" if rec.get("is_generation_protocol") else (
        "<div class='warn'>⚠ This paper uses the model mainly as an assay, not a generation "
        "protocol — the recipe below is partial.</div>")
    return f"""
<section class="card">
  <div class="hd">
    <span class="type">{esc(rec.get('organoid_type'))}</span>
    <h2>{esc(rec.get('final_organoid') or rec.get('organoid_type'))} protocol</h2>
    <div class="cite">{esc(c.get('first_author'))} {esc(c.get('year'))} &middot; {esc(c.get('journal'))}
      &middot; <a href="https://doi.org/{esc(rec.get('doi'))}">{esc(rec.get('doi'))}</a>
      &middot; <span class="lic">{esc(rec.get('license'))}</span></div>
  </div>
  {gate}
  <div class="chips"><span><b>From</b> {esc(src) or '?'}</span>
    <span><b>To</b> {esc(rec.get('final_organoid'))}</span>
    <span><b>Matrix</b> {esc(rec.get('matrix'))}</span>
    <span><b>Base media</b> {esc(rec.get('base_media'))}</span></div>
  <h3>Materials</h3>
  <table><thead><tr><th>Reagent</th><th>Dose</th><th>Role</th><th>Class</th></tr></thead><tbody>{mats}</tbody></table>
  <h3>Protocol &mdash; {len(rec.get('stages') or [])} stages</h3>
  <ol class="stages">{''.join(stages)}</ol>
  <h3>Endpoints / readouts</h3>
  <div class="eps">{endpoints or '<span class=na>none extracted</span>'}</div>
</section>"""


CSS = """
*{box-sizing:border-box} body{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;
margin:0;background:#f6f7f9;color:#1a1f29} .wrap{max-width:820px;margin:0 auto;padding:28px}
h1{font-size:22px;margin:0 0 4px} .sub{color:#5b6573;margin:0 0 24px}
.card{background:#fff;border:1px solid #e3e7ed;border-radius:12px;padding:24px;margin:0 0 28px;
box-shadow:0 1px 3px rgba(0,0,0,.05)} .hd{border-bottom:1px solid #eef0f3;padding-bottom:14px;margin-bottom:16px}
.type{display:inline-block;background:#e8f0fe;color:#1a56db;font-weight:600;font-size:12px;
text-transform:uppercase;letter-spacing:.04em;padding:3px 9px;border-radius:20px} h2{margin:8px 0 6px;font-size:20px}
.cite{color:#5b6573;font-size:13px} .cite a{color:#1a56db;text-decoration:none} .lic{color:#0a7d33;font-weight:600}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 8px} .chips span{background:#f2f4f7;border-radius:8px;
padding:6px 11px;font-size:13px} .chips b{color:#5b6573;font-weight:600;margin-right:4px}
h3{font-size:14px;text-transform:uppercase;letter-spacing:.04em;color:#5b6573;margin:22px 0 10px}
table{width:100%;border-collapse:collapse;font-size:14px} th{text-align:left;color:#5b6573;font-weight:600;
border-bottom:2px solid #eef0f3;padding:6px 8px} td{border-bottom:1px solid #f2f4f7;padding:6px 8px}
td.d{white-space:nowrap;font-variant-numeric:tabular-nums} td.k{color:#8a94a3;font-size:12px}
.stages{list-style:none;padding:0;margin:0;counter-reset:s} .stages>li{border-left:2px solid #d7deea;
padding:0 0 18px 18px;margin-left:10px;position:relative} .sh{display:flex;align-items:center;gap:10px}
.sn{position:absolute;left:-13px;width:24px;height:24px;border-radius:50%;background:#1a56db;color:#fff;
display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700} .day{margin-left:auto;
color:#8a94a3;font-size:12px;white-space:nowrap} .meta{color:#5b6573;font-size:13px;margin:2px 0 6px}
ul.reg{margin:6px 0;padding-left:18px} ul.reg li{margin:2px 0} .trans{color:#0a7d33;font-size:13px;margin:6px 0 0}
.eps{display:flex;flex-wrap:wrap;gap:6px} .ep{background:#fff4e5;color:#9a5b00;border-radius:6px;padding:4px 9px;font-size:13px}
.na{color:#b0b7c3;font-style:italic} .warn{background:#fff4e5;border:1px solid #f3d9a8;color:#9a5b00;
border-radius:8px;padding:10px 12px;margin:0 0 14px;font-size:13px}
"""


def main() -> int:
    recs = json.loads(SAMPLE.read_text())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(render(r) for r in recs)
    OUT.write_text(
        f"<!doctype html><html><head><meta charset=utf-8><title>Organoid Protocol Atlas — recipe demo</title>"
        f"<style>{CSS}</style></head><body><div class=wrap>"
        f"<h1>Recipe page — rendered from extracted data</h1>"
        f"<p class=sub>Demo of the /protocols/&lt;pmcid&gt; cookbook view (#178), rendered from "
        f"exports/sample/cookbook_sample.json — real tier1 fields + v2 stages[]. {len(recs)} protocols.</p>"
        f"{body}</div></body></html>")
    print(f"-> {OUT.relative_to(REPO)} ({OUT.stat().st_size} bytes, {len(recs)} recipes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
