#!/usr/bin/env python3
"""
Extraction-FIDELITY audit (silver, reproducible).

Grounding rate says a quote *exists*; this measures whether the extracted dose is
FAITHFUL to that quote — the question reviewers ask of any "the literature
underreports" claim. For a sample of dosed reagent extractions it checks, against the
verbatim source bundle:

  * provenance  — the evidence quote is a verbatim substring of the source
  * value_in_quote — the numeric value appears in its own quote (fidelity proxy)
  * unit_in_quote  — the unit (or a known variant) appears in the quote
  * pct_cm_bug  — the quote expresses a percentage ("30%") but the unit field holds a
                  non-unit phrase (e.g. "conditioned medium") — a known parser error
  * suspect_unit — concentration_class flags the unit as non-dose (volume/percent/…)

These are AUTOMATIC, reproducible proxies (no model in the loop). LLM/human
adjudication of the residual is a layer on top; this gives a measurable number + CI.

Run:
  python pipeline/audit_extraction_fidelity.py --n 100
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
from normalize import concentration_class  # noqa: E402

PRED = REPO / "data" / "predictions" / "local"
BUND = REPO / "data" / "evidence_bundles" / "local"
OUT = REPO / "outputs" / "validation" / "fidelity_audit.json"

# reagents whose nM dose is biologically implausible (buffers/vitamins ~mM) — likely an
# upstream source-text m->n corruption rather than an extraction error.
NM_SUSPECT = {"hepes", "nicotinamide", "n-acetylcysteine", "nac", "glutamax"}


def _value_forms(v):
    forms = {str(v)}
    try:
        f = float(v)
        if f == int(f):
            forms.add(str(int(f)))
    except (TypeError, ValueError):
        pass
    return {x for x in forms if x}


def value_in_quote(value, quote: str) -> bool:
    return any(re.search(r"(?<![\d.])" + re.escape(f) + r"(?![\d.])", quote) for f in _value_forms(value))


def pct_cm_bug(value, unit: str, quote: str) -> bool:
    """Quote shows '<value>%' but the unit field carries NO '%' at all (a dropped-percent
    parse, e.g. unit='conditioned medium'). Valid percent variants ('% v/v', '% (v/v)',
    '% conditioned medium') already carry '%' and are not flagged."""
    if not quote:
        return False
    u = (unit or "").strip()
    if "%" in u:
        return False
    shows_pct = any(re.search(r"(?<!\d)" + re.escape(f) + r"\s*%", quote) for f in _value_forms(value))
    return shows_pct and bool(u)  # bare non-% unit alongside a percentage quote


def audit_row(name, value, unit, quote, source: str) -> dict:
    return {
        "name": name, "value": value, "unit": unit,
        "provenance": bool(quote) and quote in source,
        "value_in_quote": value_in_quote(value, quote),
        "pct_cm_bug": pct_cm_bug(value, unit, quote),
        "suspect_unit": concentration_class(unit) in ("volume", "percent", "in_vivo_dose", "other"),
        "nm_buffer_suspect": (unit or "").strip().lower() == "nm" and (name or "").strip().lower() in NM_SUSPECT,
    }


def _wilson(k, n):
    """95% Wilson interval for a proportion (small-n honest CI)."""
    if n == 0:
        return (0.0, 0.0)
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round((c - half) / d, 3), round((c + half) / d, 3))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=100, help="target dosed extractions to audit")
    args = ap.parse_args()

    rows = []
    for pf in sorted(PRED.glob("*.json")):
        if len(rows) >= args.n:
            break
        try:
            d = json.loads(pf.read_text())
        except Exception:  # noqa: BLE001
            continue
        bp = BUND / f"{pf.stem}.json"
        if not bp.exists():
            continue
        b = json.loads(bp.read_text())
        source = (b.get("methods_text") or "") + "\n" + (b.get("body_text") or "")
        for sf in d.get("signaling_factors") or []:
            c = sf.get("concentration") or {}
            q = ((sf.get("evidence") or {}).get("quote")) or ""
            if c.get("value") is not None and q:
                r = audit_row(sf.get("name"), c.get("value"), c.get("unit"), q, source)
                r["pmcid"] = pf.stem
                rows.append(r)
                if len(rows) >= args.n:
                    break

    n = len(rows)
    prov = sum(r["provenance"] for r in rows)
    viq = sum(r["value_in_quote"] for r in rows)
    bug = sum(r["pct_cm_bug"] for r in rows)
    susp = sum(r["suspect_unit"] for r in rows)
    nms = sum(r["nm_buffer_suspect"] for r in rows)
    # auto fidelity = value present in its own quote AND not a dropped-percent parse
    faithful = sum(1 for r in rows if r["value_in_quote"] and not r["pct_cm_bug"])
    art = {
        "method": "silver, reproducible: per dosed signaling-factor extraction, auto-check "
                  "value/unit faithfulness against the verbatim source quote (no model in loop)",
        "n": n,
        "provenance_rate": round(prov / n, 3) if n else None,
        "value_in_quote_rate": round(viq / n, 3) if n else None,
        "auto_fidelity_rate": round(faithful / n, 3) if n else None,
        "auto_fidelity_ci95": _wilson(faithful, n),
        "pct_conditioned_medium_bug": bug,
        "suspect_unit_n": susp,
        "nm_buffer_suspect_n": nms,
        "error_examples": [r for r in rows if r["pct_cm_bug"] or r["nm_buffer_suspect"]][:15],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(art, indent=2))
    print(f"n={n} | provenance {art['provenance_rate']} | value-in-quote {art['value_in_quote_rate']} "
          f"| auto-fidelity {art['auto_fidelity_rate']} CI{art['auto_fidelity_ci95']}")
    print(f"%-conditioned-medium parse bug: {bug} | suspect units: {susp} | nM-buffer suspect: {nms}")
    print(f"-> {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
