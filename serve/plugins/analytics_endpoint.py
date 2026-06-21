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
  GET /analytics/reagent-network?q=TERM        -- reagent co-occurrence: most co-mentioned reagents
  GET /analytics/type-similarity               -- pairwise organoid type Jaccard similarity
  GET /analytics/type-timeseries              -- type publication counts by year (growth trends)
  GET /analytics/universal-reagents           -- reagents essential to each type (>= N% of protocols)
  GET /analytics/species-breakdown            -- species distribution per organoid type from protocols.jsonl
  GET /analytics/matrix-breakdown             -- extracellular matrix usage per organoid type from protocols.jsonl
  GET /analytics/base-media-breakdown         -- base media usage per organoid type from protocols.jsonl
  GET /analytics/source-cell-breakdown        -- source cell type distribution per organoid type (iPSC / adult_stem_cell / primary_tissue / ESC)
  GET /analytics/protocol-complexity          -- per-type protocol complexity: avg signaling factors, supplements, grounding rate
  GET /analytics/reporting-gaps              -- field reporting rates across the corpus (species/matrix/base_media/passaging/timeline) — transparency audit
  GET /analytics/year-trend                  -- yearly trends: paper count, avg signaling factors, avg grounding rate, field reporting rates
  GET /analytics/grounding-quality           -- reagent grounding coverage: resolved vs ungrounded, by type and by kind; top ungrounded canonical names
  GET /analytics/concentration-stats         -- aggregate concentration distributions per canonical reagent: median, min, max, n; optional ?q= filter
  GET /analytics/temporal-reagent-adoption   -- per-reagent temporal adoption: fraction of papers per year using each canonical reagent; ?q= for one reagent
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
PROTOCOLS_JSONL = REPO / "exports" / "public" / "protocols.jsonl"
MANIFEST_PATH = REPO / "exports" / "public" / "manifest.json"


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
        if otype == "all":
            continue  # consensus_all.json is the aggregate LIST, not a per-type dict
        try:
            d = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict):
            continue  # defensive: only per-type dicts expose n_protocols (avoids 500)
        available.append({
            "organoid_type": otype,
            "n_protocols": d.get("n_protocols", 0),
            "url": f"/analytics/consensus/{otype}",
        })
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


def _load_public_protocol(pmcid: str) -> dict | None:
    """
    Build a compare_protocols-compatible protocol dict from committed public JSONL.

    Loads:
      - Protocol summary from exports/public/protocols.jsonl
      - Reagents (signaling/supplement/small_molecule) from exports/public/reagents.jsonl

    This is the public-data fallback used by handle_compare when no local prediction
    or pre-computed comparison file exists. Reagent fields are re-mapped to the
    schema compare_protocols.compare_protocols() expects.
    """
    PROTOCOLS_JSONL = REPO / "exports" / "public" / "protocols.jsonl"
    if not PROTOCOLS_JSONL.exists() or not REAGENTS_JSONL.exists():
        return None

    proto: dict | None = None
    for line in PROTOCOLS_JSONL.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("pmcid", "").upper() == pmcid:
            proto = dict(rec)
            proto["_source"] = "public_summary"
            break
    if proto is None:
        return None

    # Group reagents from public reagents.jsonl
    KIND_MAP = {
        "signaling": "signaling_factors",
        "supplement": "media_supplements",
        "small_molecule": "small_molecules",
    }
    for key in KIND_MAP.values():
        proto.setdefault(key, [])

    for line in REAGENTS_JSONL.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("pmcid", "").upper() != pmcid:
            continue
        kind = r.get("kind", "")
        section = KIND_MAP.get(kind)
        if section is None:
            continue
        proto[section].append({
            "name": r.get("name") or r.get("canonical"),
            "canonical_name": r.get("canonical"),
            "role": r.get("role"),
            "value": r.get("value"),
            "unit": r.get("canonical_unit") or r.get("unit"),
            "evidence_quote": r.get("evidence_quote"),
            "grounding_status": "resolved" if r.get("grounded") else "not_found",
        })

    return proto


