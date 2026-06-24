"""
Contract + proposals-DB tests for the review/annotation plugin (serve/plugins/review.py, PR #232).

Covers the stable, offline-testable core: route registration (the public contract) and the
proposals-DB lifecycle (insert → get → list/filter). The async ASGI handlers (api_propose/
accept/reject HTTP error paths) need a datasette test client — left as a follow-up; these
tests lock the route surface + the persistence layer so a regression in either is caught.

No network, no real data/ writes (PROPOSALS_DB_PATH is redirected to tmp_path).
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "serve" / "plugins" / "review.py"

pytestmark = pytest.mark.skipif(not PLUGIN.exists(), reason="review.py plugin not present")


def _load_plugin():
    spec = importlib.util.spec_from_file_location("review_plugin", PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ImportError:
        pytest.skip("datasette not installed")
    return mod


@pytest.fixture
def review(tmp_path, monkeypatch):
    mod = _load_plugin()
    # Redirect the proposals DB to a temp file so tests never touch real data/.
    monkeypatch.setattr(mod, "PROPOSALS_DB_PATH", tmp_path / "proposals.db")
    return mod


# --------------------------------------------------------------------------- #
# Route registration — the public contract
# --------------------------------------------------------------------------- #

EXPECTED_ROUTES = {
    r"^/review/(?P<pmcid>[^/]+)$",
    r"^/api/protocol/(?P<pmcid>[^/]+)$",
    r"^/api/propose$",
    r"^/api/proposals$",
    r"^/api/proposals/(?P<id>[^/]+)/accept$",
    r"^/api/proposals/(?P<id>[^/]+)/reject$",
}


def test_register_routes_exposes_documented_surface(review):
    routes = review.register_routes()
    patterns = {p for p, _ in routes}
    missing = EXPECTED_ROUTES - patterns
    assert not missing, f"review plugin missing documented routes: {missing}"
    # every route maps to a callable handler
    for pattern, handler in routes:
        assert callable(handler), f"route {pattern} handler is not callable"


# --------------------------------------------------------------------------- #
# Proposals DB lifecycle
# --------------------------------------------------------------------------- #

def _insert(review, **over):
    row = {
        "id": over.get("id", "p1"),
        "pmcid": over.get("pmcid", "PMC123"),
        "field": over.get("field", "base_media"),
        "old_value": over.get("old_value", "DMEM"),
        "proposed_value": over.get("proposed_value", "DMEM/F12"),
        "evidence_span": over.get("evidence_span", "cultured in DMEM/F12"),
        "proposed_by": over.get("proposed_by", "agent"),
        "agent_id": over.get("agent_id", "coder"),
        "proposed_at": over.get("proposed_at", datetime.now(timezone.utc).isoformat()),
        "status": over.get("status", "pending"),
    }
    conn = review._proposals_conn()
    conn.execute(
        "INSERT INTO proposals (id,pmcid,field,old_value,proposed_value,evidence_span,"
        "proposed_by,agent_id,proposed_at,status) VALUES "
        "(:id,:pmcid,:field,:old_value,:proposed_value,:evidence_span,:proposed_by,:agent_id,:proposed_at,:status)",
        row,
    )
    conn.commit()
    return row


def test_proposals_table_created_and_default_status(review):
    conn = review._proposals_conn()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(proposals)")}
    assert {"id", "pmcid", "field", "proposed_value", "status", "proposed_by"} <= cols
    # default status is pending when not provided
    conn.execute(
        "INSERT INTO proposals (id,pmcid,field,proposed_value,proposed_by,proposed_at) "
        "VALUES ('x','PMC1','species','human','agent','2026-01-01T00:00:00Z')"
    )
    conn.commit()
    assert review._get_proposal("x")["status"] == "pending"


def test_get_and_list_roundtrip(review):
    _insert(review, id="p1", pmcid="PMC123")
    got = review._get_proposal("p1")
    assert got and got["pmcid"] == "PMC123" and got["proposed_value"] == "DMEM/F12"
    assert review._get_proposal("nope") is None
    assert [p["id"] for p in review._list_proposals()] == ["p1"]


def test_list_filters_by_pmcid_status_field(review):
    _insert(review, id="a", pmcid="PMC1", status="pending", field="base_media")
    _insert(review, id="b", pmcid="PMC1", status="accepted", field="species")
    _insert(review, id="c", pmcid="PMC2", status="pending", field="base_media")
    assert {p["id"] for p in review._list_proposals(pmcid="PMC1")} == {"a", "b"}
    assert {p["id"] for p in review._list_proposals(status="pending")} == {"a", "c"}
    assert {p["id"] for p in review._list_proposals(field="base_media")} == {"a", "c"}
    assert {p["id"] for p in review._list_proposals(pmcid="PMC1", status="pending")} == {"a"}


def test_list_ordered_by_proposed_at_desc(review):
    _insert(review, id="old", proposed_at="2026-01-01T00:00:00Z")
    _insert(review, id="new", proposed_at="2026-06-01T00:00:00Z")
    assert [p["id"] for p in review._list_proposals()] == ["new", "old"]
