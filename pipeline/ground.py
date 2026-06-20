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
  resolved      — a real service call returned an acceptable CURIE (cached);
  not_found     — the service was called and returned nothing acceptable (NEVER guessed);
  not_attempted — offline with no cached response (no call made).
A CURIE is never invented. Every `resolved` is backed by a cached response on disk.

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


def name_lookup(name: str, biolink_type: str | None = None, limit: int = 10,
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


def ground_entity(name: str, kind: str = "reagent", offline: bool = False) -> dict:
    """Resolve one free-text entity to a Biolink CURIE. Honest 3-state status."""
    rec = {"query": name, "kind": kind, "grounding_status": "not_attempted",
           "curie": None, "label": None, "biolink_category": None, "source": None}
    if not name:
        return rec
    prefixes = KIND_PREFIXES.get(kind, ())
    types = KIND_BIOLINK.get(kind, [None])
    if kind == "reagent" and re.sub(r"[^a-z0-9]", "", name.lower()) in SMALL_MOLECULES:
        # known small molecule: constrain to chemicals so abbreviations don't collide
        # with gene symbols (SAG/PGE2). Accept only chemical CURIEs.
        types = ["biolink:ChemicalEntity"]
        prefixes = ("CHEBI", "PUBCHEM.COMPOUND", "UNII", "DRUGBANK", "MESH")
    called = False
    for bt in types:
        hits = name_lookup(name, biolink_type=bt, offline=offline)
        if hits is None:
            continue              # offline + uncached for this type
        called = True
        for h in hits:
            curie = h.get("curie")
            if curie and (not prefixes or curie.split(":")[0] in prefixes):
                rec.update(grounding_status="resolved", curie=curie,
                           label=h.get("label"), source="sri-name-resolver",
                           biolink_category=_category(curie, offline) or
                           (h.get("types") or [None])[0])
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
    qs = {"q": f'id:"{name}"', "format": "json", "rows": 5, "fields": "id,ac,sy"}
    data, _ = _cached("cellosaurus", name,
                      lambda: _get_json(f"{CELLOSAURUS}?{urllib.parse.urlencode(qs)}"), offline)
    if data is None:
        return rec
    lines = (((data or {}).get("Cellosaurus") or {}).get("cell-line-list")) or []
    for cl in lines:
        names = {n.get("value", "").lower() for n in (cl.get("name-list") or [])}
        if name.lower() in names:                     # require an exact name match
            acc = next((a.get("value") for a in (cl.get("accession-list") or [])
                        if a.get("type") == "primary"), None)
            if acc:
                rec.update(grounding_status="resolved", curie=f"Cellosaurus:{acc}",
                           label=name)
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

    by_status = {}
    for r in records:
        by_status.setdefault(r["grounding_status"], 0)
        by_status[r["grounding_status"]] += 1
    coverage = {
        "generated_by": "pipeline/ground.py",
        "n": len(records),
        "by_status": by_status,
        "by_kind": {},
        "records": records,
    }
    for r in records:
        k = coverage["by_kind"].setdefault(r["kind"], {"resolved": 0, "not_found": 0, "not_attempted": 0})
        k[r["grounding_status"]] += 1
    (OUT / "coverage.json").write_text(json.dumps(coverage, indent=2, ensure_ascii=False))
    res = [r for r in records if r["grounding_status"] == "resolved"]
    print(f"grounded {len(res)}/{len(records)} | by status: {by_status}")
    for r in res[:12]:
        print(f"  {r['query']} -> {r['curie']} ({r['biolink_category']})")
    print(f"coverage artifact: {OUT/'coverage.json'}")


if __name__ == "__main__":
    main()
