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
  GET /analytics/reagent?q=TERM                 -- cross-corpus reagent lookup from reagents.jsonl
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
REAGENTS_JSONL = REPO / "exports" / "public" / "reagents.jsonl"


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


def handle_summary() -> tuple[dict, int]:
    """
    High-level corpus summary — reads all pre-computed analytics outputs and
    returns the most useful metrics in a single response. Intended for dashboard
    and monitoring use-cases where you want an at-a-glance overview.

    Fields:
      corpus: n_papers, n_organoid_types, avg_grounding_rate
      coverage: top_types_by_completeness (top 5)
      quality: n_gold/silver/bronze, avg_score
      failure_modes: top_3_clusters
      assay_endpoints: top_3_assays_by_n_papers
      reagent_grounding: corpus_pooled_grounding_rate
      analytics_ready: {artifact: bool} inventory
    """
    summary: dict = {}

    # Corpus / coverage
    if COVERAGE_REPORT_PATH.exists():
        try:
            cov = json.loads(COVERAGE_REPORT_PATH.read_text())
            summary["corpus"] = {
                "n_papers": cov.get("n_total_papers"),
                "n_organoid_types": cov.get("n_organoid_types"),
                "overall_avg_grounding_rate": cov.get("overall_avg_grounding_rate"),
                "corpus_pooled_grounding_rate": cov.get("corpus_pooled_grounding_rate"),
            }
            # Top 5 types by completeness
            ranked = cov.get("types_by_completeness", [])[:5]
            summary["top_types_by_completeness"] = [
                {
                    "organoid_type": r.get("organoid_type"),
                    "n_papers": r.get("n_papers"),
                    "completeness_score": r.get("completeness_score"),
                    "avg_grounding_rate": r.get("avg_grounding_rate"),
                }
                for r in ranked
            ]
        except (json.JSONDecodeError, OSError):
            pass

    # Quality
    quality_path = ANALYSIS_DIR / "protocol_quality_scores.json"
    if quality_path.exists():
        try:
            q = json.loads(quality_path.read_text())
            summary["quality"] = {
                "avg_score": q.get("avg_score"),
                "n_gold": q.get("n_gold"),
                "n_silver": q.get("n_silver"),
                "n_bronze": q.get("n_bronze"),
                "n_total": q.get("n_total"),
            }
        except (json.JSONDecodeError, OSError):
            pass

    # Failure modes top 3
    fm_path = ANALYSIS_DIR / "failure_mode_summary.json"
    if fm_path.exists():
        try:
            fm = json.loads(fm_path.read_text())
            by_type = fm.get("by_type") or {}
            clusters = []
            for type_label, type_data in by_type.items():
                for cluster_label, cluster_data in (type_data.get("clusters") or {}).items():
                    clusters.append({
                        "organoid_type": type_label,
                        "cluster": cluster_label,
                        "count": cluster_data.get("count", 0),
                    })
            clusters.sort(key=lambda x: -x["count"])
            summary["top_failure_mode_clusters"] = clusters[:3]
            summary["total_failure_modes"] = fm.get("total_failure_modes")
        except (json.JSONDecodeError, OSError):
            pass

    # Assay endpoints top 3
    ae_path = ANALYSIS_DIR / "assay_endpoint_summary.json"
    if ae_path.exists():
        try:
            ae_data = json.loads(ae_path.read_text())
            cross = ae_data.get("cross_type_cluster_usage", {})
            top_assays = sorted(cross.items(), key=lambda kv: -kv[1].get("n_papers", 0))[:3]
            summary["top_assay_clusters"] = [
                {
                    "cluster": k,
                    "n_papers": v.get("n_papers"),
                    "n_types": v.get("n_types"),
                }
                for k, v in top_assays
            ]
        except (json.JSONDecodeError, OSError):
            pass

    has_data = bool(summary)

    # Analytics inventory — always included so callers know what to generate
    summary["analytics_ready"] = {
        "consensus": bool(list(ANALYSIS_DIR.glob("consensus_*.json"))) if ANALYSIS_DIR.exists() else False,
        "failure_modes": (ANALYSIS_DIR / "failure_mode_summary.json").exists(),
        "lineage": (ANALYSIS_DIR / "protocol_lineage.json").exists(),
        "coverage": COVERAGE_REPORT_PATH.exists(),
        "quality": quality_path.exists(),
        "assay_endpoints": ae_path.exists(),
    }

    if not has_data:
        return {
            "error": "No analytics outputs available",
            "hint": "Run: python pipeline/system_status.py to see what to generate",
        }, 404

    return summary, 200


