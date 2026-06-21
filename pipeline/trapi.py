#!/usr/bin/env python3
"""
TRAPI (Translator Reasoner API, ReasonerStdAPI) 1.5 responder over the committed
Biolink KGX (exports/kgx/{nodes,edges}.tsv).

This makes the Organoid Protocol Atlas knowledge graph QUERYABLE, completing the
end-to-end chain:

    paper -> grounded extraction -> SRI Biolink CURIEs -> KGX -> TRAPI-queryable

Scope (intentionally minimal, DRAFT for Agent B who owns TRAPI):
  * SINGLE-HOP queries only: one qedge connecting exactly two qnodes.
  * A qnode may pin `ids: [CURIE, ...]` and/or constrain `categories: [biolink:...]`.
  * The qedge may constrain `predicates: [biolink:...]` (our graph is all
    biolink:mentions, so the default matches everything).
  * Edges are matched in BOTH directions (subject->object and object->subject),
    honoring which qnode plays subject vs object for the matched KG edge.
  * NEVER fabricate: only nodes/edges actually present in the loaded KGX are
    emitted into the knowledge_graph / results.

Multi-hop, scoring, attribute constraints, qualifier constraints, and
auxiliary_graphs are explicitly out of scope (future work).

TRAPI 1.5 shapes used (https://github.com/NCATSTranslator/ReasonerAPI):
  request  : {"message": {"query_graph": {"nodes": {...}, "edges": {...}}}}
  response : {"message": {"query_graph": ...,
                          "knowledge_graph": {"nodes": {...}, "edges": {...}},
                          "results": [ {
                              "node_bindings": {qnode_id: [{"id": kg_node_id}], ...},
                              "analyses": [ {
                                  "resource_id": <infores>,
                                  "edge_bindings": {qedge_id: [{"id": kg_edge_id}]},
                              } ],
                          } ]}}

Pure stdlib, CPU-only, offline. No git ops.

CLI:
    python pipeline/trapi.py --query pipeline/trapi_examples/<file>.json
    python pipeline/trapi.py --meta
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_NODES = REPO / "exports" / "kgx" / "nodes.tsv"
DEFAULT_EDGES = REPO / "exports" / "kgx" / "edges.tsv"

# The infores stamped onto each analysis (this responder is the resource serving
# the answer). Mirrors export_kgx.PRIMARY_KNOWLEDGE_SOURCE.
RESOURCE_ID = "infores:organoid-protocol-atlas"

NODE_COLUMNS = ["id", "category", "name", "provided_by"]

# Maps KGX edge column name → valid TRAPI attribute_type_id CURIE.
# "primary_knowledge_source" is omitted: it belongs in the sources block,
# not in attributes. Standard Biolink properties use the biolink: prefix;
# OPA-specific properties use the OPA: prefix (one colon — valid CURIE).
EDGE_ATTR_CURIE: dict[str, str] = {
    "knowledge_level": "biolink:knowledge_level",
    "agent_type": "biolink:agent_type",
    "publications": "biolink:publications",
    "role": "OPA:role",
    "concentration_value": "OPA:concentration_value",
    "concentration_unit": "OPA:concentration_unit",
    "organoid_type": "OPA:organoid_type",
    "evidence": "OPA:evidence",
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
class Graph:
    """In-memory KGX graph.

    Attributes:
        nodes:        {node_id: {"id","category","name","provided_by", ...}}
        edges:        {edge_id: {"id","subject","predicate","object", ...}}
        by_subject:   {subject_id: [edge_id, ...]}
        by_object:    {object_id: [edge_id, ...]}
    """

    __slots__ = ("nodes", "edges", "by_subject", "by_object")

    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}
        self.by_subject: dict[str, list[str]] = {}
        self.by_object: dict[str, list[str]] = {}


def load_kg(nodes_tsv=DEFAULT_NODES, edges_tsv=DEFAULT_EDGES) -> Graph:
    """Load KGX TSVs into an in-memory Graph (nodes by id; edges + subject/object indices)."""
    g = Graph()
    with open(nodes_tsv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            nid = (row.get("id") or "").strip()
            if not nid:
                continue
            g.nodes[nid] = {k: (v if v is not None else "") for k, v in row.items()}
    with open(edges_tsv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            eid = (row.get("id") or "").strip()
            subj = (row.get("subject") or "").strip()
            obj = (row.get("object") or "").strip()
            if not eid or not subj or not obj:
                continue
            g.edges[eid] = {k: (v if v is not None else "") for k, v in row.items()}
            g.by_subject.setdefault(subj, []).append(eid)
            g.by_object.setdefault(obj, []).append(eid)
    return g


# ---------------------------------------------------------------------------
# Query answering
# ---------------------------------------------------------------------------
def _qnode_matches(node: dict, qnode: dict) -> bool:
    """Does a KG node satisfy a qnode's ids/categories constraints?"""
    ids = qnode.get("ids")
    if ids and node.get("id") not in set(ids):
        return False
    cats = qnode.get("categories")
    if cats and node.get("category") not in set(cats):
        return False
    return True


