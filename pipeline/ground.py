#!/usr/bin/env python3
"""
S1 — Live entity grounding to Biolink CURIEs via the SRI services + Cellosaurus.

Free-text entity names from extraction (reagents, species, cell types, tissue,
cell lines) are resolved to ontology CURIEs using the public NCATS Translator SRI
services and Cellosaurus, then disk-cached so tests run offline:

  - SRI Name Resolver   name-resolution-sri.renci.org/lookup     (text  -> ranked CURIEs)
  - SRI Node Normalizer nodenormalization-sri.renci.org/...      (CURIE -> Biolink category)
  - Cellosaurus         api.cellosaurus.org                       (cell line -> CVCL_ RRID)

Honesty contract (sprint rules #2/#3): grounding_status is one of
  resolved      — a real service hit whose label/synonym MATCHES the query (cached);
                  accepted as a real CURIE.
  needs_review  — a real hit came back but its label/synonyms do NOT match the query
                  (near-miss / wrong entity, e.g. PGE2 -> 15-Keto-PGE2, TGF-beta1 -> a pig
                  TGF-beta receptor); kept as a flagged CANDIDATE (flags:[label_mismatch]),
                  NEVER an accepted CURIE — excluded from downstream KGX/TRAPI.
  not_found     — the service was called and returned nothing acceptable (NEVER guessed);
  not_attempted — offline with no cached response (no call made).
A CURIE is never invented, and a real service hit is necessary but NOT sufficient: only a
verified label/synonym match counts as `resolved` (accepted). Coverage separates
accepted_resolved from candidates_needs_review. Every `resolved` is cached on disk.

Run:
    python pipeline/ground.py --reagents CHIR99021 EGF Noggin   # ad-hoc
    python pipeline/ground.py                                   # ground the canonical corpus set
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "data" / "grounding" / "cache"
OUT = REPO / "outputs" / "grounding"
NAME_RESOLVER = "https://name-resolution-sri.renci.org/lookup"
NODE_NORM = "https://nodenormalization-sri.renci.org/get_normalized_nodes"
CELLOSAURUS = "https://api.cellosaurus.org/search/cell-line"

# Honest type-checking. We let the Name Resolver RANK (no forced biolink_type for
# reagents) and accept the top hit whose CURIE prefix is acceptable for the kind.
# Reality from the live service: small molecules -> CHEBI; protein growth factors ->
# NCBIGene (the gene/protein conflation clique leader, standard in Translator), NOT
# PR. We record whatever the service returns; we never coerce the type.
KIND_BIOLINK = {
    "reagent": [None],                       # unfiltered — trust ranking
    "species": ["biolink:OrganismTaxon"],    # NCBITaxon
    "tissue": ["biolink:AnatomicalEntity"],  # UBERON
    "cell_type": ["biolink:Cell"],           # CL
}
KIND_PREFIXES = {
    "reagent": ("CHEBI", "PUBCHEM.COMPOUND", "UNII", "DRUGBANK", "MESH",
                "PR", "UniProtKB", "NCBIGene", "ENSEMBL"),
    "species": ("NCBITaxon",),
    "tissue": ("UBERON",),
    "cell_type": ("CL",),
}


# Curated small-molecule reagents (norm-keys). Reagent abbreviations collide with
# gene symbols on the Name Resolver (SAG -> S-antigen gene; PGE2 -> a random locus),
# so for known small molecules we constrain the lookup to chemicals (CHEBI) instead
# of trusting the unfiltered top hit. Everything else (protein growth factors) is
# resolved unfiltered and honestly lands on its gene/protein clique (NCBIGene).
SMALL_MOLECULES = {
    "chir99021", "y27632", "sb431542", "sb202190", "a8301", "forskolin",
    "retinoicacid", "dapt", "dorsomorphin", "ldn193189", "purmorphamine", "sag",
    "pge2", "heparin", "blebbistatin", "iwp2", "nicotinamide", "nacetylcysteine",
    "dexamethasone", "gastrin", "su5402", "tgfbi", "valproicacid", "thiazovivin",
}

# Curated query ALIASES: normalized free-text -> canonical query string, for common
# typos / missing-space / hyphen / descriptor-prefix variants that SRI misses. The
# CURIE is STILL resolved live by name_lookup + the _verify gate against the aliased
# string (never hardcoded), so this fixes recall WITHOUT fabricating CURIEs. Each
# entry was confirmed to resolve to the correct chemical (see tests):
#   ActivinA->CHEBI:81351  CHIR99201(typo)->CHEBI:91091  FSK->CHEBI:93891(forskolin)
#   "ROCK inhibitor Y-27632"->CHEBI:75393  A8301->CHEBI:233322  SANT-1->PUBCHEM:6878030
#   SB431542->CHEBI:91108  IWP2->CHEBI:125649  PGE2->CHEBI:606564(prostaglandin E2)
# Excluded on purpose: gene/protein family terms (TGF-beta, BMP4, sonic hedgehog)
# resolve to species-ambiguous non-human cliques -> they MUST stay needs_review/
# not_found for human review, not be force-aliased (the PR #9 lesson).
ALIASES = {
    "activina": "Activin A",
    "chir99201": "CHIR99021",
    "fsk": "forskolin",
    "rockinhibitory27632": "Y-27632",
    "a8301": "A 83-01",
    "sant1": "SANT-1",
    "sb431542": "SB 431542",
    "iwp2": "IWP-2",
    "pge2": "prostaglandin E2",
}

# Cell-line name normalization: free-text variant -> canonical Cellosaurus query name.
# These are typographic variants (hyphen omitted, space added, etc.) of the SAME line —
# not aliases to a different line. Each entry confirmed against Cellosaurus:
#   WTC11 -> WTC-11 (Conklin lab iPSC; expected CVCL_Y803 — hyphen absent in some papers).
CELL_LINE_ALIASES: dict[str, str] = {
    "WTC11": "WTC-11",
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_") or "_"


def _get_json(url: str, timeout: int = 30, retries: int = 3):
    req = urllib.request.Request(url, headers={"accept": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception:  # noqa: BLE001 — transient SRI timeouts; retry, re-raise on last
            if attempt == retries - 1:
                raise


def _cached(kind: str, key: str, fetch, offline: bool):
    """Return (data, made_call). Reads disk cache first; only calls `fetch` if online."""
    cp = CACHE / kind / f"{_slug(key)}.json"
    if cp.exists():
        return json.loads(cp.read_text()), False
    if offline:
        return None, False
    data = fetch()
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return data, True


def name_lookup(name: str, biolink_type: str | None = None, limit: int = 20,
                offline: bool = False):
    key = f"{name}__{biolink_type or 'any'}"
    qs = {"string": name, "autocomplete": "false", "limit": limit}
    if biolink_type:
        qs["biolink_type"] = biolink_type
    data, _ = _cached("name", key, lambda: _get_json(f"{NAME_RESOLVER}?{urllib.parse.urlencode(qs)}"),
                      offline)
    return data


def node_normalize(curie: str, offline: bool = False):
    qs = {"curie": curie, "conflate": "true"}
    data, _ = _cached("norm", curie,
                      lambda: _get_json(f"{NODE_NORM}?{urllib.parse.urlencode(qs)}"), offline)
    return data


def _category(curie: str, offline: bool) -> str | None:
    norm = node_normalize(curie, offline=offline)
    node = (norm or {}).get(curie) or {}
    cats = node.get("type") or []
    return cats[0] if cats else None


_GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "κ": "kappa",
          "λ": "lambda", "μ": "u", "ω": "omega"}


def _norm(s: str | None) -> str:
    s = (s or "").lower()
    for g, r in _GREEK.items():
        s = s.replace(g, r)
    return re.sub(r"[^a-z0-9]", "", s)


def _verify(query: str, hit: dict) -> bool:
    """A resolution is ACCEPTED only if the query matches the entity's label or one
    of its synonyms (normalized). A real service hit is necessary but NOT sufficient:
    this rejects near-misses (PGE2->15-keto-PGE2) and wrong entities (TGF-β1->pig
    TGF-beta receptor) so they never count as accepted `resolved` CURIEs."""
    q = _norm(query)
    if not q:
        return False
    cands = {_norm(hit.get("label"))}
    cands.update(_norm(s) for s in (hit.get("synonyms") or []))
    return q in cands


def ground_entity(name: str, kind: str = "reagent", offline: bool = False) -> dict:
    """Resolve one free-text entity to a Biolink CURIE. Honest 3-state status."""
    rec = {"query": name, "kind": kind, "grounding_status": "not_attempted",
           "curie": None, "label": None, "biolink_category": None, "source": None,
           "flags": []}
    if not name:
        return rec
    # Curated alias: fix common typo/spacing/descriptor variants before lookup. The
    # aliased string is what we look up AND verify against; the original stays in
    # rec["query"] for provenance. CURIE still comes from SRI + _verify (no fabrication).
    lookup = name
    akey = re.sub(r"[^a-z0-9]", "", name.lower())
    if kind == "reagent" and akey in ALIASES:
        lookup = ALIASES[akey]
        rec["flags"].append(f"alias:{lookup}")
        akey = re.sub(r"[^a-z0-9]", "", lookup.lower())
    prefixes = KIND_PREFIXES.get(kind, ())
    types = KIND_BIOLINK.get(kind, [None])
    if kind == "reagent" and akey in SMALL_MOLECULES:
        # known small molecule: constrain to chemicals so abbreviations don't collide
        # with gene symbols (SAG/PGE2). Accept only chemical CURIEs.
        types = ["biolink:ChemicalEntity"]
        prefixes = ("CHEBI", "PUBCHEM.COMPOUND", "UNII", "DRUGBANK", "MESH")
    called = False
    candidate = None   # first prefix-acceptable hit that FAILED label/synonym verify
    for bt in types:
        hits = name_lookup(lookup, biolink_type=bt, offline=offline)
        if hits is None:
            continue              # offline + uncached for this type
        called = True
        for h in hits:
            curie = h.get("curie")
            if not curie or (prefixes and curie.split(":")[0] not in prefixes):
                continue
            if _verify(lookup, h):  # query matches label/synonym -> ACCEPT
                rec.update(grounding_status="resolved", curie=curie,
                           label=h.get("label"), source="sri-name-resolver",
                           biolink_category=_category(curie, offline) or
                           (h.get("types") or [None])[0])
                return rec
            if candidate is None:   # remember the best near-miss, do not accept it
                candidate = (curie, h.get("label"), (h.get("types") or [None])[0])
    if candidate:
        # a real hit came back but its label/synonyms don't match the query -> a
        # candidate for human review, NEVER an accepted CURIE (won't feed KGX as fact).
        rec.update(grounding_status="needs_review", curie=candidate[0],
                   label=candidate[1], biolink_category=candidate[2],
                   source="sri-name-resolver", flags=["label_mismatch"])
        return rec
    rec["grounding_status"] = "not_found" if called else "not_attempted"
    return rec


def ground_cell_line(name: str, offline: bool = False) -> dict:
    """Resolve a cell-line name to a Cellosaurus CVCL_ accession (the RRID)."""
    rec = {"query": name, "kind": "cell_line", "grounding_status": "not_attempted",
           "curie": None, "label": None, "biolink_category": "biolink:CellLine",
           "source": "cellosaurus"}
    if not name:
        return rec
    # Normalize to canonical Cellosaurus name before lookup (SOLR tokenizes hyphens in
    # id: queries, so "WTC-11" → empty results; WTC11 normalizes to the searchable form).
    lookup = CELL_LINE_ALIASES.get(name, name)
    # General search avoids SOLR id: tokenization issues with hyphens/spaces.
    qs = {"q": f'"{lookup}"', "format": "json", "rows": 5, "fields": "id,ac,sy"}
    data, _ = _cached("cellosaurus", lookup,
                      lambda: _get_json(f"{CELLOSAURUS}?{urllib.parse.urlencode(qs)}"), offline)
    if data is None:
        return rec
    lines = (((data or {}).get("Cellosaurus") or {}).get("cell-line-list")) or []
    for cl in lines:
        names = {n.get("value", "").lower() for n in (cl.get("name-list") or [])}
        # Accept if EITHER the original query name OR the normalized alias name matches.
        if name.lower() in names or lookup.lower() in names:
            acc = next((a.get("value") for a in (cl.get("accession-list") or [])
                        if a.get("type") == "primary"), None)
            if acc:
                rec.update(grounding_status="resolved", curie=f"Cellosaurus:{acc}",
                           label=lookup)
                return rec
    rec["grounding_status"] = "not_found"
    return rec


def _canonical_reagents() -> list[str]:
    sys.path.insert(0, str(REPO / "pipeline"))
    from normalize import CANON  # noqa: E402
    return sorted(set(CANON.values()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reagents", nargs="*", help="ad-hoc reagent names to ground")
    ap.add_argument("--offline", action="store_true", help="cache-only (no network)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    reagents = args.reagents or _canonical_reagents()
    records = [ground_entity(r, "reagent", args.offline) for r in reagents]
    records += [ground_entity(s, "species", args.offline)
                for s in ["Homo sapiens", "Mus musculus"]]
    # organoid tissue -> UBERON, source cell type -> CL
    records += [ground_entity(t, "tissue", args.offline) for t in
                ["intestine", "brain", "kidney", "liver", "lung", "retina", "stomach", "pancreas"]]
    records += [ground_entity(c, "cell_type", args.offline) for c in
                ["induced pluripotent stem cell", "embryonic stem cell"]]
    # cell lines -> Cellosaurus CVCL_ (the RRID)
    records += [ground_cell_line(cl, args.offline) for cl in ["WA09", "WTC-11"]]

    STATUSES = ("resolved", "needs_review", "not_found", "not_attempted")
    by_status = {s: 0 for s in STATUSES}
    for r in records:
        by_status[r["grounding_status"]] = by_status.get(r["grounding_status"], 0) + 1
    by_kind = {}
    for r in records:
        k = by_kind.setdefault(r["kind"], {s: 0 for s in STATUSES})
        k[r["grounding_status"]] += 1
    coverage = {
        "generated_by": "pipeline/ground.py",
        "n": len(records),
        # accepted == resolved ONLY; needs_review are candidates that must NOT feed
        # KGX/TRAPI as facts until a human accepts them.
        "accepted_resolved": by_status["resolved"],
        "candidates_needs_review": by_status["needs_review"],
        "by_status": by_status,
        "by_kind": by_kind,
        "records": records,
    }
    (OUT / "coverage.json").write_text(json.dumps(coverage, indent=2, ensure_ascii=False))
    res = [r for r in records if r["grounding_status"] == "resolved"]
    print(f"grounded {len(res)}/{len(records)} | by status: {by_status}")
    for r in res[:12]:
        print(f"  {r['query']} -> {r['curie']} ({r['biolink_category']})")
    print(f"coverage artifact: {OUT/'coverage.json'}")


if __name__ == "__main__":
    main()
