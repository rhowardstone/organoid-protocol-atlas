"""
serve/plugins/review.py — Schema-agnostic structured-data annotation plugin.

Routes:
  GET  /review/<pmcid>              — side-by-side review page
  GET  /api/pmcview/<pmcid>         — PMC full text with evidence_quote highlights (JSON)
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

import html
import json
import re
import sqlite3
import urllib.request
import uuid
import xml.etree.ElementTree as ET
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

# MIOR = Minimum Information about an Organoid Recipe
# Fields that SHOULD be present in a complete protocol record
MIOR_REQUIRED: list[dict] = [
    {"field": "organoid_type",   "label": "type"},
    {"field": "species",         "label": "species"},
    {"field": "source_cell_type","label": "source cells"},
    {"field": "matrix",          "label": "matrix"},
    {"field": "base_media",      "label": "medium"},
    {"field": "passaging",       "label": "passaging"},
    {"field": "timeline",        "label": "timeline"},
    {"field": "assay_endpoints", "label": "endpoints"},
]

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
# PMC full-text fetch + highlight
# ---------------------------------------------------------------------------

def _fetch_pmc_text(pmcid: str) -> Optional[str]:
    """Fetch full-text XML from PMC efetch, return concatenated body paragraphs."""
    pmc_num = pmcid.replace("PMC", "")
    url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pmc&id={pmc_num}&rettype=full&retmode=xml"
    )
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "OrganoidProtocolAtlas/1.0 (research tool)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_bytes = resp.read()
    except Exception:
        return None

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    # Walk body/sec/p elements; collect text with section headings
    parts: list[str] = []
    for body in root.iter("body"):
        for sec in body:
            # Section title
            title_el = sec.find("title")
            if title_el is not None and title_el.text:
                parts.append(f"\n## {title_el.text.strip()}\n")
            # Paragraphs in this section (and subsections)
            for p in sec.iter("p"):
                # Flatten text including nested spans/italic/bold
                text = "".join(p.itertext()).strip()
                if text:
                    parts.append(text)

    return "\n\n".join(parts) if parts else None


def _highlight_quotes(plain_text: str, quotes: list[dict]) -> str:
    """
    Given plain text and a list of {name, quote} dicts, return an HTML string
    where each matched evidence_quote is wrapped in a <mark> tag.
    Unmatched text is HTML-escaped.
    """
    # Build a list of (start, end, name) for all found quotes, non-overlapping
    intervals: list[tuple[int, int, str]] = []
    for q in quotes:
        raw = q.get("quote", "") or ""
        raw = raw.strip()
        if len(raw) < 8:
            continue
        idx = plain_text.find(raw)
        if idx == -1:
            # Try case-insensitive
            lo = plain_text.lower().find(raw.lower())
            if lo == -1:
                continue
            idx = lo
            raw = plain_text[idx: idx + len(raw)]
        intervals.append((idx, idx + len(raw), q["name"]))

    # Sort and de-overlap (keep first occurrence of overlapping spans)
    intervals.sort(key=lambda x: x[0])
    merged: list[tuple[int, int, str]] = []
    prev_end = -1
    for start, end, name in intervals:
        if start >= prev_end:
            merged.append((start, end, name))
            prev_end = end

    # Build HTML string
    result_parts: list[str] = []
    cursor = 0
    for start, end, name in merged:
        if cursor < start:
            result_parts.append(html.escape(plain_text[cursor:start]))
        span_text = html.escape(plain_text[start:end])
        name_esc = html.escape(name, quote=True)
        result_parts.append(
            f'<mark class="ev-highlight" data-reagent="{name_esc}" '
            f'title="{name_esc}">{span_text}</mark>'
        )
        cursor = end
    if cursor < len(plain_text):
        result_parts.append(html.escape(plain_text[cursor:]))

    # Convert double-newlines to paragraph breaks for readable output
    joined = "".join(result_parts)
    joined = re.sub(r'\n## ([^\n]+)\n', r'<h3 class="pmc-sec-title">\1</h3>', joined)
    joined = re.sub(r'\n\n+', '</p><p class="pmc-para">', joined)
    return f'<p class="pmc-para">{joined}</p>'


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

    # MIOR coverage: which required fields are present vs absent
    mior_status = []
    for m in MIOR_REQUIRED:
        val = protocol.get(m["field"])
        present = val is not None and val != "" and val != []
        mior_status.append({**m, "present": present, "value": val})

    template = datasette.jinja_env.get_template("review.html")
    html_out = template.render(
        protocol=protocol,
        reagents=reagents,
        proposals=proposals,
        field_meta=FIELD_META,
        pmcid=pmcid,
        mior_status=mior_status,
        has_pmc=pmcid.startswith("PMC"),
    )
    return Response.html(html_out)


async def api_pmcview(scope, receive, send):
    """GET /api/pmcview/<pmcid> — fetch PMC full text, highlight evidence_quotes."""
    pmcid = scope["url_route"]["kwargs"]["pmcid"]
    datasette = scope["datasette"]

    if not pmcid.startswith("PMC"):
        return Response.json(
            {"error": "no_pmc", "message": "PMC full text only available for PMC IDs"},
            status=404,
        )

    # Get evidence quotes from DB
    try:
        result = await datasette.execute(
            "atlas",
            "SELECT name, canonical, evidence_quote FROM reagents "
            "WHERE pmcid=? AND evidence_quote IS NOT NULL AND evidence_quote != ''",
            [pmcid],
        )
        quotes = [
            {"name": r[1] or r[0], "quote": r[2]}
            for r in result.rows
        ]
    except Exception:
        quotes = []

    plain_text = _fetch_pmc_text(pmcid)
    if plain_text is None:
        return Response.json(
            {"error": "fetch_failed", "message": "Could not retrieve PMC full text"},
            status=502,
        )

    highlighted_html = _highlight_quotes(plain_text, quotes)
    found = highlighted_html.count('class="ev-highlight"')

    return Response.json({
        "html": highlighted_html,
        "found": found,
        "total": len(quotes),
        "pmcid": pmcid,
    })


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
        (r"^/api/pmcview/(?P<pmcid>[^/]+)$", api_pmcview),
        (r"^/api/protocol/(?P<pmcid>[^/]+)$", api_protocol),
        (r"^/api/propose$", api_propose),
        (r"^/api/proposals$", api_proposals),
        (r"^/api/proposals/(?P<id>[^/]+)/accept$", api_accept),
        (r"^/api/proposals/(?P<id>[^/]+)/reject$", api_reject),
    ]
