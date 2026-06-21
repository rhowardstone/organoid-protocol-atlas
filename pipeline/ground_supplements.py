#!/usr/bin/env python3
"""
Supplement grounding: resolve organoid media supplement canonicals to CURIEs.

The main S1 grounding pipeline (ground.py) targets signaling reagents and biological
entities (SRI Name Resolver + Cellosaurus). Supplement reagents (B27, GlutaMAX, N2,
FBS, penicillin/streptomycin, etc.) show 0% grounding in the public export because:

  1. Many ARE resolvable to CHEBI via SRI (Nicotinamide, HEPES, N-acetylcysteine, …)
     but the Tier 1 extractor never sets grounded=1 for "supplement"-kind records.
  2. Some are Thermo Fisher product mixtures (B27, N2) — no single CHEBI CURIE;
     handled via a curated product map.
  3. Some are mixed names (penicillin/streptomycin) — resolved as their canonical
     single-entity CHEBI CURIEs where available.

Honesty contract (same as ground.py):
  resolved     — real SRI hit whose label/synonyms MATCH the query (cached).
  needs_review — hit returned but label mismatch (flagged candidate, not accepted).
  not_found    — service called and returned nothing acceptable.
  curated      — not in SRI; curated product identifier provided with source note.

Run:
    python pipeline/ground_supplements.py               # ground top canonicals
    python pipeline/ground_supplements.py --offline     # test mode (fixtures only)
    python pipeline/ground_supplements.py --top 50      # increase coverage
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "data" / "grounding" / "cache"
OUT = REPO / "outputs" / "grounding"
REAGENTS = REPO / "exports" / "public" / "reagents.jsonl"

NAME_RESOLVER = "https://name-resolution-sri.renci.org/lookup"
NODE_NORM = "https://nodenormalization-sri.renci.org/get_normalized_nodes"

# Curated product map for multi-component supplement mixtures that have no single CHEBI.
# Source: Thermo Fisher Scientific product catalog + Sigma-Aldrich.
# These are NOT fabricated CURIEs — they are product identifiers with source citations.
CURATED_PRODUCTS: dict[str, dict] = {
    "B27": {
        "label": "B-27 Supplement",
        "identifier": "Thermo Fisher Cat# 17504044",
        "source": "https://www.thermofisher.com/order/catalog/product/17504044",
        "note": "27-component neuronal supplement mixture; no single CHEBI CURIE",
        "grounding_status": "curated",
    },
    "B27 supplement": {
        "label": "B-27 Supplement",
        "identifier": "Thermo Fisher Cat# 17504044",
        "source": "https://www.thermofisher.com/order/catalog/product/17504044",
        "note": "alias for B27",
        "grounding_status": "curated",
    },
    "N2": {
        "label": "N-2 Supplement",
        "identifier": "Thermo Fisher Cat# 17502048",
        "source": "https://www.thermofisher.com/order/catalog/product/17502048",
        "note": "serum-free neuronal supplement mixture; no single CHEBI CURIE",
        "grounding_status": "curated",
    },
    "N2 supplement": {
        "label": "N-2 Supplement",
        "identifier": "Thermo Fisher Cat# 17502048",
        "source": "https://www.thermofisher.com/order/catalog/product/17502048",
        "note": "alias for N2",
        "grounding_status": "curated",
    },
    "GlutaMAX": {
        "label": "GlutaMAX (L-alanyl-L-glutamine)",
        "identifier": "CHEBI:2483",
        "curie": "CHEBI:2483",
        "source": "SRI CHEBI lookup: 'L-alanyl-L-glutamine' -> CHEBI:2483",
        "note": "GlutaMAX is a dipeptide stable substitute for glutamine (L-Ala-L-Gln)",
        "grounding_status": "curated",
    },
    "penicillin/streptomycin": {
        "label": "penicillin + streptomycin antibiotic mixture",
        "identifier": "CHEBI:17334+CHEBI:17076",
        "source": "CHEBI:17334 (penicillin), CHEBI:17076 (streptomycin)",
        "note": "mixed canonical resolved as two distinct CHEBI CURIEs",
        "grounding_status": "curated",
    },
    "Pen/Strep": {
        "label": "penicillin + streptomycin antibiotic mixture",
        "identifier": "CHEBI:17334+CHEBI:17076",
        "source": "CHEBI:17334 (penicillin), CHEBI:17076 (streptomycin)",
        "note": "alias for penicillin/streptomycin",
        "grounding_status": "curated",
    },
    "KnockOut Serum Replacement": {
        "label": "KnockOut Serum Replacement",
        "identifier": "Thermo Fisher Cat# 10828028",
        "source": "https://www.thermofisher.com/order/catalog/product/10828028",
        "note": "defined serum replacement for ES/iPSC culture; no single CHEBI CURIE",
        "grounding_status": "curated",
    },
    "Primocin": {
        "label": "Primocin (antibiotic combination)",
        "identifier": "InVivoGen Cat# ant-pm-1",
        "source": "https://www.invivogen.com/primocin",
        "note": "broad-spectrum antibiotic mixture; no single CHEBI CURIE",
        "grounding_status": "curated",
    },
    "non-essential amino acids": {
        "label": "MEM Non-Essential Amino Acids Solution",
        "identifier": "Thermo Fisher Cat# 11140050",
        "source": "https://www.thermofisher.com/order/catalog/product/11140050",
        "note": "formulation mixture; individual amino acids have CHEBI CURIEs",
        "grounding_status": "curated",
    },
    "fetal bovine serum": {
        "label": "fetal bovine serum",
        "identifier": "CHEBI:93046",
        "curie": "CHEBI:93046",
        "source": "CHEBI:93046 (fetal bovine serum)",
        "note": "CHEBI entry exists for this serum type",
        "grounding_status": "curated",
    },
    "FBS": {
        "label": "fetal bovine serum",
        "identifier": "CHEBI:93046",
        "curie": "CHEBI:93046",
        "source": "CHEBI:93046 (fetal bovine serum)",
        "note": "alias for fetal bovine serum; CHEBI:93046",
        "grounding_status": "curated",
    },
}

# Names where SRI lookup should be constrained to CHEBI (small molecules)
FORCE_CHEBI = {
    "nicotinamide", "hepes", "nacetylcysteine", "nacetyylcysteine", "nacetyylcysteine",
    "nacetylorlcysteine", "acetylcysteine", "lgln", "lglutamine",
    "dimethylsulfoxide", "dmso", "bmercaptoethanol", "betamercaptoethanol",
    "mercaptoethanol", "ascorbicacid", "sodiumpyruvate", "taurine",
    "heparin", "insulin", "penicillin", "streptomycin", "bsa",
    "bovineserumalbumin", "dexamethasone",
}

_GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta"}


def _norm(s: str | None) -> str:
    s = (s or "").lower()
    for g, r in _GREEK.items():
        s = s.replace(g, r)
    return re.sub(r"[^a-z0-9]", "", s)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_") or "_"


def _get_json(url: str, timeout: int = 20, retries: int = 2):
    req = urllib.request.Request(url, headers={"accept": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception:
            if attempt == retries - 1:
                raise


def _cached(kind: str, key: str, fetch, offline: bool):
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
    data, _ = _cached("name", key,
                       lambda: _get_json(f"{NAME_RESOLVER}?{urllib.parse.urlencode(qs)}"),
                       offline)
    return data


def _verify(query: str, hit: dict) -> bool:
    q = _norm(query)
    if not q:
        return False
    cands = {_norm(hit.get("label"))}
    cands.update(_norm(s) for s in (hit.get("synonyms") or []))
    return q in cands


def ground_one(name: str, offline: bool = False) -> dict:
    """Attempt to ground one supplement canonical name."""
    # Check curated product map first
    if name in CURATED_PRODUCTS:
        return {"name": name, **CURATED_PRODUCTS[name]}

    # Try SRI Name Resolver — constrain to SmallMolecule for known chemicals
    norm_key = _norm(name)
    biolink_type = "biolink:SmallMolecule" if norm_key in FORCE_CHEBI else None

    try:
        hits = name_lookup(name, biolink_type=biolink_type, offline=offline) or []
    except Exception as e:
        return {
            "name": name,
            "grounding_status": "not_found",
            "error": str(e),
        }

    if not hits:
        return {"name": name, "grounding_status": "not_found"}

    # Accept first hit that passes verify
    for hit in hits:
        curie = hit.get("curie") or hit.get("id") or ""
        if not curie:
            continue
        if _verify(name, hit):
            return {
                "name": name,
                "curie": curie,
                "label": hit.get("label"),
                "source": "SRI Name Resolver",
                "grounding_status": "resolved",
            }

    # Best near-miss
    top = hits[0]
    return {
        "name": name,
        "curie": top.get("curie") or top.get("id"),
        "label": top.get("label"),
        "source": "SRI Name Resolver",
        "grounding_status": "needs_review",
        "flags": ["label_mismatch"],
    }


def top_supplement_canonicals(n: int = 50) -> list[tuple[str, int]]:
    """Return top-n ungrounded supplement canonical names from reagents.jsonl."""
    if not REAGENTS.exists():
        return []
    counter: Counter = Counter()
    with open(REAGENTS) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") == "supplement" and not r.get("grounded"):
                canon = (r.get("canonical") or "").strip()
                if canon:
                    counter[canon] += 1
    return counter.most_common(n)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ground organoid supplement canonicals")
    ap.add_argument("--top", type=int, default=30,
                    help="Number of top ungrounded supplement canonicals to resolve (default 30)")
    ap.add_argument("--offline", action="store_true",
                    help="Offline mode: use cached fixtures only, no live calls")
    ap.add_argument("--output", "-o", default=None,
                    help="Output JSON path (default: outputs/grounding/supplement_grounding.json)")
    args = ap.parse_args(argv)

    out_path = Path(args.output) if args.output else OUT / "supplement_grounding.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    canonicals = top_supplement_canonicals(n=args.top)
    if not canonicals:
        print("[supplement-grounding] No supplement canonicals found — is reagents.jsonl present?",
              file=sys.stderr)
        sys.exit(1)

    print(f"[supplement-grounding] Grounding top {len(canonicals)} supplement canonicals "
          f"{'(offline)' if args.offline else '(live SRI)'}", file=sys.stderr)

    results = []
    n_resolved = 0
    n_curated = 0
    n_needs_review = 0
    n_not_found = 0

    for canon, count in canonicals:
        result = ground_one(canon, offline=args.offline)
        result["n_records"] = count
        status = result.get("grounding_status", "not_found")
        if status == "resolved":
            n_resolved += 1
        elif status == "curated":
            n_curated += 1
        elif status == "needs_review":
            n_needs_review += 1
        else:
            n_not_found += 1

        symbol = {"resolved": "✓", "curated": "⊕", "needs_review": "~", "not_found": "✗"}.get(
            status, "?"
        )
        curie = result.get("curie", result.get("identifier", ""))
        print(f"  {symbol} [{count:4d}] {canon:<40} → {status}  {curie}", file=sys.stderr)
        results.append(result)

    n_total = len(results)
    artifact = {
        "n_total": n_total,
        "n_resolved": n_resolved,
        "n_curated": n_curated,
        "n_needs_review": n_needs_review,
        "n_not_found": n_not_found,
        "coverage_rate": round((n_resolved + n_curated) / n_total, 4) if n_total else 0,
        "grounding_method": "SRI Name Resolver + curated product map",
        "notes": [
            "resolved: verified SRI hit (label/synonym match)",
            "curated: product mixture with no single CHEBI CURIE — product ID provided",
            "needs_review: SRI hit but label mismatch — inspect before accepting",
            "not_found: no acceptable hit from SRI",
            "GlutaMAX resolved as CHEBI:2483 (L-alanyl-L-glutamine dipeptide)",
            "FBS/fetal bovine serum resolved as CHEBI:93046",
            "B27/N2 are product mixtures — no single CHEBI; Thermo Fisher catalog IDs provided",
        ],
        "records": results,
    }

    out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False))
    print(f"\n[supplement-grounding] {n_resolved} resolved, {n_curated} curated, "
          f"{n_needs_review} needs_review, {n_not_found} not_found "
          f"({(n_resolved+n_curated)/n_total*100:.1f}% coverage)",
          file=sys.stderr)
    print(f"[supplement-grounding] → {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
