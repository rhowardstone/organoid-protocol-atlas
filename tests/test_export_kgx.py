"""
S2 KGX export tests — OFFLINE, no network, no filesystem.

Feed tiny inline fake sidecars (a mix of resolved / needs_review / not_found) to
the pure builder and assert the honesty contract:
  - only accepted `resolved` entities become nodes/edges;
  - needs_review + not_found are preserved as review_items and NEVER leak into
    nodes/edges (would poison the graph, per the S1->S2 handoff);
  - KGX required columns present on every node/edge;
  - every node category / edge predicate is a valid Biolink term (allow-list);
  - manifest counts match the emitted graph.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import export_kgx  # noqa: E402


# --- tiny inline fixtures ---------------------------------------------------
SIDECARS = [
    {
        "pmcid": "PMC0000001",
        "organoid_type": "intestinal",
        "entities": [
            {"query": "CHIR99021", "kind": "reagent", "grounding_status": "resolved",
             "curie": "CHEBI:91091", "label": "CHIR99021",
             "biolink_category": "biolink:SmallMolecule", "source": "sri-name-resolver",
             "flags": [], "field": "signaling_factors"},
            {"query": "Wnt3A", "kind": "reagent", "grounding_status": "resolved",
             "curie": "NCBIGene:482208", "label": "WNT3A",
             "biolink_category": "biolink:Gene", "source": "sri-name-resolver",
             "flags": [], "field": "signaling_factors"},
            {"query": "PGE2", "kind": "reagent", "grounding_status": "needs_review",
             "curie": "CHEBI:99999", "label": "15-Keto-PGE2",
             "biolink_category": "biolink:SmallMolecule", "source": "sri-name-resolver",
             "flags": ["label_mismatch"], "field": "signaling_factors"},
            {"query": "Lgr5+", "kind": "cell_line", "grounding_status": "not_found",
             "curie": None, "label": None, "biolink_category": "biolink:CellLine",
             "source": "cellosaurus", "flags": [], "field": "source_cells.line_name"},
        ],
    },
    {
        "pmcid": "PMC0000002",
        "organoid_type": "lung",
        "entities": [
            # same CURIE as paper 1 -> must dedup to ONE node, but a distinct edge.
            {"query": "CHIR99021", "kind": "reagent", "grounding_status": "resolved",
             "curie": "CHEBI:91091", "label": "CHIR99021",
             "biolink_category": "biolink:SmallMolecule", "source": "sri-name-resolver",
             "flags": [], "field": "signaling_factors"},
        ],
    },
]

PREDICTIONS = {
    "PMC0000001": {
        "signaling_factors": [
            {"name": "CHIR99021", "role": "GSK3 inhibitor",
             "concentration": {"value": 3.0, "unit": "μM"},
             "evidence": {"quote": "CHIR99021 was added at 3 μM to activate Wnt."}},
            {"name": "Wnt3A", "role": "signaling",
             "concentration": None, "evidence": {"quote": "Wnt3A in the niche medium."}},
        ],
    },
    "PMC0000002": {
        "signaling_factors": [
            {"name": "CHIR99021", "role": "GSK3 inhibitor",
             "concentration": {"value": 5.0, "unit": "μM"}, "evidence": {"quote": "5 μM CHIR."}},
        ],
    },
}


def _build():
    return export_kgx.build_kgx(SIDECARS, PREDICTIONS)


# --- tests ------------------------------------------------------------------
def test_only_resolved_become_nodes():
    nodes, _, _, _ = _build()
    node_ids = {n["id"] for n in nodes}
    # accepted resolved CURIEs + one publication node per paper:
    assert "CHEBI:91091" in node_ids
    assert "NCBIGene:482208" in node_ids
    assert "PMC:0000001" in node_ids and "PMC:0000002" in node_ids
    # needs_review / not_found CURIEs MUST NOT be nodes:
    assert "CHEBI:99999" not in node_ids


def test_resolved_curie_deduped_to_single_node():
    nodes, _, _, _ = _build()
    chir = [n for n in nodes if n["id"] == "CHEBI:91091"]
    assert len(chir) == 1


def test_needs_review_and_not_found_go_to_review_only():
    nodes, edges, review_items, _ = _build()
    statuses = {r["grounding_status"] for r in review_items}
    assert statuses == {"needs_review", "not_found"}
    queries = {r["query"] for r in review_items}
    assert queries == {"PGE2", "Lgr5+"}
    # and they never leak into the graph
    graph_curies = {n["id"] for n in nodes} | {e["object"] for e in edges}
    assert "CHEBI:99999" not in graph_curies  # needs_review CURIE
    for r in review_items:
        if r["curie"]:
            assert r["curie"] not in graph_curies


def test_edges_subject_is_publication_object_is_entity():
    _, edges, _, _ = _build()
    for e in edges:
        assert e["subject"].startswith(("PMC:", "PMID:"))
        assert e["predicate"] == export_kgx.USES_PREDICATE
        assert e["object"].startswith(("CHEBI:", "NCBIGene:"))
    # one edge per (paper, resolved entity): 2 in paper1 + 1 in paper2 = 3
    assert len(edges) == 3


def test_edge_carries_qualifiers_from_prediction():
    _, edges, _, _ = _build()
    chir1 = [e for e in edges if e["subject"] == "PMC:0000001" and e["object"] == "CHEBI:91091"][0]
    assert chir1["role"] == "GSK3 inhibitor"
    assert chir1["concentration_value"] == 3.0
    assert chir1["concentration_unit"] == "μM"
    assert chir1["organoid_type"] == "intestinal"
    assert chir1["evidence"] and len(chir1["evidence"]) <= export_kgx.EVIDENCE_SNIPPET_MAX


def test_required_columns_present():
    nodes, edges, _, _ = _build()
    for n in nodes:
        for col in export_kgx.NODE_COLUMNS:
            assert col in n
    required_edge = ("id", "subject", "predicate", "object",
                     "knowledge_level", "agent_type", "primary_knowledge_source", "publications")
    for e in edges:
        for col in required_edge:
            assert col in e


def test_categories_and_predicates_are_biolink_valid():
    nodes, edges, _, _ = _build()
    ok, _used_real, errors = export_kgx.validate_kgx(nodes, edges)
    assert ok, errors
    for n in nodes:
        assert n["category"] in export_kgx.ALLOWED_NODE_CATEGORIES
    for e in edges:
        assert e["predicate"] in export_kgx.ALLOWED_PREDICATES


def test_manifest_counts_match_graph():
    nodes, edges, review_items, manifest = _build()
    assert manifest["n_nodes"] == len(nodes)
    assert manifest["n_edges"] == len(edges)
    assert manifest["n_review_items"] == len(review_items)
    assert manifest["n_papers"] == 2
    assert sum(manifest["n_nodes_by_category"].values()) == len(nodes)
    assert sum(manifest["n_edges_by_predicate"].values()) == len(edges)
    # 3 resolved entity-instances out of 5 total entities across the two papers
    assert manifest["entities_total"] == 5
    assert manifest["entities_resolved"] == 3
    assert manifest["resolved_rate"] == round(3 / 5, 4)


def test_no_fabricated_curies():
    nodes, _, _, _ = _build()
    allowed = {"CHEBI:91091", "NCBIGene:482208", "PMC:0000001", "PMC:0000002"}
    assert {n["id"] for n in nodes} == allowed