def _predicate_ok(edge: dict, predicates) -> bool:
    if not predicates:
        return True
    return edge.get("predicate") in set(predicates)


def _build_kg_node(node: dict) -> dict:
    """TRAPI knowledge_graph node object from a KGX node row."""
    out = {
        "name": node.get("name") or None,
        "categories": [node["category"]] if node.get("category") else [],
        "attributes": [],
    }
    return out


def _build_kg_edge(edge: dict) -> dict:
    """TRAPI knowledge_graph edge object from a KGX edge row.

    Non-empty KGX edge columns are surfaced as TRAPI attributes (attribute_type_id
    namespaced under this resource so we don't over-claim Biolink slot semantics).
    """
    attributes = []
    for col, curie in EDGE_ATTR_CURIE.items():
        val = edge.get(col)
        if val not in (None, ""):
            attributes.append(
                {
                    "attribute_type_id": curie,
                    "value": val,
                }
            )
    sources = [
        {
            "resource_id": edge.get("primary_knowledge_source") or RESOURCE_ID,
            "resource_role": "primary_knowledge_source",
        }
    ]
    return {
        "subject": edge["subject"],
        "predicate": edge.get("predicate") or "biolink:related_to",
        "object": edge["object"],
        "sources": sources,
        "attributes": attributes,
    }


