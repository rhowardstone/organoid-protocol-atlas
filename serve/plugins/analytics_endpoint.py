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
  GET /analytics/kgx-summary                 -- KGX graph state: node/edge counts, resolution rate, review queue breakdown, top not-found and needs-review entities
  GET /analytics/concentration-by-type       -- per-organoid-type concentration stats for one canonical reagent: median/min/max/n per unit per type; requires ?q=
  GET /analytics/journal-breakdown           -- journal contribution counts cross-corpus and per organoid type; optional ?type= for one type
  GET /analytics/type-comparison             -- side-by-side organoid type comparison: shared/unique canonical reagents, Jaccard score, per-kind breakdown; requires ?a= and ?b=
  GET /analytics/concentration-deviation     -- dose inconsistency ranking: canonical reagents sorted by coefficient of variation (std/mean) per dominant unit; min_n= threshold (default 3)
  GET /analytics/reagent-prevalence          -- type-breadth ranking: canonical reagents sorted by n_organoid_types they appear in; ?q= for per-type breakdown of one canonical; ?min_types= threshold
  GET /analytics/protocol-outliers           -- per-type outlier detection on n_signaling_factors: complex and minimal protocols (z-score threshold, default 1.5); ?type= for one type
  GET /analytics/grounding-distribution      -- per-paper grounding rate histogram (10 buckets 0-100%); per-type mean; top/bottom 20 papers; ?type= for one type; live from protocols.jsonl
  GET /analytics/type-maturity               -- field maturity classification per organoid type: first_year, n_years_active, trajectory (accelerating/stable/slowing), maturity_tier; live from protocols.jsonl
  GET /analytics/reagent-cooccurrence        -- pairwise signaling-factor co-occurrence: top 100 pairs by n_papers with Jaccard; ?q= for one canonical; ?type= filter; live from reagents.jsonl
  GET /analytics/supplement-breakdown        -- per-type and cross-type breakdown of supplements (kind=supplement): top 50 globally, cross-type list, per-type top 10; ?q= and ?type= filters; live from reagents.jsonl
  GET /analytics/role-breakdown              -- normalized functional role distribution for signaling reagents: signaling_factor/growth_factor/differentiation/inhibitor/agonist etc.; ?q= for one role; ?type= filter; live from reagents.jsonl
  GET /analytics/type-reagent-heatmap        -- type × canonical usage matrix: top_n canonicals × all types, each cell = n_papers; ?kind= filter; ?top_n= (default 20); live from reagents.jsonl
  GET /analytics/canonical-name-variants     -- normalization complexity report: canonical → all raw names that map to it; top 30 by n_variants; ?q= for one canonical; live from reagents.jsonl
  GET /analytics/concentration-unit-distribution -- unit inconsistency report: canonicals using >1 unit system; top 30 by n_units; ?q= for one canonical with min/median/max per unit; live from reagents.jsonl
  GET /analytics/protocol-size-distribution  -- full histogram of n_signaling_factors and n_supplements per paper; global + per-type mean/median/std; ?type= for one type; live from protocols.jsonl
  GET /analytics/evidence-quote-coverage     -- per-type and per-kind rate of verbatim evidence quotes in reagent records; ?type= for one type with top canonicals; ?kind=signaling|supplement filter; live from reagents.jsonl
  GET /analytics/concentration-value-rate   -- canonicals ranked by fraction of records with a numeric dose value; highest_reporters + lowest_reporters lists; ?q= for per-type breakdown; ?min_n= threshold; ?kind= filter; live from reagents.jsonl
  GET /analytics/kind-ambiguity            -- canonicals that appear in both signaling and supplement kinds; sorted by ambiguity (minority_fraction); ?q= for per-type kind breakdown; ?min_n= threshold; live from reagents.jsonl
  GET /analytics/canonical-type-adoption   -- reagent diffusion: n_organoid_types using each canonical by year (first_year, n_types_current, year_peak); ?q= for per-year type list; ?min_types= filter; live from both JSONLs
  GET /analytics/unit-normalization-report  -- shows how raw unit strings cluster into canonical_unit groups (ng/mL←[ng/mL,ng/ml,ng ml-1], uM←[μM,µM,µm,...]); sorted by n_raw_strings; ?q= for one canonical_unit; live from reagents.jsonl
  GET /analytics/source-cell-reagent-profile -- characteristic reagents by source_cell_type (iPSC/adult_stem_cell/primary_tissue/ESC); top 20 canonicals per source; pairwise Jaccard; ?source= for one source type; live from both JSONLs
  GET /analytics                                -- index of available analytics

