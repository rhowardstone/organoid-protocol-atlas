#!/usr/bin/env python3
"""
R2: concentration-unit VALIDITY audit. Classifies every public reagent record that
carries a numeric value via normalize.concentration_class and reports how many use a
real culture concentration vs a suspect unit (in-vivo dose / dispensed volume / bare
percent / unrecognized). Motivated by the #39 evidence-fidelity judge, which caught
in-vivo doses (afatinib mg/kg) and volumes mis-extracted as concentrations.

Output (generated, no hand-typed numbers): outputs/validation/unit_audit.json.
The suspect records are a REVIEW-QUEUE signal, not auto-deletes.

Run:  python pipeline/audit_units.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
import normalize as nz  # noqa: E402

REAGENTS = REPO / "exports" / "public" / "reagents.jsonl"
OUT = REPO / "outputs" / "validation" / "unit_audit.json"


def audit(rows):
    withv = [r for r in rows if r.get("value") is not None]
    counts = Counter(nz.concentration_class(r.get("unit")) for r in withv)
    suspect = [{"id": r.get("id"), "name": r.get("name"), "unit": r.get("unit"),
                "value": r.get("value"), "class": nz.concentration_class(r.get("unit")),
                "pmcid": r.get("pmcid")}
               for r in withv if nz.is_suspect_concentration(r.get("unit"))]

    # UCUM coverage: how many concentration-class records map to a UCUM code
    conc_rows = [r for r in withv if nz.concentration_class(r.get("unit")) == "concentration"]
    ucum_mapped = [r for r in conc_rows if nz.ucum_unit(r.get("unit")) is not None]
    ucum_by_canon: dict[str, str] = {}
    for r in conc_rows:
        canon = nz.canon_unit(r.get("unit"))
        if canon:
            ucum = nz.ucum_unit(r.get("unit"))
            ucum_by_canon[canon] = ucum or "(unmapped)"

    return {
        "method": "R2 concentration-unit validity (normalize.concentration_class) over "
                  "public reagents with a numeric value; suspect = in_vivo_dose|volume|"
                  "percent|other (review-queue signal, not auto-delete). "
                  "ucum_unit() maps canonical units to UCUM expressions.",
        "n_with_value": len(withv),
        "class_counts": dict(counts),
        "suspect_total": len(suspect),
        "suspect_rate": round(len(suspect) / len(withv), 4) if withv else 0.0,
        "ucum_coverage": {
            "n_concentration_class": len(conc_rows),
            "n_ucum_mapped": len(ucum_mapped),
            "ucum_rate": round(len(ucum_mapped) / len(conc_rows), 4) if conc_rows else None,
            "canon_to_ucum": ucum_by_canon,
        },
        "suspect": sorted(suspect, key=lambda s: (s["class"], str(s["name"]))),
    }


def main():
    rows = [json.loads(l) for l in REAGENTS.read_text().splitlines() if l.strip()]
    art = audit(rows)
    art["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(art, indent=2))
    print(f"n_with_value={art['n_with_value']} class_counts={art['class_counts']}")
    print(f"suspect={art['suspect_total']} rate={art['suspect_rate']} -> {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
