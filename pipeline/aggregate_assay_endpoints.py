#!/usr/bin/env python3
"""
Aggregate assay endpoint data across the public corpus.

Parses the assay_endpoints field (dot/bullet-separated terms) from
protocols.jsonl, normalises to keyword clusters, and reports:

  - Per-type: which assay clusters appear, and in what fraction of papers
  - Cross-type: which assays are universal vs. type-specific
  - Raw top-N term frequency (unnormalised)

Clusters use substring/regex matching (same pattern as aggregate_failure_modes.py).

Input:  exports/public/protocols.jsonl
Output: outputs/analysis/assay_endpoint_summary.json

Run:
  python pipeline/aggregate_assay_endpoints.py
  python pipeline/aggregate_assay_endpoints.py --min-papers 3
  python pipeline/aggregate_assay_endpoints.py --json      (pretty JSON)
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent.parent
PROTOCOLS_JSONL = REPO / "exports" / "public" / "protocols.jsonl"
OUT_PATH = REPO / "outputs" / "analysis" / "assay_endpoint_summary.json"

# Separator pattern for the assay_endpoints field
_TERM_SEP = re.compile(r"\s*[·•,;/]\s*")


# --------------------------------------------------------------------------- #
# Assay clusters (order matters — first match wins for primary label)
# --------------------------------------------------------------------------- #

class AssayCluster(NamedTuple):
    label: str
    patterns: list[str]  # matched case-insensitively as substrings


ASSAY_CLUSTERS: list[AssayCluster] = [
    AssayCluster("immunostaining_IF_IHC", [
        "immunofluor", "immunohistochem", "immunostain",
        r"\bIF\b", r"\bIHC\b",
    ]),
    AssayCluster("gene_expression_qPCR", [
        "gene expression", r"rt[- ]?q?pcr", r"q[rt]?[-_\s]?pcr",
        "rtpcr", "qpcr", r"\bpcr\b",
    ]),
    AssayCluster("RNA_sequencing", [
        "rna.?seq", "rnaseq", "scrna", "single.?cell rna", "rna sequencing",
        "transcriptom", "bulk rna", r"\bscRNA\b",
    ]),
    AssayCluster("flow_cytometry_FACS", [
        "flow cytometry", r"\bfacs\b", "fluorescence.activated",
    ]),
    AssayCluster("electron_microscopy", [
        "electron microscop", r"\bsem\b", r"\btem\b",
        "scanning electron", "transmission electron",
    ]),
    AssayCluster("histology_morphology", [
        "histol", "h&e", "hematoxylin", "morphol", "staining",
    ]),
    AssayCluster("western_blot", [
        "western blot", "western blotting", r"\bwb\b",
    ]),
    AssayCluster("secretion_functional_assay", [
        "secretion", "elisa", "insulin", "albumin secret", "c-peptide",
        "amylase", "functional",
    ]),
    AssayCluster("proliferation_viability", [
        "prolifer", "viabilit", r"\bki67\b", "mts assay", "cell count",
        "annexin", "apoptosis",
    ]),
    AssayCluster("calcium_imaging_electrophysiology", [
        "calcium", r"\beph\b", "electrophysiol", "patch clamp",
        "action potential", "cardiomyocyte beating",
    ]),
    AssayCluster("proteomics_mass_spec", [
        "proteomics", "mass spec", r"\bms\b", "liquid chromatography",
        r"\blc-ms\b",
    ]),
    AssayCluster("single_cell_analysis", [
        "single.cell", "single cell", "droplet",
    ]),
]


def assign_clusters(
    term: str,
    clusters: list[AssayCluster],
) -> list[str]:
    """
    Return list of cluster labels whose patterns match term.
    Matching is case-insensitive. A term can belong to multiple clusters.
    Returns ["other"] if no cluster matches.
    """
    matched = []
    for cluster in clusters:
        for pat in cluster.patterns:
            if re.search(pat, term, re.IGNORECASE):
                matched.append(cluster.label)
                break  # one match per cluster is enough
    return matched if matched else ["other"]


def parse_assay_terms(raw: str) -> list[str]:
    """Split a raw assay_endpoints string into individual terms."""
    if not raw or not raw.strip():
        return []
    return [t.strip().lower() for t in _TERM_SEP.split(raw) if t.strip()]


def aggregate_assay_endpoints(
    protocols: list[dict],
    clusters: list[AssayCluster] | None = None,
) -> dict:
    """
    Compute assay endpoint summary across a list of protocols.
    Pure function — no I/O.

    Returns a dict with:
      by_type: {organoid_type: {cluster_label: {n_papers, fraction, examples}}}
      cross_type: {cluster_label: {n_types, n_papers, types}}
      raw_terms: [{term, count}]
      n_total_with_assays: int
      n_total_papers: int
    """
    if clusters is None:
        clusters = ASSAY_CLUSTERS

    n_total = len(protocols)
    raw_term_counter: Counter = Counter()
    # by_type -> cluster_label -> set of pmcids
    by_type: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    cross_type_cluster: dict[str, set[str]] = defaultdict(set)  # cluster → set of types
    cross_type_papers: dict[str, set[str]] = defaultdict(set)   # cluster → set of pmcids

    n_with_assays = 0

    for p in protocols:
        raw = p.get("assay_endpoints") or ""
        if not raw or str(raw).lower().strip() in (
            "null", "none", "not_reported", "not_extracted", "not_applicable", "tbd"
        ):
            continue

        pmcid = p.get("pmcid") or "unknown"
        otype = (p.get("organoid_type") or "unknown").lower()
        terms = parse_assay_terms(raw)
        if not terms:
            continue

        n_with_assays += 1
        raw_term_counter.update(terms)

        # Which clusters does this paper trigger?
        paper_clusters: set[str] = set()
        for term in terms:
            for label in assign_clusters(term, clusters):
                paper_clusters.add(label)

        for label in paper_clusters:
            by_type[otype][label].add(pmcid)
            cross_type_cluster[label].add(otype)
            cross_type_papers[label].add(pmcid)

    # Compute per-type fractions
    type_paper_counts: Counter = Counter(
        p.get("organoid_type", "unknown").lower() for p in protocols
    )

    by_type_out: dict[str, dict] = {}
    for otype, label_pmcids in by_type.items():
        total_in_type = type_paper_counts[otype]
        clusters_out = {}
        for label, pmcid_set in sorted(label_pmcids.items(),
                                       key=lambda kv: -len(kv[1])):
            n = len(pmcid_set)
            clusters_out[label] = {
                "n_papers": n,
                "fraction": round(n / total_in_type, 4) if total_in_type else 0.0,
            }
        by_type_out[otype] = clusters_out

    cross_type_out: dict[str, dict] = {}
    for label in sorted(cross_type_cluster.keys(),
                        key=lambda l: -len(cross_type_papers[l])):
        cross_type_out[label] = {
            "n_types": len(cross_type_cluster[label]),
            "n_papers": len(cross_type_papers[label]),
            "types": sorted(cross_type_cluster[label]),
        }

    return {
        "n_total_papers": n_total,
        "n_with_assay_endpoints": n_with_assays,
        "coverage_fraction": round(n_with_assays / n_total, 4) if n_total else 0.0,
        "n_clusters": len(clusters),
        "by_organoid_type": by_type_out,
        "cross_type_cluster_usage": cross_type_out,
        "raw_top_terms": [
            {"term": term, "count": count}
            for term, count in raw_term_counter.most_common(30)
        ],
    }


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #

def load_protocols(path: Path | None = None) -> list[dict]:
    p = path or PROTOCOLS_JSONL
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Aggregate assay endpoint data across corpus")
    ap.add_argument("--output", "-o", default=None, help="Output JSON path")
    ap.add_argument("--json", action="store_true", help="Pretty-print JSON to stdout")
    args = ap.parse_args()

    protocols = load_protocols()
    if not protocols:
        print(f"No protocols at {PROTOCOLS_JSONL}", file=sys.stderr)
        sys.exit(1)

    summary = aggregate_assay_endpoints(protocols)

    if args.json:
        print(json.dumps(summary, indent=2))
        return

    out_path = Path(args.output) if args.output else OUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))

    n_total = summary["n_total_papers"]
    n_with = summary["n_with_assay_endpoints"]
    cov = summary["coverage_fraction"]
    print(f"Assay endpoint summary → {out_path}")
    print(f"Papers: {n_total}  |  with assays: {n_with} ({cov:.0%})")
    print(f"\nTop 10 cluster usage across corpus:")
    for label, data in list(summary["cross_type_cluster_usage"].items())[:10]:
        print(f"  {label:40s} {data['n_papers']:4d} papers in {data['n_types']:2d} types")
    print(f"\nTop 10 raw terms:")
    for item in summary["raw_top_terms"][:10]:
        print(f"  {item['count']:4d}  {item['term']}")


if __name__ == "__main__":
    main()