def handle_status() -> tuple[dict, int]:
    """Live system health check from system_status.py pure functions."""
    try:
        import system_status as ss
    except ImportError:
        return {"error": "system_status module not available"}, 500

    corpus = ss.check_corpus(ss.PROTOCOLS_JSONL)
    artifacts = ss.check_analytics_artifacts(ss.ANALYTICS_ARTIFACTS)
    consensus = ss.check_consensus_files()
    manifest = ss.check_manifest(ss.MANIFEST)
    status = ss.compute_status(corpus, artifacts, consensus, manifest)

    http_status = 200 if (status["healthy"] and consensus["n_files"] > 0) else 503
    return status, http_status


def handle_quality(organoid_type: str | None, tier: str | None) -> tuple[dict, int]:
    """
    Return pre-computed protocol quality scores.
    Optional ?type= and ?tier=gold|silver|bronze filters.
    """
    path = ANALYSIS_DIR / "protocol_quality_scores.json"
    if not path.exists():
        return {
            "error": "Protocol quality scores not computed",
            "hint": "Run: python pipeline/score_protocol_quality.py",
        }, 404
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"error": "malformed quality scores file"}, 500

    # Apply filters
    scores = data.get("scores", [])
    if organoid_type:
        otype = organoid_type.strip().lower()
        scores = [r for r in scores if (r.get("organoid_type") or "").lower() == otype]
    if tier:
        tier = tier.strip().lower()
        if tier not in ("gold", "silver", "bronze"):
            return {"error": "invalid tier; use gold, silver, or bronze"}, 400
        scores = [r for r in scores if r.get("quality_tier") == tier]

    return {
        "n_total": data.get("n_total"),
        "avg_score": data.get("avg_score"),
        "n_gold": data.get("n_gold"),
        "n_silver": data.get("n_silver"),
        "n_bronze": data.get("n_bronze"),
        "gold_threshold": data.get("gold_threshold"),
        "silver_threshold": data.get("silver_threshold"),
        "organoid_type_filter": organoid_type,
        "tier_filter": tier,
        "n_results": len(scores),
        "scores": scores[:200],  # cap to keep response reasonable
    }, 200


def handle_assay_endpoints() -> tuple[dict, int]:
    """Return pre-computed assay endpoint cluster summary."""
    path = ANALYSIS_DIR / "assay_endpoint_summary.json"
    if not path.exists():
        return {
            "error": "Assay endpoint summary not computed",
            "hint": "Run: python pipeline/aggregate_assay_endpoints.py",
        }, 404
    try:
        return json.loads(path.read_text()), 200
    except json.JSONDecodeError:
        return {"error": "malformed assay endpoint summary file"}, 500


def handle_reagent(query: str, organoid_type: str | None, min_papers: int) -> tuple[dict, int]:
    """Cross-corpus reagent lookup from reagents.jsonl."""
    if not query or not query.strip():
        return {
            "error": "pass ?q=reagent_name",
            "example": "/analytics/reagent?q=EGF",
        }, 400

    query = query.strip()[:100]

    if not REAGENTS_JSONL.exists():
        return {
            "error": "reagents.jsonl not found",
            "path": str(REAGENTS_JSONL),
        }, 404

    try:
        import reagent_lookup as rl
    except ImportError:
        return {"error": "reagent_lookup module not available"}, 500

    records = rl.load_reagents(REAGENTS_JSONL)
    if not records:
        return {"error": "reagents.jsonl is empty", "n_records": 0}, 404

    result = rl.lookup(records, query, organoid_type, min_papers)
    return result, 200


