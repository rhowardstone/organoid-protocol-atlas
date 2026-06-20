#!/usr/bin/env python3
"""
Tier 3 — protocol-by-reference: DETECTION (the router signal).

Some papers don't print their full culture protocol; they delegate it to a prior
paper ("differentiation ... was carried out as previously described [11]",
"Intestinal organoids were cultured as previously described (Sato et al., 2011)").
For those, the grounded protocol lives in the CITED paper, not this one.

This module flags exactly those papers — and only those — so a downstream
fetch+extract step (reusing the existing Tier-0/Tier-1 on the cited paper) runs on
a small, justified subset (the ≤20% Tier-3 cap is defined by this set, not guessed).

Discipline:
- EXTERNAL citations only. A self-reference ("as described in step 13",
  "Extended Experimental Procedures", "section above") points to the paper's own
  text, not another paper — excluded.
- CULTURE-protocol context only. Delegations about sequencing / immunostaining /
  mouse strains / imaging are not culture protocols — excluded.
- The delegation must sit next to a resolvable citation marker: a numbered ref
  (superscript/bracket) or a named "(Author et al., year)".

Run:  python pipeline/tier3_detect.py   ->  outputs/tier3/candidates.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUNDLES = REPO / "data" / "evidence_bundles" / "local"
OUT = REPO / "outputs" / "tier3"

DELEG = re.compile(
    r"(as (?:previously |prev\.? )?described|previously described|"
    r"based on (?:a )?(?:previously described|the) (?:protocol|method)|"
    r"modif\w+ (?:of|the) [^.]{0,40}?(?:protocol|method)|adapted from)", re.I)

# culture-protocol context (must be near the phrase)
CULT = re.compile(
    r"(different\w+|cultur\w+|organoid|expand\w+|passag\w+|maintain\w+|"
    r"embryoid|definitive endoderm|spheroid|staged|reprogram\w+)", re.I)

# non-culture contexts (assay/animal/seq) — exclude
EXCL = re.compile(
    r"(sequenc\w+|immuno\w+|stain\w+|antibod\w+|qPCR|RNA-?seq|FACS|flow cytom\w+|"
    r"histolog\w+|imaging|microscop\w+|\bmice\b|\bmouse\b|western|ELISA|"
    r"genotyp\w+|library prep|reprogram\w+ using)", re.I)

# self-reference markers — exclude (points to the paper's own steps/sections)
SELF = re.compile(
    r"(step\s*\d|steps\s*\d|procedure step|section (?:above|below)|"
    r"Extended (?:Experimental|Data)|as described (?:above|below)|"
    r"in ref\.?\s*\d|previous section|earlier in)", re.I)

# resolvable external citation marker near the phrase
NAMED = re.compile(r"\(([A-Z][A-Za-z\-]+)\s+et\s+al\.?\s*,?\s*(\d{4})[a-z]?\s*\)")
NUMREF = re.compile(r"described[^.]{0,40}?\b\d{1,3}\b")


def detect_one(b: dict) -> dict | None:
    # normalize non-breaking spaces (common in PMC XML) so the citation/whitespace
    # patterns match reliably ("Sato et\xa0al , 2011 )").
    m = (b.get("methods_text", "") or "").replace("\xa0", " ")
    for mm in DELEG.finditer(m):
        s, e = mm.start(), mm.end()
        near = m[max(0, s - 120):e + 140]
        tight = m[max(0, s - 70):e + 70]
        if not CULT.search(near) or EXCL.search(tight) or SELF.search(tight):
            continue
        named = NAMED.search(m[s:e + 90])
        numbered = bool(NUMREF.search(m[max(0, s - 10):e + 50]))
        if not (named or numbered):
            continue
        cite = None
        if named:
            cite = {"kind": "named", "author": named.group(1), "year": named.group(2)}
        elif numbered:
            cite = {"kind": "numbered"}
        return {
            "pmcid": b["pmcid"], "organoid_type": b.get("organoid_type"),
            "doi": b.get("doi"),
            "delegation": tight.replace("\n", " ").strip(),
            "cited": cite,
        }
    return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cands = []
    total = 0
    for bp in sorted(BUNDLES.glob("*.json")):
        total += 1
        b = json.loads(bp.read_text())
        r = detect_one(b)
        if r:
            cands.append(r)
    cap = round(0.20 * total)
    (OUT / "candidates.json").write_text(json.dumps({
        "corpus": total, "tier3_cap_20pct": cap,
        "n_candidates": len(cands), "candidates": cands,
    }, indent=2))
    print(f"Tier-3 candidates: {len(cands)}/{total} (20% cap = {cap})")
    for c in cands:
        cited = c["cited"]
        tag = f"{cited.get('author')} {cited.get('year')}" if cited["kind"] == "named" else "[numbered ref]"
        print(f"  {c['pmcid']} ({c['organoid_type']}) -> {tag}")
    if len(cands) > cap:
        print(f"  NOTE: {len(cands)} candidates exceed the {cap}-paper cap; "
              f"prioritize named/resolvable citations first.")


if __name__ == "__main__":
    main()