def _answer_hub_two_hop(qnodes: dict, qedges: dict, graph: Graph, query_graph: dict) -> dict:
    """Two-hop hub pattern (3 qnodes, 2 qedges sharing one qnode).

    Identifies the hub qnode (appears in both edges), finds all KG nodes
    that can serve as the hub, then for each hub returns every (leaf_a, leaf_b)
    pair connected through it.

    Primary use-case for this KGX: "find all entities co-mentioned with X in
    any paper" — hub=Publication, leaf_a pinned to X, leaf_b free.
    """
    qedge_list = list(qedges.items())
    qeid_0, qedge_0 = qedge_list[0]
    qeid_1, qedge_1 = qedge_list[1]

    e0_nids = {qedge_0["subject"], qedge_0["object"]}
    e1_nids = {qedge_1["subject"], qedge_1["object"]}
    hub_set = e0_nids & e1_nids

    # Must be exactly one shared qnode (the hub).
    if len(hub_set) != 1:
        return _wrap(query_graph, {}, {}, [])
    hub_qid = next(iter(hub_set))

    # Determine which leaf each edge connects to the hub.
    # (e0 → leaf_a, e1 → leaf_b — we detect roles for each edge)
    def _leaf_of(qedge, hub_qid):
        """Return (leaf_qid, hub_is_subject_in_edge)."""
        if qedge["subject"] == hub_qid:
            return qedge["object"], True
        return qedge["subject"], False

    leaf_a_qid, hub_is_subj_in_e0 = _leaf_of(qedge_0, hub_qid)
    leaf_b_qid, hub_is_subj_in_e1 = _leaf_of(qedge_1, hub_qid)

    hub_q = qnodes.get(hub_qid, {})
    leaf_a_q = qnodes.get(leaf_a_qid, {})
    leaf_b_q = qnodes.get(leaf_b_qid, {})
    preds_0 = qedge_0.get("predicates")
    preds_1 = qedge_1.get("predicates")

    def _edges_for_hub_leaf(hub_nid, leaf_q, hub_is_subj, predicates):
        """Yield (eid, leaf_node) pairs where the hub connects to a matching leaf."""
        if hub_is_subj:
            for eid in graph.by_subject.get(hub_nid, []):
                e = graph.edges[eid]
                if not _predicate_ok(e, predicates):
                    continue
                leaf_node = graph.nodes.get(e["object"])
                if leaf_node and _qnode_matches(leaf_node, leaf_q):
                    yield eid, leaf_node
        else:
            for eid in graph.by_object.get(hub_nid, []):
                e = graph.edges[eid]
                if not _predicate_ok(e, predicates):
                    continue
                leaf_node = graph.nodes.get(e["subject"])
                if leaf_node and _qnode_matches(leaf_node, leaf_q):
                    yield eid, leaf_node

    # Collect candidate hub KG nodes via the pinned leaf_a IDs (if any),
    # then cross with leaf_b.  If neither leaf is pinned, scan all hub candidates.
    pinned_a = [i for i in (leaf_a_q.get("ids") or []) if i in graph.nodes]
    pinned_b = [i for i in (leaf_b_q.get("ids") or []) if i in graph.nodes]

    # Build hub_nid → [(eid_to_a, leaf_a_node)] mapping
    hub_to_a: dict[str, list] = {}
    if pinned_a:
        for aid in pinned_a:
            idx = graph.by_object if hub_is_subj_in_e0 else graph.by_subject
            for eid in idx.get(aid, []):
                e = graph.edges[eid]
                if not _predicate_ok(e, preds_0):
                    continue
                hub_nid = e["subject"] if hub_is_subj_in_e0 else e["object"]
                hub_node = graph.nodes.get(hub_nid)
                leaf_a_node = graph.nodes.get(aid)
                if hub_node and leaf_a_node and _qnode_matches(hub_node, hub_q) and _qnode_matches(leaf_a_node, leaf_a_q):
                    hub_to_a.setdefault(hub_nid, []).append((eid, leaf_a_node))
    else:
        # No pinned leaf_a: discover hubs from pinned_b side or scan all
        if pinned_b:
            idx = graph.by_object if hub_is_subj_in_e1 else graph.by_subject
            for bid in pinned_b:
                for eid in idx.get(bid, []):
                    e = graph.edges[eid]
                    hub_nid = e["subject"] if hub_is_subj_in_e1 else e["object"]
                    hub_node = graph.nodes.get(hub_nid)
                    if hub_node and _qnode_matches(hub_node, hub_q):
                        hub_to_a.setdefault(hub_nid, [])
        else:
            # Fully open query: collect all matching hub nodes from edge traversal
            for hub_nid, hub_node in graph.nodes.items():
                if _qnode_matches(hub_node, hub_q):
                    hub_to_a[hub_nid] = []

    kg_nodes: dict[str, dict] = {}
    kg_edges: dict[str, dict] = {}
    results: list[dict] = []

    for hub_nid, a_pairs in hub_to_a.items():
        hub_node = graph.nodes.get(hub_nid)
        if hub_node is None:
            continue

        # If leaf_a was unpinned, find all edges from this hub to leaf_a matches
        if not a_pairs:
            a_pairs = list(_edges_for_hub_leaf(hub_nid, leaf_a_q, hub_is_subj_in_e0, preds_0))

        # Find all edges from this hub to leaf_b matches
        b_pairs = list(_edges_for_hub_leaf(hub_nid, leaf_b_q, hub_is_subj_in_e1, preds_1))
        if not a_pairs or not b_pairs:
            continue

        kg_nodes[hub_nid] = _build_kg_node(hub_node)

        for eid_a, leaf_a_node in a_pairs:
            for eid_b, leaf_b_node in b_pairs:
                # Skip trivial self-mention: same entity bound to both leaf qnodes.
                # Co-mention queries should not include "X co-mentioned with X".
                if leaf_a_node["id"] == leaf_b_node["id"] and leaf_a_qid != leaf_b_qid:
                    continue

                kg_nodes[leaf_a_node["id"]] = _build_kg_node(leaf_a_node)
                kg_nodes[leaf_b_node["id"]] = _build_kg_node(leaf_b_node)
                kg_edges[eid_a] = _build_kg_edge(graph.edges[eid_a])
                kg_edges[eid_b] = _build_kg_edge(graph.edges[eid_b])
                results.append({
                    "node_bindings": {
                        hub_qid: [{"id": hub_nid}],
                        leaf_a_qid: [{"id": leaf_a_node["id"]}],
                        leaf_b_qid: [{"id": leaf_b_node["id"]}],
                    },
                    "analyses": [{
                        "resource_id": RESOURCE_ID,
                        "edge_bindings": {
                            qeid_0: [{"id": eid_a}],
                            qeid_1: [{"id": eid_b}],
                        },
                    }],
                })

    return _wrap(query_graph, kg_nodes, kg_edges, results)


