#!/usr/bin/env python3
"""
Tier 3 — protocol-by-reference: RESOLVE + VERIFY (the safe half of the chain).

Takes the NAMED culture-protocol delegations the detector found ("...cultured as
previously described (Sato et al, 2011)") and resolves each to the cited paper's
PMCID via a FIELDED Europe PMC query, then VERIFIES the hit before trusting it.

Why named-only / why verify so hard: resolving the wrong paper would attribute a
protocol to a source it didn't come from — fabricated provenance, which the whole
project forbids. Numbered superscript refs ("described 11") need fragile
marker->reference-list mapping and are deliberately NOT auto-resolved here.

Verification gate (all required): the cited author surname appears in the hit's
author list, the publication year matches exactly, and the hit has a PMCID.
Unverified resolutions are recorded as such and NOT passed downstream.

Run:  python pipeline/tier3_resolve.py   ->  outputs/tier3/resolved.json
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUNDLES = REPO / "data" / "evidence_bundles" / "local"
OUT = REPO / "outputs" / "tier3"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

sys.path.insert(0, str(REPO / "pipeline"))
from tier3_detect import CULT, DELEG, EXCL, NAMED, SELF  # noqa: E402

# topic terms to disambiguate the citation (organoid domain)
TOPIC = "organoid OR Lgr5 OR stem cell OR differentiation OR epithelial"

# a culture-protocol source's TITLE should be about organoid/epithelial-stem-cell
# culture — this is what rejects same-author/same-year-but-wrong-paper hits
# (e.g. "Koo 2011" resolving to a mammary-gland paper instead of the Lgr5 one).
TITLE_OK = re.compile(
    r"(organoid|enteroid|colonoid|spheroid|\bLgr5\b|crypt|intestin\w+)", re.I)


def named_delegations(b: dict) -> list[dict]:
    m = (b.get("methods_text", "") or "").replace("\xa0", " ")
    out, seen = [], set()
    for mm in DELEG.finditer(m):
        s, e = mm.start(), mm.end()
        near, tight = m[max(0, s - 120):e + 140], m[max(0, s - 70):e + 70]
        if not CULT.search(near) or EXCL.search(tight) or SELF.search(tight):
            continue
        nm = NAMED.search(m[s:e + 90])
        if not nm:
            continue
        key = (nm.group(1), nm.group(2))
        if key in seen:
            continue
        seen.add(key)
        out.append({"author": nm.group(1), "year": nm.group(2),
                    "context": re.sub(r"\s+", " ", m[max(0, s - 40):e + 70]).strip()})
    return out


def epmc_search(query: str, n: int = 5) -> list[dict]:
    url = f"{EPMC}?query={urllib.parse.quote(query)}&format=json&pageSize={n}"
    d = json.load(urllib.request.urlopen(url, timeout=30))
    return d.get("resultList", {}).get("result", [])


def resolve(author: str, year: str) -> dict | None:
    q = f'AUTH:"{author}" AND PUB_YEAR:{year} AND ({TOPIC})'
    for r in epmc_search(q):
        authstr = (r.get("authorString") or "")
        title = r.get("title") or ""
        verified = (author.lower() in authstr.lower()
                    and str(r.get("pubYear")) == str(year)
                    and bool(r.get("pmcid"))
                    and bool(TITLE_OK.search(title)))
        if verified:
            return {
                "cited_pmcid": r.get("pmcid"), "cited_doi": r.get("doi"),
                "cited_title": r.get("title"), "cited_authors": authstr[:60],
                "cited_year": r.get("pubYear"), "cited_journal": r.get("journalTitle"),
                "is_open_access": r.get("isOpenAccess") == "Y",
                "verified": True,
            }
    return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    resolved = []
    for bp in sorted(BUNDLES.glob("*.json")):
        b = json.loads(bp.read_text())
        for d in named_delegations(b):
            r = resolve(d["author"], d["year"])
            rec = {"source_pmcid": b["pmcid"], "source_organoid_type": b.get("organoid_type"),
                   "cited_author": d["author"], "cited_year": d["year"],
                   "context": d["context"]}
            if r:
                rec.update(r)
            else:
                rec.update({"verified": False, "note": "no verified Europe PMC match"})
            resolved.append(rec)
            tag = (f"-> {r['cited_pmcid']} (OA={r['is_open_access']})" if r else "-> UNVERIFIED")
            print(f"  {b['pmcid']} cites {d['author']} {d['year']} {tag}")

    (OUT / "resolved.json").write_text(json.dumps({
        "n": len(resolved),
        "verified": sum(1 for r in resolved if r.get("verified")),
        "fetchable_oa": sum(1 for r in resolved if r.get("is_open_access")),
        "resolved": resolved,
    }, indent=2))
    v = sum(1 for r in resolved if r.get("verified"))
    oa = sum(1 for r in resolved if r.get("is_open_access"))
    print(f"\nTier-3 resolve: {len(resolved)} named delegations | "
          f"{v} verified | {oa} open-access (fetchable for inherited extraction)")


if __name__ == "__main__":
    main()