def handle_candidates() -> tuple[dict, int]:
    """Return OA verification status of the candidate pool — how many papers are
    public_ok (CC0/CC-BY), rejected (NC/ND/unknown), or quarantine (API error)."""
    import csv as _csv
    oa_results = REPO / "data" / "corpus" / "oa_verified" / "oa_results.json"
    incoming = REPO / "data" / "corpus" / "incoming"
    # Count candidates across all pool files
    pool_counts: dict[str, int] = {}
    if incoming.exists():
        for p in sorted(incoming.glob("organoid_corpus_candidates_*.csv")):
            try:
                rows = list(_csv.DictReader(p.open(encoding="utf-8-sig")))
                pool_counts[p.name] = len(rows)
            except OSError:
                pass
    total_candidates = sum(pool_counts.values())

    if oa_results.exists():
        try:
            oa = json.loads(oa_results.read_text())
        except json.JSONDecodeError:
            return {"error": "malformed oa_results.json"}, 500
        return {
            "total_candidates": total_candidates,
            "pools": pool_counts,
            "oa_verified": {
                "pool_size": oa.get("pool_size", 0),
                "public_ok": oa.get("public_ok", 0),
                "rejected": oa.get("rejected", 0),
                "quarantine": oa.get("quarantine", 0),
                "license_mismatches": oa.get("license_mismatches", 0),
            },
            "public_pmcids_sample": (oa.get("public_pmcids") or [])[:10],
        }, 200
    return {
        "total_candidates": total_candidates,
        "pools": pool_counts,
        "oa_verified": None,
        "hint": "Run: python pipeline/verify_oa_license.py to generate oa_results.json",
    }, 200


def handle_mior() -> tuple[dict, int]:
    """Return pre-computed MIOR completeness report."""
    path = ANALYSIS_DIR / "mior_completeness.json"
    if not path.exists():
        return {
            "error": "MIOR completeness report not computed",
            "hint": "Run: python pipeline/score_mior.py",
        }, 404
    try:
        return json.loads(path.read_text()), 200
    except json.JSONDecodeError:
        return {"error": "malformed MIOR completeness file"}, 500


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
            "/analytics/reagent?q=TERM": "cross-corpus reagent lookup: usage, concentrations, evidence quotes",
            "/analytics/assay-endpoints": "assay endpoint cluster summary (per type + cross-type)",
            "/analytics/quality": "per-paper quality scores (gold/silver/bronze) + corpus summary",
            "/analytics/mior": "MIOR completeness report (Minimum Information About an Organoid Research)",
            "/analytics/candidates": "OA/license verification status of the candidate pools (issue #14 pipeline)",
            "/analytics/status": "live system health check (corpus + analytics artifact inventory)",
            "/analytics/summary": "high-level dashboard: corpus stats, quality distribution, top types/assays/failures",
        },
        "generate": {
            "consensus": "python pipeline/compute_consensus.py --all",
            "failure_modes": "python pipeline/aggregate_failure_modes.py",
            "lineage": "python pipeline/build_lineage.py",
            "compare": "python pipeline/compare_protocols.py PMC111 PMC222",
            "coverage": "python pipeline/generate_coverage_report.py",
            "assay_endpoints": "python pipeline/aggregate_assay_endpoints.py",
            "quality": "python pipeline/score_protocol_quality.py",
            "mior": "python pipeline/score_mior.py",
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


async def route_summary(datasette, request):
    data, status = handle_summary()
    return Response.json(data, status=status)


async def route_status(datasette, request):
    data, status = handle_status()
    return Response.json(data, status=status)


async def route_quality(datasette, request):
    organoid_type = request.args.get("type") or None
    tier = request.args.get("tier") or None
    data, status = handle_quality(organoid_type, tier)
    return Response.json(data, status=status)


async def route_assay_endpoints(datasette, request):
    data, status = handle_assay_endpoints()
    return Response.json(data, status=status)


async def route_reagent(datasette, request):
    query = request.args.get("q", "")
    organoid_type = request.args.get("type") or None
    try:
        min_papers = int(request.args.get("min_papers", "1"))
    except (TypeError, ValueError):
        min_papers = 1
    data, status = handle_reagent(query, organoid_type, min_papers)
    return Response.json(data, status=status)


async def route_candidates(datasette, request):
    data, status = handle_candidates()
    return Response.json(data, status=status)


async def route_mior(datasette, request):
    data, status = handle_mior()
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
        (r"^/analytics/reagent$", route_reagent),
        (r"^/analytics/assay-endpoints$", route_assay_endpoints),
        (r"^/analytics/quality$", route_quality),
        (r"^/analytics/mior$", route_mior),
        (r"^/analytics/candidates$", route_candidates),
        (r"^/analytics/status$", route_status),
        (r"^/analytics/summary$", route_summary),
    ]