def handle_compare(pmcid_a: str, pmcid_b: str) -> tuple[dict, int]:
    """
    Return protocol comparison. Checks pre-computed cache first, then computes
    on-demand from public JSONL if both PMCIDs are in the public corpus.
    """
    # Sanitize
    for p in (pmcid_a, pmcid_b):
        if not re.match(r'^PMC\d+$', p.upper()):
            return {"error": f"invalid PMCID: {p!r} — expected PMC followed by digits"}, 400

    pmcid_a = pmcid_a.upper()
    pmcid_b = pmcid_b.upper()

    # Check both orderings (pre-computed cache)
    for a, b in ((pmcid_a, pmcid_b), (pmcid_b, pmcid_a)):
        path = COMPARISON_DIR / f"{a}_vs_{b}.json"
        if path.exists():
            try:
                return json.loads(path.read_text()), 200
            except json.JSONDecodeError:
                return {"error": "malformed comparison file"}, 500

    # On-demand comparison from public JSONL
    try:
        from compare_protocols import compare_protocols as _compare
    except ImportError:
        return {
            "error": f"No comparison found for {pmcid_a} vs {pmcid_b}",
            "hint": f"Run: python pipeline/compare_protocols.py {pmcid_a} {pmcid_b}",
        }, 404

    pa = _load_public_protocol(pmcid_a)
    pb = _load_public_protocol(pmcid_b)

    if pa is None:
        return {
            "error": f"{pmcid_a} not found in public corpus",
            "hint": f"Run: python pipeline/compare_protocols.py {pmcid_a} {pmcid_b}",
        }, 404
    if pb is None:
        return {
            "error": f"{pmcid_b} not found in public corpus",
            "hint": f"Run: python pipeline/compare_protocols.py {pmcid_a} {pmcid_b}",
        }, 404

    try:
        result = _compare(pa, pb, pmcid_a, pmcid_b)
        result["computed_on_demand"] = True
        result["note"] = "Comparison computed from public JSONL (summary-level); reagents included."
        return result, 200
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Comparison failed: {exc}"}, 500


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

    # Manifest — n_reagents and schema_version let dashboard callers avoid a separate fetch
    if MANIFEST_PATH.exists():
        try:
            mf = json.loads(MANIFEST_PATH.read_text())
            summary["manifest"] = {
                "n_reagents": (mf.get("tables") or {}).get("reagents"),
                "schema_version": mf.get("schema_version"),
            }
        except (json.JSONDecodeError, OSError):
            pass

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

    # MIOR completeness summary — embed key fields so /analytics/summary callers
    # get MIOR stats without a second fetch (the full report is still at /analytics/mior)
    mior_path = ANALYSIS_DIR / "mior_completeness.json"
    if mior_path.exists():
        try:
            mior = json.loads(mior_path.read_text())
            summary["mior"] = {
                "avg_mior_completeness": mior.get("avg_mior_completeness"),
                "n_full": mior.get("n_full"),
                "n_partial": mior.get("n_partial"),
                "n_sparse": mior.get("n_sparse"),
                "n_total": mior.get("n_total"),
            }
        except (json.JSONDecodeError, OSError):
            pass

    # Species + matrix + base_media + source_cell snapshots — single pass.
    # Derived live so the summary stays fresh without a separate pre-computed artifact.
    if PROTOCOLS_JSONL.exists():
        try:
            sp_counts: dict[str, int] = {}
            mx_counts: dict[str, int] = {}
            bm_counts: dict[str, int] = {}
            sc_counts: dict[str, int] = {}
            for line in PROTOCOLS_JSONL.read_text().splitlines():
                if not line.strip():
                    continue
                p = json.loads(line)
                raw_sp = (p.get("species") or "not_stated").strip()
                sp = _SPECIES_ALIASES.get(raw_sp.lower(), raw_sp.lower())
                sp_counts[sp] = sp_counts.get(sp, 0) + 1
                raw_mx = (p.get("matrix") or "not_stated").strip()
                mx = _MATRIX_ALIASES.get(raw_mx.lower(), raw_mx)
                mx_counts[mx] = mx_counts.get(mx, 0) + 1
                raw_bm = (p.get("base_media") or "not_stated").strip()
                bm = _BASE_MEDIA_ALIASES.get(raw_bm.lower(), raw_bm)
                bm_counts[bm] = bm_counts.get(bm, 0) + 1
                raw_sc = (p.get("source_cell_type") or "not_stated").strip()
                sc = _SOURCE_CELL_ALIASES.get(raw_sc.lower(), raw_sc)
                sc_counts[sc] = sc_counts.get(sc, 0) + 1
            summary["species_snapshot"] = dict(sorted(sp_counts.items(), key=lambda kv: -kv[1])[:3])
            summary["matrix_snapshot"] = dict(sorted(mx_counts.items(), key=lambda kv: -kv[1])[:3])
            summary["base_media_snapshot"] = dict(sorted(bm_counts.items(), key=lambda kv: -kv[1])[:3])
            summary["source_cell_snapshot"] = dict(sorted(sc_counts.items(), key=lambda kv: -kv[1])[:3])
        except (json.JSONDecodeError, OSError):
            pass

    # Live-derived convenience fields — excluded from has_data gate.
    _analytics_keys = set(summary) - {
        "manifest", "mior", "species_snapshot", "matrix_snapshot",
        "base_media_snapshot", "source_cell_snapshot",
    }
    has_data = bool(_analytics_keys)

    # Analytics inventory — always included so callers know what to generate
    summary["analytics_ready"] = {
        "consensus": bool(list(ANALYSIS_DIR.glob("consensus_*.json"))) if ANALYSIS_DIR.exists() else False,
        "failure_modes": (ANALYSIS_DIR / "failure_mode_summary.json").exists(),
        "lineage": (ANALYSIS_DIR / "protocol_lineage.json").exists(),
        "coverage": COVERAGE_REPORT_PATH.exists(),
        "quality": quality_path.exists(),
        "assay_endpoints": ae_path.exists(),
        "mior": mior_path.exists(),
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


def handle_reagent_network(query: str, limit: int) -> tuple[dict, int]:
    """Reagent co-occurrence network from reagents.jsonl.

    Returns the reagents most commonly co-mentioned in the same papers as
    the queried reagent.  Useful for "what else is always used with EGF?"
    """
    if not query or not query.strip():
        return {
            "error": "pass ?q=reagent_name",
            "example": "/analytics/reagent-network?q=EGF",
        }, 400

    query = query.strip()[:100]
    limit = max(1, min(limit, 100))

    if not REAGENTS_JSONL.exists():
        return {
            "error": "reagents.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    q_lower = query.lower()
    # pass 1 — find PMCIDs where the query reagent appears
    query_pmcids: set[str] = set()
    all_rows: list[dict] = []
    try:
        for line in REAGENTS_JSONL.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            all_rows.append(r)
            name = (r.get("canonical") or r.get("name") or "").lower()
            if q_lower in name or name in q_lower:
                pmcid = r.get("pmcid", "")
                if pmcid:
                    query_pmcids.add(pmcid)
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"reagents.jsonl unreadable: {exc}"}, 500

    if not query_pmcids:
        return {
            "query": query,
            "n_papers": 0,
            "co_occurring": [],
            "note": "No papers found mentioning this reagent",
        }, 200

    # pass 2 — count co-occurring reagents in those papers
    counts: dict[str, int] = {}
    for r in all_rows:
        if r.get("pmcid", "") not in query_pmcids:
            continue
        name = r.get("canonical") or r.get("name") or ""
        if not name or name.lower() == q_lower:
            continue
        counts[name] = counts.get(name, 0) + 1

    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:limit]
    return {
        "query": query,
        "n_papers": len(query_pmcids),
        "co_occurring": [{"name": n, "papers": c, "rank": i + 1}
                         for i, (n, c) in enumerate(ranked)],
    }, 200


def handle_universal_reagents(
    organoid_type: str | None,
    min_fraction: float,
) -> tuple[dict, int]:
    """Return type-essential reagents from reagents.jsonl.

    For each organoid type (or the requested one), returns canonical reagents
    that appear in at least `min_fraction` of that type's protocols.

    Also returns cross-type universals — reagents appearing in >= half the types
    (regardless of per-type frequency).
    """
    min_fraction = max(0.0, min(min_fraction, 1.0))

    if not REAGENTS_JSONL.exists():
        return {
            "error": "reagents.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    if organoid_type and not re.match(r'^[\w-]+$', organoid_type):
        return {"error": "invalid organoid_type"}, 400

    papers_by_type: dict[str, set[str]] = {}
    reagent_papers_by_type: dict[str, dict[str, set[str]]] = {}

    try:
        for line in REAGENTS_JSONL.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            ot = (r.get("organoid_type") or r.get("type") or "").strip()
            pmcid = (r.get("pmcid") or "").strip()
            canonical = (r.get("canonical") or r.get("name") or "").strip().lower()
            if not ot or ot == "other" or not pmcid or not canonical:
                continue
            papers_by_type.setdefault(ot, set()).add(pmcid)
            reagent_papers_by_type.setdefault(ot, {}).setdefault(canonical, set()).add(pmcid)
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"reagents.jsonl unreadable: {exc}"}, 500

    if not papers_by_type:
        return {"error": "no typed reagent data found", "n_types": 0}, 404

    types_to_process = ([organoid_type] if organoid_type and organoid_type in papers_by_type
                        else sorted(papers_by_type))

    per_type: dict[str, dict] = {}
    for t in types_to_process:
        n_papers = len(papers_by_type[t])
        essentials = []
        for canonical, pmcids in reagent_papers_by_type.get(t, {}).items():
            frac = len(pmcids) / n_papers if n_papers else 0.0
            if frac >= min_fraction:
                essentials.append({
                    "canonical": canonical,
                    "fraction": round(frac, 4),
                    "n_papers": len(pmcids),
                    "n_total_papers": n_papers,
                })
        essentials.sort(key=lambda x: (-x["fraction"], x["canonical"]))
        per_type[t] = {"n_papers": n_papers, "essentials": essentials}

    # Cross-type universals: reagents present in >= 50% of types
    n_types = len(papers_by_type)
    reagent_type_count: dict[str, int] = {}
    for t in papers_by_type:
        n_p = len(papers_by_type[t])
        for canonical, pmcids in reagent_papers_by_type.get(t, {}).items():
            if n_p and len(pmcids) / n_p >= min_fraction:
                reagent_type_count[canonical] = reagent_type_count.get(canonical, 0) + 1
    cross_type = sorted(
        [{"canonical": c, "n_types": cnt}
         for c, cnt in reagent_type_count.items()
         if cnt >= n_types / 2],
        key=lambda x: (-x["n_types"], x["canonical"]),
    )

    result: dict = {
        "min_fraction": min_fraction,
        "n_types_with_data": n_types,
        "cross_type_universals": cross_type,
        "per_type": per_type,
    }
    if organoid_type:
        if organoid_type not in papers_by_type:
            return {
                "error": f"No reagent data for '{organoid_type}'",
                "available_types": sorted(papers_by_type),
            }, 404
        result["organoid_type"] = organoid_type

    return result, 200