def answer(trapi_message: dict, graph: Graph) -> dict:
    """Answer a TRAPI query (single-hop or 2-hop hub) against the loaded KGX.

    Supported patterns:
      Single-hop  (1 qedge, 2 qnodes): standard subject → predicate → object.
      Two-hop hub (2 qedge, 3 qnodes): both edges share one qnode (the hub).
        Examples: leaf_a ← hub → leaf_b  (co-mentions via a shared publication).

    Returns a TRAPI 1.5 response message. Unsupported or unmatched queries
    return empty results — never raises for a well-formed request.
    """
    message = (trapi_message or {}).get("message", {}) or {}
    query_graph = message.get("query_graph", {}) or {}
    qnodes = query_graph.get("nodes", {}) or {}
    qedges = query_graph.get("edges", {}) or {}

    kg_nodes: dict[str, dict] = {}
    kg_edges: dict[str, dict] = {}
    results: list[dict] = []

    if len(qedges) == 2 and len(qnodes) == 3:
        return _answer_hub_two_hop(qnodes, qedges, graph, query_graph)

    # Single-hop: exactly one qedge over two qnodes. Anything else returns empty.
    if len(qedges) != 1 or len(qnodes) != 2:
        return _wrap(query_graph, kg_nodes, kg_edges, results)

    qedge_id, qedge = next(iter(qedges.items()))
    subj_qid = qedge.get("subject")
    obj_qid = qedge.get("object")
    predicates = qedge.get("predicates")

    subj_q = qnodes.get(subj_qid)
    obj_q = qnodes.get(obj_qid)
    if subj_q is None or obj_q is None:
        return _wrap(query_graph, kg_nodes, kg_edges, results)

    # Collect candidate KG edges. We honor the qedge's subject/object roles but
    # also try the reverse orientation, so a pin on either qnode finds its edges
    # regardless of whether the KGX stored it as subject or object.
    candidate_edge_ids: set[str] = set()

    def _pinned_ids(q):
        return [i for i in (q.get("ids") or []) if i in graph.nodes]

    subj_ids = _pinned_ids(subj_q)
    obj_ids = _pinned_ids(obj_q)

    if subj_ids:
        for cid in subj_ids:
            candidate_edge_ids.update(graph.by_subject.get(cid, []))
            candidate_edge_ids.update(graph.by_object.get(cid, []))
    if obj_ids:
        for cid in obj_ids:
            candidate_edge_ids.update(graph.by_subject.get(cid, []))
            candidate_edge_ids.update(graph.by_object.get(cid, []))
    if not subj_ids and not obj_ids:
        # Neither qnode pinned: scan all edges (category-only / open query).
        candidate_edge_ids.update(graph.edges.keys())

    for eid in candidate_edge_ids:
        edge = graph.edges.get(eid)
        if edge is None or not _predicate_ok(edge, predicates):
            continue
        s_node = graph.nodes.get(edge["subject"])
        o_node = graph.nodes.get(edge["object"])
        if s_node is None or o_node is None:
            continue  # never emit an edge whose endpoints aren't real nodes

        # Try both orientations: which KG endpoint fills which qnode.
        # Orientation A: KG subject -> subj_q, KG object -> obj_q.
        if _qnode_matches(s_node, subj_q) and _qnode_matches(o_node, obj_q):
            _emit(
                kg_nodes, kg_edges, results, graph,
                eid, edge, subj_qid, s_node, obj_qid, o_node, qedge_id,
            )
        # Orientation B (reverse): KG subject -> obj_q, KG object -> subj_q.
        # Only meaningful when it's a genuinely different binding.
        if subj_qid != obj_qid and _qnode_matches(s_node, obj_q) and _qnode_matches(o_node, subj_q):
            _emit(
                kg_nodes, kg_edges, results, graph,
                eid, edge, subj_qid, o_node, obj_qid, s_node, qedge_id,
            )

    return _wrap(query_graph, kg_nodes, kg_edges, results)


