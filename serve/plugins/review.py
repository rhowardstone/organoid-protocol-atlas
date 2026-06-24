"""
serve/plugins/review.py — Schema-agnostic structured-data annotation plugin.

Routes:
  GET  /review/<pmcid>              — side-by-side review page
  POST /api/propose                 — submit an edit proposal (human or agent)
  GET  /api/proposals               — list proposals (?pmcid=, ?status=, ?field=)
  POST /api/proposals/<id>/accept   — accept a proposal (sets status=accepted)
  POST /api/proposals/<id>/reject   — reject a proposal (sets status=rejected)
  GET  /api/protocol/<pmcid>        — full structured record as JSON (agent-readable)

Auth:
  Humans: no account needed; proposals are always pending until reviewed.
  Agents: X-Codex-Agent header for logging; any value accepted.

The plugin is schema-agnostic: it reads whatever columns exist in the protocols
and reagents tables and renders them generically. The only schema-specific knowledge
is the FIELD_META dict below, which annotates fields with human-readable labels and
the evidence_column that grounds each one.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from datasette import hookimpl
from datasette.utils.asgi import Response, Request

# ---------------------------------------------------------------------------
# Field metadata — schema-specific display hints only. The rest is generic.
# ---------------------------------------------------------------------------

FIELD_META: dict[str, dict] = {
    "organoid_type":     {"label": "Organoid / model type", "editable": True},
    "species":           {"label": "Species", "editable": True},
    "source_cell_type":  {"label": "Source cell type", "editable": True},
    "matrix":            {"label": "Matrix / scaffold", "editable": True},
    "base_media":        {"label": "Base medium", "editable": True},
    "passaging":         {"label": "Passaging", "editable": True},
    "timeline":          {"label": "Timeline", "editable": True},
    "assay_endpoints":   {"label": "Assay endpoints", "editable": True},
    "first_author":      {"label": "First author", "editable": False},
    "year":              {"label": "Year", "editable": False},
    "journal":           {"label": "Journal", "editable": False},
    "doi":               {"label": "DOI", "editable": False},
    "grounding_rate":    {"label": "Grounding rate", "editable": False},
}

PROPOSALS_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "proposals.db"


# ---------------------------------------------------------------------------
# Proposals DB (separate from atlas.db — no schema migration needed)
# ---------------------------------------------------------------------------

def _proposals_conn() -> sqlite3.Connection:
    PROPOSALS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PROPOSALS_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proposals (
            id TEXT PRIMARY KEY,
            pmcid TEXT NOT NULL,
            field TEXT NOT NULL,
            old_value TEXT,
            proposed_value TEXT NOT NULL,
            evidence_span TEXT,
            proposed_by TEXT NOT NULL,
            agent_id TEXT,
            proposed_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reviewed_by TEXT,
            reviewed_at TEXT,
            notes TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_proposals_pmcid ON proposals(pmcid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status)")
    conn.commit()
    return conn


def _get_proposal(proposal_id: str) -> Optional[dict]:
    conn = _proposals_conn()
    row = conn.execute("SELECT * FROM proposals WHERE id=?", [proposal_id]).fetchone()
    return dict(row) if row else None


def _list_proposals(pmcid=None, status=None, field=None) -> list[dict]:
    conn = _proposals_conn()
    where, params = [], []
    if pmcid:
        where.append("pmcid=?"); params.append(pmcid)
    if status:
        where.append("status=?"); params.append(status)
    if field:
        where.append("field=?"); params.append(field)
    sql = "SELECT * FROM proposals"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY proposed_at DESC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def review_page(scope, receive, send):
    """GET /review/<pmcid> — side-by-side review page."""
    request = Request(scope, receive)
    pmcid = scope["url_route"]["kwargs"]["pmcid"]
    datasette = scope["datasette"]

    # Fetch protocol record
    try:
        result = await datasette.execute("atlas", "SELECT * FROM protocols WHERE pmcid=?", [pmcid])
        row = result.first()
    except Exception:
        row = None

    if not row:
        return Response.html(
            f"<h1>404 — protocol {pmcid!r} not found</h1>", status=404
        )

    protocol = dict(zip(result.columns, row))

    # Fetch reagents with evidence quotes
    try:
        reagent_result = await datasette.execute(
            "atlas",
            "SELECT name, canonical, role, value, canonical_unit, evidence_quote, grounded, kind "
            "FROM reagents WHERE pmcid=? ORDER BY kind, name",
            [pmcid],
        )
        reagents = [dict(zip(reagent_result.columns, r)) for r in reagent_result.rows]
    except Exception:
        reagents = []

    proposals = _list_proposals(pmcid=pmcid)

    template = datasette.jinja_env.get_template("review.html")
    html = template.render(
        protocol=protocol,
        reagents=reagents,
        proposals=proposals,
        field_meta=FIELD_META,
        pmcid=pmcid,
    )
    return Response.html(html)


async def api_protocol(scope, receive, send):
    """GET /api/protocol/<pmcid> — full record + proposals as JSON (agent-readable)."""
    request = Request(scope, receive)
    pmcid = scope["url_route"]["kwargs"]["pmcid"]
    datasette = scope["datasette"]

    try:
        result = await datasette.execute("atlas", "SELECT * FROM protocols WHERE pmcid=?", [pmcid])
        row = result.first()
        if not row:
            return Response.json({"error": "not found"}, status=404)
        protocol = dict(zip(result.columns, row))
    except Exception as e:
        return Response.json({"error": str(e)}, status=500)

    reagent_result = await datasette.execute(
        "atlas",
        "SELECT name, canonical, role, value, canonical_unit, evidence_quote, grounded, kind "
        "FROM reagents WHERE pmcid=?",
        [pmcid],
    )
    reagents = [dict(zip(reagent_result.columns, r)) for r in reagent_result.rows]

    return Response.json({
        "protocol": protocol,
        "reagents": reagents,
        "proposals": _list_proposals(pmcid=pmcid, status="pending"),
        "schema": "https://organoid-protocol-atlas.onrender.com/llms.txt",
    })


async def api_propose(scope, receive, send):
    """POST /api/propose — submit an edit proposal."""
    request = Request(scope, receive)
    if request.method != "POST":
        return Response.json({"error": "POST required"}, status=405)

    agent_id = request.headers.get("x-codex-agent", "")
    try:
        body = json.loads(await request.post_body())
    except Exception:
        return Response.json({"error": "invalid JSON"}, status=400)

    required = {"pmcid", "field", "proposed_value"}
    if not required.issubset(body):
        return Response.json({"error": f"missing fields: {required - set(body)}"}, status=400)

    proposal_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()
    proposed_by = agent_id or body.get("proposed_by") or "human"

    conn = _proposals_conn()
    conn.execute(
        "INSERT INTO proposals (id, pmcid, field, old_value, proposed_value, evidence_span, "
        "proposed_by, agent_id, proposed_at, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            proposal_id, body["pmcid"], body["field"],
            body.get("old_value"), body["proposed_value"],
            body.get("evidence_span"), proposed_by, agent_id, now, "pending",
        ],
    )
    conn.commit()

    return Response.json({"id": proposal_id, "status": "pending", "proposed_at": now}, status=201)


async def api_proposals(scope, receive, send):
    """GET /api/proposals — list proposals."""
    request = Request(scope, receive)
    params = dict(request.args)
    proposals = _list_proposals(
        pmcid=params.get("pmcid"),
        status=params.get("status"),
        field=params.get("field"),
    )
    return Response.json({"proposals": proposals, "count": len(proposals)})


async def api_accept(scope, receive, send):
    """POST /api/proposals/<id>/accept — accept a proposal."""
    request = Request(scope, receive)
    if request.method != "POST":
        return Response.json({"error": "POST required"}, status=405)
    proposal_id = scope["url_route"]["kwargs"]["id"]
    agent_id = request.headers.get("x-codex-agent", "human")
    now = datetime.now(timezone.utc).isoformat()
    conn = _proposals_conn()
    conn.execute(
        "UPDATE proposals SET status='accepted', reviewed_by=?, reviewed_at=? WHERE id=?",
        [agent_id, now, proposal_id],
    )
    conn.commit()
    proposal = _get_proposal(proposal_id)
    if not proposal:
        return Response.json({"error": "not found"}, status=404)
    return Response.json(proposal)


async def api_reject(scope, receive, send):
    """POST /api/proposals/<id>/reject — reject a proposal."""
    request = Request(scope, receive)
    if request.method != "POST":
        return Response.json({"error": "POST required"}, status=405)
    proposal_id = scope["url_route"]["kwargs"]["id"]
    agent_id = request.headers.get("x-codex-agent", "human")
    now = datetime.now(timezone.utc).isoformat()
    conn = _proposals_conn()
    conn.execute(
        "UPDATE proposals SET status='rejected', reviewed_by=?, reviewed_at=? WHERE id=?",
        [agent_id, now, proposal_id],
    )
    conn.commit()
    proposal = _get_proposal(proposal_id)
    if not proposal:
        return Response.json({"error": "not found"}, status=404)
    return Response.json(proposal)


# ---------------------------------------------------------------------------
# Datasette hook
# ---------------------------------------------------------------------------

@hookimpl
def register_routes():
    return [
        (r"^/review/(?P<pmcid>[^/]+)$", review_page),
        (r"^/api/protocol/(?P<pmcid>[^/]+)$", api_protocol),
        (r"^/api/propose$", api_propose),
        (r"^/api/proposals$", api_proposals),
        (r"^/api/proposals/(?P<id>[^/]+)/accept$", api_accept),
        (r"^/api/proposals/(?P<id>[^/]+)/reject$", api_reject),
    ]