def handle_type_timeseries() -> tuple[dict, int]:
    """Organoid type publication counts by year from protocols.jsonl.

    Shows how each organoid type's presence in the corpus has grown or shifted
    over time — useful for identifying emerging types and publication trends.
    """
    if not PROTOCOLS_JSONL.exists():
        return {
            "error": "protocols.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    by_year: dict[str, dict[str, int]] = {}
    by_type: dict[str, dict[str, int]] = {}
    total_by_year: dict[str, int] = {}

    try:
        for line in PROTOCOLS_JSONL.read_text().splitlines():
            if not line.strip():
                continue
            p = json.loads(line)
            year = str(p.get("year") or "").strip()
            otype = (p.get("organoid_type") or "").strip()
            if not year or not otype or otype == "other":
                continue
            by_year.setdefault(year, {}).setdefault(otype, 0)
            by_year[year][otype] += 1
            by_type.setdefault(otype, {}).setdefault(year, 0)
            by_type[otype][year] += 1
            total_by_year[year] = total_by_year.get(year, 0) + 1
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"protocols.jsonl unreadable: {exc}"}, 500

    if not by_year:
        return {"error": "no year data in protocols.jsonl", "n_papers": 0}, 404

    years = sorted(by_year.keys())
    first_appearance = {
        t: min(y for y in ys if ys[y] > 0)
        for t, ys in by_type.items()
    }

    return {
        "years": years,
        "by_year": {y: by_year[y] for y in years},
        "by_type": {t: by_type[t] for t in sorted(by_type)},
        "total_by_year": {y: total_by_year[y] for y in years},
        "first_appearance": dict(sorted(first_appearance.items(), key=lambda x: x[1])),
    }, 200


def handle_type_similarity(top_n: int) -> tuple[dict, int]:
    """Pairwise organoid type similarity from reagents.jsonl (Jaccard on canonical reagents).

    Returns per-type top-N most similar types with shared reagent count and Jaccard score.
    Useful for: "which organoid types have the most protocol overlap with cerebral?"
    """
    top_n = max(1, min(top_n, 50))

    if not REAGENTS_JSONL.exists():
        return {
            "error": "reagents.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    # Build per-type canonical reagent sets
    reagents_by_type: dict[str, set[str]] = {}
    try:
        for line in REAGENTS_JSONL.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            otype = r.get("organoid_type") or r.get("type") or ""
            canonical = (r.get("canonical") or r.get("name") or "").strip().lower()
            if not otype or not canonical:
                continue
            reagents_by_type.setdefault(otype, set()).add(canonical)
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"reagents.jsonl unreadable: {exc}"}, 500

    if not reagents_by_type:
        return {"error": "no typed reagents found in reagents.jsonl", "n_types": 0}, 404

    types = sorted(reagents_by_type)

    def jaccard(a: set, b: set) -> float:
        return len(a & b) / len(a | b) if (a or b) else 0.0

    per_type = {}
    for t in types:
        ts = reagents_by_type[t]
        neighbors = []
        for u in types:
            if u == t:
                continue
            us = reagents_by_type[u]
            j = jaccard(ts, us)
            if j > 0:
                neighbors.append({
                    "type": u,
                    "jaccard": round(j, 4),
                    "n_shared": len(ts & us),
                    "n_union": len(ts | us),
                })
        neighbors.sort(key=lambda x: (-x["jaccard"], x["type"]))
        per_type[t] = {
            "n_reagents": len(ts),
            "top_similar": neighbors[:top_n],
        }

    return {
        "n_types": len(types),
        "method": "Jaccard similarity on canonical reagent names from reagents.jsonl",
        "per_type": per_type,
    }, 200


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


_SPECIES_ALIASES: dict[str, str] = {
    "homo sapiens": "human",
    "murine": "mouse",
    "mus musculus": "mouse",
}


def handle_species_breakdown(organoid_type: str | None) -> tuple[dict, int]:
    """Species distribution per organoid type from protocols.jsonl.

    Normalises legacy aliases (murine→mouse, Homo sapiens→human) and returns
    per-type counts for human / mouse / other, plus cross-corpus totals.
    Optional ?type= restricts output to one organoid type.
    """
    if not PROTOCOLS_JSONL.exists():
        return {
            "error": "protocols.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    if organoid_type and not re.match(r'^[\w-]+$', organoid_type):
        return {"error": "invalid organoid_type"}, 400

    per_type: dict[str, dict[str, int]] = {}
    cross_corpus: dict[str, int] = {}

    try:
        for line in PROTOCOLS_JSONL.read_text().splitlines():
            if not line.strip():
                continue
            p = json.loads(line)
            ot = (p.get("organoid_type") or "").strip()
            if not ot or ot == "other":
                continue
            raw = (p.get("species") or "not_stated").strip()
            sp = _SPECIES_ALIASES.get(raw.lower(), raw.lower())
            per_type.setdefault(ot, {})
            per_type[ot][sp] = per_type[ot].get(sp, 0) + 1
            cross_corpus[sp] = cross_corpus.get(sp, 0) + 1
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"protocols.jsonl unreadable: {exc}"}, 500

    if not per_type:
        return {"error": "no organoid type data in protocols.jsonl"}, 404

    if organoid_type:
        if organoid_type not in per_type:
            return {
                "error": f"No data for organoid type '{organoid_type}'",
                "available_types": sorted(per_type),
            }, 404
        return {
            "organoid_type": organoid_type,
            "species": per_type[organoid_type],
        }, 200

    # Sort each type's dict by count descending
    summary_per_type = {
        t: dict(sorted(counts.items(), key=lambda kv: -kv[1]))
        for t, counts in sorted(per_type.items())
    }
    return {
        "cross_corpus": dict(sorted(cross_corpus.items(), key=lambda kv: -kv[1])),
        "per_type": summary_per_type,
        "n_types": len(per_type),
    }, 200


_MATRIX_ALIASES: dict[str, str] = {
    # Matrigel variants
    "matrigel": "Matrigel",
    "matrigel™": "Matrigel",
    "matrigel tm": "Matrigel",
    "corning matrigel": "Matrigel",
    "corning matrigel hc": "Matrigel",
    "growth factor reduced matrigel": "Matrigel",
    "growth factor-reduced matrigel": "Matrigel",
    # Geltrex
    "geltrex": "Geltrex",
    "geltrex ldev-free": "Geltrex",
    # Basement membrane extract
    "bme": "BME",
    "basement membrane extract": "BME",
    "cultrex basement membrane extract, type 2": "BME",
    "cultrex bme": "BME",
    "cultrex pathclear bme": "BME",
    # Vitronectin
    "vitronectin": "Vitronectin",
    "vitronectin xf": "Vitronectin",
    # Collagen
    "collagen": "collagen",
    "collagen i": "collagen",
    "collagen i-matrigel": "collagen+Matrigel",
    # Laminin
    "laminin": "laminin",
    "laminin-511": "laminin",
    "laminin 511": "laminin",
}


