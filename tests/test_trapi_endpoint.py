"""
TRAPI Datasette-endpoint tests — OFFLINE, no live server, no network.

We exercise the plugin's PURE handler logic (handle_query / handle_meta) directly,
rather than spinning up Datasette. The Datasette routes are thin wrappers over these
handlers, so testing the handlers covers the request-handling contract:

  * POST a valid single-hop query -> (200, TRAPI-shaped dict with results)
  * POST malformed / empty JSON    -> (400, TRAPI error shape) — never a crash
  * POST a non-TRAPI object        -> (400, TRAPI error shape)
  * GET meta                       -> (200, categories + predicate counts)
  * missing KG (graph=None)        -> (503, honest TRAPI-shaped "not available")

Most assertions use a tiny inline graph; one smoke test runs against the REAL
committed exports/kgx if present.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
sys.path.insert(0, str(REPO / "serve" / "plugins"))

import trapi  # noqa: E402  (pipeline/trapi.py)
import trapi_endpoint as te  # noqa: E402  (serve/plugins/trapi_endpoint.py)


# --- tiny inline graph ------------------------------------------------------
def _fake_graph():
    g = trapi.Graph()
    nodes = [
        {"id": "PMC:1", "category": "biolink:Publication", "name": "Paper 1"},
        {"id": "CHEBI:100", "category": "biolink:SmallMolecule", "name": "DrugA"},
        {"id": "NCBIGene:9", "category": "biolink:Gene", "name": "GeneB"},
    ]
    for n in nodes:
        g.nodes[n["id"]] = n
    edges = [
        {"id": "e1", "subject": "PMC:1", "predicate": "biolink:mentions",
         "object": "CHEBI:100", "primary_knowledge_source": "infores:test"},
        {"id": "e2", "subject": "PMC:1", "predicate": "biolink:mentions",
         "object": "NCBIGene:9", "primary_knowledge_source": "infores:test"},
    ]
    for e in edges:
        g.edges[e["id"]] = e
        g.by_subject.setdefault(e["subject"], []).append(e["id"])
        g.by_object.setdefault(e["object"], []).append(e["id"])
    return g


_SINGLE_HOP = {
    "message": {
        "query_graph": {
            "nodes": {"pub": {"ids": ["PMC:1"]}, "thing": {}},
            "edges": {"e0": {"subject": "pub", "object": "thing",
                             "predicates": ["biolink:mentions"]}},
        }
    }
}


# --- POST /trapi/query ------------------------------------------------------
def test_valid_single_hop_returns_trapi_results():
    g = _fake_graph()
    status, payload = te.handle_query(json.dumps(_SINGLE_HOP).encode(), g)
    assert status == 200
    msg = payload["message"]
    assert "query_graph" in msg and "knowledge_graph" in msg
    results = msg["results"]
    assert len(results) == 2  # PMC:1 mentions DrugA and GeneB
    r = results[0]
    assert set(r["node_bindings"].keys()) == {"pub", "thing"}
    assert "id" in r["node_bindings"]["pub"][0]
    assert r["analyses"][0]["resource_id"] == trapi.RESOURCE_ID
    # no fabrication: every KG node id is a real graph node
    for nid in msg["knowledge_graph"]["nodes"]:
        assert nid in g.nodes


def test_malformed_json_returns_400_not_crash():
    g = _fake_graph()
    status, payload = te.handle_query(b"{not valid json", g)
    assert status == 400
    # TRAPI-shaped error body (empty results + status/description), not a stack trace
    assert payload["message"]["results"] == []
    assert "status" in payload and "description" in payload


def test_empty_body_returns_400():
    g = _fake_graph()
    status, payload = te.handle_query(b"", g)
    assert status == 400
    assert payload["message"]["results"] == []


def test_non_trapi_object_returns_400():
    g = _fake_graph()
    status, payload = te.handle_query(json.dumps({"foo": "bar"}).encode(), g)
    assert status == 400
    assert "message" in payload  # missing "message" key in request -> 400


def test_string_body_also_accepted():
    # handler accepts str as well as bytes (defensive)
    g = _fake_graph()
    status, payload = te.handle_query(json.dumps(_SINGLE_HOP), g)
    assert status == 200
    assert len(payload["message"]["results"]) == 2


# --- GET /trapi/meta_knowledge_graph ---------------------------------------
def test_meta_returns_categories_and_predicate_counts():
    g = _fake_graph()
    status, meta = te.handle_meta(g)
    assert status == 200
    assert meta["counts"]["n_nodes"] == 3
    assert meta["counts"]["n_edges"] == 2
    assert meta["predicates"]["biolink:mentions"]["count"] == 2
    assert "biolink:Publication" in meta["nodes"]
    assert "biolink:SmallMolecule" in meta["nodes"]


# --- graceful degradation (KG missing) -------------------------------------
def test_query_without_kg_degrades_gracefully():
    status, payload = te.handle_query(json.dumps(_SINGLE_HOP).encode(), None)
    assert status == 503
    assert payload["status"] == "KGNotAvailable"
    assert payload["message"]["results"] == []  # honest, not a crash


def test_meta_without_kg_degrades_gracefully():
    status, payload = te.handle_meta(None)
    assert status == 503
    assert payload["status"] == "KGNotAvailable"


# --- result cap -------------------------------------------------------------
def test_results_are_capped_and_kg_pruned():
    g = _fake_graph()
    open_query = {"message": {"query_graph": {
        "nodes": {"a": {}, "b": {}},
        "edges": {"e0": {"subject": "a", "object": "b"}},
    }}}
    status, payload = te.handle_query(json.dumps(open_query).encode(), g, max_results=1)
    assert status == 200
    assert len(payload["message"]["results"]) == 1
    # KG pruned to only what the kept result binds (no orphan nodes/edges)
    kg = payload["message"]["knowledge_graph"]
    bound_nodes = {b["id"] for r in payload["message"]["results"]
                   for binds in r["node_bindings"].values() for b in binds}
    assert set(kg["nodes"].keys()) <= bound_nodes
    assert payload["description"].startswith("results truncated")


# --- real-KGX smoke ---------------------------------------------------------
def test_real_kg_query_smoke():
    nodes_tsv = REPO / "exports" / "kgx" / "nodes.tsv"
    edges_tsv = REPO / "exports" / "kgx" / "edges.tsv"
    if not nodes_tsv.exists() or not edges_tsv.exists():
        import pytest
        pytest.skip("committed KGX not present")
    g = trapi.load_kg(nodes_tsv, edges_tsv)
    status, payload = te.handle_query(json.dumps(te._EXAMPLE_QUERY).encode(), g)
    assert status == 200
    assert len(payload["message"]["results"]) >= 1
    # meta over the real graph too
    mstatus, meta = te.handle_meta(g)
    assert mstatus == 200
    assert meta["counts"]["n_nodes"] > 100
