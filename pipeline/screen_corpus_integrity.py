#!/usr/bin/env python3
"""
Corpus-integrity screen — guard against retracted papers, fabricated/mismatched DOIs,
and (heuristically) paper-mill / AI-generated junk.

The Atlas already has a strong provenance moat: it ingests ONLY publisher-deposited
PMC Open Access JATS — the version of record, not web snapshots (archive.today) or
un-vetted preprints. This adds the missing active checks, cross-referencing each
paper's DOI against Crossref:

  * resolves    — the DOI exists at Crossref (catches fabricated DOIs)
  * title_match — stored title ~ Crossref title (catches mismatched/spoofed DOIs)
  * retracted   — Crossref 'update-to' carries a retraction (or the work type is a
                  retraction) — a retracted protocol must never feed standardization stats
  * tortured    — Problematic-Paper-Screener-style "tortured phrase" heuristic on the
                  title (a weak paper-mill signal; flag-for-review only, never auto-drop)

Retracted / unresolved / mismatched papers are FLAGGED (quarantine + review), not
silently deleted. Pure helpers (title_similar, is_retracted, has_tortured_phrase) are
unit-tested offline; the Crossref calls are a runtime concern.

Run:
  python pipeline/screen_corpus_integrity.py --n 80          # sample
  python pipeline/screen_corpus_integrity.py --all           # whole corpus
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "data" / "corpus" / "corpus.tsv"
OUT = REPO / "outputs" / "validation" / "integrity_report.json"
CROSSREF = "https://api.crossref.org/works/"
UA = "organoid-protocol-atlas/integrity (mailto:atlas@example.org)"

# "tortured phrases" — paper-mill paraphrase tells (Cabanac et al.). A tiny seed list;
# a hit is a REVIEW flag, never an auto-reject.
TORTURED_PHRASES = {
    "bosom peril": "breast cancer", "counterfeit consciousness": "artificial intelligence",
    "leukemia disease": "leukemia", "irregular esteem": "random value",
    "gigantic information": "big data", "engine learning": "machine learning",
}


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (t or "").lower()).strip()


def title_similar(a: str, b: str, thresh: float = 0.6) -> bool:
    """Token Jaccard over normalized titles — robust to punctuation/casing. True if the
    two titles plausibly refer to the same work."""
    ta, tb = set(_norm_title(a).split()), set(_norm_title(b).split())
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= thresh


def is_retracted(msg: dict) -> bool:
    """A Crossref work record indicates retraction of THIS work."""
    if (msg.get("type") or "").lower() in ("retraction", "retracted-article"):
        return True
    for u in msg.get("update-to", []) or []:
        if "retract" in (u.get("type") or "").lower():
            return True
    # 'updated-by' a retraction notice
    for u in msg.get("relation", {}).get("is-retracted-by", []) or []:
        return True
    return False


def has_tortured_phrase(text: str) -> bool:
    low = (text or "").lower()
    return any(p in low for p in TORTURED_PHRASES)


def crossref(doi: str) -> dict | None:
    url = CROSSREF + urllib.parse.quote(doi)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r).get("message")
    except Exception:  # noqa: BLE001  (404 / network -> treat as unresolved)
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.2)
    args = ap.parse_args()

    import csv
    rows = list(csv.DictReader(open(CORPUS), delimiter="\t"))
    rows = [r for r in rows if (r.get("doi") or "").strip()]
    if not args.all:
        rows = rows[: args.n]

    flagged = {"retracted": [], "unresolved": [], "title_mismatch": [], "tortured": []}
    checked = 0
    for r in rows:
        doi, title, pmcid = r["doi"].strip(), r.get("title", ""), r.get("pmcid", "")
        msg = crossref(doi)
        checked += 1
        if msg is None:
            flagged["unresolved"].append({"pmcid": pmcid, "doi": doi})
        else:
            if is_retracted(msg):
                flagged["retracted"].append({"pmcid": pmcid, "doi": doi, "title": title})
            cr_title = (msg.get("title") or [""])[0]
            if title and cr_title and not title_similar(title, cr_title):
                flagged["title_mismatch"].append({"pmcid": pmcid, "doi": doi,
                                                  "stored": title[:80], "crossref": cr_title[:80]})
        if has_tortured_phrase(title):
            flagged["tortured"].append({"pmcid": pmcid, "doi": doi, "title": title[:100]})
        time.sleep(args.sleep)

    report = {
        "method": "Crossref cross-reference of corpus DOIs: retraction, DOI-resolution, "
                  "title-match; tortured-phrase heuristic on title. Flag-and-quarantine, "
                  "never silent-delete. Provenance moat: PMC OA JATS (version of record) only.",
        "checked": checked,
        "n_retracted": len(flagged["retracted"]),
        "n_unresolved_doi": len(flagged["unresolved"]),
        "n_title_mismatch": len(flagged["title_mismatch"]),
        "n_tortured_phrase": len(flagged["tortured"]),
        "clean_rate": round(1 - sum(len(v) for v in flagged.values()) / checked, 4) if checked else None,
        "flagged": flagged,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2))
    print(f"checked {checked} | retracted {report['n_retracted']} | unresolved-DOI "
          f"{report['n_unresolved_doi']} | title-mismatch {report['n_title_mismatch']} | "
          f"tortured {report['n_tortured_phrase']} | clean {report['clean_rate']}")
    print(f"-> {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