def handle_matrix_breakdown(organoid_type: str | None) -> tuple[dict, int]:
    """Extracellular matrix usage per organoid type from protocols.jsonl.

    Normalises common variants (Matrigel™/Corning Matrigel → Matrigel, BME variants → BME,
    vitronectin XF → Vitronectin, Laminin 511 → laminin) and returns per-type matrix
    distribution plus cross-corpus totals. Optional ?type=kidney for one type.
    """
    if not PROTOCOLS_JSONL.exists():
        return {
            "error": "protocols.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    if organoid_type and not re.match(r'^[\w-]+$', organoid_type):
        return {"error": "invalid organoid_type"}, 400

    per_type: dict[str, dict[str, int]] = {}
    cross_corpus: dict[str, int] = {}

    try:
        for line in PROTOCOLS_JSONL.read_text().splitlines():
            if not line.strip():
                continue
            p = json.loads(line)
            ot = (p.get("organoid_type") or "").strip()
            if not ot or ot == "other":
                continue
            raw = (p.get("matrix") or "not_stated").strip()
            mx = _MATRIX_ALIASES.get(raw.lower(), raw)
            per_type.setdefault(ot, {})
            per_type[ot][mx] = per_type[ot].get(mx, 0) + 1
            cross_corpus[mx] = cross_corpus.get(mx, 0) + 1
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"protocols.jsonl unreadable: {exc}"}, 500

    if not per_type:
        return {"error": "no organoid type data in protocols.jsonl"}, 404

    if organoid_type:
        if organoid_type not in per_type:
            return {
                "error": f"No data for organoid type '{organoid_type}'",
                "available_types": sorted(per_type),
            }, 404
        return {
            "organoid_type": organoid_type,
            "matrix": dict(sorted(per_type[organoid_type].items(), key=lambda kv: -kv[1])),
        }, 200

    summary_per_type = {
        t: dict(sorted(counts.items(), key=lambda kv: -kv[1]))
        for t, counts in sorted(per_type.items())
    }
    return {
        "cross_corpus": dict(sorted(cross_corpus.items(), key=lambda kv: -kv[1])),
        "per_type": summary_per_type,
        "n_types": len(per_type),
    }, 200


_BASE_MEDIA_ALIASES: dict[str, str] = {
    # Advanced DMEM/F12 variants
    "advanced dmem/f12": "Advanced DMEM/F12",
    "advanced dmem/f-12": "Advanced DMEM/F12",
    "advanced dmem-f12": "Advanced DMEM/F12",
    "addmem/f12": "Advanced DMEM/F12",
    "adf": "Advanced DMEM/F12",
    # DMEM/F12 variants
    "dmem/f12": "DMEM/F12",
    "dmem/f-12": "DMEM/F12",
    "dmem:f12": "DMEM/F12",
    "dmem/f12 (1:1)": "DMEM/F12",
    # mTeSR variants
    "mtesr plus medium": "mTeSR Plus",
    "mtesr plus": "mTeSR Plus",
    "mtesr1": "mTeSR1",
    "mtesr 1": "mTeSR1",
    # E8 variants
    "e8 medium": "Essential 8",
    "essential 8": "Essential 8",
    "essential 8 flex medium": "Essential 8",
    "tesr-e8": "Essential 8",
    "tesr e8": "Essential 8",
    # RPMI variants
    "rpmi 1640": "RPMI 1640",
    "rpmi-1640": "RPMI 1640",
    "rpmi": "RPMI 1640",
    # DMEM variants
    "dmem": "DMEM",
    "high-glucose dmem": "DMEM",
    # StemFlex
    "stemflex": "StemFlex",
    "stemflex medium": "StemFlex",
}


def handle_base_media_breakdown(organoid_type: str | None) -> tuple[dict, int]:
    """Base media usage per organoid type from protocols.jsonl.

    Normalises common variant names (Advanced DMEM/F-12 → Advanced DMEM/F12,
    DMEM:F12 → DMEM/F12, mTeSR Plus medium → mTeSR Plus, Essential 8 variants,
    RPMI variants). Optional ?type=kidney for one type.
    """
    if not PROTOCOLS_JSONL.exists():
        return {
            "error": "protocols.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    if organoid_type and not re.match(r'^[\w-]+$', organoid_type):
        return {"error": "invalid organoid_type"}, 400

    per_type: dict[str, dict[str, int]] = {}
    cross_corpus: dict[str, int] = {}

    try:
        for line in PROTOCOLS_JSONL.read_text().splitlines():
            if not line.strip():
                continue
            p = json.loads(line)
            ot = (p.get("organoid_type") or "").strip()
            if not ot or ot == "other":
                continue
            raw = (p.get("base_media") or "not_stated").strip()
            bm = _BASE_MEDIA_ALIASES.get(raw.lower(), raw)
            per_type.setdefault(ot, {})
            per_type[ot][bm] = per_type[ot].get(bm, 0) + 1
            cross_corpus[bm] = cross_corpus.get(bm, 0) + 1
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"protocols.jsonl unreadable: {exc}"}, 500

    if not per_type:
        return {"error": "no organoid type data in protocols.jsonl"}, 404

    if organoid_type:
        if organoid_type not in per_type:
            return {
                "error": f"No data for organoid type '{organoid_type}'",
                "available_types": sorted(per_type),
            }, 404
        return {
            "organoid_type": organoid_type,
            "base_media": dict(sorted(per_type[organoid_type].items(), key=lambda kv: -kv[1])),
        }, 200

    return {
        "cross_corpus": dict(sorted(cross_corpus.items(), key=lambda kv: -kv[1])),
        "per_type": {
            t: dict(sorted(counts.items(), key=lambda kv: -kv[1]))
            for t, counts in sorted(per_type.items())
        },
        "n_types": len(per_type),
    }, 200


# Source cell type values from protocols.jsonl are already normalised by the pipeline
# (iPSC / adult_stem_cell / primary_tissue / ESC / other).  The alias dict below
# handles any legacy / LLM-variant spellings that slip through.
_SOURCE_CELL_ALIASES: dict[str, str] = {
    "ipsc": "iPSC",
    "ips cell": "iPSC",
    "ips cells": "iPSC",
    "induced pluripotent stem cell": "iPSC",
    "induced pluripotent stem cells": "iPSC",
    "pluripotent stem cell": "iPSC",
    "hipscs": "iPSC",
    "hipsc": "iPSC",
    "esc": "ESC",
    "embryonic stem cell": "ESC",
    "embryonic stem cells": "ESC",
    "hesc": "ESC",
    "hescs": "ESC",
    "es cell": "ESC",
    "adult stem cell": "adult_stem_cell",
    "adult_stemcell": "adult_stem_cell",
    "primary": "primary_tissue",
    "primary tissue": "primary_tissue",
    "primary cells": "primary_tissue",
    "primary cell": "primary_tissue",
    "biopsy": "primary_tissue",
}


