"""
TRAPI (Translator Reasoner API) 1.5 endpoint — a Datasette plugin that makes the
committed Biolink KGX (exports/kgx/{nodes,edges}.tsv) live-queryable on the hosted
Atlas, completing the chain:

    paper -> grounded extraction -> SRI Biolink CURIEs -> KGX -> TRAPI-queryable (LIVE)

This is a thin serve-layer wrapper. ALL the graph logic lives in pipeline/trapi.py
(load_kg / answer / meta_knowledge_graph); this module only:
  * loads the KGX once and caches the Graph in module state (lazy, on first request),
  * exposes pure request handlers so they can be unit-tested without a live server,
  * registers Datasette routes that are thin wrappers over those handlers.

Routes (mirrors ask.py's register_routes pattern):
  - POST /trapi/query                  -> TRAPI response for a single-hop query
  - GET  /trapi/meta_knowledge_graph   -> KGX summary (categories/predicates/counts)
  - GET  /trapi                        -> minimal HTML explainer + try-it console

Discipline (same ethos as ask.py): degrade gracefully. If exports/kgx is missing we
return an honest "KG not available" rather than crashing; malformed request bodies
return a TRAPI-shaped 400 error, never a 500. Pure stdlib + datasette. No network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from datasette import hookimpl, Response

# pipeline/trapi.py holds the real logic. Add the repo's pipeline dir to sys.path
# so this works whether Datasette is launched from the repo root or elsewhere
# (mirrors the sys.path.insert pattern used across the pipeline/tests).
REPO = Path(__file__).resolve().parent.parent.parent
PIPELINE = REPO / "pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

import trapi  # noqa: E402  (pipeline/trapi.py)

NODES_TSV = REPO / "exports" / "kgx" / "nodes.tsv"
EDGES_TSV = REPO / "exports" / "kgx" / "edges.tsv"

# Cap how many results we serialize per query so a wide-open query can't blow up
# the response. The underlying answer() still computes honestly; we only truncate
# the results list (and prune the knowledge_graph to what the kept results bind).
MAX_RESULTS = 1000

# Cached graph + a flag so we don't retry loading on every request once we know the
# KGX is absent. (None, False) = not yet loaded; (None, True) = tried, unavailable.
_GRAPH = None
_LOAD_ATTEMPTED = False


# ---------------------------------------------------------------------------
# Graph loading (cached in module state)
# ---------------------------------------------------------------------------
def get_graph(nodes_tsv=NODES_TSV, edges_tsv=EDGES_TSV):
    """Return the cached KGX Graph, loading it once. None if the KGX is absent."""
    global _GRAPH, _LOAD_ATTEMPTED
    if _GRAPH is not None:
        return _GRAPH
    if _LOAD_ATTEMPTED:
        return None
    _LOAD_ATTEMPTED = True
    if not Path(nodes_tsv).exists() or not Path(edges_tsv).exists():
        return None
    try:
        _GRAPH = trapi.load_kg(nodes_tsv, edges_tsv)
    except Exception:  # noqa: BLE001 — never crash serve startup on a bad KGX
        _GRAPH = None
    return _GRAPH


def _kg_unavailable() -> dict:
    """A TRAPI-shaped, honest 'no KG here' payload (not an exception)."""
    return {
        "message": {"query_graph": {}, "knowledge_graph": {"nodes": {}, "edges": {}},
                    "results": []},
        "status": "KGNotAvailable",
        "description": "The knowledge graph (exports/kgx) is not available on this "
                       "deployment, so TRAPI queries cannot be answered here.",
    }


def _trapi_error(description: str) -> dict:
    """A TRAPI-shaped error body (TRAPI responses carry status/description fields)."""
    return {
        "message": {"query_graph": {}, "knowledge_graph": {"nodes": {}, "edges": {}},
                    "results": []},
        "status": "QueryNotTraversable",
        "description": description,
    }


def _cap_results(response: dict, max_results: int = MAX_RESULTS) -> dict:
    """Truncate results to max_results and prune the KG to bound the payload."""
    msg = response.get("message", {}) or {}
    results = msg.get("results", []) or []
    if len(results) <= max_results:
        return response
    kept = results[:max_results]
    # Keep only KG nodes/edges that the kept results actually bind, so the trimmed
    # response stays internally consistent (no orphan / dangling references).
    keep_nodes, keep_edges = set(), set()
    for r in kept:
        for binds in (r.get("node_bindings") or {}).values():
            for b in binds:
                keep_nodes.add(b.get("id"))
        for a in (r.get("analyses") or []):
            for binds in (a.get("edge_bindings") or {}).values():
                for b in binds:
                    keep_edges.add(b.get("id"))
    kg = msg.get("knowledge_graph", {}) or {}
    msg["results"] = kept
    msg["knowledge_graph"] = {
        "nodes": {k: v for k, v in (kg.get("nodes") or {}).items() if k in keep_nodes},
        "edges": {k: v for k, v in (kg.get("edges") or {}).items() if k in keep_edges},
    }
    response["message"] = msg
    response["description"] = f"results truncated to {max_results}"
    return response


# ---------------------------------------------------------------------------
# Pure handlers (unit-testable without Datasette)
# ---------------------------------------------------------------------------
def handle_query(body_bytes, graph, max_results: int = MAX_RESULTS):
    """Core POST /trapi/query logic.

    Returns (status_code, dict). Never raises for bad input:
      * missing KG          -> (503, KG-unavailable TRAPI body)
      * unparseable body    -> (400, TRAPI error body)
      * not a TRAPI message -> (400, TRAPI error body)
      * valid query         -> (200, TRAPI response), capped to max_results
    """
    if graph is None:
        return 503, _kg_unavailable()

    if isinstance(body_bytes, (bytes, bytearray)):
        raw = bytes(body_bytes).decode("utf-8", errors="replace")
    else:
        raw = body_bytes or ""
    if not raw.strip():
        return 400, _trapi_error("empty request body; expected a TRAPI "
                                 '{"message": {"query_graph": ...}}')
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        return 400, _trapi_error("request body is not valid JSON")
    if not isinstance(body, dict) or "message" not in body:
        return 400, _trapi_error('request must be a JSON object with a "message" key')

    try:
        response = trapi.answer(body, graph)
    except Exception as exc:  # noqa: BLE001 — surface as TRAPI 400, never a 500
        return 400, _trapi_error(f"could not process query_graph: {exc}")
    return 200, _cap_results(response, max_results)


def handle_meta(graph):
    """Core GET /trapi/meta_knowledge_graph logic. Returns (status_code, dict)."""
    if graph is None:
        return 503, _kg_unavailable()
    return 200, trapi.meta_knowledge_graph(graph)


# ---------------------------------------------------------------------------
# Datasette route wrappers (thin)
# ---------------------------------------------------------------------------
async def trapi_query(datasette, request):
    body_bytes = await request.post_body()
    status, payload = handle_query(body_bytes, get_graph())
    return Response.json(payload, status=status)


async def trapi_meta(datasette, request):
    status, payload = handle_meta(get_graph())
    return Response.json(payload, status=status)


async def trapi_home(datasette, request):
    return Response.html(_home_html(get_graph()))


# ---------------------------------------------------------------------------
# Minimal HTML explainer + try-it console (site style: atlas.css + apa-topbar)
# ---------------------------------------------------------------------------
_EXAMPLE_QUERY = {
    "message": {
        "query_graph": {
            "nodes": {
                "pub": {"ids": ["PMC:10000618"], "categories": ["biolink:Publication"]},
                "thing": {},
            },
            "edges": {
                "e0": {"subject": "pub", "object": "thing",
                       "predicates": ["biolink:mentions"]},
            },
        }
    }
}


def _meta_summary_html(graph) -> str:
    if graph is None:
        return ('<p class="apa-sub">The knowledge graph is not available on this '
                'deployment, so the live console below will report it honestly.</p>')
    meta = trapi.meta_knowledge_graph(graph)
    esc = _esc
    cats = "".join(
        f"<li><code>{esc(c)}</code> &middot; {d['count']}</li>"
        for c, d in meta["nodes"].items())
    preds = "".join(
        f"<li><code>{esc(p)}</code> &middot; {d['count']}</li>"
        for p, d in meta["predicates"].items())
    return (
        f'<p class="apa-sub">{meta["counts"]["n_nodes"]} nodes and '
        f'{meta["counts"]["n_edges"]} edges loaded.</p>'
        f"<div style='display:flex;gap:2rem;flex-wrap:wrap'>"
        f"<div><h3>Node categories</h3><ul>{cats}</ul></div>"
        f"<div><h3>Predicates</h3><ul>{preds}</ul></div></div>"
    )


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _home_html(graph) -> str:
    example = json.dumps(_EXAMPLE_QUERY, indent=2)
    summary = _meta_summary_html(graph)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TRAPI endpoint - Organoid Protocol Atlas</title>
  <link rel="stylesheet" href="/static/atlas.css">
</head>
<body class="index">
<div class="apa-topbar">
  <span class="dot"></span> <a href="/">ORGANOID PROTOCOL ATLAS</a>
  <span class="dot"></span> <a href="/atlas/protocols">Protocols</a>
  <span class="dot"></span> <a href="/explore">Explore</a>
  <span class="dot"></span> <a href="/heatmap">Heatmap</a>
  <span class="dot"></span> <a href="/consensus">Consensus</a>
  <span class="dot"></span> <a href="/dashboard">Dashboard</a>
  <span class="dot"></span> <a href="/ask">Ask</a>
</div>

<div class="apa-ask-head">
  <div class="apa-kicker">TRAPI 1.5 - Translator Reasoner API over the Biolink KGX</div>
  <h1>Query the Atlas knowledge graph (TRAPI)</h1>
  <p class="apa-sub">The extracted, SRI-grounded organoid knowledge graph is served as
  a TRAPI 1.5 endpoint. Single-hop queries are supported: one edge connecting two
  nodes, where a node may pin <code>ids</code> (Biolink CURIEs) and/or constrain
  <code>categories</code>, and the edge may constrain <code>predicates</code>.</p>
  <ul>
    <li><code>POST /trapi/query</code> - body is a TRAPI message; returns a TRAPI response.</li>
    <li><code>GET /trapi/meta_knowledge_graph</code> - the KG summary (categories, predicates, counts).</li>
  </ul>
  {summary}
</div>

<div class="apa-ask-head">
  <h2>Try it</h2>
  <p class="apa-sub">Edit the TRAPI query below and run it against the live graph.</p>
  <textarea id="q" rows="18" style="width:100%;font-family:monospace;font-size:13px">{_esc(example)}</textarea>
  <div class="apa-ask-form"><button id="run" type="button">Run query</button></div>
</div>

<div id="out" class="apa-ask-out"></div>

<script>
const esc = s => (s==null?'':String(s)).replace(/[&<>"]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
const out = document.getElementById('out');
document.getElementById('run').addEventListener('click', async () => {{
  out.innerHTML = '<div class="apa-ask-loading">Running TRAPI query...</div>';
  let body;
  try {{ body = JSON.parse(document.getElementById('q').value); }}
  catch(e) {{ out.innerHTML = '<div class="apa-ask-card">Not valid JSON: ' + esc(e.message) + '</div>'; return; }}
  let resp, data;
  try {{
    resp = await fetch('/trapi/query', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(body)}});
    data = await resp.json();
  }} catch(e) {{ out.innerHTML = '<div class="apa-ask-card">Could not reach the TRAPI endpoint.</div>'; return; }}
  const n = (data.message && data.message.results) ? data.message.results.length : 0;
  out.innerHTML = '<div class="apa-ask-card"><div class="apa-ask-q">HTTP ' + resp.status + ' &middot; ' + n + ' result(s)</div>'
    + '<pre style="overflow:auto;max-height:60vh">' + esc(JSON.stringify(data, null, 2)) + '</pre></div>';
}});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Route registration (mirrors ask.py)
# ---------------------------------------------------------------------------
@hookimpl
def register_routes():
    return [
        (r"^/trapi/query$", trapi_query),
        (r"^/trapi/meta_knowledge_graph$", trapi_meta),
        (r"^/trapi$", trapi_home),
    ]
