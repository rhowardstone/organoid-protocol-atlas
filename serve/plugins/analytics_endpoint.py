"""
Analytics REST endpoint — Datasette plugin exposing pre-computed analysis outputs.

Routes (all return JSON; read-only, no writes):
  GET /analytics/consensus/{organoid_type}      -- consensus concentrations/reagents for one type
  GET /analytics/consensus                      -- list available consensus files
  GET /analytics/compare/{pmcid_a}/{pmcid_b}   -- protocol diff (loads cached or computes on-demand)
  GET /analytics/failure-modes                  -- failure mode cluster summary
  GET /analytics/lineage                        -- DOI→DOI protocol lineage graph
  GET /analytics/substitutions?q=Matrigel       -- search ProtocolModification records
  GET /analytics/coverage                       -- per-type corpus coverage & completeness report
  GET /analytics/coverage/{organoid_type}       -- coverage for one organoid type
  GET /analytics                                -- index of available analytics

All endpoints degrade gracefully — if the pre-computed file doesn't exist they return
a 404 with an actionable message telling the user what command to run to generate it.
This is the serve-layer wrapper; all analysis logic lives in pipeline/*.py.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from datasette import hookimpl, Response

REPO = Path(__file__).resolve().parent.parent.parent
PIPELINE = REPO / "pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

ANALYSIS_DIR = REPO / "outputs" / "analysis"
COMPARISON_DIR = REPO / "outputs" / "comparison"
COVERAGE_REPORT_PATH = ANALYSIS_DIR / "coverage_report.json"


# --------------------------------------------------------------------------- #
# Pure handlers (testable without Datasette)
# --------------------------------------------------------------------------- #

def handle_consensus_list() -> tuple[dict, int]:
    """Return list of available consensus files."""
    if not ANALYSIS_DIR.exists():
        return {"available": [], "hint": "Run: python pipeline/compute_consensus.py --all"}, 200
    files = sorted(ANALYSIS_DIR.glob("consensus_*.json"))
    available = []
    for f in files:
        otype = f.stem.replace("consensus_", "")
        try:
            d = json.loads(f.read_text())
            available.append({
                "organoid_type": otype,
                "n_protocols": d.get("n_protocols", 0),
                "url": f"/analytics/consensus/{otype}",
            })
        except json.JSONDecodeError:
            pass
    return {"available": available}, 200


def handle_consensus(organoid_type: str) -> tuple[dict, int]:
    """Return pre-computed consensus for one organoid type."""
    # Sanitize: only allow word chars and hyphens
    if not re.match(r'^[\w-]+$', organoid_type):
        return {"error": "invalid organoid_type"}, 400
    path = ANALYSIS_DIR / f"consensus_{organoid_type}.json"
    if not path.exists():
        return {
            "error": f"No consensus computed for '{organoid_type}'",
            "hint": f"Run: python pipeline/compute_consensus.py {organoid_type}",
        }, 404
    try:
        return json.loads(path.read_text()), 200
    except json.JSONDecodeError:
        return {"error": "malformed consensus file"}, 500


def handle_failure_modes() -> tuple[dict, int]:
    """Return failure mode cluster summary."""
    path = ANALYSIS_DIR / "failure_mode_summary.json"
    if not path.exists():
        return {
            "error": "Failure mode summary not computed",
            "hint": "Run: python pipeline/aggregate_failure_modes.py",
        }, 404
    try:
        return json.loads(path.read_text()), 200
    except json.JSONDecodeError:
        return {"error": "malformed failure mode file"}, 500


def handle_lineage() -> tuple[dict, int]:
    """Return protocol lineage graph."""
    path = ANALYSIS_DIR / "protocol_lineage.json"
    if not path.exists():
        return {
            "error": "Protocol lineage graph not built",
            "hint": "Run: python pipeline/build_lineage.py",
        }, 404
    try:
        return json.loads(path.read_text()), 200
    except json.JSONDecodeError:
        return {"error": "malformed lineage file"}, 500


def handle_compare(pmcid_a: str, pmcid_b: str) -> tuple[dict, int]:
    """
    Return protocol comparison. Checks pre-computed cache first.
    Does NOT compute on-demand in the web process (would need local predictions).
    """
    # Sanitize
    for p in (pmcid_a, pmcid_b):
        if not re.match(r'^PMC\d+$', p.upper()):
            return {"error": f"invalid PMCID: {p!r} — expected PMC followed by digits"}, 400

    pmcid_a = pmcid_a.upper()
    pmcid_b = pmcid_b.upper()

    # Check both orderings
    for a, b in ((pmcid_a, pmcid_b), (pmcid_b, pmcid_a)):
        path = COMPARISON_DIR / f"{a}_vs_{b}.json"
        if path.exists():
            try:
                return json.loads(path.read_text()), 200
            except json.JSONDecodeError:
                return {"error": "malformed comparison file"}, 500

    return {
        "error": f"No comparison found for {pmcid_a} vs {pmcid_b}",
        "hint": f"Run: python pipeline/compare_protocols.py {pmcid_a} {pmcid_b}",
    }, 404


def handle_substitutions(query: str, to_query: str | None, organoid_type: str | None) -> tuple[dict, int]:
    """Search ProtocolModification records for substitutions involving a reagent term."""
    if not query or not query.strip():
        return {"error": "pass ?q=reagent_name", "example": "/analytics/substitutions?q=Matrigel"}, 400
    # Sanitize: max 100 chars, printable only
    query = query.strip()[:100]
    if to_query:
        to_query = to_query.strip()[:100]

    try:
        import find_substitutions as fs
    except ImportError:
        return {"error": "find_substitutions module not available"}, 500

    modifications = fs.load_all_modifications()
    if organoid_type:
        modifications = [m for m in modifications
                         if m.get("organoid_type", "").lower() == organoid_type.lower()]

    hits = fs.search_substitutions(modifications, query, to_query)
    return {
        "query": query,
        "to_query": to_query,
        "organoid_type": organoid_type,
        "n_hits": len(hits),
        "results": hits,
        "hint": ("No modification records loaded — run: python pipeline/tier1_extract.py"
                 if not modifications else None),
    }, 200


def handle_coverage() -> tuple[dict, int]:
    """Return pre-computed corpus coverage report (all types)."""
    if not COVERAGE_REPORT_PATH.exists():
        return {
            "error": "Coverage report not computed",
            "hint": "Run: python pipeline/generate_coverage_report.py",
        }, 404
    try:
        return json.loads(COVERAGE_REPORT_PATH.read_text()), 200
    except json.JSONDecodeError:
        return {"error": "malformed coverage report file"}, 500


def handle_coverage_type(organoid_type: str) -> tuple[dict, int]:
    """Return coverage stats for a single organoid type."""
    if not re.match(r'^[\w-]+$', organoid_type):
        return {"error": "invalid organoid_type"}, 400

    data, status = handle_coverage()
    if status != 200:
        return data, status

    by_type = data.get("by_organoid_type", {})
    otype_lower = organoid_type.lower()
    if otype_lower not in by_type:
        return {
            "error": f"No coverage data for '{organoid_type}'",
            "available": sorted(by_type.keys()),
        }, 404

    return {
        "organoid_type": otype_lower,
        **by_type[otype_lower],
        "corpus_summary": {
            "n_total_papers": data.get("n_total_papers"),
            "n_organoid_types": data.get("n_organoid_types"),
            "overall_avg_grounding_rate": data.get("overall_avg_grounding_rate"),
        },
    }, 200


def handle_index() -> tuple[dict, int]:
    """Analytics endpoint index."""
    return {
        "endpoints": {
            "/analytics/consensus": "list available organoid type consensus files",
            "/analytics/consensus/{organoid_type}": "consensus concentrations, reagents, timeline for one type",
            "/analytics/failure-modes": "failure mode cluster summary across all corpus papers",
            "/analytics/lineage": "DOI→DOI protocol lineage graph (ProtocolModification data)",
            "/analytics/compare/{pmcid_a}/{pmcid_b}": "protocol diff between two papers",
            "/analytics/substitutions?q=TERM": "search ProtocolModification records for reagent substitutions",
            "/analytics/coverage": "per-type corpus coverage and completeness report",
            "/analytics/coverage/{organoid_type}": "coverage stats for one organoid type",
        },
        "generate": {
            "consensus": "python pipeline/compute_consensus.py --all",
            "failure_modes": "python pipeline/aggregate_failure_modes.py",
            "lineage": "python pipeline/build_lineage.py",
            "compare": "python pipeline/compare_protocols.py PMC111 PMC222",
            "coverage": "python pipeline/generate_coverage_report.py",
        },
    }, 200


# --------------------------------------------------------------------------- #
# Datasette route wrappers
# --------------------------------------------------------------------------- #

async def route_analytics_index(datasette, request):
    data, status = handle_index()
    return Response.json(data, status=status)


async def route_consensus_list(datasette, request):
    data, status = handle_consensus_list()
    return Response.json(data, status=status)


async def route_consensus(datasette, request):
    organoid_type = request.url_vars.get("organoid_type", "")
    data, status = handle_consensus(organoid_type)
    return Response.json(data, status=status)


async def route_failure_modes(datasette, request):
    data, status = handle_failure_modes()
    return Response.json(data, status=status)


async def route_lineage(datasette, request):
    data, status = handle_lineage()
    return Response.json(data, status=status)


async def route_compare(datasette, request):
    pmcid_a = request.url_vars.get("pmcid_a", "")
    pmcid_b = request.url_vars.get("pmcid_b", "")
    data, status = handle_compare(pmcid_a, pmcid_b)
    return Response.json(data, status=status)


async def route_substitutions(datasette, request):
    query = request.args.get("q", "")
    to_query = request.args.get("to") or None
    organoid_type = request.args.get("type") or None
    data, status = handle_substitutions(query, to_query, organoid_type)
    return Response.json(data, status=status)


async def route_coverage(datasette, request):
    data, status = handle_coverage()
    return Response.json(data, status=status)


async def route_coverage_type(datasette, request):
    organoid_type = request.url_vars.get("organoid_type", "")
    data, status = handle_coverage_type(organoid_type)
    return Response.json(data, status=status)


@hookimpl
def register_routes():
    return [
        (r"^/analytics$", route_analytics_index),
        (r"^/analytics/consensus$", route_consensus_list),
        (r"^/analytics/consensus/(?P<organoid_type>[\w-]+)$", route_consensus),
        (r"^/analytics/failure-modes$", route_failure_modes),
        (r"^/analytics/lineage$", route_lineage),
        (r"^/analytics/compare/(?P<pmcid_a>PMC\d+)/(?P<pmcid_b>PMC\d+)$",
         route_compare),
        (r"^/analytics/substitutions$", route_substitutions),
        (r"^/analytics/coverage$", route_coverage),
        (r"^/analytics/coverage/(?P<organoid_type>[\w-]+)$", route_coverage_type),
    ]