def handle_source_cell_breakdown(organoid_type: str | None) -> tuple[dict, int]:
    """Source cell type distribution per organoid type from protocols.jsonl.

    Normalises legacy variant spellings to the canonical set (iPSC,
    adult_stem_cell, primary_tissue, ESC, other). Optional ?type=kidney
    for one type.
    """
    if not PROTOCOLS_JSONL.exists():
        return {
            "error": "protocols.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    if organoid_type and not re.match(r'^[\w-]+$', organoid_type):
        return {"error": "invalid organoid_type"}, 400

    per_type: dict[str, dict[str, int]] = {}
    cross_corpus: dict[str, int] = {}

    try:
        for line in PROTOCOLS_JSONL.read_text().splitlines():
            if not line.strip():
                continue
            p = json.loads(line)
            ot = (p.get("organoid_type") or "").strip()
            if not ot or ot == "other":
                continue
            raw = (p.get("source_cell_type") or "not_stated").strip()
            sc = _SOURCE_CELL_ALIASES.get(raw.lower(), raw)
            per_type.setdefault(ot, {})
            per_type[ot][sc] = per_type[ot].get(sc, 0) + 1
            cross_corpus[sc] = cross_corpus.get(sc, 0) + 1
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"protocols.jsonl unreadable: {exc}"}, 500

    if not per_type:
        return {"error": "no organoid type data in protocols.jsonl"}, 404

    if organoid_type:
        if organoid_type not in per_type:
            return {
                "error": f"No data for organoid type '{organoid_type}'",
                "available_types": sorted(per_type),
            }, 404
        return {
            "organoid_type": organoid_type,
            "source_cell_type": dict(sorted(per_type[organoid_type].items(), key=lambda kv: -kv[1])),
        }, 200

    return {
        "cross_corpus": dict(sorted(cross_corpus.items(), key=lambda kv: -kv[1])),
        "per_type": {
            t: dict(sorted(counts.items(), key=lambda kv: -kv[1]))
            for t, counts in sorted(per_type.items())
        },
        "n_types": len(per_type),
    }, 200


def handle_protocol_complexity(organoid_type: str | None) -> tuple[dict, int]:
    """Per-type protocol complexity metrics from protocols.jsonl.

    Aggregates n_signaling_factors, n_supplements, n_figure_confirmed, and
    grounding_rate per organoid type. Returns mean, min, max, and n for each
    field so callers can assess which types require the most complex protocols.
    Optional ?type=kidney to return stats for one type.
    """
    if not PROTOCOLS_JSONL.exists():
        return {
            "error": "protocols.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    if organoid_type and not re.match(r'^[\w-]+$', organoid_type):
        return {"error": "invalid organoid_type"}, 400

    # Accumulate per-type lists for each metric.
    _FIELDS = ["n_signaling_factors", "n_supplements", "n_figure_confirmed", "grounding_rate"]
    buckets: dict[str, dict[str, list]] = {}

    try:
        for line in PROTOCOLS_JSONL.read_text().splitlines():
            if not line.strip():
                continue
            p = json.loads(line)
            ot = (p.get("organoid_type") or "").strip()
            if not ot or ot == "other":
                continue
            buckets.setdefault(ot, {f: [] for f in _FIELDS})
            for f in _FIELDS:
                v = p.get(f)
                if v is not None:
                    try:
                        buckets[ot][f].append(float(v))
                    except (TypeError, ValueError):
                        pass
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"protocols.jsonl unreadable: {exc}"}, 500

    if not buckets:
        return {"error": "no organoid type data in protocols.jsonl"}, 404

    def _stats(vals: list) -> dict | None:
        if not vals:
            return None
        return {
            "mean": round(sum(vals) / len(vals), 3),
            "min": min(vals),
            "max": max(vals),
            "n": len(vals),
        }

    def _type_summary(ot: str) -> dict:
        b = buckets[ot]
        # paper count = longest field list (grounding_rate is always present)
        n_papers = max(len(b[f]) for f in _FIELDS) if b else 0
        return {
            "n_papers": n_papers,
            **{f: _stats(b[f]) for f in _FIELDS},
        }

    if organoid_type:
        if organoid_type not in buckets:
            return {
                "error": f"No data for organoid type '{organoid_type}'",
                "available_types": sorted(buckets),
            }, 404
        return {"organoid_type": organoid_type, **_type_summary(organoid_type)}, 200

    per_type = {t: _type_summary(t) for t in sorted(buckets)}
    # cross-corpus ranking by avg n_signaling_factors
    ranked = sorted(
        [(t, s["n_signaling_factors"]["mean"]) for t, s in per_type.items()
         if s["n_signaling_factors"]],
        key=lambda x: -x[1],
    )
    return {
        "per_type": per_type,
        "n_types": len(per_type),
        "ranking_by_avg_signaling_factors": [t for t, _ in ranked],
    }, 200


def handle_reporting_gaps(organoid_type: str | None) -> tuple[dict, int]:
    """Field reporting rates across protocols.jsonl — transparency audit.

    Shows what fraction of papers report each key protocol field (species,
    matrix, base_media, source_cell_type, passaging, timeline). Helps
    researchers understand systematic reporting gaps in the literature and
    in our extraction. Optional ?type=kidney for one organoid type.
    """
    if not PROTOCOLS_JSONL.exists():
        return {
            "error": "protocols.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    if organoid_type and not re.match(r'^[\w-]+$', organoid_type):
        return {"error": "invalid organoid_type"}, 400

    # Fields to audit; values of None/""/not_stated count as not-reported.
    _AUDIT_FIELDS = [
        "species", "matrix", "base_media", "source_cell_type", "passaging", "timeline",
    ]

    def _is_reported(val) -> bool:
        if val is None:
            return False
        s = str(val).strip().lower()
        return s not in ("", "not_stated", "not_reported")

    def _field_stats(rows: list[dict]) -> dict:
        n = len(rows)
        if n == 0:
            return {}
        stats: dict[str, dict] = {}
        for f in _AUDIT_FIELDS:
            rep = sum(1 for r in rows if _is_reported(r.get(f)))
            stats[f] = {
                "reported": rep,
                "not_stated": n - rep,
                "total": n,
                "reporting_rate": round(rep / n, 4),
            }
        return stats

    # Build per-type bucket.
    by_type: dict[str, list] = {}
    all_rows: list[dict] = []

    try:
        for line in PROTOCOLS_JSONL.read_text().splitlines():
            if not line.strip():
                continue
            p = json.loads(line)
            ot = (p.get("organoid_type") or "").strip()
            if not ot or ot == "other":
                continue
            by_type.setdefault(ot, []).append(p)
            all_rows.append(p)
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"protocols.jsonl unreadable: {exc}"}, 500

    if not by_type:
        return {"error": "no organoid type data in protocols.jsonl"}, 404

    if organoid_type:
        if organoid_type not in by_type:
            return {
                "error": f"No data for organoid type '{organoid_type}'",
                "available_types": sorted(by_type),
            }, 404
        rows_for_type = by_type[organoid_type]
        return {
            "organoid_type": organoid_type,
            "n_papers": len(rows_for_type),
            "fields": _field_stats(rows_for_type),
        }, 200

    cross_corpus = _field_stats(all_rows)
    per_type = {t: {"n_papers": len(rs), "fields": _field_stats(rs)} for t, rs in sorted(by_type.items())}

    # Rank fields by cross-corpus reporting gap (lowest rate = biggest gap).
    ranked_gaps = sorted(
        cross_corpus.keys(),
        key=lambda f: cross_corpus[f]["reporting_rate"],
    )

    return {
        "n_papers": len(all_rows),
        "n_types": len(by_type),
        "cross_corpus": cross_corpus,
        "ranking_by_gap": ranked_gaps,
        "per_type": per_type,
    }, 200


