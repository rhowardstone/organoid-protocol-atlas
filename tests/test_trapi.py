"""
TRAPI responder tests — OFFLINE.

Most assertions run against a tiny inline fake graph (4 nodes / 3 edges) so the
TRAPI shape is checked deterministically. One smoke test parses the REAL committed
exports/kgx/*.tsv and asserts an example query returns >= 1 result.

Single-hop only (multi-hop is future work).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import trapi  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "pipeline" / "trapi_examples"


# --- tiny inline fake graph -------------------------------------------------
def _fake_graph():
    g = trapi.Graph()
    nodes = [
        {"id": "PMC:1", "category": "biolink:Publication", "name": "Paper 1",
         "provided_by": "infores:test"},
        {"id": "CHEBI:100", "category": "biolink:SmallMolecule", "name": "DrugA",
         "provided_by": "infores:test"},
        {"id": "NCBIGene:9", "category": "biolink:Gene", "name": "GeneB",
         "provided_by": "infores:test"},
        {"id": "CHEBI:200", "category": "biolink:SmallMolecule", "name": "DrugC",
         "provided_by": "infores:test"},
    ]
    for n in nodes:
        g.nodes[n["id"]] = n
    edges = [
        {"id": "e1", "subject": "PMC:1", "predicate": "biolink:mentions",
         "object": "CHEBI:100", "primary_knowledge_source": "infores:test",
         "role": "agonist"},
        {"id": "e2", "subject": "PMC:1", "predicate": "biolink:mentions",
         "object": "NCBIGene:9", "primary_knowledge_source": "infores:test"},
        {"id": "e3", "subject": "PMC:1", "predicate": "biolink:mentions",
         "object": "CHEBI:200", "primary_knowledge_source": "infores:test"},
    ]
    for e in edges:
        g.edges[e["id"]] = e
        g.by_subject.setdefault(e["subject"], []).append(e["id"])
        g.by_object.setdefault(e["object"], []).append(e["id"])
    return g


def _query(subj_q, obj_q, predicates=None):
    edge = {"subject": "s", "object": "o"}
    if predicates is not None:
        edge["predicates"] = predicates
    return {
        "message": {
            "query_graph": {
                "nodes": {"s": subj_q, "o": obj_q},
                "edges": {"e0": edge},
            }
        }
    }


def _ids_in_binding(result, qnode_id):
    return [b["id"] for b in result["node_bindings"][qnode_id]]


# --- structural / shape -----------------------------------------------------
def test_pinned_subject_returns_objects():
    g = _fake_graph()
    resp = _q_answer(g, {"ids": ["PMC:1"]}, {})
    msg = resp["message"]
    objs = {_ids_in_binding(r, "o")[0] for r in msg["results"]}
    assert objs == {"CHEBI:100", "NCBIGene:9", "CHEBI:200"}
    # every result pins the subject qnode back to PMC:1
    assert all(_ids_in_binding(r, "s") == ["PMC:1"] for r in msg["results"])


def test_result_trapi_shape():
    g = _fake_graph()
    resp = _q_answer(g, {"ids": ["PMC:1"]}, {"categories": ["biolink:SmallMolecule"]})
    r = resp["message"]["results"][0]
    # node_bindings present for both qnodes, each a list of {"id": ...}
    assert set(r["node_bindings"].keys()) == {"s", "o"}
    assert "id" in r["node_bindings"]["s"][0]
    # analyses carry edge_bindings + resource_id (TRAPI 1.5)
    analysis = r["analyses"][0]
    assert analysis["resource_id"] == trapi.RESOURCE_ID
    assert "e0" in analysis["edge_bindings"]
    assert "id" in analysis["edge_bindings"]["e0"][0]


def test_pinned_object_reverse_query():
    g = _fake_graph()
    # pin the OBJECT (reagent), publications open -> reverse-direction match
    resp = _q_answer(g, {"categories": ["biolink:Publication"]}, {"ids": ["CHEBI:100"]})
    results = resp["message"]["results"]
    assert len(results) == 1
    assert _ids_in_binding(results[0], "s") == ["PMC:1"]
    assert _ids_in_binding(results[0], "o") == ["CHEBI:100"]


def test_category_constraint_filters():
    g = _fake_graph()
    resp = _q_answer(g, {"ids": ["PMC:1"]}, {"categories": ["biolink:SmallMolecule"]})
    objs = {_ids_in_binding(r, "o")[0] for r in resp["message"]["results"]}
    assert objs == {"CHEBI:100", "CHEBI:200"}  # NCBIGene:9 excluded


def test_predicate_constraint():
    g = _fake_graph()
    # a predicate not in the graph -> no matches
    resp = _q_answer(g, {"ids": ["PMC:1"]}, {}, predicates=["biolink:treats"])
    assert resp["message"]["results"] == []
    # the real predicate -> matches
    resp2 = _q_answer(g, {"ids": ["PMC:1"]}, {}, predicates=["biolink:mentions"])
    assert len(resp2["message"]["results"]) == 3


def test_unmatched_query_returns_empty_not_error():
    g = _fake_graph()
    resp = _q_answer(g, {"ids": ["PMC:does-not-exist"]}, {})
    assert resp["message"]["results"] == []
    assert resp["message"]["knowledge_graph"]["nodes"] == {}
    assert resp["message"]["knowledge_graph"]["edges"] == {}


def test_no_fabricated_ids():
    g = _fake_graph()
    resp = _q_answer(g, {"ids": ["PMC:1"]}, {})
    kg = resp["message"]["knowledge_graph"]
    # every KG node id exists in the input graph
    for nid in kg["nodes"]:
        assert nid in g.nodes
    # every KG edge id exists, and its endpoints exist in the input graph
    for eid, edge in kg["edges"].items():
        assert eid in g.edges
        assert edge["subject"] in g.nodes
        assert edge["object"] in g.nodes
    # every binding id is a real KG node id present in the knowledge_graph
    for r in resp["message"]["results"]:
        for binds in r["node_bindings"].values():
            for b in binds:
                assert b["id"] in kg["nodes"]


def test_multihop_returns_empty():
    g = _fake_graph()
    # three qnodes / two qedges -> unsupported -> empty (not an error)
    req = {
        "message": {
            "query_graph": {
                "nodes": {"a": {"ids": ["PMC:1"]}, "b": {}, "c": {}},
                "edges": {
                    "e0": {"subject": "a", "object": "b"},
                    "e1": {"subject": "b", "object": "c"},
                },
            }
        }
    }
    resp = trapi.answer(req, g)
    assert resp["message"]["results"] == []


def test_meta_knowledge_graph():
    g = _fake_graph()
    meta = trapi.meta_knowledge_graph(g)
    assert meta["counts"]["n_nodes"] == 4
    assert meta["counts"]["n_edges"] == 3
    assert meta["predicates"]["biolink:mentions"]["count"] == 3
    assert "biolink:SmallMolecule" in meta["nodes"]


# --- real-KGX smoke test ----------------------------------------------------
def test_real_kg_loads_and_answers():
    nodes_tsv = REPO / "exports" / "kgx" / "nodes.tsv"
    edges_tsv = REPO / "exports" / "kgx" / "edges.tsv"
    if not nodes_tsv.exists() or not edges_tsv.exists():
        import pytest
        pytest.skip("committed KGX not present")
    g = trapi.load_kg(nodes_tsv, edges_tsv)
    assert len(g.nodes) > 100
    assert len(g.edges) > 100
    req = json.loads((EXAMPLES / "01_publication_mentions.json").read_text())
    resp = trapi.answer(req, g)
    assert len(resp["message"]["results"]) >= 1
    # no fabrication against the real graph either
    for nid in resp["message"]["knowledge_graph"]["nodes"]:
        assert nid in g.nodes


# --- CURIE compliance -------------------------------------------------------
def test_edge_attr_curies_are_single_colon():
    """Every EDGE_ATTR_CURIE value must be a valid CURIE (exactly one colon)."""
    for col, curie in trapi.EDGE_ATTR_CURIE.items():
        assert curie.count(":") == 1, (
            f"EDGE_ATTR_CURIE[{col!r}] = {curie!r} — invalid CURIE (must have exactly one colon)"
        )


def test_build_kg_edge_no_double_colon_attribute_type_ids():
    """_build_kg_edge must not produce attribute_type_ids with two colons."""
    edge = {
        "id": "e_test",
        "subject": "PMC:1",
        "predicate": "biolink:mentions",
        "object": "CHEBI:100",
        "primary_knowledge_source": "infores:test",
        "knowledge_level": "prediction",
        "agent_type": "automated_agent",
        "publications": "PMID:12345",
        "role": "catalyst",
        "concentration_value": "10.0",
        "concentration_unit": "ng/mL",
        "organoid_type": "intestinal",
        "evidence": "EGF was used at 10 ng/mL",
    }
    result = trapi._build_kg_edge(edge)
    for attr in result["attributes"]:
        tid = attr["attribute_type_id"]
        assert tid.count(":") == 1, f"Attribute type_id has two colons: {tid!r}"


def test_build_kg_edge_primary_knowledge_source_not_in_attributes():
    """primary_knowledge_source belongs in sources, not attributes."""
    edge = {
        "id": "e_test",
        "subject": "PMC:1",
        "predicate": "biolink:mentions",
        "object": "CHEBI:100",
        "primary_knowledge_source": "infores:test",
        "knowledge_level": "prediction",
    }
    result = trapi._build_kg_edge(edge)
    attr_type_ids = {a["attribute_type_id"] for a in result["attributes"]}
    # No attribute should reference primary_knowledge_source
    for tid in attr_type_ids:
        assert "primary_knowledge_source" not in tid
    # But it must appear in sources
    assert any(
        s.get("resource_role") == "primary_knowledge_source"
        for s in result["sources"]
    )


def test_build_kg_edge_standard_biolink_attributes_used():
    """knowledge_level, agent_type, publications use biolink: prefix."""
    edge = {
        "id": "e_test",
        "subject": "PMC:1",
        "predicate": "biolink:mentions",
        "object": "CHEBI:100",
        "primary_knowledge_source": "infores:test",
        "knowledge_level": "prediction",
        "agent_type": "automated_agent",
        "publications": "PMID:99",
    }
    result = trapi._build_kg_edge(edge)
    by_value = {a["value"]: a["attribute_type_id"] for a in result["attributes"]}
    assert by_value["prediction"] == "biolink:knowledge_level"
    assert by_value["automated_agent"] == "biolink:agent_type"
    assert by_value["PMID:99"] == "biolink:publications"


def test_full_response_no_double_colon_attribute_type_ids():
    """End-to-end: TRAPI answer over the fake graph has no double-colon attribute_type_ids."""
    g = _fake_graph()
    resp = _q_answer(g, {"ids": ["PMC:1"]}, {})
    for _eid, edge in resp["message"]["knowledge_graph"]["edges"].items():
        for attr in edge.get("attributes", []):
            tid = attr["attribute_type_id"]
            assert tid.count(":") == 1, f"Double-colon attribute_type_id in response: {tid!r}"


# --- helper -----------------------------------------------------------------
def _q_answer(g, subj_q, obj_q, predicates=None):
    return trapi.answer(_query(subj_q, obj_q, predicates), g)