All endpoints degrade gracefully — if the pre-computed file doesn't exist they return
a 404 with an actionable message telling the user what command to run to generate it.
This is the serve-layer wrapper; all analysis logic lives in pipeline/*.py.
"""

from __future__ import annotations

import json
import math
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


def handle_type_comparison(type_a: str | None, type_b: str | None) -> tuple[dict, int]:
    """Side-by-side comparison of two organoid types' canonical reagent profiles.

    Returns shared canonical reagents (appearing in both types), reagents unique
    to each type, Jaccard similarity, and per-reagent-kind breakdown. Requires
    ?a= and ?b= specifying the two organoid type names.
    Complements /analytics/type-similarity (which gives Jaccard scores for all pairs)
    by surfacing the actual reagent lists, not just the score.
    """
    if not REAGENTS_JSONL.exists():
        return {"error": "reagents.jsonl not found", "hint": "Run: python pipeline/export_public.py"}, 404

    for val in (type_a, type_b):
        if not val or not val.strip():
            return {"error": "pass ?a= and ?b= specifying two organoid types"}, 400
        if not re.match(r'^[\w-]+$', val):
            return {"error": f"invalid organoid_type: '{val}'"}, 400

    type_a = type_a.strip()
    type_b = type_b.strip()

    if type_a == type_b:
        return {"error": "?a= and ?b= must be different organoid types"}, 400

    # Build per-type: {canonical_lower -> {canonical_display, kinds: set, n_records}}
    def _norm(name: str) -> str:
        return (name or "").strip().lower()

    type_data: dict[str, dict[str, dict]] = {type_a: {}, type_b: {}}

    try:
        for line in REAGENTS_JSONL.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            ot = r.get("organoid_type") or ""
            if ot not in (type_a, type_b):
                continue
            cname_display = (r.get("canonical") or r.get("name") or "unknown").strip()
            cname_lower = _norm(cname_display)
            kind = r.get("kind") or "unknown"
            bucket = type_data[ot]
            if cname_lower not in bucket:
                bucket[cname_lower] = {"canonical": cname_display, "kinds": set(), "n_records": 0}
            bucket[cname_lower]["kinds"].add(kind)
            bucket[cname_lower]["n_records"] += 1
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"reagents.jsonl unreadable: {exc}"}, 500

    set_a = set(type_data[type_a])
    set_b = set(type_data[type_b])

    if not set_a:
        return {"error": f"no reagents found for organoid_type '{type_a}'"}, 404
    if not set_b:
        return {"error": f"no reagents found for organoid_type '{type_b}'"}, 404

    shared_keys = set_a & set_b
    only_a_keys = set_a - set_b
    only_b_keys = set_b - set_a
    union_keys = set_a | set_b

    jaccard = round(len(shared_keys) / len(union_keys), 4) if union_keys else 0.0

    def _format(keys: set, bucket: dict) -> list:
        return sorted(
            [{"canonical": bucket[k]["canonical"],
              "kinds": sorted(bucket[k]["kinds"]),
              "n_records": bucket[k]["n_records"]}
             for k in keys],
            key=lambda x: -x["n_records"],
        )

    def _kind_breakdown(keys: set, bucket_a: dict, bucket_b: dict) -> dict:
        all_kinds: set = set()
        for k in keys:
            all_kinds |= bucket_a.get(k, {}).get("kinds", set())
            all_kinds |= bucket_b.get(k, {}).get("kinds", set())
        result = {}
        for kind in sorted(all_kinds):
            result[kind] = {
                "n_in_a": sum(1 for k in keys if kind in bucket_a.get(k, {}).get("kinds", set())),
                "n_in_b": sum(1 for k in keys if kind in bucket_b.get(k, {}).get("kinds", set())),
            }
        return result

    return {
        "type_a": type_a,
        "type_b": type_b,
        "jaccard_similarity": jaccard,
        "n_shared": len(shared_keys),
        "n_only_a": len(only_a_keys),
        "n_only_b": len(only_b_keys),
        "n_union": len(union_keys),
        "shared": _format(shared_keys, type_data[type_a]),
        "only_a": _format(only_a_keys, type_data[type_a]),
        "only_b": _format(only_b_keys, type_data[type_b]),
        "kind_breakdown_shared": _kind_breakdown(shared_keys, type_data[type_a], type_data[type_b]),
    }, 200


def handle_journal_breakdown(organoid_type: str | None) -> tuple[dict, int]:
    """Journal contribution counts from protocols.jsonl.

    Returns cross-corpus journal counts (top 50 by n_papers) and, for each
    organoid type, the top 5 contributing journals. Optional ?type= restricts
    output to a single organoid type with its full journal breakdown.
    Useful for auditing corpus composition bias.
    """
    if not PROTOCOLS_JSONL.exists():
        return {"error": "protocols.jsonl not found", "hint": "Run: python pipeline/export_public.py"}, 404

    if organoid_type is not None and not re.match(r'^[\w-]+$', organoid_type):
        return {"error": "invalid organoid_type"}, 400

    from collections import Counter as _Counter

    per_type: dict[str, dict[str, int]] = {}
    cross_corpus: dict[str, int] = {}

    try:
        for line in PROTOCOLS_JSONL.read_text().splitlines():
            if not line.strip():
                continue
            p = json.loads(line)
            ot = (p.get("organoid_type") or "").strip()
            journal = (p.get("journal") or "unknown").strip()
            if not ot or ot == "other":
                continue
            cross_corpus[journal] = cross_corpus.get(journal, 0) + 1
            per_type.setdefault(ot, {})
            per_type[ot][journal] = per_type[ot].get(journal, 0) + 1
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"protocols.jsonl unreadable: {exc}"}, 500

    if not per_type:
        return {"error": "no organoid type data in protocols.jsonl"}, 404

    if organoid_type:
        if organoid_type not in per_type:
            return {"error": f"no data for organoid_type '{organoid_type}'",
                    "available_types": sorted(per_type)}, 404
        return {
            "organoid_type": organoid_type,
            "journals": dict(sorted(per_type[organoid_type].items(), key=lambda kv: -kv[1])),
            "n_journals": len(per_type[organoid_type]),
            "n_papers": sum(per_type[organoid_type].values()),
        }, 200

    # Sort cross-corpus top 50
    top_journals = sorted(cross_corpus, key=lambda j: -cross_corpus[j])[:50]
    # Per-type top 5 journals
    per_type_top5 = {
        ot: [{"journal": j, "n_papers": cnt}
             for j, cnt in sorted(per_type[ot].items(), key=lambda kv: -kv[1])[:5]]
        for ot in sorted(per_type)
    }
    return {
        "cross_corpus": {j: cross_corpus[j] for j in top_journals},
        "n_journals_total": len(cross_corpus),
        "n_types": len(per_type),
        "per_type_top5": per_type_top5,
    }, 200


def handle_concentration_by_type(query: str | None) -> tuple[dict, int]:
    """Per-organoid-type concentration breakdown for one canonical reagent.

    Requires ?q= specifying the canonical reagent name (case-insensitive substring match).
    For the best-matched canonical, returns concentration statistics (median/min/max/n)
    broken down by organoid type and by canonical unit. Useful for comparing dose ranges
    across organoid systems (e.g. EGF: 100 ng/mL in intestinal vs 50 ng/mL in kidney).
    """
    if not REAGENTS_JSONL.exists():
        return {"error": "reagents.jsonl not found", "hint": "Run: python pipeline/export_public.py"}, 404

    if not query or not query.strip():
        return {"error": "pass ?q= canonical reagent name"}, 400

    q_lower = query.strip().lower()

    try:
        rows = [
            json.loads(line)
            for line in REAGENTS_JSONL.read_text().splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"reagents.jsonl unreadable: {exc}"}, 500

    # Case-insensitive substring match on canonical name
    by_canonical: dict[str, list] = {}
    for r in rows:
        cname = (r.get("canonical") or r.get("name") or "unknown").strip()
        if q_lower in cname.lower():
            by_canonical.setdefault(cname, []).append(r)

    if not by_canonical:
        return {"error": f"no reagents matching '{query}'"}, 404

    # Prefer exact match; else largest group
    exact = next((k for k in by_canonical if k.lower() == q_lower), None)
    canonical_name = exact or max(by_canonical, key=lambda k: len(by_canonical[k]))
    matched_rows = by_canonical[canonical_name]

    # Group by organoid_type, then by canonical_unit within each type
    by_type: dict[str, dict[str, list]] = {}
    for r in matched_rows:
        ot = r.get("organoid_type") or "unknown"
        unit = (r.get("canonical_unit") or r.get("unit") or "unknown").strip()
        v = r.get("value")
        by_type.setdefault(ot, {}).setdefault(unit, [])
        if v is not None:
            try:
                by_type[ot][unit].append(float(v))
            except (TypeError, ValueError):
                pass

    def _stats(vs: list) -> dict:
        n = len(vs)
        if n == 0:
            return {"n": 0, "median": None, "min": None, "max": None}
        vs_s = sorted(vs)
        med = vs_s[n // 2] if n % 2 else (vs_s[n // 2 - 1] + vs_s[n // 2]) / 2
        return {"n": n, "median": round(med, 4), "min": round(min(vs), 4), "max": round(max(vs), 4)}

    per_type_result = {}
    for ot in sorted(by_type):
        unit_map = by_type[ot]
        all_vals = [v for vs in unit_map.values() for v in vs]
        n_records = sum(len(r.get("canonical") or "") >= 0  # True for all — just count rows
                        for r in matched_rows if (r.get("organoid_type") or "unknown") == ot)
        dominant_unit = max(unit_map, key=lambda u: len(unit_map[u])) if unit_map else None
        per_type_result[ot] = {
            "n_records": n_records,
            "n_with_value": len(all_vals),
            "dominant_unit": dominant_unit,
            "stats_per_unit": {u: _stats(vs) for u, vs in sorted(unit_map.items()) if vs},
        }

    return {
        "canonical": canonical_name,
        "canonical_query": query,
        "all_matches": sorted(by_canonical) if len(by_canonical) > 1 else None,
        "n_organoid_types": len(per_type_result),
        "by_type": per_type_result,
    }, 200


def handle_reagent_prevalence(query: str | None, min_types: int = 1) -> tuple[dict, int]:
    """Type-breadth ranking of canonical reagents.

    Returns canonicals sorted by how many organoid types they appear in.
    High breadth = used across many types (universal); low breadth = specialist.

    Without ?q=: ranked list of all canonicals with n_types >= min_types (default 1),
    plus breadth_distribution (count of canonicals per n_types bucket),
    plus n_canonicals_total, n_types_total.
    Each entry: canonical, n_types, n_records, types (sorted).

    With ?q= (case-insensitive substring): full per-type detail for one canonical —
    n_records per type, sorted by n_records desc.
    """
    if not REAGENTS_JSONL.exists():
        return {"error": "reagents.jsonl not found", "hint": "Run: python pipeline/export_public.py"}, 404

    try:
        rows = [
            json.loads(line)
            for line in REAGENTS_JSONL.read_text().splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"reagents.jsonl unreadable: {exc}"}, 500

    from collections import defaultdict, Counter
    # Build: canonical → {type → n_records}
    canon_type_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for r in rows:
        canon = (r.get("canonical") or r.get("name") or "").strip()
        if not canon:
            continue
        ot = (r.get("organoid_type") or "unknown").strip()
        canon_type_counts[canon][ot] += 1

    if query and query.strip():
        # Per-type detail for one canonical (substring match, case-insensitive)
        q_lower = query.strip().lower()
        matches = {c: d for c, d in canon_type_counts.items() if q_lower in c.lower()}
        if not matches:
            return {"error": f"no canonical matching '{query}'"}, 404
        exact = next((c for c in matches if c.lower() == q_lower), None)
        canon = exact or max(matches, key=lambda c: sum(matches[c].values()))
        type_map = canon_type_counts[canon]
        per_type = sorted(
            [{"organoid_type": t, "n_records": n} for t, n in type_map.items()],
            key=lambda x: x["n_records"], reverse=True
        )
        return {
            "canonical": canon,
            "canonical_query": query,
            "n_types": len(type_map),
            "n_records_total": sum(type_map.values()),
            "per_type": per_type,
        }, 200

    # Cross-corpus breadth ranking
    breadth_dist: dict[int, int] = Counter()
    entries = []
    for canon, type_map in canon_type_counts.items():
        n_t = len(type_map)
        breadth_dist[n_t] += 1
        if n_t < min_types:
            continue
        entries.append({
            "canonical": canon,
            "n_types": n_t,
            "n_records": sum(type_map.values()),
            "types": sorted(type_map),
        })

    entries.sort(key=lambda x: (x["n_types"], x["n_records"]), reverse=True)

    # Convenience sub-lists
    cross_field = [e for e in entries if e["n_types"] >= 20]
    specialist = sorted(
        [e for e in entries if e["n_types"] <= 2],
        key=lambda x: x["n_records"], reverse=True
    )[:20]

    return {
        "n_canonicals_total": len(canon_type_counts),
        "n_types_total": len({ot for d in canon_type_counts.values() for ot in d}),
        "min_types_threshold": min_types,
        "n_canonicals_above_threshold": len(entries),
        "breadth_distribution": {str(k): v for k, v in sorted(breadth_dist.items(), reverse=True)},
        "cross_field": cross_field,  # appear in >= 20 types
        "specialist": specialist,  # appear in <= 2 types, top 20 by n_records
        "all_canonicals": entries,  # full ranked list (may be large)
    }, 200


def handle_protocol_outliers(organoid_type: str | None, z_thresh: float = 1.5) -> tuple[dict, int]:
    """Per-type outlier detection on n_signaling_factors.

    For each organoid type, computes mean and std of n_signaling_factors across papers,
    then flags papers as 'complex' (n_sf > mean + z_thresh*std) or 'minimal'
    (n_sf < mean - z_thresh*std, floor 1). Returns per-type statistics with the
    outlier paper lists (pmcid, doi, year, n_signaling_factors, z_score).

    Without ?type=: returns all types sorted by mean n_sf desc.
    With ?type=kidney: returns full outlier detail for one type.

    Optional ?z_thresh= to change sensitivity (default 1.5).
    """
    if not PROTOCOLS_JSONL.exists():
        return {"error": "protocols.jsonl not found", "hint": "Run: python pipeline/export_public.py"}, 404

    try:
        rows = [
            json.loads(line)
            for line in PROTOCOLS_JSONL.read_text().splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"protocols.jsonl unreadable: {exc}"}, 500

    from collections import defaultdict

    # Group by type; collect (n_sf, pmcid, doi, year) tuples
    by_type: dict[str, list] = defaultdict(list)
    for r in rows:
        sf = r.get("n_signaling_factors")
        if sf is None:
            continue
        ot = (r.get("organoid_type") or "unknown").strip()
        by_type[ot].append({
            "pmcid": r.get("pmcid"),
            "doi": r.get("doi"),
            "year": r.get("year"),
            "n_signaling_factors": sf,
        })

    def _type_stats(paper_list: list) -> dict:
        sfs = [p["n_signaling_factors"] for p in paper_list]
        n = len(sfs)
        mean = sum(sfs) / n
        if n >= 2:
            variance = sum((x - mean) ** 2 for x in sfs) / (n - 1)
            std = math.sqrt(variance)
        else:
            std = 0.0
        threshold_hi = mean + z_thresh * std
        threshold_lo = max(1.0, mean - z_thresh * std)
        complex_papers = []
        minimal_papers = []
        for p in paper_list:
            sf = p["n_signaling_factors"]
            z = (sf - mean) / std if std > 0 else 0.0
            if sf > threshold_hi:
                complex_papers.append({**p, "z_score": round(z, 2)})
            elif sf < threshold_lo:
                minimal_papers.append({**p, "z_score": round(z, 2)})
        complex_papers.sort(key=lambda x: -x["n_signaling_factors"])
        minimal_papers.sort(key=lambda x: x["n_signaling_factors"])
        return {
            "n_papers": n,
            "mean_n_sf": round(mean, 2),
            "std_n_sf": round(std, 2),
            "threshold_complex": round(threshold_hi, 2),
            "threshold_minimal": round(threshold_lo, 2),
            "n_complex": len(complex_papers),
            "n_minimal": len(minimal_papers),
            "complex_protocols": complex_papers,
            "minimal_protocols": minimal_papers,
        }

    if organoid_type and organoid_type.strip():
        ot = organoid_type.strip().lower()
        # case-insensitive match
        matched = next((k for k in by_type if k.lower() == ot), None)
        if matched is None:
            return {"error": f"no protocols found for organoid_type '{organoid_type}'"}, 404
        stats = _type_stats(by_type[matched])
        return {"organoid_type": matched, "z_thresh": z_thresh, **stats}, 200

    # Cross-corpus: all types
    per_type = {}
    for ot, papers in by_type.items():
        per_type[ot] = _type_stats(papers)

    # Summary sorted by mean_n_sf desc
    ranking = sorted(per_type, key=lambda t: per_type[t]["mean_n_sf"], reverse=True)

    return {
        "z_thresh": z_thresh,
        "n_types": len(per_type),
        "n_papers_total": sum(v["n_papers"] for v in per_type.values()),
        "ranking_by_mean_sf": ranking,
        "per_type": per_type,
    }, 200


def handle_grounding_distribution(organoid_type: str | None) -> tuple[dict, int]:
    """Per-paper grounding rate histogram, live from protocols.jsonl.

    Without ?type=: cross-corpus histogram (10 buckets: 0-10%, 10-20%, ..., 90-100%),
    per-type mean grounding rate (ranked best→worst), top 20 / bottom 20 papers by
    grounding_rate, and overall corpus mean/median.

    With ?type=kidney: full distribution detail for one organoid type, plus its top/bottom
    10 papers.

    Grounding rate = reagents_grounded / reagents_total per paper (from protocols.jsonl).
    Papers with reagents_total=0 or grounding_rate=None are excluded.
    """
    if not PROTOCOLS_JSONL.exists():
        return {"error": "protocols.jsonl not found", "hint": "Run: python pipeline/export_public.py"}, 404

    try:
        rows = [
            json.loads(line)
            for line in PROTOCOLS_JSONL.read_text().splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"protocols.jsonl unreadable: {exc}"}, 500

    from collections import defaultdict

    def _parse_paper(r: dict) -> dict | None:
        gr = r.get("grounding_rate")
        if gr is None:
            return None
        try:
            gr = float(gr)
        except (TypeError, ValueError):
            return None
        if gr < 0 or gr > 1:
            return None
        return {
            "pmcid": r.get("pmcid"),
            "doi": r.get("doi"),
            "year": r.get("year"),
            "organoid_type": (r.get("organoid_type") or "unknown").strip(),
            "grounding_rate": round(gr, 4),
            "reagents_grounded": r.get("reagents_grounded"),
            "reagents_total": r.get("reagents_total"),
        }

    def _histogram(papers: list) -> dict:
        buckets = {f"{i*10}-{(i+1)*10}%": 0 for i in range(10)}
        for p in papers:
            bucket_idx = min(9, int(p["grounding_rate"] * 10))
            label = f"{bucket_idx*10}-{(bucket_idx+1)*10}%"
            buckets[label] += 1
        return buckets

    def _stats(papers: list) -> dict:
        n = len(papers)
        if n == 0:
            return {"n": 0, "mean": None, "median": None}
        vals = sorted(p["grounding_rate"] for p in papers)
        mean = round(sum(vals) / n, 4)
        median = vals[n // 2] if n % 2 else round((vals[n // 2 - 1] + vals[n // 2]) / 2, 4)
        return {"n": n, "mean": mean, "median": median}

    all_papers = [p for r in rows for p in [_parse_paper(r)] if p is not None]

    if organoid_type and organoid_type.strip():
        ot = organoid_type.strip().lower()
        type_papers = [p for p in all_papers if p["organoid_type"].lower() == ot]
        if not type_papers:
            return {"error": f"no grounding data for organoid_type '{organoid_type}'"}, 404
        ot_display = type_papers[0]["organoid_type"]
        top10 = sorted(type_papers, key=lambda x: -x["grounding_rate"])[:10]
        bot10 = sorted(type_papers, key=lambda x: x["grounding_rate"])[:10]
        return {
            "organoid_type": ot_display,
            **_stats(type_papers),
            "histogram": _histogram(type_papers),
            "top_10_by_grounding_rate": top10,
            "bottom_10_by_grounding_rate": bot10,
        }, 200

    # Cross-corpus
    by_type: dict[str, list] = defaultdict(list)
    for p in all_papers:
        by_type[p["organoid_type"]].append(p)

    per_type_mean = {
        ot: round(sum(p["grounding_rate"] for p in ps) / len(ps), 4)
        for ot, ps in by_type.items()
    }
    ranking = sorted(per_type_mean, key=per_type_mean.get, reverse=True)

    top20 = sorted(all_papers, key=lambda x: -x["grounding_rate"])[:20]
    bot20 = sorted(all_papers, key=lambda x: x["grounding_rate"])[:20]

    return {
        **_stats(all_papers),
        "n_types": len(by_type),
        "histogram": _histogram(all_papers),
        "ranking_by_mean_grounding_rate": ranking,
        "per_type_mean": per_type_mean,
        "top_20_by_grounding_rate": top20,
        "bottom_20_by_grounding_rate": bot20,
    }, 200


def handle_type_maturity(organoid_type: str | None) -> tuple[dict, int]:
    """Field maturity classification per organoid type.

    For each organoid type, computes:
      - first_year: earliest paper year in the corpus
      - last_year: most recent paper year
      - n_years_active: last_year - first_year + 1
      - n_papers_total: total papers
      - papers_by_year: yearly paper count dict
      - trajectory: 'accelerating' / 'stable' / 'slowing' — ratio of
        second-half vs first-half avg annual publication rate
      - maturity_tier: 'established' (>=50 papers OR first_year<=2017),
        'developing' (20-49 OR 2018-2021), 'emerging' (<20 AND >=2022)

    Without ?type=: all types sorted by n_papers_total desc.
    With ?type=kidney: full detail for one type.
    """
    if not PROTOCOLS_JSONL.exists():
        return {"error": "protocols.jsonl not found", "hint": "Run: python pipeline/export_public.py"}, 404

    try:
        rows = [
            json.loads(line)
            for line in PROTOCOLS_JSONL.read_text().splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"protocols.jsonl unreadable: {exc}"}, 500

    from collections import defaultdict, Counter as _Counter

    type_year_counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        ot = (r.get("organoid_type") or "unknown").strip()
        yr_raw = r.get("year")
        if yr_raw and str(yr_raw).isdigit():
            type_year_counts[ot][int(yr_raw)] += 1

    def _type_record(ot: str, year_counts: dict[int, int]) -> dict:
        years = sorted(year_counts)
        first_yr = years[0]
        last_yr = years[-1]
        n_active = last_yr - first_yr + 1
        n_total = sum(year_counts.values())
        papers_by_year = {str(y): year_counts[y] for y in years}

        # Trajectory: compare avg annual rate in the first half vs second half
        if len(years) >= 4:
            mid = len(years) // 2
            first_half = years[:mid]
            second_half = years[mid:]
            avg_first = sum(year_counts[y] for y in first_half) / len(first_half)
            avg_second = sum(year_counts[y] for y in second_half) / len(second_half)
            ratio = avg_second / avg_first if avg_first > 0 else 1.0
            if ratio > 1.3:
                trajectory = "accelerating"
            elif ratio < 0.75:
                trajectory = "slowing"
            else:
                trajectory = "stable"
        else:
            trajectory = "insufficient_data"

        # Maturity tier
        if n_total >= 50 or first_yr <= 2017:
            tier = "established"
        elif n_total >= 20 or first_yr <= 2021:
            tier = "developing"
        else:
            tier = "emerging"

        return {
            "organoid_type": ot,
            "first_year": first_yr,
            "last_year": last_yr,
            "n_years_active": n_active,
            "n_papers_total": n_total,
            "papers_by_year": papers_by_year,
            "trajectory": trajectory,
            "maturity_tier": tier,
        }

    if organoid_type and organoid_type.strip():
        ot_lower = organoid_type.strip().lower()
        matched = next((k for k in type_year_counts if k.lower() == ot_lower), None)
        if matched is None:
            return {"error": f"no protocols found for organoid_type '{organoid_type}'"}, 404
        return _type_record(matched, type_year_counts[matched]), 200

    records = [_type_record(ot, yc) for ot, yc in type_year_counts.items()]
    records.sort(key=lambda x: x["n_papers_total"], reverse=True)

    # Summary groupings
    by_tier: dict[str, list] = {"established": [], "developing": [], "emerging": []}
    by_trajectory: dict[str, list] = {"accelerating": [], "stable": [], "slowing": [],
                                       "insufficient_data": []}
    for rec in records:
        by_tier.setdefault(rec["maturity_tier"], []).append(rec["organoid_type"])
        by_trajectory.setdefault(rec["trajectory"], []).append(rec["organoid_type"])

    return {
        "n_types": len(records),
        "n_papers_total": sum(r["n_papers_total"] for r in records),
        "by_tier": by_tier,
        "by_trajectory": by_trajectory,
        "all_types": records,
    }, 200


def handle_concentration_deviation(min_n: int = 3) -> tuple[dict, int]:
    """Dose inconsistency ranking: canonical reagents sorted by coefficient of variation.

    For each canonical reagent + dominant unit, computes CV = std/mean across all
    records with a numeric value. High CV means inconsistent dosing across labs — a
    signal for dose uncertainty or protocol variation. Only reagents with n_with_value
    >= min_n (default 3) are included, since CV is meaningless for tiny samples.

    Optional: ?min_n=5 to raise the sample-size threshold.

    Returns:
      - most_variable: top 30 by CV desc (dose most debated)
      - most_consistent: top 30 by CV asc, CV < 0.5 only (dose well-established)
      - n_canonicals_total: total canonicals with enough data
      - n_excluded_too_few: how many canonicals had < min_n values
    """
    if not REAGENTS_JSONL.exists():
        return {"error": "reagents.jsonl not found", "hint": "Run: python pipeline/export_public.py"}, 404

    try:
        rows = [
            json.loads(line)
            for line in REAGENTS_JSONL.read_text().splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"reagents.jsonl unreadable: {exc}"}, 500

    # Accumulate values per (canonical, dominant_unit) — use canonical_unit as the unit key
    # Two passes: first collect all values, then pick dominant unit per canonical
    from collections import defaultdict
    canon_unit_vals: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    canon_n_records: dict[str, int] = defaultdict(int)

    for r in rows:
        canon = (r.get("canonical") or r.get("name") or "").strip()
        if not canon:
            continue
        canon_n_records[canon] += 1
        v = r.get("value")
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        unit = (r.get("canonical_unit") or r.get("unit") or "unknown").strip()
        canon_unit_vals[canon][unit].append(fv)

    def _cv_stats(vals: list[float], unit: str, n_records: int) -> dict:
        n = len(vals)
        if n < 2:
            return None
        mean = sum(vals) / n
        if mean == 0:
            return None
        variance = sum((x - mean) ** 2 for x in vals) / (n - 1)
        std = math.sqrt(variance)
        cv = std / mean
        vmin, vmax = min(vals), max(vals)
        med_sorted = sorted(vals)
        median = med_sorted[n // 2] if n % 2 else (med_sorted[n // 2 - 1] + med_sorted[n // 2]) / 2
        return {
            "canonical": None,  # filled by caller
            "dominant_unit": unit,
            "n_records": n_records,
            "n_with_value": n,
            "mean": round(mean, 4),
            "median": round(median, 4),
            "std": round(std, 4),
            "cv": round(cv, 4),
            "min": round(vmin, 4),
            "max": round(vmax, 4),
        }

    results = []
    n_excluded = 0

    for canon, unit_map in canon_unit_vals.items():
        # dominant unit = one with most values
        dom_unit = max(unit_map, key=lambda u: len(unit_map[u]))
        dom_vals = unit_map[dom_unit]
        if len(dom_vals) < min_n:
            n_excluded += 1
            continue
        stat = _cv_stats(dom_vals, dom_unit, canon_n_records[canon])
        if stat is None:
            n_excluded += 1
            continue
        stat["canonical"] = canon
        results.append(stat)

    if not results:
        return {
            "most_variable": [],
            "most_consistent": [],
            "n_canonicals_total": 0,
            "n_excluded_too_few": n_excluded,
            "min_n_threshold": min_n,
        }, 200

    results.sort(key=lambda x: x["cv"], reverse=True)
    most_variable = results[:30]
    most_consistent = sorted(
        [r for r in results if r["cv"] < 0.5],
        key=lambda x: x["cv"]
    )[:30]

    return {
        "most_variable": most_variable,
        "most_consistent": most_consistent,
        "n_canonicals_total": len(results),
        "n_excluded_too_few": n_excluded,
        "min_n_threshold": min_n,
    }, 200


KGX_DIR = REPO / "exports" / "kgx"


def handle_kgx_summary() -> tuple[dict, int]:
    """KGX graph state from committed exports/kgx artifacts.

    Reads kgx_manifest.json for node/edge counts and resolution metrics, then
    reads review_items.jsonl for a breakdown of grounding review queue status.
    Surfaces top not_found and needs_review entities for S1/S2 sprint triage.
    Returns 404 when the KGX export hasn't been generated yet.
    """
    from collections import Counter as _Counter

    manifest_path = KGX_DIR / "kgx_manifest.json"
    review_path = KGX_DIR / "review_items.jsonl"

    if not manifest_path.exists():
        return {
            "error": "KGX manifest not found",
            "hint": "Run: python pipeline/export_kgx.py",
        }, 404

    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"kgx_manifest.json unreadable: {exc}"}, 500

    result: dict = {
        "generated_at": manifest.get("generated_at"),
        "n_papers": manifest.get("n_papers", 0),
        "n_nodes": manifest.get("n_nodes", 0),
        "n_edges": manifest.get("n_edges", 0),
        "n_nodes_by_category": manifest.get("n_nodes_by_category", {}),
        "n_edges_by_predicate": manifest.get("n_edges_by_predicate", {}),
        "entities_total": manifest.get("entities_total", 0),
        "entities_resolved": manifest.get("entities_resolved", 0),
        "resolved_rate": manifest.get("resolved_rate"),
        "validation": manifest.get("validation", {}),
        "predicate": manifest.get("predicate"),
        "knowledge_level": manifest.get("knowledge_level"),
    }

    if not review_path.exists():
        result["review_queue"] = None
        result["hint_review"] = "Run: python pipeline/export_kgx.py to generate review_items.jsonl"
        return result, 200

    try:
        review_rows = [
            json.loads(line)
            for line in review_path.read_text().splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, OSError) as exc:
        result["review_queue_error"] = str(exc)
        return result, 200

    status_counts = dict(_Counter(r.get("grounding_status") for r in review_rows))
    flag_counts = dict(_Counter(f for r in review_rows for f in r.get("flags", [])))
    kind_counts = dict(_Counter(r.get("kind") for r in review_rows))

    # Top not_found: most common query strings that SRI couldn't resolve
    not_found = [r for r in review_rows if r.get("grounding_status") == "not_found"]
    top_not_found = [
        {"query": q, "count": c, "kind": kind_counts.get("reagent")}
        for q, c in _Counter(r["query"] for r in not_found).most_common(20)
    ]
    # Re-annotate with the actual kind per query
    nf_kind: dict[str, list] = {}
    for r in not_found:
        nf_kind.setdefault(r.get("query", ""), []).append(r.get("kind", "unknown"))
    top_not_found = [
        {"query": q, "count": c, "kinds": list(set(nf_kind.get(q, [])))}
        for q, c in _Counter(r["query"] for r in not_found).most_common(20)
    ]

    # Top needs_review: most common label mismatches (SRI returned a CURIE but label differs)
    nr_rows = [r for r in review_rows if r.get("grounding_status") == "needs_review"]
    top_needs_review = [
        {
            "query": r.get("query"),
            "curie": r.get("curie"),
            "label": r.get("label"),
            "flags": r.get("flags", []),
            "kind": r.get("kind"),
            "field": r.get("field"),
        }
        for r in nr_rows[:20]
    ]

    result["review_queue"] = {
        "total": len(review_rows),
        "by_status": status_counts,
        "by_kind": kind_counts,
        "by_flag": flag_counts,
        "top_not_found": top_not_found,
        "top_needs_review": top_needs_review,
    }
    return result, 200


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


def handle_reagent_cooccurrence(
    query: str | None,
    organoid_type: str | None,
    min_papers: int = 3,
) -> tuple[dict, int]:
    """Pairwise signaling-factor co-occurrence analysis.

    Without ?q=: returns top 100 pairs by n_papers with min_papers threshold.
    With ?q=EGF: returns all canonicals that co-occur with EGF, sorted by n_papers.
    ?type= filters to one organoid type.
    """
    from itertools import combinations

    if not REAGENTS_JSONL.exists():
        return {
            "error": "reagents.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    reagents = [
        json.loads(line)
        for line in REAGENTS_JSONL.read_text().splitlines()
        if line.strip()
    ]
    rows = [r for r in reagents if r.get("kind") == "signaling" and r.get("canonical")]
    if organoid_type:
        rows = [r for r in rows if r.get("organoid_type") == organoid_type]

    # Canonical set per paper (deduplicated)
    paper_canonicals: dict[str, set] = {}
    for r in rows:
        pmcid = r["pmcid"]
        if pmcid not in paper_canonicals:
            paper_canonicals[pmcid] = set()
        paper_canonicals[pmcid].add(r["canonical"])

    n_papers_total = len(paper_canonicals)
    if n_papers_total == 0:
        return {
            "n_papers_total": 0,
            "n_canonicals": 0,
            "organoid_type": organoid_type,
            "top_pairs": [],
        }, 200

    # Papers per canonical
    canonical_papers: dict[str, set] = {}
    for pmcid, canons in paper_canonicals.items():
        for c in canons:
            if c not in canonical_papers:
                canonical_papers[c] = set()
            canonical_papers[c].add(pmcid)

    if query:
        # Exact match first, then case-insensitive substring
        q_lower = query.lower()
        if query in canonical_papers:
            target = query
        else:
            matched = [c for c in canonical_papers if q_lower in c.lower()]
            if not matched:
                return {
                    "error": f"No signaling canonical matching {query!r}",
                    "hint": "use /analytics/reagent-prevalence to browse available canonicals",
                }, 404
            target = matched[0]

        target_papers = canonical_papers[target]
        pairs = []
        for other, other_papers in canonical_papers.items():
            if other == target:
                continue
            inter = len(target_papers & other_papers)
            if inter == 0:
                continue
            union = len(target_papers | other_papers)
            pairs.append({
                "canonical": other,
                "n_papers": inter,
                "n_papers_target": len(target_papers),
                "n_papers_other": len(other_papers),
                "jaccard": round(inter / union, 4),
            })
        pairs.sort(key=lambda x: (-x["n_papers"], -x["jaccard"]))
        return {
            "query_canonical": target,
            "n_papers_total": n_papers_total,
            "organoid_type": organoid_type,
            "n_co_occurring": len(pairs),
            "co_occurring": pairs[:50],
        }, 200

    # Global top pairs
    canons = list(canonical_papers.keys())
    pairs = []
    for a, b in combinations(canons, 2):
        inter = len(canonical_papers[a] & canonical_papers[b])
        if inter < min_papers:
            continue
        union = len(canonical_papers[a] | canonical_papers[b])
        pairs.append({
            "canonical_a": a,
            "canonical_b": b,
            "n_papers": inter,
            "n_papers_a": len(canonical_papers[a]),
            "n_papers_b": len(canonical_papers[b]),
            "jaccard": round(inter / union, 4),
        })
    pairs.sort(key=lambda x: (-x["n_papers"], -x["jaccard"]))

    return {
        "n_papers_total": n_papers_total,
        "n_canonicals": len(canons),
        "organoid_type": organoid_type,
        "min_papers": min_papers,
        "n_pairs": len(pairs),
        "top_pairs": pairs[:100],
    }, 200


def handle_supplement_breakdown(
    query: str | None,
    organoid_type: str | None,
    min_types: int = 10,
) -> tuple[dict, int]:
    """Per-type and cross-type breakdown of supplements (kind=supplement).

    Without params: global top 50 by n_papers, cross-type list (>= min_types),
    and per-type top 10.
    ?q=GlutaMAX: per-type breakdown for one canonical (substring match).
    ?type=kidney: full breakdown for one organoid type.
    ?min_types=: threshold for cross_type_supplements (default 10).
    """
    if not REAGENTS_JSONL.exists():
        return {
            "error": "reagents.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    reagents = [
        json.loads(line)
        for line in REAGENTS_JSONL.read_text().splitlines()
        if line.strip()
    ]
    rows = [r for r in reagents if r.get("kind") == "supplement" and r.get("canonical")]

    # Group: organoid_type → canonical → set of pmcids
    from collections import defaultdict
    type_canon_papers: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for r in rows:
        type_canon_papers[r["organoid_type"]][r["canonical"]].add(r["pmcid"])

    # All canonicals → deduplicated paper set across types
    canonical_papers: dict[str, set] = defaultdict(set)
    for typ, canon_dict in type_canon_papers.items():
        for canon, papers in canon_dict.items():
            canonical_papers[canon].update(papers)

    # Papers with at least one supplement record
    all_suppl_papers: set = set()
    for papers in canonical_papers.values():
        all_suppl_papers.update(papers)

    # n_types per canonical
    canonical_ntypes: dict[str, int] = {
        c: sum(1 for typ in type_canon_papers if c in type_canon_papers[typ])
        for c in canonical_papers
    }

    if query:
        q_lower = query.lower()
        if query in canonical_papers:
            target = query
        else:
            matched = [c for c in canonical_papers if q_lower in c.lower()]
            if not matched:
                return {
                    "error": f"No supplement canonical matching {query!r}",
                    "hint": "use /analytics/supplement-breakdown without ?q= to browse",
                }, 404
            target = matched[0]

        per_type = sorted(
            [
                {
                    "organoid_type": typ,
                    "n_papers": len(type_canon_papers[typ].get(target, set())),
                }
                for typ in type_canon_papers
                if target in type_canon_papers[typ]
            ],
            key=lambda x: -x["n_papers"],
        )
        return {
            "query_canonical": target,
            "n_papers_total": len(canonical_papers[target]),
            "n_types": canonical_ntypes[target],
            "per_type": per_type,
        }, 200

    if organoid_type:
        if organoid_type not in type_canon_papers:
            return {
                "error": f"No supplement data for organoid type {organoid_type!r}",
                "hint": "use /analytics/supplement-breakdown without ?type= to see all types",
            }, 404
        canon_dict = type_canon_papers[organoid_type]
        top_supps = sorted(
            [
                {
                    "canonical": c,
                    "n_papers": len(papers),
                    "n_types_total": canonical_ntypes.get(c, 1),
                }
                for c, papers in canon_dict.items()
            ],
            key=lambda x: -x["n_papers"],
        )
        return {
            "organoid_type": organoid_type,
            "n_papers": len(set(p for papers in canon_dict.values() for p in papers)),
            "n_supplement_canonicals": len(canon_dict),
            "top_supplements": top_supps[:50],
        }, 200

    # Global view
    cross_type = sorted(
        [
            {
                "canonical": c,
                "n_types": canonical_ntypes[c],
                "n_papers": len(canonical_papers[c]),
            }
            for c in canonical_papers
            if canonical_ntypes[c] >= min_types
        ],
        key=lambda x: (-x["n_types"], -x["n_papers"]),
    )

    top_supps = sorted(
        [
            {
                "canonical": c,
                "n_papers": len(canonical_papers[c]),
                "n_types": canonical_ntypes[c],
            }
            for c in canonical_papers
        ],
        key=lambda x: (-x["n_papers"], -x["n_types"]),
    )

    per_type = {
        typ: sorted(
            [{"canonical": c, "n_papers": len(papers)} for c, papers in canon_dict.items()],
            key=lambda x: -x["n_papers"],
        )[:10]
        for typ, canon_dict in sorted(
            type_canon_papers.items(),
            key=lambda kv: -sum(len(v) for v in kv[1].values()),
        )
    }

    return {
        "n_papers_with_supplements": len(all_suppl_papers),
        "n_supplement_canonicals": len(canonical_papers),
        "min_types_threshold": min_types,
        "cross_type_supplements": cross_type,
        "top_supplements": top_supps[:50],
        "per_type": per_type,
    }, 200


# Normalized functional role categories for signaling reagents
_ROLE_MAP: dict[str, str] = {
    "signaling factor": "signaling_factor",
    "signaling": "signaling_factor",
    "signaling pathway": "signaling_factor",
    "growth factor": "growth_factor",
    "differentiation": "differentiation",
    "induction": "differentiation",
    "morphogen": "differentiation",
    "inhibitor": "inhibitor",
    "inhibition": "inhibitor",
    "supplement": "supplement",
    "supplementation": "supplement",
    "treatment": "treatment",
    "stimulation": "treatment",
    "activation": "agonist",
    "agonist": "agonist",
    "pathway agonist": "agonist",
    "conditioned medium": "conditioned_medium",
    "proliferation": "proliferation",
}


def _normalize_role(raw: str | None) -> str:
    if raw is None or str(raw).lower().strip() in ("null", "not stated", ""):
        return "not_stated"
    return _ROLE_MAP.get(str(raw).strip().lower(), "other")


def handle_role_breakdown(
    query: str | None,
    organoid_type: str | None,
) -> tuple[dict, int]:
    """Functional role distribution for signaling (kind=signaling) reagents.

    Without params: global role distribution (normalized) + per-type breakdown.
    ?q=differentiation: top canonicals assigned that normalized role, sorted by n_papers.
    ?type=kidney: role distribution for one organoid type.
    Roles are normalized: signaling_factor / growth_factor / differentiation /
    inhibitor / supplement / treatment / agonist / conditioned_medium /
    proliferation / other / not_stated.
    """
    if not REAGENTS_JSONL.exists():
        return {
            "error": "reagents.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    reagents = [
        json.loads(line)
        for line in REAGENTS_JSONL.read_text().splitlines()
        if line.strip()
    ]
    rows = [r for r in reagents if r.get("kind") == "signaling"]
    if organoid_type:
        rows = [r for r in rows if r.get("organoid_type") == organoid_type]

    if not rows:
        return {
            "error": f"No signaling records for organoid type {organoid_type!r}" if organoid_type else "No signaling records found",
            "hint": "use /analytics/role-breakdown without ?type= to see all types",
        }, 404

    n_total = len(rows)

    if query:
        # Return top canonicals for this normalized role
        known_roles = set(_ROLE_MAP.values()) | {"other", "not_stated"}
        if query not in known_roles:
            return {
                "error": f"Unknown role {query!r}",
                "valid_roles": sorted(known_roles),
            }, 404
        from collections import defaultdict
        canon_papers: dict[str, set] = defaultdict(set)
        for r in rows:
            if _normalize_role(r.get("role")) == query and r.get("canonical"):
                canon_papers[r["canonical"]].add(r["pmcid"])
        top = sorted(
            [{"canonical": c, "n_papers": len(p), "n_records": len([x for x in rows if x.get("canonical") == c and _normalize_role(x.get("role")) == query])}
             for c, p in canon_papers.items()],
            key=lambda x: (-x["n_papers"], -x["n_records"]),
        )
        return {
            "role": query,
            "organoid_type": organoid_type,
            "n_canonicals": len(top),
            "top_canonicals": top[:50],
        }, 200

    # Global role distribution
    from collections import Counter, defaultdict
    role_counter: Counter = Counter()
    for r in rows:
        role_counter[_normalize_role(r.get("role"))] += 1

    role_dist = sorted(
        [
            {
                "role": role,
                "n_records": count,
                "pct": round(count / n_total * 100, 1),
            }
            for role, count in role_counter.items()
        ],
        key=lambda x: -x["n_records"],
    )
    n_with_role = n_total - role_counter.get("not_stated", 0)

    # Per-type breakdown
    type_role: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        type_role[r.get("organoid_type", "unknown")][_normalize_role(r.get("role"))] += 1

    per_type = {
        typ: sorted(
            [{"role": role, "n_records": count} for role, count in cntr.items()],
            key=lambda x: -x["n_records"],
        )
        for typ, cntr in sorted(type_role.items(), key=lambda kv: -sum(kv[1].values()))
    }

    return {
        "n_records_total": n_total,
        "n_with_role": n_with_role,
        "organoid_type": organoid_type,
        "role_distribution": role_dist,
        "per_type": per_type,
    }, 200


def handle_type_reagent_heatmap(
    kind: str | None,
    top_n: int = 20,
) -> tuple[dict, int]:
    """Type × canonical reagent usage matrix for heatmap visualization.

    Returns a matrix-ready structure: top_n canonical reagents (columns)
    ordered by total n_papers, and per-organoid-type row vectors of n_papers.

    ?kind=signaling|supplement|all — which kind to include (default: signaling).
    ?top_n= — number of canonical columns (default 20, max 50).
    """
    if not REAGENTS_JSONL.exists():
        return {
            "error": "reagents.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    kind = (kind or "signaling").lower()
    if kind not in ("signaling", "supplement", "all"):
        return {
            "error": f"Invalid kind {kind!r}; must be signaling, supplement, or all",
        }, 400
    top_n = min(max(1, top_n), 50)

    reagents = [
        json.loads(line)
        for line in REAGENTS_JSONL.read_text().splitlines()
        if line.strip()
    ]
    if kind != "all":
        rows = [r for r in reagents if r.get("kind") == kind and r.get("canonical")]
    else:
        rows = [r for r in reagents if r.get("canonical")]

    # Build: (type, canonical) → set of pmcids
    from collections import defaultdict
    tc_papers: dict[tuple, set] = defaultdict(set)
    for r in rows:
        tc_papers[(r.get("organoid_type", "unknown"), r["canonical"])].add(r["pmcid"])

    # Global n_papers per canonical (across all types, deduplicated)
    canon_papers_global: dict[str, set] = defaultdict(set)
    for (typ, canon), papers in tc_papers.items():
        canon_papers_global[canon].update(papers)

    # Top N canonicals by total n_papers
    top_canonicals = sorted(
        canon_papers_global.keys(),
        key=lambda c: (-len(canon_papers_global[c]), c),
    )[:top_n]

    # All organoid types, sorted by total n_papers descending
    type_papers_total: dict[str, set] = defaultdict(set)
    for (typ, canon), papers in tc_papers.items():
        type_papers_total[typ].update(papers)
    all_types = sorted(type_papers_total.keys(), key=lambda t: -len(type_papers_total[t]))

    # Build matrix rows
    matrix = [
        {
            "organoid_type": typ,
            "n_papers_total": len(type_papers_total[typ]),
            "values": [len(tc_papers.get((typ, c), set())) for c in top_canonicals],
        }
        for typ in all_types
    ]

    return {
        "kind": kind,
        "top_n": top_n,
        "n_types": len(all_types),
        "canonicals": top_canonicals,
        "matrix": matrix,
    }, 200


def handle_canonical_name_variants(
    query: str | None,
    min_variants: int = 2,
) -> tuple[dict, int]:
    """Canonical → raw name variant mapping (normalization complexity report).

    Shows how many distinct raw names the pipeline normalizes to each canonical.
    Without ?q=: top 30 most-ambiguous canonicals by n_variants (>= min_variants).
    With ?q=FGF2: full variant list for one canonical (exact then substring match).
    ?min_variants=: floor for the global list (default 2).
    """
    if not REAGENTS_JSONL.exists():
        return {
            "error": "reagents.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    reagents = [
        json.loads(line)
        for line in REAGENTS_JSONL.read_text().splitlines()
        if line.strip()
    ]

    from collections import defaultdict
    # canonical → set of raw names + paper count
    canon_names: dict[str, set] = defaultdict(set)
    canon_records: dict[str, int] = defaultdict(int)
    for r in reagents:
        c = r.get("canonical")
        n = r.get("name")
        if c and n:
            canon_names[c].add(n)
            canon_records[c] += 1

    if query:
        q_lower = query.lower()
        if query in canon_names:
            target = query
        else:
            matched = [c for c in canon_names if q_lower in c.lower()]
            if not matched:
                return {
                    "error": f"No canonical matching {query!r}",
                    "hint": "use /analytics/canonical-name-variants without ?q= to browse",
                }, 404
            target = matched[0]
        return {
            "canonical": target,
            "n_variants": len(canon_names[target]),
            "n_records": canon_records[target],
            "names": sorted(canon_names[target]),
        }, 200

    # Global: filter by min_variants, sort by n_variants desc
    entries = [
        {
            "canonical": c,
            "n_variants": len(names),
            "n_records": canon_records[c],
            "names": sorted(names),
        }
        for c, names in canon_names.items()
        if len(names) >= min_variants
    ]
    entries.sort(key=lambda x: (-x["n_variants"], -x["n_records"]))

    return {
        "n_canonicals_total": len(canon_names),
        "n_with_multiple_names": sum(1 for n in canon_names.values() if len(n) >= 2),
        "min_variants": min_variants,
        "n_above_threshold": len(entries),
        "most_ambiguous": entries[:30],
    }, 200


def handle_concentration_unit_distribution(
    query: str | None,
    min_n: int = 3,
) -> tuple[dict, int]:
    """Concentration unit inconsistency report: which canonicals use multiple unit systems.

    Without ?q=: top 30 canonicals by n_units descending (most unit-inconsistent),
    filtered to those with >= min_n total concentration records.
    With ?q=EGF: full unit distribution for one canonical including min/median/max per unit.
    ?min_n=: minimum concentration records to include a canonical (default 3).
    """
    if not REAGENTS_JSONL.exists():
        return {
            "error": "reagents.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    reagents = [
        json.loads(line)
        for line in REAGENTS_JSONL.read_text().splitlines()
        if line.strip()
    ]

    from collections import defaultdict
    # canonical → unit → list of numeric values
    canon_unit_values: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in reagents:
        c = r.get("canonical")
        u = r.get("canonical_unit")
        v = r.get("value")
        if c and u and v is not None:
            try:
                canon_unit_values[c][u].append(float(v))
            except (TypeError, ValueError):
                pass

    def _median(vals: list) -> float:
        s = sorted(vals)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0

    if query:
        q_lower = query.lower()
        if query in canon_unit_values:
            target = query
        else:
            matched = [c for c in canon_unit_values if q_lower in c.lower()]
            if not matched:
                return {
                    "error": f"No canonical with concentration data matching {query!r}",
                    "hint": "use /analytics/concentration-stats to see all canonicals with values",
                }, 404
            target = matched[0]

        unit_dict = canon_unit_values[target]
        n_total = sum(len(v) for v in unit_dict.values())
        units = sorted(
            [
                {
                    "unit": u,
                    "n_records": len(vals),
                    "pct": round(len(vals) / n_total * 100, 1),
                    "min": round(min(vals), 4),
                    "median": round(_median(vals), 4),
                    "max": round(max(vals), 4),
                }
                for u, vals in unit_dict.items()
            ],
            key=lambda x: -x["n_records"],
        )
        dominant = units[0]["unit"] if units else None
        return {
            "canonical": target,
            "n_units": len(unit_dict),
            "n_records_total": n_total,
            "is_unit_consistent": len(unit_dict) == 1,
            "dominant_unit": dominant,
            "units": units,
        }, 200

    # Global: multi-unit canonicals
    multi_unit = []
    for c, unit_dict in canon_unit_values.items():
        n_total = sum(len(v) for v in unit_dict.values())
        if n_total < min_n:
            continue
        dominant = max(unit_dict, key=lambda u: len(unit_dict[u]))
        multi_unit.append({
            "canonical": c,
            "n_units": len(unit_dict),
            "n_records_total": n_total,
            "dominant_unit": dominant,
            "dominant_pct": round(len(unit_dict[dominant]) / n_total * 100, 1),
        })
    multi_unit.sort(key=lambda x: (-x["n_units"], -x["n_records_total"]))

    n_canonicals_total = sum(1 for u in canon_unit_values.values() if sum(len(v) for v in u.values()) >= min_n)

    return {
        "n_canonicals_with_values": n_canonicals_total,
        "n_multi_unit": sum(1 for e in multi_unit if e["n_units"] > 1),
        "min_n": min_n,
        "multi_unit_canonicals": [e for e in multi_unit if e["n_units"] > 1][:30],
        "single_unit_count": sum(1 for e in multi_unit if e["n_units"] == 1),
    }, 200


def handle_protocol_size_distribution(
    organoid_type: str | None,
) -> tuple[dict, int]:
    """Full distribution of protocol sizes (n_signaling_factors + n_supplements) per paper.

    Complements /analytics/protocol-complexity (averages) and /analytics/protocol-outliers
    (extremes) by showing the full shape of the distribution.

    Without ?type=: global histogram + per-type summary (mean, median, min, max, std).
    With ?type=kidney: full histograms for one type only.
    """
    if not PROTOCOLS_JSONL.exists():
        return {
            "error": "protocols.jsonl not found",
            "hint": "Run: python pipeline/export_public.py",
        }, 404

    protocols = [
        json.loads(line)
        for line in PROTOCOLS_JSONL.read_text().splitlines()
        if line.strip()
    ]

    def _stats(vals: list) -> dict:
        if not vals:
            return {"mean": None, "median": None, "std": None, "min": None, "max": None, "n_papers": 0}
        n = len(vals)
        mean = sum(vals) / n
        s = sorted(vals)
        median = float(s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)
        variance = sum((x - mean) ** 2 for x in vals) / (n - 1) if n > 1 else 0.0
        return {
            "mean": round(mean, 2),
            "median": median,
            "std": round(variance ** 0.5, 2),
            "min": min(vals),
            "max": max(vals),
            "n_papers": n,
        }

    def _histogram(vals: list) -> list:
        from collections import Counter
        counts = Counter(vals)
        return [{"value": v, "n_papers": counts[v]} for v in sorted(counts)]

    if organoid_type:
        rows = [r for r in protocols if r.get("organoid_type") == organoid_type]
        if not rows:
            return {
                "error": f"No protocols for organoid type {organoid_type!r}",
                "hint": "use /analytics/protocol-size-distribution without ?type= to see all types",
            }, 404
        sf_vals = [r["n_signaling_factors"] for r in rows if r.get("n_signaling_factors") is not None]
        supp_vals = [r["n_supplements"] for r in rows if r.get("n_supplements") is not None]
        return {
            "organoid_type": organoid_type,
            "signaling_factors": {**_stats(sf_vals), "histogram": _histogram(sf_vals)},
            "supplements": {**_stats(supp_vals), "histogram": _histogram(supp_vals)},
        }, 200

    # Global
    sf_vals = [r["n_signaling_factors"] for r in protocols if r.get("n_signaling_factors") is not None]
    supp_vals = [r["n_supplements"] for r in protocols if r.get("n_supplements") is not None]

    from collections import defaultdict
    type_sf: dict[str, list] = defaultdict(list)
    type_supp: dict[str, list] = defaultdict(list)
    for r in protocols:
        typ = r.get("organoid_type", "unknown")
        if r.get("n_signaling_factors") is not None:
            type_sf[typ].append(r["n_signaling_factors"])
        if r.get("n_supplements") is not None:
            type_supp[typ].append(r["n_supplements"])

    per_type = {
        typ: {
            "mean_sf": round(sum(sf) / len(sf), 2) if sf else None,
            "median_sf": float(sorted(sf)[len(sf) // 2]) if sf else None,
            "mean_supp": round(sum(supp) / len(supp), 2) if supp else None,
            "n_papers": max(len(sf), len(supp)),
        }
        for typ in sorted(set(list(type_sf.keys()) + list(type_supp.keys())))
        for sf, supp in [(type_sf.get(typ, []), type_supp.get(typ, []))]
    }

    return {
        "n_papers_total": len(protocols),
        "signaling_factors": {**_stats(sf_vals), "histogram": _histogram(sf_vals)},
        "supplements": {**_stats(supp_vals), "histogram": _histogram(supp_vals)},
        "per_type": per_type,
    }, 200


def handle_source_cell_reagent_profile(source=None, min_papers=3):
    """Route 52: characteristic canonical reagents by source_cell_type.

    Joins protocols.jsonl (source_cell_type) with reagents.jsonl (canonical)
    to produce per-source_cell_type reagent profiles. iPSC protocols use very
    different signaling than adult_stem_cell protocols (CHIR99021/FGF2/BMP4
    vs EGF/R-spondin1/Noggin).

    Without ?source=: global summary for all source types — top 20 canonicals,
    n_papers per source, pairwise Jaccard similarity between source types.
    With ?source=iPSC: detailed profile for one source type with top 30
    canonicals, uniqueness scores vs other sources.
    """
    protocols = [
        json.loads(line)
        for line in PROTOCOLS_JSONL.read_text().splitlines()
        if line.strip()
    ]
    reagents = [
        json.loads(line)
        for line in REAGENTS_JSONL.read_text().splitlines()
        if line.strip()
    ]

    # Build doi→source_cell_type index
    doi_source: dict[str, str] = {}
    for p in protocols:
        doi = p.get("doi", "")
        sct = p.get("source_cell_type", "")
        if doi and sct:
            doi_source[doi] = sct

    from collections import defaultdict

    # For each source type: set of dois + canonical counter
    source_dois: dict[str, set] = {}
    source_canon: dict[str, defaultdict] = {}
    for r in reagents:
        doi = r.get("doi", "")
        c = r.get("canonical", "")
        sct = doi_source.get(doi, "")
        if not sct or not c:
            continue
        source_dois.setdefault(sct, set()).add(doi)
        source_canon.setdefault(sct, defaultdict(set))
        source_canon[sct][c].add(doi)

    valid_sources = sorted(source_dois.keys())

    if source:
        if source not in source_dois:
            return {
                "error": f"No protocols found for source_cell_type '{source}'",
                "known_sources": valid_sources,
            }, 404

        n_papers = len(source_dois[source])
        canon_counts = {
            c: len(dois) for c, dois in source_canon[source].items()
        }

        # Compute uniqueness: fraction of this source's canon dois NOT in other sources
        other_source_dois = set()
        for sct, dois in source_dois.items():
            if sct != source:
                other_source_dois.update(dois)

        # Which canonicals appear in other source types?
        other_source_canons: set[str] = set()
        for sct, cmap in source_canon.items():
            if sct != source:
                other_source_canons.update(
                    c for c, dois in cmap.items() if len(dois) >= min_papers
                )

        top_canonicals = []
        for c, n_p in sorted(canon_counts.items(), key=lambda x: -x[1]):
            if n_p < min_papers:
                continue
            top_canonicals.append({
                "canonical": c,
                "n_papers": n_p,
                "exclusive_to_source": c not in other_source_canons,
            })

        top_canonicals.sort(key=lambda x: -x["n_papers"])

        return {
            "source_cell_type": source,
            "n_papers": n_papers,
            "min_papers": min_papers,
            "top_canonicals": top_canonicals[:30],
        }, 200

    # Global summary
    per_source = []
    for sct in valid_sources:
        n_papers = len(source_dois[sct])
        top_20 = sorted(
            [(c, len(dois)) for c, dois in source_canon[sct].items()],
            key=lambda x: -x[1]
        )[:20]
        per_source.append({
            "source_cell_type": sct,
            "n_papers": n_papers,
            "top_canonicals": [{"canonical": c, "n_papers": n} for c, n in top_20],
        })

    # Pairwise Jaccard on canonical sets (canonicals with >= min_papers)
    source_sets = {
        sct: {c for c, dois in source_canon[sct].items() if len(dois) >= min_papers}
        for sct in valid_sources
    }
    pairwise = []
    for i, a in enumerate(valid_sources):
        for b in valid_sources[i + 1:]:
            sa, sb = source_sets[a], source_sets[b]
            union = sa | sb
            jaccard = round(len(sa & sb) / len(union), 4) if union else 0.0
            pairwise.append({
                "source_a": a,
                "source_b": b,
                "jaccard": jaccard,
                "shared_n": len(sa & sb),
            })

    pairwise.sort(key=lambda x: -x["jaccard"])

    return {
        "min_papers": min_papers,
        "per_source": per_source,
        "pairwise_jaccard": pairwise,
    }, 200


def handle_unit_normalization_report(query=None):
    """Route 51: how raw unit strings cluster into canonical_unit groups.

    Each canonical_unit (normalized form) may have been derived from multiple
    distinct raw unit strings (e.g. canonical_unit='uM' ← raw: μM, µM, µm, uM, μmol/L, ...).
    This report shows those clusters to validate and audit the normalization mapping.

    Without ?q=: returns all canonical_unit groups sorted by n_raw_strings desc (most
    ambiguous first). Also shows overall coverage (how many records have canonical_unit).
    With ?q=uM: detailed breakdown of raw strings + per-canonical usage for that unit.
    """
    reagents = [
        json.loads(line)
        for line in REAGENTS_JSONL.read_text().splitlines()
        if line.strip()
    ]

    from collections import defaultdict, Counter

    n_total = len(reagents)
    n_with_cu = sum(1 for r in reagents if r.get("canonical_unit", ""))

    # Build canonical_unit → {raw_unit → n_records}
    cu_raw: dict[str, Counter] = {}
    for r in reagents:
        cu = r.get("canonical_unit", "")
        ru = r.get("unit", "")
        if not cu:
            continue
        cu_raw.setdefault(cu, Counter())
        if ru:
            cu_raw[cu][ru] += 1

    if query:
        # Detailed breakdown for one canonical_unit
        query_cu = query.strip()
        if query_cu not in cu_raw:
            known = sorted(cu_raw.keys())
            return {
                "error": f"No canonical_unit '{query_cu}' found",
                "known_canonical_units": known[:30],
            }, 404

        raw_counts = cu_raw[query_cu]
        n_records = sum(raw_counts.values())

        # Per canonical: which canonicals use this unit most?
        canon_cu: Counter = Counter()
        for r in reagents:
            if r.get("canonical_unit", "") == query_cu:
                c = r.get("canonical", "")
                if c:
                    canon_cu[c] += 1

        return {
            "canonical_unit": query_cu,
            "n_records": n_records,
            "n_raw_strings": len(raw_counts),
            "raw_strings": [
                {"raw_unit": ru, "n_records": cnt}
                for ru, cnt in raw_counts.most_common()
            ],
            "top_canonicals": [
                {"canonical": c, "n_records": cnt}
                for c, cnt in canon_cu.most_common(20)
            ],
        }, 200

    # Global summary
    units = []
    for cu, raw_cnt in cu_raw.items():
        n_raw = len(raw_cnt)
        n_rec = sum(raw_cnt.values())
        units.append({
            "canonical_unit": cu,
            "n_records": n_rec,
            "n_raw_strings": n_raw,
            "raw_strings": [ru for ru, _ in raw_cnt.most_common()],
            "most_common_raw": raw_cnt.most_common(1)[0][0] if raw_cnt else None,
        })

    units.sort(key=lambda x: (-x["n_raw_strings"], -x["n_records"]))

    return {
        "n_total_reagents": n_total,
        "n_with_canonical_unit": n_with_cu,
        "coverage_rate": round(n_with_cu / n_total, 4) if n_total else 0.0,
        "n_canonical_units": len(units),
        "unit_clusters": units,
    }, 200


def handle_canonical_type_adoption(query=None, min_types=5):
    """Route 50: reagent diffusion — how many distinct organoid types use each canonical per year.

    Builds a doi→year map from protocols.jsonl, then for each canonical tracks
    which types adopt it each year. Surfaces reagents that spread broadly across
    the field vs those that remain type-specific.

    Without ?q=: returns top 50 by n_types_current (all canonicals with >= min_types types),
    with first_year, n_types_current, year_peak (year of most new-type adoptions).
    With ?q=EGF: per-year list of organoid types + cumulative n_types.
    """
    protocols = [
        json.loads(line)
        for line in PROTOCOLS_JSONL.read_text().splitlines()
        if line.strip()
    ]
    reagents = [
        json.loads(line)
        for line in REAGENTS_JSONL.read_text().splitlines()
        if line.strip()
    ]

    # Build doi→year index
    doi_year: dict[str, int] = {}
    for p in protocols:
        doi = p.get("doi", "")
        y = p.get("year")
        if doi and y:
            try:
                doi_year[doi] = int(y)
            except (TypeError, ValueError):
                pass

    from collections import defaultdict

    if query:
        # Per-year type list for one canonical
        canon_lower = query.lower()
        subset = [r for r in reagents if (r.get("canonical") or "").lower() == canon_lower]
        if not subset:
            return {"error": f"No reagents found for canonical '{query}'"}, 404

        year_types: dict[int, set] = {}
        for r in subset:
            doi = r.get("doi", "")
            typ = r.get("organoid_type", "")
            y = doi_year.get(doi)
            if y and typ:
                year_types.setdefault(y, set()).add(typ)

        all_types: set = set()
        by_year = []
        for y in sorted(year_types):
            new_types = sorted(year_types[y] - all_types)
            all_types.update(year_types[y])
            by_year.append({
                "year": y,
                "n_types_this_year": len(year_types[y]),
                "types_this_year": sorted(year_types[y]),
                "new_types": new_types,
                "n_new_types": len(new_types),
                "cumulative_n_types": len(all_types),
            })

        year_of_peak = max(year_types, key=lambda y: len(year_types[y])) if year_types else None

        return {
            "canonical": query,
            "n_types_current": len(all_types),
            "first_year": min(year_types) if year_types else None,
            "year_peak": year_of_peak,
            "by_year": by_year,
        }, 200

    # Global ranking
    canon_year_types: dict[str, dict[int, set]] = {}
    for r in reagents:
        c = r.get("canonical", "")
        doi = r.get("doi", "")
        typ = r.get("organoid_type", "")
        y = doi_year.get(doi)
        if not c or not typ or not y:
            continue
        canon_year_types.setdefault(c, {})
        canon_year_types[c].setdefault(y, set()).add(typ)

    rows = []
    for c, by_year in canon_year_types.items():
        all_types: set = set()
        for types in by_year.values():
            all_types.update(types)
        n_types = len(all_types)
        if n_types < min_types:
            continue
        first_year = min(by_year)
        year_peak = max(by_year, key=lambda y: len(by_year[y]))
        rows.append({
            "canonical": c,
            "n_types_current": n_types,
            "first_year": first_year,
            "year_peak": year_peak,
            "n_years_active": max(by_year) - first_year + 1,
        })

    rows.sort(key=lambda x: (-x["n_types_current"], x["first_year"]))

    return {
        "min_types": min_types,
        "n_canonicals": len(rows),
        "top_by_type_breadth": rows[:50],
    }, 200


def handle_kind_ambiguity(query=None, min_n=3):
    """Route 49: canonicals that appear in both signaling and supplement kinds.

    Sorted by minority_fraction (how often the minority kind appears) to surface
    true ambiguity vs. rare mis-classifications. High minority_fraction means a
    canonical is routinely classified as both — likely a normalization target.

    Without ?q=: returns all dual-kind canonicals with >= min_n total records,
    sorted by minority_fraction desc.
    With ?q=CANONICAL: per-type kind breakdown for that canonical.
    """
    reagents = [
        json.loads(line)
        for line in REAGENTS_JSONL.read_text().splitlines()
        if line.strip()
    ]

    if query:
        subset = [r for r in reagents if (r.get("canonical") or "").lower() == query.lower()]
        if not subset:
            return {"error": f"No reagents found for canonical '{query}'"}, 404

        from collections import defaultdict
        type_kind: dict[str, dict[str, int]] = {}
        for r in subset:
            typ = r.get("organoid_type", "unknown")
            k = r.get("kind", "unknown")
            type_kind.setdefault(typ, {"signaling": 0, "supplement": 0})
            if k in ("signaling", "supplement"):
                type_kind[typ][k] += 1

        per_type = []
        for typ in sorted(type_kind):
            sig = type_kind[typ]["signaling"]
            sup = type_kind[typ]["supplement"]
            total = sig + sup
            dominant = "signaling" if sig >= sup else "supplement"
            minority = total - max(sig, sup)
            per_type.append({
                "organoid_type": typ,
                "n_signaling": sig,
                "n_supplement": sup,
                "n_total": total,
                "dominant_kind": dominant,
                "minority_fraction": round(minority / total, 4) if total else 0.0,
            })
        per_type.sort(key=lambda x: (-x["minority_fraction"], x["organoid_type"]))

        n_sig = sum(e["n_signaling"] for e in per_type)
        n_sup = sum(e["n_supplement"] for e in per_type)
        n_tot = n_sig + n_sup
        return {
            "canonical": query,
            "min_n": min_n,
            "n_signaling": n_sig,
            "n_supplement": n_sup,
            "n_total": n_tot,
            "global_dominant_kind": "signaling" if n_sig >= n_sup else "supplement",
            "global_minority_fraction": round(min(n_sig, n_sup) / n_tot, 4) if n_tot else 0.0,
            "per_type": per_type,
        }, 200

    # Global view
    from collections import defaultdict
    canon_map: dict[str, dict[str, int]] = {}
    for r in reagents:
        c = r.get("canonical", "")
        k = r.get("kind", "")
        if not c or k not in ("signaling", "supplement"):
            continue
        canon_map.setdefault(c, {"signaling": 0, "supplement": 0})
        canon_map[c][k] += 1

    dual_kind = []
    for c, counts in canon_map.items():
        sig = counts["signaling"]
        sup = counts["supplement"]
        if sig == 0 or sup == 0:
            continue
        total = sig + sup
        if total < min_n:
            continue
        minority = min(sig, sup)
        dominant = "signaling" if sig >= sup else "supplement"
        dual_kind.append({
            "canonical": c,
            "n_signaling": sig,
            "n_supplement": sup,
            "n_total": total,
            "dominant_kind": dominant,
            "minority_fraction": round(minority / total, 4),
        })

    dual_kind.sort(key=lambda x: (-x["minority_fraction"], -x["n_total"]))

    return {
        "min_n": min_n,
        "n_dual_kind_canonicals": len(dual_kind),
        "dual_kind_canonicals": dual_kind,
    }, 200


def handle_concentration_value_rate(query=None, min_n=5, kind=None):
    """Route 48: canonicals ranked by fraction of records that carry a numeric dose value.

    Different from /analytics/concentration-stats (which ranks by absolute n_with_value).
    This surfaces 'commonly used but rarely dosed' reagents (high n_total, low rate)
    and 'well-reported' ones (high rate).

    Without ?q=: returns highest_reporters and lowest_reporters lists (top 30 each)
    for canonicals with >= min_n records.
    With ?q=CANONICAL: per-type value rate breakdown for that canonical.
    Optional ?kind=signaling|supplement filter.
    Optional ?min_n= threshold (default 5).
    """
    reagents = [
        json.loads(line)
        for line in REAGENTS_JSONL.read_text().splitlines()
        if line.strip()
    ]

    valid_kinds = {"signaling", "supplement"}
    if kind and kind not in valid_kinds:
        return {"error": f"?kind= must be one of {sorted(valid_kinds)}"}, 400
    if kind:
        reagents = [r for r in reagents if r.get("kind") == kind]

    def _has_value(r):
        v = r.get("value")
        if v in (None, "", "None"):
            return False
        try:
            float(str(v))
            return True
        except (TypeError, ValueError):
            return False

    if query:
        # Per-type breakdown for one canonical
        subset = [r for r in reagents if (r.get("canonical") or "").lower() == query.lower()]
        if not subset:
            return {"error": f"No reagents found for canonical '{query}'"}, 404

        type_map: dict[str, list[int]] = {}
        for r in subset:
            typ = r.get("organoid_type", "unknown")
            type_map.setdefault(typ, [0, 0])
            type_map[typ][1] += 1
            if _has_value(r):
                type_map[typ][0] += 1

        per_type = []
        for typ in sorted(type_map):
            n_v, n_t = type_map[typ]
            per_type.append({
                "organoid_type": typ,
                "n_with_value": n_v,
                "n_total": n_t,
                "value_rate": round(n_v / n_t, 4) if n_t else None,
            })
        per_type.sort(key=lambda x: (-(x["value_rate"] or 0), x["organoid_type"]))

        n_v_total = sum(e["n_with_value"] for e in per_type)
        n_t_total = sum(e["n_total"] for e in per_type)
        return {
            "canonical": query,
            "kind_filter": kind,
            "n_with_value": n_v_total,
            "n_total": n_t_total,
            "overall_value_rate": round(n_v_total / n_t_total, 4) if n_t_total else 0.0,
            "per_type": per_type,
        }, 200

    # Global ranking
    canon_map: dict[str, list[int]] = {}
    for r in reagents:
        c = r.get("canonical", "")
        if not c:
            continue
        canon_map.setdefault(c, [0, 0])
        canon_map[c][1] += 1
        if _has_value(r):
            canon_map[c][0] += 1

    ranked = []
    for c, (n_v, n_t) in canon_map.items():
        if n_t < min_n:
            continue
        ranked.append({
            "canonical": c,
            "n_with_value": n_v,
            "n_total": n_t,
            "value_rate": round(n_v / n_t, 4),
        })

    ranked.sort(key=lambda x: (-x["value_rate"], -x["n_total"]))
    highest = ranked[:30]
    ranked.sort(key=lambda x: (x["value_rate"], -x["n_total"]))
    lowest = ranked[:30]

    n_all_v = sum(e["n_with_value"] for e in ranked)
    n_all_t = sum(e["n_total"] for e in ranked)

    return {
        "kind_filter": kind,
        "min_n": min_n,
        "n_canonicals_evaluated": len(ranked),
        "overall_value_rate": round(n_all_v / n_all_t, 4) if n_all_t else 0.0,
        "highest_reporters": highest,
        "lowest_reporters": lowest,
    }, 200


def handle_evidence_quote_coverage(organoid_type=None, kind=None):
    """Route 47: per-type and per-kind rate of verbatim evidence quotes in reagent records.

    Without filters: global rate, by_kind breakdown (signaling/supplement),
    per_type list sorted by coverage_rate desc.
    With ?type=kidney: coverage for that type only, plus top 20 canonicals by coverage_rate.
    With ?kind=signaling: restrict all stats to that kind.
    """
    reagents = [
        json.loads(line)
        for line in REAGENTS_JSONL.read_text().splitlines()
        if line.strip()
    ]

    # Apply kind filter
    valid_kinds = {"signaling", "supplement"}
    if kind and kind not in valid_kinds:
        return {"error": f"?kind= must be one of {sorted(valid_kinds)}"}, 400
    if kind:
        reagents = [r for r in reagents if r.get("kind") == kind]

    def _has_quote(r):
        q = r.get("evidence_quote")
        return bool(q and str(q).strip())

    if organoid_type:
        subset = [r for r in reagents if r.get("organoid_type") == organoid_type]
        if not subset:
            known = sorted({r.get("organoid_type", "") for r in reagents} - {""})
            return {
                "error": f"No reagents for type '{organoid_type}'",
                "known_types": known,
            }, 404

        n_total = len(subset)
        n_with_quote = sum(1 for r in subset if _has_quote(r))
        coverage_rate = round(n_with_quote / n_total, 4) if n_total else 0.0

        # by_kind breakdown
        by_kind = {}
        for k in ("signaling", "supplement"):
            ks = [r for r in subset if r.get("kind") == k]
            n_k = len(ks)
            n_k_q = sum(1 for r in ks if _has_quote(r))
            by_kind[k] = {
                "n_with_quote": n_k_q,
                "n_total": n_k,
                "coverage_rate": round(n_k_q / n_k, 4) if n_k else None,
            }

        # Top 20 canonicals by coverage_rate (min 3 records)
        from collections import defaultdict
        canon_map = defaultdict(lambda: [0, 0])
        for r in subset:
            c = r.get("canonical", "")
            if not c:
                continue
            canon_map[c][1] += 1
            if _has_quote(r):
                canon_map[c][0] += 1
        canon_rows = []
        for c, (n_q, n_t) in canon_map.items():
            if n_t >= 3:
                canon_rows.append({
                    "canonical": c,
                    "n_with_quote": n_q,
                    "n_total": n_t,
                    "coverage_rate": round(n_q / n_t, 4),
                })
        canon_rows.sort(key=lambda x: (-x["coverage_rate"], -x["n_total"]))

        return {
            "organoid_type": organoid_type,
            "kind_filter": kind,
            "n_with_quote": n_with_quote,
            "n_total": n_total,
            "coverage_rate": coverage_rate,
            "by_kind": by_kind,
            "top_canonicals_by_coverage": canon_rows[:20],
        }, 200

    # Global view
    n_total = len(reagents)
    n_with_quote = sum(1 for r in reagents if _has_quote(r))
    overall_rate = round(n_with_quote / n_total, 4) if n_total else 0.0

    # by_kind global breakdown
    by_kind = {}
    for k in ("signaling", "supplement"):
        ks = [r for r in reagents if r.get("kind") == k]
        n_k = len(ks)
        n_k_q = sum(1 for r in ks if _has_quote(r))
        by_kind[k] = {
            "n_with_quote": n_k_q,
            "n_total": n_k,
            "coverage_rate": round(n_k_q / n_k, 4) if n_k else None,
        }

    # per_type breakdown
    from collections import defaultdict
    type_map = defaultdict(lambda: {"signaling": [0, 0], "supplement": [0, 0]})
    for r in reagents:
        typ = r.get("organoid_type", "")
        k = r.get("kind", "")
        if not typ or k not in ("signaling", "supplement"):
            continue
        type_map[typ][k][1] += 1
        if _has_quote(r):
            type_map[typ][k][0] += 1

    per_type = []
    for typ in sorted(type_map):
        sig = type_map[typ]["signaling"]
        sup = type_map[typ]["supplement"]
        n_t = sig[1] + sup[1]
        n_q = sig[0] + sup[0]
        per_type.append({
            "organoid_type": typ,
            "n_with_quote": n_q,
            "n_total": n_t,
            "coverage_rate": round(n_q / n_t, 4) if n_t else None,
            "signaling_rate": round(sig[0] / sig[1], 4) if sig[1] else None,
            "supplement_rate": round(sup[0] / sup[1], 4) if sup[1] else None,
        })
    per_type.sort(key=lambda x: (-(x["coverage_rate"] or 0), x["organoid_type"]))

    return {
        "kind_filter": kind,
        "n_with_quote": n_with_quote,
        "n_total": n_total,
        "overall_coverage_rate": overall_rate,
        "by_kind": by_kind,
        "per_type": per_type,
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
            "/analytics/kgx-summary": "KGX graph state: node/edge counts by category, resolution rate, review queue breakdown (needs_review/not_found/not_attempted), top unresolved entities for S1/S2 triage",
            "/analytics/concentration-by-type": "per-organoid-type concentration stats for one canonical reagent — median/min/max/n per unit per type; requires ?q=EGF; useful for comparing dose ranges across organoid systems",
            "/analytics/journal-breakdown": "journal contribution counts: cross-corpus top 50 + per-type top 5; optional ?type=kidney for full breakdown of one type — audits corpus composition and journal bias",
            "/analytics/type-comparison": "side-by-side organoid type comparison: shared/unique canonical reagents, Jaccard score, per-kind breakdown; requires ?a=intestinal&b=cerebral",
            "/analytics/concentration-deviation": "dose inconsistency ranking: canonical reagents sorted by coefficient of variation (std/mean) across records with numeric values; ?min_n= to set sample threshold (default 3)",
            "/analytics/reagent-prevalence": "type-breadth ranking: canonical reagents sorted by number of organoid types they appear in; cross_field (>=20 types) + specialist (<=2 types) sub-lists; ?q=EGF for per-type breakdown; ?min_types= threshold",
            "/analytics/protocol-outliers": "per-type outlier detection on n_signaling_factors: complex (high SF count) and minimal (low SF count) protocols per organoid type, with z-scores; ?type=kidney for one type; ?z_thresh= to adjust sensitivity (default 1.5)",
            "/analytics/grounding-distribution": "per-paper grounding rate histogram (10 buckets 0-100%), per-type mean ranking, top/bottom 20 papers; ?type=kidney for one type; live from protocols.jsonl",
            "/analytics/type-maturity": "field maturity classification per organoid type: first_year, n_years_active, n_papers_total, trajectory (accelerating/stable/slowing), maturity_tier (established/developing/emerging); ?type=kidney for one type",
            "/analytics/reagent-cooccurrence": "pairwise signaling-factor co-occurrence: top pairs by n_papers with Jaccard similarity; ?q=EGF for all partners of one canonical; ?type= for one organoid type; ?min_papers= threshold (default 3)",
            "/analytics/supplement-breakdown": "per-type and cross-type breakdown of supplement (kind=supplement) canonicals: global top 50 by n_papers, cross-type list (>= min_types organoid types), per-type top 10; ?q=GlutaMAX for one canonical; ?type=kidney for one type; ?min_types= threshold (default 10)",
            "/analytics/role-breakdown": "normalized functional role distribution for signaling (kind=signaling) reagents: signaling_factor/growth_factor/differentiation/inhibitor/supplement/treatment/agonist/conditioned_medium/proliferation/other/not_stated; ?q=differentiation for top canonicals with that role; ?type= filter",
            "/analytics/type-reagent-heatmap": "organoid type × canonical reagent usage matrix for visualization: top_n canonicals (columns) × all types (rows), each cell = n_papers; ?kind=signaling|supplement|all (default signaling); ?top_n= (default 20, max 50)",
            "/analytics/canonical-name-variants": "normalization complexity report: for each canonical, all distinct raw names that map to it; top 30 most-ambiguous sorted by n_variants; ?q=FGF2 for one canonical; ?min_variants= floor (default 2)",
            "/analytics/concentration-unit-distribution": "unit inconsistency report: canonicals using multiple concentration unit systems; top 30 by n_units; ?q=EGF for full unit breakdown with min/median/max per unit; ?min_n= records threshold (default 3)",
            "/analytics/protocol-size-distribution": "full distribution of protocol sizes: histogram of n_signaling_factors and n_supplements per paper (global + per-type mean/median/std); ?type=kidney for one type with full histograms",
            "/analytics/evidence-quote-coverage": "per-type and per-kind rate of verbatim evidence quotes in reagent records; overall_coverage_rate + by_kind breakdown; per_type sorted by coverage_rate; ?type=kidney for top canonicals by coverage; ?kind=signaling|supplement filter",
            "/analytics/concentration-value-rate": "canonicals ranked by fraction of records with a numeric dose value; highest_reporters (well-dosed) + lowest_reporters (commonly used but rarely dosed); ?q=Wnt3a for per-type breakdown; ?min_n= threshold (default 5); ?kind= filter",
            "/analytics/kind-ambiguity": "canonicals that appear in both signaling and supplement kinds; sorted by minority_fraction (ambiguity score); highlights normalization targets; ?q=Y-27632 for per-type kind breakdown; ?min_n= threshold (default 3)",
            "/analytics/canonical-type-adoption": "reagent diffusion: for each canonical, tracks n distinct organoid types using it per year (first_year, n_types_current, year_peak = most new-type adoptions); ?q=EGF for per-year type list; ?min_types= threshold (default 5)",
            "/analytics/unit-normalization-report": "audit of raw unit string → canonical_unit normalization clusters: e.g. 'uM' ← [μM, µM, µm, μmol/L, ...]; sorted by n_raw_strings; ?q=uM for detailed breakdown + top canonicals using that unit",
            "/analytics/source-cell-reagent-profile": "characteristic canonical reagents by source_cell_type (iPSC / adult_stem_cell / primary_tissue / ESC); top 20 per source + pairwise Jaccard similarity; ?source=iPSC for top 30 with exclusivity scores; ?min_papers= threshold (default 3)",
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


async def route_type_comparison(datasette, request):
    type_a = request.args.get("a") or None
    type_b = request.args.get("b") or None
    data, status = handle_type_comparison(type_a, type_b)
    return Response.json(data, status=status)


async def route_journal_breakdown(datasette, request):
    organoid_type = request.args.get("type") or None
    data, status = handle_journal_breakdown(organoid_type)
    return Response.json(data, status=status)


async def route_concentration_by_type(datasette, request):
    query = request.args.get("q") or None
    data, status = handle_concentration_by_type(query)
    return Response.json(data, status=status)


async def route_reagent_prevalence(datasette, request):
    query = request.args.get("q") or None
    try:
        min_types = int(request.args.get("min_types") or 1)
    except (TypeError, ValueError):
        min_types = 1
    data, status = handle_reagent_prevalence(query, min_types)
    return Response.json(data, status=status)


async def route_protocol_outliers(datasette, request):
    organoid_type = request.args.get("type") or None
    try:
        z_thresh = float(request.args.get("z_thresh") or 1.5)
    except (TypeError, ValueError):
        z_thresh = 1.5
    data, status = handle_protocol_outliers(organoid_type, z_thresh)
    return Response.json(data, status=status)


async def route_grounding_distribution(datasette, request):
    organoid_type = request.args.get("type") or None
    data, status = handle_grounding_distribution(organoid_type)
    return Response.json(data, status=status)


async def route_type_maturity(datasette, request):
    organoid_type = request.args.get("type") or None
    data, status = handle_type_maturity(organoid_type)
    return Response.json(data, status=status)


async def route_protocol_size_distribution(datasette, request):
    organoid_type = request.args.get("type") or None
    data, status = handle_protocol_size_distribution(organoid_type)
    return Response.json(data, status=status)


async def route_evidence_quote_coverage(datasette, request):
    organoid_type = request.args.get("type") or None
    kind = request.args.get("kind") or None
    data, status = handle_evidence_quote_coverage(organoid_type, kind)
    return Response.json(data, status=status)


async def route_concentration_value_rate(datasette, request):
    query = request.args.get("q") or None
    kind = request.args.get("kind") or None
    try:
        min_n = int(request.args.get("min_n") or 5)
    except (TypeError, ValueError):
        min_n = 5
    data, status = handle_concentration_value_rate(query, min_n, kind)
    return Response.json(data, status=status)


async def route_kind_ambiguity(datasette, request):
    query = request.args.get("q") or None
    try:
        min_n = int(request.args.get("min_n") or 3)
    except (TypeError, ValueError):
        min_n = 3
    data, status = handle_kind_ambiguity(query, min_n)
    return Response.json(data, status=status)


async def route_canonical_type_adoption(datasette, request):
    query = request.args.get("q") or None
    try:
        min_types = int(request.args.get("min_types") or 5)
    except (TypeError, ValueError):
        min_types = 5
    data, status = handle_canonical_type_adoption(query, min_types)
    return Response.json(data, status=status)


async def route_unit_normalization_report(datasette, request):
    query = request.args.get("q") or None
    data, status = handle_unit_normalization_report(query)
    return Response.json(data, status=status)


async def route_source_cell_reagent_profile(datasette, request):
    source = request.args.get("source") or None
    try:
        min_papers = int(request.args.get("min_papers") or 3)
    except (TypeError, ValueError):
        min_papers = 3
    data, status = handle_source_cell_reagent_profile(source, min_papers)
    return Response.json(data, status=status)


async def route_concentration_unit_distribution(datasette, request):
    query = request.args.get("q") or None
    try:
        min_n = int(request.args.get("min_n") or 3)
    except (TypeError, ValueError):
        min_n = 3
    data, status = handle_concentration_unit_distribution(query, min_n)
    return Response.json(data, status=status)


async def route_canonical_name_variants(datasette, request):
    query = request.args.get("q") or None
    try:
        min_variants = int(request.args.get("min_variants") or 2)
    except (TypeError, ValueError):
        min_variants = 2
    data, status = handle_canonical_name_variants(query, min_variants)
    return Response.json(data, status=status)


async def route_type_reagent_heatmap(datasette, request):
    kind = request.args.get("kind") or None
    try:
        top_n = int(request.args.get("top_n") or 20)
    except (TypeError, ValueError):
        top_n = 20
    data, status = handle_type_reagent_heatmap(kind, top_n)
    return Response.json(data, status=status)


async def route_role_breakdown(datasette, request):
    query = request.args.get("q") or None
    organoid_type = request.args.get("type") or None
    data, status = handle_role_breakdown(query, organoid_type)
    return Response.json(data, status=status)


async def route_supplement_breakdown(datasette, request):
    query = request.args.get("q") or None
    organoid_type = request.args.get("type") or None
    try:
        min_types = int(request.args.get("min_types") or 10)
    except (TypeError, ValueError):
        min_types = 10
    data, status = handle_supplement_breakdown(query, organoid_type, min_types)
    return Response.json(data, status=status)


async def route_reagent_cooccurrence(datasette, request):
    query = request.args.get("q") or None
    organoid_type = request.args.get("type") or None
    try:
        min_papers = int(request.args.get("min_papers") or 3)
    except (TypeError, ValueError):
        min_papers = 3
    data, status = handle_reagent_cooccurrence(query, organoid_type, min_papers)
    return Response.json(data, status=status)


async def route_concentration_deviation(datasette, request):
    try:
        min_n = int(request.args.get("min_n") or 3)
    except (TypeError, ValueError):
        min_n = 3
    data, status = handle_concentration_deviation(min_n)
    return Response.json(data, status=status)


async def route_kgx_summary(datasette, request):
    data, status = handle_kgx_summary()
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
        (r"^/analytics/type-comparison$", route_type_comparison),
        (r"^/analytics/concentration-deviation$", route_concentration_deviation),
        (r"^/analytics/reagent-prevalence$", route_reagent_prevalence),
        (r"^/analytics/protocol-outliers$", route_protocol_outliers),
        (r"^/analytics/grounding-distribution$", route_grounding_distribution),
        (r"^/analytics/type-maturity$", route_type_maturity),
        (r"^/analytics/reagent-cooccurrence$", route_reagent_cooccurrence),
        (r"^/analytics/supplement-breakdown$", route_supplement_breakdown),
        (r"^/analytics/role-breakdown$", route_role_breakdown),
        (r"^/analytics/type-reagent-heatmap$", route_type_reagent_heatmap),
        (r"^/analytics/canonical-name-variants$", route_canonical_name_variants),
        (r"^/analytics/concentration-unit-distribution$", route_concentration_unit_distribution),
        (r"^/analytics/protocol-size-distribution$", route_protocol_size_distribution),
        (r"^/analytics/evidence-quote-coverage$", route_evidence_quote_coverage),
        (r"^/analytics/concentration-value-rate$", route_concentration_value_rate),
        (r"^/analytics/kind-ambiguity$", route_kind_ambiguity),
        (r"^/analytics/canonical-type-adoption$", route_canonical_type_adoption),
        (r"^/analytics/unit-normalization-report$", route_unit_normalization_report),
        (r"^/analytics/source-cell-reagent-profile$", route_source_cell_reagent_profile),
        (r"^/analytics/journal-breakdown$", route_journal_breakdown),
        (r"^/analytics/concentration-by-type$", route_concentration_by_type),
        (r"^/analytics/kgx-summary$", route_kgx_summary),
        (r"^/analytics/assay-endpoints$", route_assay_endpoints),
        (r"^/analytics/quality$", route_quality),
        (r"^/analytics/mior$", route_mior),
        (r"^/analytics/candidates$", route_candidates),
        (r"^/analytics/status$", route_status),
        (r"^/analytics/summary$", route_summary),
    ]