def handle_year_trend() -> tuple[dict, int]:
    """Yearly trends in publication volume, protocol complexity, and reporting quality.

    Aggregates per-year from protocols.jsonl: paper count, avg n_signaling_factors,
    avg grounding_rate, and field reporting rates (species/matrix/base_media/
    passaging/timeline). Shows how the field has evolved and whether reporting
    completeness has improved over time.
    """
    if not PROTOCOLS_JSONL.exists():
        return {
            "error": "protocols.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    _REPORT_FIELDS = ["species", "matrix", "base_media", "passaging", "timeline"]

    def _is_reported(val) -> bool:
        if val is None:
            return False
        return str(val).strip().lower() not in ("", "not_stated", "not_reported")

    by_year: dict[str, dict] = {}

    try:
        for line in PROTOCOLS_JSONL.read_text().splitlines():
            if not line.strip():
                continue
            p = json.loads(line)
            yr = str(p.get("year") or "").strip()
            if not yr:
                continue
            if yr not in by_year:
                by_year[yr] = {
                    "n_papers": 0,
                    "_sf": [],
                    "_gr": [],
                    **{f: {"reported": 0, "total": 0} for f in _REPORT_FIELDS},
                }
            by_year[yr]["n_papers"] += 1
            nsf = p.get("n_signaling_factors")
            if nsf is not None:
                try:
                    by_year[yr]["_sf"].append(float(nsf))
                except (TypeError, ValueError):
                    pass
            gr = p.get("grounding_rate")
            if gr is not None:
                try:
                    by_year[yr]["_gr"].append(float(gr))
                except (TypeError, ValueError):
                    pass
            for f in _REPORT_FIELDS:
                by_year[yr][f]["total"] += 1
                if _is_reported(p.get(f)):
                    by_year[yr][f]["reported"] += 1
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"protocols.jsonl unreadable: {exc}"}, 500

    if not by_year:
        return {"error": "no year data in protocols.jsonl"}, 404

    def _finalize(yd: dict) -> dict:
        sf_list = yd.pop("_sf")
        gr_list = yd.pop("_gr")
        result = {
            "n_papers": yd["n_papers"],
            "avg_signaling_factors": round(sum(sf_list) / len(sf_list), 2) if sf_list else None,
            "avg_grounding_rate": round(sum(gr_list) / len(gr_list), 4) if gr_list else None,
            "reporting_rates": {
                f: round(yd[f]["reported"] / yd[f]["total"], 4) if yd[f]["total"] else None
                for f in _REPORT_FIELDS
            },
        }
        return result

    years_sorted = sorted(by_year)
    return {
        "years": {yr: _finalize(by_year[yr]) for yr in years_sorted},
        "n_years": len(years_sorted),
        "year_range": [years_sorted[0], years_sorted[-1]],
    }, 200


