#!/usr/bin/env python3
"""
Reagent name normalization (entity canonicalization).

The Tier-1 extractions carry the surface form a paper used (R-Spondin1, R-spondin,
RSPO1, bFGF, FGF2, Y-27632, Y27632, ...). For comparison/consensus we need one
canonical entity per reagent. This is the normalization the prototype anticipated
(eval's NAME_CANON stub) and what the JD calls "entity normalization".

Two layers:
  1. A curated CANON map of common organoid reagents (handles semantic synonyms the
     crude key misses, e.g. bFGF == FGF2, RSPO1 == R-spondin1).
  2. Corpus-aware fallback: surface variants that share a normalized key (case /
     spacing / punctuation) collapse to their most frequent surface form.

Deterministic, no model. `ontology_id` (ChEBI/PR) enrichment is a later step.
"""

from __future__ import annotations

import collections
import re


def norm_key(name: str | None) -> str:
    """Aggressive match key: lowercase, strip all non-alphanumerics."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# crude-key -> canonical display name. Keys are norm_key() outputs.
CANON = {
    # R-spondins (keep distinct family members; collapse surface + RSPO aliases)
    "rspondin1": "R-spondin1", "rspondin": "R-spondin1", "rspo1": "R-spondin1",
    "rspondin2": "R-spondin2", "rspo2": "R-spondin2",
    "rspondin3": "R-spondin3", "rspo3": "R-spondin3",
    # ROCK inhibitor
    "y27632": "Y-27632", "rockinhibitor": "Y-27632", "rockinhibitory27632": "Y-27632",
    # TGF-β / Activin / SMAD
    "activina": "Activin A", "activin": "Activin A",
    "sb431542": "SB431542", "a8301": "A83-01",
    # Wnt / GSK3
    "wnt3a": "Wnt3a", "chir99021": "CHIR99021", "chir": "CHIR99021",
    # FGFs (bFGF == FGF2); include spelled-out forms (papers vary)
    "bfgf": "FGF2", "fgf2": "FGF2", "fgfbasic": "FGF2", "basicfgf": "FGF2",
    "basicfibroblastgrowthfactor": "FGF2", "fibroblastgrowthfactor2": "FGF2",
    "fgf4": "FGF4", "fgf7": "FGF7", "fgf9": "FGF9", "fgf10": "FGF10",
    "fibroblastgrowthfactor4": "FGF4", "fibroblastgrowthfactor7": "FGF7",
    "fibroblastgrowthfactor9": "FGF9", "fibroblastgrowthfactor10": "FGF10",
    # BMP axis (incl. spelled-out forms)
    "bmp4": "BMP4", "bmp7": "BMP7", "noggin": "Noggin",
    "bonemorphogeneticprotein4": "BMP4", "bonemorphogeneticprotein7": "BMP7",
    "epidermalgrowthfactor": "EGF", "hepatocytegrowthfactor": "HGF",
    "vascularendothelialgrowthfactor": "VEGF",
    "dorsomorphin": "Dorsomorphin", "ldn193189": "LDN-193189",
    # growth factors / neurotrophins
    "egf": "EGF", "hgf": "HGF", "bdnf": "BDNF", "nt3": "NT-3", "ntf3": "NT-3",
    "gdnf": "GDNF", "vegf": "VEGF", "igf1": "IGF-1", "tgfb1": "TGF-β1",
    # small molecules / supplements that recur as signaling
    "gastrin": "Gastrin", "nicotinamide": "Nicotinamide",
    "nacetylcysteine": "N-acetylcysteine", "nac": "N-acetylcysteine",
    "retinoicacid": "Retinoic acid", "ra": "Retinoic acid",
    "alltransretinoicacid": "Retinoic acid", "atra": "Retinoic acid",
    "dexamethasone": "Dexamethasone", "forskolin": "Forskolin",
    "pge2": "PGE2", "prostaglandine2": "PGE2", "prostaglandinee2": "PGE2",
    "prostaglandine2pge2": "PGE2", "heparin": "Heparin",
    "sag": "SAG", "purmorphamine": "Purmorphamine", "dapt": "DAPT", "shh": "SHH",
}


# Abbreviations that appear in figure schematics (Tier-2 vision) but rarely in prose.
# These extend CANON for the vision gate only (kept separate to avoid widening the
# text path, where the full names are already used).
FIG_ABBREV = {
    "acta": "Activin A", "nog": "Noggin", "sb": "SB431542",
    "fsk": "Forskolin", "ldn": "LDN-193189", "dm": "Dorsomorphin",
}


def canonical_or_none(name: str | None) -> str | None:
    """Return the canonical reagent name iff `name` is a known culture factor.

    The gate for Tier-2 vision: figure OCR surfaces panel labels, reporters
    (mCherry, shNT) and assay compounds (cisplatin, lucifer yellow) that pass a
    crude substring-grounding check. Only names resolving to a curated culture
    factor (CANON or a known figure abbreviation) are kept as protocol reagents.
    """
    k = norm_key(name)
    if not k:
        return None
    return CANON.get(k) or FIG_ABBREV.get(k)


def build_canon_map(names) -> dict:
    """raw name -> canonical name. CANON first; else most-frequent surface form per key."""
    by_key = collections.defaultdict(collections.Counter)
    for n in names:
        if n:
            by_key[norm_key(n)][n.strip()] += 1
    out = {}
    for n in names:
        if not n:
            continue
        k = norm_key(n)
        if k in CANON:
            out[n] = CANON[k]
        else:
            out[n] = by_key[k].most_common(1)[0][0]  # collapse case/space variants
    return out


if __name__ == "__main__":
    import json, glob
    names = []
    for pf in glob.glob("data/predictions/local/*.json"):
        p = json.load(open(pf))
        names += [r.get("name") for r in (p.get("signaling_factors") or [])]
    m = build_canon_map(names)
    raw = len({n for n in names if n})
    canon = len(set(m.values()))
    print(f"raw distinct: {raw} -> canonical distinct: {canon}")
