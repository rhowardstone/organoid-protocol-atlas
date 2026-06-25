#!/usr/bin/env python3
"""
S2 — Biolink-compliant KGX export from grounded organoid-protocol predictions.

Consumes the S1 grounded sidecars (data/predictions/local/grounded/*.json) and the
matching Tier-1 predictions, and emits a KGX TSV knowledge graph:

  exports/kgx/nodes.tsv         one node per unique accepted `resolved` CURIE,
                                plus one biolink:Publication node per paper.
  exports/kgx/edges.tsv         "this publication mentions reagent/cell-line X"
                                edges, subject=Publication, object=entity CURIE.
  exports/kgx/review_items.jsonl `needs_review` + `not_found` entities, preserved
                                as NON-facts for human review (never in nodes/edges).
  exports/kgx/kgx_manifest.json generated counts (the single metric artifact).

Honesty / license contract (mirrors pipeline/ground.py):
  - Only accepted `resolved` groundings become graph facts. `needs_review`
    (real hit, label_mismatch) and `not_found` are demoted to review_items and
    NEVER appear in nodes.tsv / edges.tsv.
  - No CURIE is ever fabricated: every node id is a CURIE that the sidecar already
    marked `resolved`.
  - License-safe: only CURIEs / labels / predicates / a SHORT evidence snippet
    (<= EVIDENCE_SNIPPET_MAX chars) / provenance. Never full methods text.

Publication CURIE policy:
  The grounded sidecars and predictions carry a PMC id but no PMID, so we mint a
  defensible `PMC:<digits>` CURIE for each paper (prefix registered in the Bioregistry
  / identifiers.org as `pmc`, https://bioregistry.io/registry/pmc). If a PMID ever
  becomes available it should be preferred (PMID:<n>); see _publication_curie().

Predicate choice:
  We model the protocol/publication-to-reagent relation with biolink:mentions
  (https://biolink.github.io/biolink-model/mentions/). It is the low-commitment,
  defensible predicate for "an information content entity (the Publication) refers
  to a named thing": domain = InformationContentEntity, range = NamedThing, which
  is exactly Publication -> {Gene, SmallMolecule, CellLine, ...}. Stronger relational
  predicates (has_participant / has_input) assert a biological process/activity we
  have NOT extracted, so we deliberately stay at `mentions` for v0. The qualifiers
  (role, concentration, organoid_type) carry the protocol-usage detail as edge
  properties without over-asserting the predicate.

Run:
    python pipeline/export_kgx.py
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GROUNDED = REPO / "data" / "predictions" / "local" / "grounded"
PRED = REPO / "data" / "predictions" / "local"
OUT = REPO / "exports" / "kgx"
CORPUS = REPO / "data" / "corpus" / "corpus.tsv"


def cc_corpus_pmcids() -> set:
    """License-safe corpus subset for the public KGX: papers in corpus.tsv with a
    CC0/CC-BY license. Mirrors the public-export redistribution policy so the KGX
    never carries mentions from non-CC or non-corpus (rejected/thin) predictions."""
    sys.path.insert(0, str(REPO / "pipeline"))
    from export_public import is_public_license  # noqa: E402
    out = set()
    if CORPUS.exists():
        for r in csv.DictReader(CORPUS.open(encoding="utf-8-sig"), delimiter="\t"):
            if r.get("pmcid") and is_public_license(r.get("license")):
                out.add(r["pmcid"])
    return out

# --- provenance / policy constants -----------------------------------------
PRIMARY_KNOWLEDGE_SOURCE = "infores:organoid-protocol-atlas"
# Tier-1 predictions are LLM-extracted, so the graph facts are predictions made by
# an automated agent (not asserted by a human curator or a primary db).
KNOWLEDGE_LEVEL = "prediction"
AGENT_TYPE = "automated_agent"
USES_PREDICATE = "biolink:mentions"
PUBLICATION_CATEGORY = "biolink:Publication"
EVIDENCE_SNIPPET_MAX = 300  # snippet-only policy: never full methods text

# --- Biolink allow-list (fallback validation) ------------------------------
# Vendored explicit allow-list of the Biolink classes/slots we actually emit.
# Source: Biolink Model (https://biolink.github.io/biolink-model/). Used when no
# real Biolink toolkit (bmt) is importable; every emitted node category and edge
# predicate is asserted to be a member of these sets.
ALLOWED_NODE_CATEGORIES = {
    "biolink:Gene",
    "biolink:Protein",
    "biolink:SmallMolecule",
    "biolink:ChemicalEntity",
    "biolink:MolecularMixture",
    "biolink:CellLine",
    "biolink:Publication",
}
ALLOWED_PREDICATES = {
    "biolink:mentions",
}

# KGX TSV required-column contracts.
NODE_COLUMNS = ["id", "category", "name", "provided_by"]
EDGE_COLUMNS = [
    "id",
    "subject",
    "predicate",
    "object",
    "knowledge_level",
    "agent_type",
    "primary_knowledge_source",
    "publications",
    # optional protocol-usage qualifiers / properties (KGX allows extra columns):
    "role",
    "concentration_value",
    "concentration_unit",
    "organoid_type",
    "evidence",
]

# Fields in a prediction record that hold reagent-like items keyed by `name`.
_REAGENT_FIELDS = ("signaling_factors", "small_molecules", "media_supplements")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def _publication_curie(pmcid: str, prediction: dict | None) -> str:
    """Pick a defensible publication CURIE: prefer PMID if ever present, else PMC."""
    if prediction:
        for key in ("pmid", "PMID", "pubmed_id"):
            val = prediction.get(key)
            if val:
                digits = str(val).replace("PMID:", "").strip()
                if digits:
                    return f"PMID:{digits}"
    digits = str(pmcid).replace("PMC", "").strip()
    return f"PMC:{digits}"


def _clip(text, limit=EVIDENCE_SNIPPET_MAX):
    if not text:
        return ""
    text = " ".join(str(text).split())
    return text[: limit - 1] + "…" if len(text) > limit else text


def _index_prediction(prediction: dict | None) -> dict:
    """name -> {role, concentration, evidence_quote} from a prediction record.

    Lets edges carry protocol-usage detail. Matching is by the same `name` the
    sidecar used as its `query` (verified 1:1 for signaling_factors).
    """
    index = {}
    if not prediction:
        return index
    for field in _REAGENT_FIELDS:
        for item in prediction.get(field) or []:
            name = item.get("name")
            if not name:
                continue
            conc = item.get("concentration") or {}
            ev = item.get("evidence") or {}
            index[name] = {
                "role": item.get("role") or "",
                "concentration_value": conc.get("value"),
                "concentration_unit": conc.get("unit") or conc.get("canonical_unit") or "",
                "evidence": ev.get("quote") or "",
            }
    return index


def _edge_id(subject: str, predicate: str, obj: str) -> str:
    pred = predicate.split(":", 1)[-1]
    return f"{subject}--{pred}--{obj}"


def build_kgx(sidecars, predictions):
    """Pure graph builder: (list[sidecar], {pmcid: prediction}) ->
    (nodes, edges, review_items, manifest).

    No filesystem access; callable directly from tests. `nodes`/`edges` are lists
    of dicts keyed by NODE_COLUMNS / EDGE_COLUMNS; `review_items` is a list of dicts;
    `manifest` is the counts dict.
    """
    nodes: dict[str, dict] = {}        # node id -> row
    edges: list[dict] = []
    review_items: list[dict] = []
    seen_edges: set[str] = set()

    papers = set()
    total_entities = 0
    resolved_entities = 0

    for sidecar in sidecars:
        pmcid = sidecar.get("pmcid")
        organoid_type = sidecar.get("organoid_type") or ""
        prediction = (predictions or {}).get(pmcid)
        pub_curie = _publication_curie(pmcid, prediction)
        pred_index = _index_prediction(prediction)

        # Publication node (one per paper).
        if pub_curie not in nodes:
            nodes[pub_curie] = {
                "id": pub_curie,
                "category": PUBLICATION_CATEGORY,
                "name": pmcid,
                "provided_by": PRIMARY_KNOWLEDGE_SOURCE,
            }
        papers.add(pub_curie)

        for ent in sidecar.get("entities", []):
            total_entities += 1
            status = ent.get("grounding_status")

            if status != "resolved":
                # needs_review + not_found (and not_attempted) -> NON-facts.
                review_items.append(
                    {
                        "pmcid": pmcid,
                        "publication": pub_curie,
                        "query": ent.get("query"),
                        "kind": ent.get("kind"),
                        "grounding_status": status,
                        "curie": ent.get("curie"),
                        "label": ent.get("label"),
                        "biolink_category": ent.get("biolink_category"),
                        "source": ent.get("source"),
                        "flags": ent.get("flags", []),
                        "field": ent.get("field"),
                    }
                )
                continue

            curie = ent.get("curie")
            category = ent.get("biolink_category")
            if not curie or not category:
                # defensive: a `resolved` row must carry a real CURIE+category.
                continue
            resolved_entities += 1

            # Entity node (dedup by CURIE).
            if curie not in nodes:
                nodes[curie] = {
                    "id": curie,
                    "category": category,
                    "name": ent.get("label") or ent.get("query") or "",
                    "provided_by": PRIMARY_KNOWLEDGE_SOURCE,
                }

            # Usage edge: Publication --mentions--> entity.
            eid = _edge_id(pub_curie, USES_PREDICATE, curie)
            if eid in seen_edges:
                continue
            seen_edges.add(eid)
            detail = pred_index.get(ent.get("query"), {})
            edges.append(
                {
                    "id": eid,
                    "subject": pub_curie,
                    "predicate": USES_PREDICATE,
                    "object": curie,
                    "knowledge_level": KNOWLEDGE_LEVEL,
                    "agent_type": AGENT_TYPE,
                    "primary_knowledge_source": PRIMARY_KNOWLEDGE_SOURCE,
                    "publications": pub_curie,
                    "role": detail.get("role", ""),
                    "concentration_value": detail.get("concentration_value")
                    if detail.get("concentration_value") is not None
                    else "",
                    "concentration_unit": detail.get("concentration_unit", ""),
                    "organoid_type": organoid_type,
                    "evidence": _clip(detail.get("evidence", "")),
                }
            )

    nodes_list = list(nodes.values())

    # --- manifest counts (single generated metric artifact) ---
    n_nodes_by_category: dict[str, int] = {}
    for n in nodes_list:
        n_nodes_by_category[n["category"]] = n_nodes_by_category.get(n["category"], 0) + 1
    n_edges_by_predicate: dict[str, int] = {}
    for e in edges:
        n_edges_by_predicate[e["predicate"]] = n_edges_by_predicate.get(e["predicate"], 0) + 1
    n_review_by_status: dict[str, int] = {}
    for r in review_items:
        s = r["grounding_status"]
        n_review_by_status[s] = n_review_by_status.get(s, 0) + 1

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "predicate": USES_PREDICATE,
        "primary_knowledge_source": PRIMARY_KNOWLEDGE_SOURCE,
        "knowledge_level": KNOWLEDGE_LEVEL,
        "agent_type": AGENT_TYPE,
        "n_papers": len(papers),
        "n_nodes": len(nodes_list),
        "n_nodes_by_category": n_nodes_by_category,
        "n_edges": len(edges),
        "n_edges_by_predicate": n_edges_by_predicate,
        "n_review_items": len(review_items),
        "n_review_by_status": n_review_by_status,
        "entities_total": total_entities,
        "entities_resolved": resolved_entities,
        "resolved_rate": round(resolved_entities / total_entities, 4) if total_entities else 0.0,
    }
    return nodes_list, edges, review_items, manifest


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_kgx(nodes, edges):
    """Validate categories/predicates + KGX required-column contract.

    Uses the real Biolink Model Toolkit (bmt) when importable; otherwise falls
    back to the vendored allow-list. Returns (ok, used_real_toolkit, errors).
    """
    errors: list[str] = []
    used_real = False

    # Required-column contract (always checked).
    for n in nodes:
        for col in NODE_COLUMNS:
            if col not in n:
                errors.append(f"node {n.get('id')!r} missing required column {col!r}")
        if not n.get("id") or not n.get("category"):
            errors.append(f"node {n.get('id')!r} has empty id/category")
    for e in edges:
        for col in ("id", "subject", "predicate", "object",
                    "knowledge_level", "agent_type", "primary_knowledge_source"):
            if col not in e:
                errors.append(f"edge {e.get('id')!r} missing required column {col!r}")

    node_cats = {n["category"] for n in nodes if n.get("category")}
    edge_preds = {e["predicate"] for e in edges if e.get("predicate")}

    try:  # real Biolink validation if the toolkit is present
        from bmt import Toolkit  # type: ignore

        tk = Toolkit()
        used_real = True

        def _valid_class(cat):
            name = cat.replace("biolink:", "")
            el = tk.get_element(name)
            return el is not None

        def _valid_predicate(pred):
            name = pred.replace("biolink:", "").replace("_", " ")
            return name in set(tk.get_all_predicates())

        for cat in node_cats:
            if not _valid_class(cat):
                errors.append(f"category {cat!r} is not a valid Biolink class (bmt)")
        for pred in edge_preds:
            if not _valid_predicate(pred):
                errors.append(f"predicate {pred!r} is not a valid Biolink predicate (bmt)")
    except Exception:
        # Fallback: vendored allow-list.
        for cat in node_cats:
            if cat not in ALLOWED_NODE_CATEGORIES:
                errors.append(f"category {cat!r} not in vendored Biolink allow-list")
        for pred in edge_preds:
            if pred not in ALLOWED_PREDICATES:
                errors.append(f"predicate {pred!r} not in vendored Biolink allow-list")

    return (len(errors) == 0, used_real, errors)


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------
def load_sidecars(grounded_dir=GROUNDED, pred_dir=PRED, allowed=None):
    """Read grounded sidecars and their matching prediction records.
    If `allowed` (a set of pmcids) is given, only those papers are included —
    used to gate the public KGX to the license-safe CC corpus."""
    sidecars, predictions = [], {}
    for path in sorted(Path(grounded_dir).glob("*.json")):
        sidecar = json.loads(path.read_text())
        pmcid = sidecar.get("pmcid")
        if allowed is not None and pmcid not in allowed:
            continue
        sidecars.append(sidecar)
        pred_path = Path(pred_dir) / f"{pmcid}.json"
        if pred_path.exists():
            try:
                predictions[pmcid] = json.loads(pred_path.read_text())
            except Exception:
                predictions[pmcid] = None
    return sidecars, predictions


def _write_tsv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_outputs(nodes, edges, review_items, manifest, out_dir=OUT):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_tsv(out_dir / "nodes.tsv", NODE_COLUMNS, nodes)
    _write_tsv(out_dir / "edges.tsv", EDGE_COLUMNS, edges)
    with open(out_dir / "review_items.jsonl", "w", encoding="utf-8") as fh:
        for item in review_items:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    (out_dir / "kgx_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    return out_dir


def main():
    allowed = cc_corpus_pmcids()
    print(f"  license gate: {len(allowed)} CC corpus papers eligible for KGX", flush=True)
    sidecars, predictions = load_sidecars(allowed=allowed)
    nodes, edges, review_items, manifest = build_kgx(sidecars, predictions)
    ok, used_real, errors = validate_kgx(nodes, edges)
    manifest["validation"] = {
        "ok": ok,
        "toolkit": "bmt" if used_real else "vendored-allow-list",
        "errors": errors,
    }
    out_dir = write_outputs(nodes, edges, review_items, manifest, OUT)

    print(f"KGX export -> {out_dir}")
    print(f"  nodes.tsv          : {manifest['n_nodes']} nodes {manifest['n_nodes_by_category']}")
    print(f"  edges.tsv          : {manifest['n_edges']} edges {manifest['n_edges_by_predicate']}")
    print(f"  review_items.jsonl : {manifest['n_review_items']} {manifest['n_review_by_status']}")
    print(f"  papers             : {manifest['n_papers']}")
    print(f"  resolved rate      : {manifest['resolved_rate']} "
          f"({manifest['entities_resolved']}/{manifest['entities_total']})")
    print(f"  predicate          : {manifest['predicate']}")
    print(f"  validation         : ok={ok} via "
          f"{'real Biolink toolkit (bmt)' if used_real else 'vendored allow-list (no bmt installed)'}")
    if errors:
        print("  VALIDATION ERRORS:")
        for err in errors:
            print(f"    - {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