def handle_grounding_quality(organoid_type: str | None) -> tuple[dict, int]:
    """Reagent grounding coverage from reagents.jsonl.

    Reports grounding_rate (fraction of reagents with grounded=1), evidence_quote_rate
    (fraction with a verbatim evidence quote), and suspect_unit_count. Broken down
    cross-corpus, per organoid type, and by reagent kind (signaling/supplement/
    small_molecule/matrix). Also surfaces the top ungrounded canonical names to
    prioritise future SRI grounding work (Issue #8 S1).

    Optional: ?type=kidney filters to one organoid type.
    """
    if not REAGENTS_JSONL.exists():
        return {
            "error": "reagents.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    if organoid_type is not None and not re.match(r'^[\w-]+$', organoid_type):
        return {"error": "invalid organoid_type"}, 400

    try:
        rows = [
            json.loads(line)
            for line in REAGENTS_JSONL.read_text().splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"reagents.jsonl unreadable: {exc}"}, 500

    if organoid_type:
        rows = [r for r in rows if r.get("organoid_type") == organoid_type]
        if not rows:
            return {
                "error": f"no reagents found for organoid_type '{organoid_type}'",
                "hint": "check /analytics/coverage for available types",
            }, 404

    def _stats(subset: list[dict]) -> dict:
        n = len(subset)
        if n == 0:
            return {"n_reagents": 0, "n_grounded": 0, "grounding_rate": None,
                    "n_with_quote": 0, "evidence_quote_rate": None, "n_suspect_unit": 0}
        n_grounded = sum(1 for r in subset if r.get("grounded"))
        n_quote = sum(1 for r in subset if r.get("evidence_quote"))
        n_suspect = sum(1 for r in subset if r.get("suspect_unit"))
        return {
            "n_reagents": n,
            "n_grounded": n_grounded,
            "grounding_rate": round(n_grounded / n, 4),
            "n_with_quote": n_quote,
            "evidence_quote_rate": round(n_quote / n, 4),
            "n_suspect_unit": n_suspect,
        }

    cross = _stats(rows)

    # per organoid type
    by_type: dict[str, list] = {}
    for r in rows:
        ot = r.get("organoid_type") or "unknown"
        by_type.setdefault(ot, []).append(r)
    per_type = {ot: _stats(subset) for ot, subset in sorted(by_type.items())}

    # by reagent kind
    by_kind: dict[str, list] = {}
    for r in rows:
        k = r.get("kind") or "unknown"
        by_kind.setdefault(k, []).append(r)
    by_kind_stats = {k: _stats(subset) for k, subset in sorted(by_kind.items())}

    # top ungrounded canonical names (for S1 grounding prioritization)
    ungrounded = [r.get("canonical") or r.get("name") or "unknown"
                  for r in rows if not r.get("grounded")]
    from collections import Counter
    top_ungrounded = [
        {"canonical": name, "count": cnt}
        for name, cnt in Counter(ungrounded).most_common(20)
    ]

    ranking_by_grounding_rate = sorted(
        [ot for ot in per_type if per_type[ot]["n_reagents"] >= 5],
        key=lambda ot: per_type[ot]["grounding_rate"] or 0,
        reverse=True,
    )

    result: dict = {
        "cross_corpus": cross,
        "per_type": per_type if organoid_type is None else None,
        "by_kind": by_kind_stats,
        "top_ungrounded": top_ungrounded,
        "n_types": len(per_type),
    }
    if organoid_type is None:
        result["ranking_by_grounding_rate"] = ranking_by_grounding_rate
    else:
        result["organoid_type"] = organoid_type
        del result["per_type"]

    return result, 200


def handle_concentration_stats(query: str | None, organoid_type: str | None) -> tuple[dict, int]:
    """Aggregate concentration statistics per canonical reagent from reagents.jsonl.

    Groups all reagents by `canonical` name (falling back to `name`), then for each
    group computes: median/min/max/std value (within-unit), n_with_value, n_total,
    organoid_types where used, and most common unit. Optional ?q= filters to one
    canonical name; optional ?type= restricts to one organoid type.

    Returns the top 50 canonical reagents by n_with_value when ?q= is absent,
    sorted by n_with_value descending. Returns a single-reagent object when ?q= is present.
    """
    if not REAGENTS_JSONL.exists():
        return {
            "error": "reagents.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    if organoid_type is not None and not re.match(r'^[\w-]+$', organoid_type):
        return {"error": "invalid organoid_type"}, 400

    query_norm = (query or "").strip()[:100].lower() if query else None

    try:
        rows = [
            json.loads(line)
            for line in REAGENTS_JSONL.read_text().splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"reagents.jsonl unreadable: {exc}"}, 500

    if organoid_type:
        rows = [r for r in rows if r.get("organoid_type") == organoid_type]
        if not rows:
            return {
                "error": f"no reagents found for organoid_type '{organoid_type}'",
                "hint": "check /analytics/coverage for available types",
            }, 404

    # Group rows by canonical name
    by_name: dict[str, list] = {}
    for r in rows:
        cname = (r.get("canonical") or r.get("name") or "unknown").strip()
        by_name.setdefault(cname, []).append(r)

    def _conc_stats(reagent_rows: list) -> dict:
        n_total = len(reagent_rows)
        vals_by_unit: dict[str, list] = {}
        for r in reagent_rows:
            v = r.get("value")
            u = (r.get("canonical_unit") or r.get("unit") or "unknown").strip()
            if v is not None:
                try:
                    vals_by_unit.setdefault(u, []).append(float(v))
                except (TypeError, ValueError):
                    pass

        n_with_value = sum(len(vs) for vs in vals_by_unit.values())
        otypes = sorted({r.get("organoid_type") or "unknown" for r in reagent_rows})

        # Dominant unit by count
        dominant_unit = max(vals_by_unit, key=lambda u: len(vals_by_unit[u])) if vals_by_unit else None

        stats_per_unit = {}
        for u, vs in sorted(vals_by_unit.items()):
            n = len(vs)
            vs_sorted = sorted(vs)
            median = vs_sorted[n // 2] if n % 2 else (vs_sorted[n // 2 - 1] + vs_sorted[n // 2]) / 2
            mean = sum(vs) / n
            variance = sum((v - mean) ** 2 for v in vs) / n if n > 1 else 0.0
            std = variance ** 0.5
            stats_per_unit[u] = {
                "n": n,
                "median": round(median, 4),
                "min": round(min(vs), 4),
                "max": round(max(vs), 4),
                "std": round(std, 4),
            }

        return {
            "n_total": n_total,
            "n_with_value": n_with_value,
            "dominant_unit": dominant_unit,
            "stats_per_unit": stats_per_unit,
            "organoid_types": otypes,
        }

    if query_norm:
        # Single-reagent lookup — case-insensitive substring match
        matches = {name: r for name, r in by_name.items() if query_norm in name.lower()}
        if not matches:
            return {
                "error": f"no reagents matching '{query_norm}'",
                "hint": "use /analytics/reagent?q=TERM for FTS lookup",
            }, 404
        # Exact match preferred; else most-common match
        exact = next((k for k in matches if k.lower() == query_norm), None)
        canonical_name = exact or max(matches, key=lambda k: len(matches[k]))
        return {
            "canonical": canonical_name,
            **_conc_stats(matches[canonical_name]),
            "all_matches": sorted(matches) if len(matches) > 1 else None,
        }, 200

    # Return top-50 by n_with_value
    all_stats = {name: _conc_stats(r) for name, r in by_name.items()}
    top = sorted(all_stats, key=lambda k: all_stats[k]["n_with_value"], reverse=True)[:50]
    return {
        "top_reagents": [{"canonical": name, **all_stats[name]} for name in top],
        "n_canonical_names": len(all_stats),
        "n_types": len({r.get("organoid_type") for r in rows}),
        "organoid_type_filter": organoid_type,
    }, 200


def handle_temporal_reagent_adoption(query: str | None, organoid_type: str | None) -> tuple[dict, int]:
    """Per-reagent temporal adoption from reagents.jsonl joined with protocols.jsonl.

    For each publication year, computes what fraction of papers published that year
    used the queried canonical reagent. Requires ?q= to name the canonical reagent
    (case-insensitive substring match). Optional ?type= restricts to one organoid type.

    Without ?q=, returns the top 20 reagents by peak annual adoption fraction with
    their trend direction — useful for discovering what to query next.
    """
    if not REAGENTS_JSONL.exists():
        return {"error": "reagents.jsonl not found", "hint": "Run: python pipeline/export_public.py"}, 404
    if not PROTOCOLS_JSONL.exists():
        return {"error": "protocols.jsonl not found", "hint": "Run: python pipeline/export_public.py"}, 404

    if organoid_type is not None and not re.match(r'^[\w-]+$', organoid_type):
        return {"error": "invalid organoid_type"}, 400

    # Build PMCID -> year map (and optional type filter set) from protocols.jsonl
    pmcid_year: dict[str, str] = {}
    pmcid_type: dict[str, str] = {}
    try:
        for line in PROTOCOLS_JSONL.read_text().splitlines():
            if not line.strip():
                continue
            p = json.loads(line)
            pmcid = p.get("pmcid")
            yr = p.get("year")
            ot = p.get("organoid_type") or ""
            if pmcid and yr:
                pmcid_year[pmcid] = str(yr)
                pmcid_type[pmcid] = ot
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"protocols.jsonl unreadable: {exc}"}, 500

    # Apply type filter to the paper universe
    if organoid_type:
        valid_pmcids = {p for p, t in pmcid_type.items() if t == organoid_type}
    else:
        valid_pmcids = set(pmcid_year)

    if not valid_pmcids:
        return {"error": f"no papers found for organoid_type '{organoid_type}'"}, 404

    # Year -> n_papers_total in the (optionally filtered) corpus
    from collections import Counter as _Counter
    year_total: dict[str, int] = _Counter(pmcid_year[p] for p in valid_pmcids)

    # Load reagents
    try:
        reagent_rows = [
            json.loads(line)
            for line in REAGENTS_JSONL.read_text().splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"reagents.jsonl unreadable: {exc}"}, 500

    def _adoption_for_canonical(rows: list) -> dict:
        """Given reagent rows for one canonical, return per-year adoption data."""
        pmcids_using = {r["pmcid"] for r in rows if r.get("pmcid") in valid_pmcids}
        years_data = {}
        for yr in sorted(year_total):
            papers_this_yr = {p for p in valid_pmcids if pmcid_year.get(p) == yr}
            n_total = len(papers_this_yr)
            n_with = len(papers_this_yr & pmcids_using)
            years_data[yr] = {
                "n_papers_total": n_total,
                "n_papers_with_reagent": n_with,
                "adoption_fraction": round(n_with / n_total, 3) if n_total else None,
            }

        year_list = sorted(year_total)
        fracs = [years_data[y]["adoption_fraction"] for y in year_list
                 if years_data[y]["adoption_fraction"] is not None]

        early = [years_data[y]["adoption_fraction"] for y in year_list[:3]
                 if years_data[y]["adoption_fraction"] is not None]
        recent = [years_data[y]["adoption_fraction"] for y in year_list[-3:]
                  if years_data[y]["adoption_fraction"] is not None]
        early_avg = round(sum(early) / len(early), 3) if early else None
        recent_avg = round(sum(recent) / len(recent), 3) if recent else None
        peak_frac = max(fracs) if fracs else None
        peak_yr = next((y for y in year_list if years_data[y]["adoption_fraction"] == peak_frac), None)

        direction = "stable"
        if early_avg is not None and recent_avg is not None:
            delta = recent_avg - early_avg
            if delta > 0.05:
                direction = "rising"
            elif delta < -0.05:
                direction = "falling"

        return {
            "years": years_data,
            "n_years": len(year_list),
            "trend": {
                "first_year": year_list[0] if year_list else None,
                "last_year": year_list[-1] if year_list else None,
                "peak_year": peak_yr,
                "peak_adoption": peak_frac,
                "early_adoption_avg": early_avg,
                "recent_adoption_avg": recent_avg,
                "direction": direction,
            },
            "n_pmcids_using": len(pmcids_using),
        }

    # Group all reagent rows by canonical name
    by_canonical: dict[str, list] = {}
    for r in reagent_rows:
        cname = (r.get("canonical") or r.get("name") or "unknown").strip()
        by_canonical.setdefault(cname, []).append(r)

    if query:
        q_lower = query.strip().lower()
        matches = {k: v for k, v in by_canonical.items() if q_lower in k.lower()}
        if not matches:
            return {"error": f"no reagents matching '{query}'"}, 404
        exact = next((k for k in matches if k.lower() == q_lower), None)
        canonical_name = exact or max(matches, key=lambda k: len(matches[k]))
        result = {
            "canonical": canonical_name,
            "canonical_query": query,
            "organoid_type_filter": organoid_type,
            "all_matches": sorted(matches) if len(matches) > 1 else None,
            **_adoption_for_canonical(matches[canonical_name]),
        }
        return result, 200

    # No query: return top 20 by peak adoption fraction
    summaries = []
    for cname, rows in by_canonical.items():
        ad = _adoption_for_canonical(rows)
        peak = ad["trend"]["peak_adoption"] or 0
        if peak > 0:
            summaries.append({
                "canonical": cname,
                "n_pmcids_using": ad["n_pmcids_using"],
                "trend": ad["trend"],
            })
    summaries.sort(key=lambda s: -(s["trend"]["peak_adoption"] or 0))
    return {
        "organoid_type_filter": organoid_type,
        "top_reagents_by_peak_adoption": summaries[:20],
        "n_canonicals_total": len(by_canonical),
        "corpus_years": sorted(year_total.keys()),
        "hint": "pass ?q=TERM to get full year-by-year adoption data for one reagent",
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
            "/analytics/reagent-network?q=TERM": "reagent co-occurrence: which reagents most often appear in the same papers as TERM",
            "/analytics/type-similarity": "pairwise organoid type similarity (Jaccard on canonical reagent sets) — which types share the most protocol overlap",
            "/analytics/type-timeseries": "organoid type publication counts by year — growth trends and first-appearance dates from protocols.jsonl",
            "/analytics/universal-reagents": "type-essential reagents: canonical reagents appearing in >= 50% of protocols for each type; also cross-type universals",
            "/analytics/species-breakdown": "species distribution per organoid type (human / mouse / other) from protocols.jsonl; optional ?type=kidney",
            "/analytics/matrix-breakdown": "extracellular matrix usage per organoid type (Matrigel / Geltrex / Vitronectin / ...) with alias normalisation; optional ?type=kidney",
            "/analytics/base-media-breakdown": "base media usage per organoid type (DMEM/F12 / mTeSR1 / Advanced DMEM/F12 / ...) with alias normalisation; optional ?type=kidney",
            "/analytics/source-cell-breakdown": "source cell type distribution per organoid type (iPSC / adult_stem_cell / primary_tissue / ESC); optional ?type=kidney",
            "/analytics/protocol-complexity": "per-type protocol complexity: avg n_signaling_factors, n_supplements, n_figure_confirmed, grounding_rate with min/max/n; ranked by complexity",
            "/analytics/reporting-gaps": "field reporting rates across the corpus (species/matrix/base_media/source_cell_type/passaging/timeline) — transparency audit; optional ?type=kidney",
            "/analytics/year-trend": "yearly trends: paper count, avg n_signaling_factors, avg grounding_rate, field reporting rates by year — shows how the field has evolved",
            "/analytics/grounding-quality": "reagent grounding coverage: grounding_rate, evidence_quote_rate, suspect_unit_count — by type and by kind; top ungrounded canonical names for S1 prioritisation",
            "/analytics/concentration-stats": "aggregate concentration distributions per canonical reagent: median, min, max, std, dominant unit — top 50 by n_with_value; ?q= for one reagent, ?type= for one type",
            "/analytics/temporal-reagent-adoption": "per-reagent temporal adoption: fraction of papers per year using each canonical reagent; ?q= for full year-by-year data, ?type= for one organoid type; without ?q= returns top 20 by peak adoption",
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


async def route_universal_reagents(datasette, request):
    organoid_type = request.args.get("type") or None
    try:
        min_fraction = float(request.args.get("min_fraction", "0.5"))
    except (TypeError, ValueError):
        min_fraction = 0.5
    data, status = handle_universal_reagents(organoid_type, min_fraction)
    return Response.json(data, status=status)


async def route_type_timeseries(datasette, request):
    data, status = handle_type_timeseries()
    return Response.json(data, status=status)


async def route_type_similarity(datasette, request):
    try:
        top_n = int(request.args.get("top_n", "5"))
    except (TypeError, ValueError):
        top_n = 5
    data, status = handle_type_similarity(top_n)
    return Response.json(data, status=status)


async def route_reagent_network(datasette, request):
    query = request.args.get("q", "")
    try:
        limit = int(request.args.get("limit", "20"))
    except (TypeError, ValueError):
        limit = 20
    data, status = handle_reagent_network(query, limit)
    return Response.json(data, status=status)


async def route_species_breakdown(datasette, request):
    organoid_type = request.args.get("type") or None
    data, status = handle_species_breakdown(organoid_type)
    return Response.json(data, status=status)


async def route_matrix_breakdown(datasette, request):
    organoid_type = request.args.get("type") or None
    data, status = handle_matrix_breakdown(organoid_type)
    return Response.json(data, status=status)


async def route_base_media_breakdown(datasette, request):
    organoid_type = request.args.get("type") or None
    data, status = handle_base_media_breakdown(organoid_type)
    return Response.json(data, status=status)


async def route_source_cell_breakdown(datasette, request):
    organoid_type = request.args.get("type") or None
    data, status = handle_source_cell_breakdown(organoid_type)
    return Response.json(data, status=status)


async def route_protocol_complexity(datasette, request):
    organoid_type = request.args.get("type") or None
    data, status = handle_protocol_complexity(organoid_type)
    return Response.json(data, status=status)


async def route_reporting_gaps(datasette, request):
    organoid_type = request.args.get("type") or None
    data, status = handle_reporting_gaps(organoid_type)
    return Response.json(data, status=status)


async def route_year_trend(datasette, request):
    data, status = handle_year_trend()
    return Response.json(data, status=status)


async def route_grounding_quality(datasette, request):
    organoid_type = request.args.get("type") or None
    data, status = handle_grounding_quality(organoid_type)
    return Response.json(data, status=status)


async def route_concentration_stats(datasette, request):
    query = request.args.get("q") or None
    organoid_type = request.args.get("type") or None
    data, status = handle_concentration_stats(query, organoid_type)
    return Response.json(data, status=status)


async def route_temporal_reagent_adoption(datasette, request):
    query = request.args.get("q") or None
    organoid_type = request.args.get("type") or None
    data, status = handle_temporal_reagent_adoption(query, organoid_type)
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
        (r"^/analytics/reagent-network$", route_reagent_network),
        (r"^/analytics/type-similarity$", route_type_similarity),
        (r"^/analytics/type-timeseries$", route_type_timeseries),
        (r"^/analytics/universal-reagents$", route_universal_reagents),
        (r"^/analytics/species-breakdown$", route_species_breakdown),
        (r"^/analytics/matrix-breakdown$", route_matrix_breakdown),
        (r"^/analytics/base-media-breakdown$", route_base_media_breakdown),
        (r"^/analytics/source-cell-breakdown$", route_source_cell_breakdown),
        (r"^/analytics/protocol-complexity$", route_protocol_complexity),
        (r"^/analytics/reporting-gaps$", route_reporting_gaps),
        (r"^/analytics/year-trend$", route_year_trend),
        (r"^/analytics/grounding-quality$", route_grounding_quality),
        (r"^/analytics/concentration-stats$", route_concentration_stats),
        (r"^/analytics/temporal-reagent-adoption$", route_temporal_reagent_adoption),
        (r"^/analytics/assay-endpoints$", route_assay_endpoints),
        (r"^/analytics/quality$", route_quality),
        (r"^/analytics/mior$", route_mior),
        (r"^/analytics/candidates$", route_candidates),
        (r"^/analytics/status$", route_status),
        (r"^/analytics/summary$", route_summary),
    ]