def _emit(kg_nodes, kg_edges, results, graph,
          eid, edge, subj_qid, subj_node, obj_qid, obj_node, qedge_id):
    """Add an edge+its nodes to the KG and a result row (TRAPI 1.5 shape)."""
    kg_nodes[subj_node["id"]] = _build_kg_node(subj_node)
    kg_nodes[obj_node["id"]] = _build_kg_node(obj_node)
    kg_edges[eid] = _build_kg_edge(edge)
    results.append(
        {
            "node_bindings": {
                subj_qid: [{"id": subj_node["id"]}],
                obj_qid: [{"id": obj_node["id"]}],
            },
            "analyses": [
                {
                    "resource_id": RESOURCE_ID,
                    "edge_bindings": {qedge_id: [{"id": eid}]},
                }
            ],
        }
    )


def _wrap(query_graph, kg_nodes, kg_edges, results) -> dict:
    return {
        "message": {
            "query_graph": query_graph,
            "knowledge_graph": {"nodes": kg_nodes, "edges": kg_edges},
            "results": results,
        }
    }


# ---------------------------------------------------------------------------
# Metadata stub (/meta_knowledge_graph-style summary)
# ---------------------------------------------------------------------------
def meta_knowledge_graph(graph: Graph) -> dict:
    """A tiny static TRAPI-ish summary of the loaded KGX.

    Reports node categories present (with counts), predicates present (with counts),
    and the edge connectivity by (subject_category, predicate, object_category).
    """
    nodes_by_cat: dict[str, int] = {}
    for n in graph.nodes.values():
        cat = n.get("category") or "biolink:NamedThing"
        nodes_by_cat[cat] = nodes_by_cat.get(cat, 0) + 1

    edges_by_pred: dict[str, int] = {}
    triples: dict[tuple, int] = {}
    for e in graph.edges.values():
        pred = e.get("predicate") or "biolink:related_to"
        edges_by_pred[pred] = edges_by_pred.get(pred, 0) + 1
        s = graph.nodes.get(e["subject"], {}).get("category", "biolink:NamedThing")
        o = graph.nodes.get(e["object"], {}).get("category", "biolink:NamedThing")
        triples[(s, pred, o)] = triples.get((s, pred, o), 0) + 1

    return {
        "nodes": {
            cat: {"count": cnt} for cat, cnt in sorted(nodes_by_cat.items())
        },
        "edges": [
            {
                "subject": s,
                "predicate": p,
                "object": o,
                "count": cnt,
            }
            for (s, p, o), cnt in sorted(triples.items())
        ],
        "predicates": {p: {"count": c} for p, c in sorted(edges_by_pred.items())},
        "counts": {
            "n_nodes": len(graph.nodes),
            "n_edges": len(graph.edges),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", help="path to a TRAPI request JSON file")
    parser.add_argument("--nodes", default=str(DEFAULT_NODES), help="KGX nodes.tsv")
    parser.add_argument("--edges", default=str(DEFAULT_EDGES), help="KGX edges.tsv")
    parser.add_argument("--meta", action="store_true",
                        help="print the meta_knowledge_graph summary instead of querying")
    args = parser.parse_args(argv)

    graph = load_kg(args.nodes, args.edges)

    if args.meta:
        print(json.dumps(meta_knowledge_graph(graph), indent=2, ensure_ascii=False))
        return 0

    if not args.query:
        parser.error("either --query <file.json> or --meta is required")

    request = json.loads(Path(args.query).read_text(encoding="utf-8"))
    response = answer(request, graph)
    print(json.dumps(response, indent=2, ensure_ascii=False))
    # Brief stderr summary so the CLI is useful in a pipeline.
    n_results = len(response["message"]["results"])
    print(f"[trapi] {args.query}: {n_results} result(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
