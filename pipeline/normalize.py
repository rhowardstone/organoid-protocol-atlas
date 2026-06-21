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
    "rhbmp4": "BMP4", "rhbmp7": "BMP7", "rhnoggin": "Noggin", "rhegf": "EGF",
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


def canon_unit(u: str | None) -> str | None:
    """Canonical concentration unit. Unifies the two micro signs (µ U+00B5 / μ
    U+03BC), the "ng ml -1" / "ng ml−1" / "ng/ml" notations, and molar forms, so
    doses that are really the same unit compare and range correctly.
    """
    if not u:
        return None
    s = u.strip().replace("μ", "u").replace("µ", "u").replace("−", "-")
    low = s.lower()
    # mass per volume: support /mL, /uL, /L (e.g. "ng/uL", "ng ml -1")
    m = re.match(r"^(ng|ug|mg|pg|g)\s*[/·.]?\s*(ml|ul|l)(?:\s*[-–]?\s*1)?$", low)
    if m:
        num = {"ng": "ng", "ug": "ug", "mg": "mg", "pg": "pg", "g": "g"}[m.group(1)]
        den = {"ml": "mL", "ul": "uL", "l": "L"}[m.group(2)]
        return f"{num}/{den}"
    # activity per volume (enzymes/hormones): U/mL, mU/mL, IU/mL
    a = re.match(r"^(u|mu|iu|kiu)\s*[/·.]?\s*ml(?:\s*[-–]?\s*1)?$", low)
    if a:
        return {"u": "U/mL", "mu": "mU/mL", "iu": "IU/mL", "kiu": "kIU/mL"}[a.group(1)]
    molar = {"um": "uM", "umol/l": "uM", "nm": "nM", "nmol/l": "nM",
             "mm": "mM", "mmol/l": "mM", "m": "M", "mol/l": "M", "pm": "pM", "fm": "fM"}
    low_ns = low.replace(" ", "")  # tolerate spaced molar like "n m" -> nM
    if low_ns in molar:
        return molar[low_ns]
    return s  # percent variants etc. kept verbatim (carry meaning, e.g. % v/v)


# Concentration-unit VALIDITY classes (R2 — validity filter motivated by the #39
# evidence-fidelity judge, which caught in-vivo doses and volumes mis-extracted as
# culture concentrations). Separates real culture concentrations from:
#   in_vivo_dose : mass-per-bodyweight dosing (mg/kg, mg kg-1 day-1) — animal, not culture
#   volume       : a bare dispensed volume (50 µl) — an amount pipetted, not a concentration
#   percent      : bare % — ambiguous (v/v, conditioned-medium fraction, or a stray statistic)
# These three are SUSPECT as reagent concentrations and should be flagged for review.
_INVIVO_RE = re.compile(r"(?:^|[^a-z])(?:p|n|u|µ|μ|m)?g\s*[ ·/-]*\s*kg(?:\b|\s*-?\s*1)|/kg|\bmpk\b", re.I)
_VOLUME_RE = re.compile(r"^(?:p|n|u|m)?l$")  # pl/nl/ul/ml/l (after micro-sign fold), bare volume

CONC_OK = {"M", "mM", "uM", "nM", "pM", "fM",
           "ng/mL", "ug/mL", "mg/mL", "pg/mL", "g/mL", "ng/uL", "ug/uL", "pg/uL", "mg/uL",
           "ng/L", "ug/L", "mg/L", "g/L",
           "U/mL", "mU/mL", "IU/mL", "kIU/mL"}


def concentration_class(unit: str | None) -> str:
    """Classify a reagent's concentration unit for VALIDITY (not just canonicalization):
    'concentration' (a real culture conc), 'in_vivo_dose', 'volume', 'percent',
    'missing', or 'other'. The first non-'concentration'/'missing' classes are suspect."""
    if not unit or not str(unit).strip():
        return "missing"
    s = str(unit).strip()
    if _INVIVO_RE.search(s):
        return "in_vivo_dose"
    base = s.replace("μ", "u").replace("µ", "u").replace("−", "-").lower()
    if _VOLUME_RE.match(base):
        return "volume"
    if "%" in s:
        return "percent"
    if (canon_unit(s) or s) in CONC_OK:
        return "concentration"
    return "other"


def is_suspect_concentration(unit: str | None) -> bool:
    """True if the unit is not a valid culture concentration (in-vivo dose / volume /
    bare percent / unrecognized) — a flag for the review queue, not an auto-delete."""
    return concentration_class(unit) in ("in_vivo_dose", "volume", "percent", "other")


# UCUM (Unified Code for Units of Measure) mapping.
# Maps canonical units (output of canon_unit) to UCUM expression strings.
# Source: https://ucum.org/ucum (ANSI/HL7 standard)
# Only units that appear in biological culture protocol data are listed.
# Units not listed here return None from ucum_unit().
_CANON_TO_UCUM: dict[str, str] = {
    # Mass per volume
    "ng/mL": "ng.mL-1",
    "ug/mL": "ug.mL-1",
    "mg/mL": "mg.mL-1",
    "pg/mL": "pg.mL-1",
    "g/mL":  "g.mL-1",
    "ng/uL": "ng.uL-1",
    "ug/uL": "ug.uL-1",
    "pg/uL": "pg.uL-1",
    "mg/uL": "mg.uL-1",
    "ng/L":  "ng.L-1",
    "ug/L":  "ug.L-1",
    "mg/L":  "mg.L-1",
    "g/L":   "g.L-1",
    # Molar concentration
    "M":     "mol.L-1",
    "mM":    "mmol.L-1",
    "uM":    "umol.L-1",
    "nM":    "nmol.L-1",
    "pM":    "pmol.L-1",
    "fM":    "fmol.L-1",
    # Enzyme activity per volume
    "U/mL":    "U.mL-1",
    "mU/mL":   "mU.mL-1",
    "IU/mL":   "[IU].mL-1",
    "kIU/mL":  "k[IU].mL-1",
}


def ucum_unit(u: str | None) -> str | None:
    """Return the UCUM expression for a concentration unit, or None if not mappable.

    Accepts any form accepted by canon_unit() (raw extracted strings, Unicode
    micro signs, slash/dot/space notations). Returns None for percent, in-vivo
    doses, volumes, and unrecognised units — callers should check
    concentration_class() first when those categories matter.

    Examples:
        ucum_unit("ng/ml")   -> "ng.mL-1"
        ucum_unit("nM")      -> "nmol.L-1"
        ucum_unit("µg/mL")   -> "ug.mL-1"
        ucum_unit("mg/kg")   -> None   (in-vivo dose, not a culture concentration)
        ucum_unit(None)      -> None
    """
    c = canon_unit(u)
    if c is None:
        return None
    return _CANON_TO_UCUM.get(c)


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
