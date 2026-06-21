#!/usr/bin/env python3
"""
Protocol lineage graph builder: construct a directed DOI→DOI graph from
ProtocolModification records extracted across the corpus.

Each ProtocolModification says "this paper (source_doi) modified a prior
protocol (cited_doi), changing X". That gives a directed edge:
  cited_doi  →  source_doi   (with label = change_description)

The result is a protocol family tree: follow edges forward to see how a
seminal protocol (Sato 2009, Lancaster 2013, etc.) evolved across the field.

Data sources (tried in order per paper):
  1. data/predictions/local/{pmcid}.json  -- full v0.4 prediction
  2. outputs/tier1/extraction_summary.json -- modifications field if present

Output:
  outputs/analysis/protocol_lineage.json    -- nodes + edges (always written)
  outputs/analysis/protocol_lineage.dot     -- Graphviz DOT (--dot flag)

Run:
  python pipeline/build_lineage.py
  python pipeline/build_lineage.py --dot
  python pipeline/build_lineage.py --root 10.1038/nature07935
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
PRED_DIR = REPO / "data" / "predictions" / "local"
SUMMARY_PATH = REPO / "outputs" / "tier1" / "extraction_summary.json"
OUT_JSON = REPO / "outputs" / "analysis" / "protocol_lineage.json"
OUT_DOT = REPO / "outputs" / "analysis" / "protocol_lineage.dot"


# --------------------------------------------------------------------------- #
# Pure graph logic (fully offline-testable)
# --------------------------------------------------------------------------- #

def build_graph(modifications: list[dict]) -> dict[str, Any]:
    """
    Build a directed graph from modification records.

    Each record: {source_doi, cited_doi, change_description, pmcid, organoid_type}

    Returns:
      {
        "nodes": [{doi, pmcids, organoid_types, n_in, n_out}],
        "edges": [{from, to, change_description, pmcid}],
        "roots": [doi]   # nodes with no incoming edges (seminal papers)
      }
    """
    edges: list[dict] = []
    node_pmcids: dict[str, set] = defaultdict(set)
    node_types: dict[str, set] = defaultdict(set)
    in_degree: dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)

    seen_edges: set[tuple] = set()

    for m in modifications:
        src = (m.get("source_doi") or "").strip()
        cited = (m.get("cited_doi") or "").strip()
        pmcid = m.get("pmcid", "")
        otype = m.get("organoid_type", "unknown")
        change = (m.get("change_description") or "").strip()

        if not src or not cited:
            continue  # need both endpoints for an edge

        edge_key = (cited, src, change[:60])
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)

        edges.append({"from": cited, "to": src, "change_description": change, "pmcid": pmcid})
        out_degree[cited] += 1
        in_degree[src] += 1

        for doi in (src, cited):
            node_pmcids[doi].add(pmcid)
            node_types[doi].add(otype)

    all_dois = set(node_pmcids.keys())
    roots = sorted(d for d in all_dois if in_degree[d] == 0 and out_degree[d] > 0)

    nodes = sorted(
        [
            {
                "doi": doi,
                "pmcids": sorted(node_pmcids[doi]),
                "organoid_types": sorted(node_types[doi]),
                "n_in": in_degree[doi],
                "n_out": out_degree[doi],
            }
            for doi in all_dois
        ],
        key=lambda n: (-n["n_out"], n["doi"]),
    )

    return {
        "n_nodes": len(nodes),
        "n_edges": len(edges),
        "roots": roots,
        "nodes": nodes,
        "edges": edges,
    }


def subgraph_from_root(graph: dict, root_doi: str) -> dict:
    """
    Return the subgraph reachable from root_doi (BFS forward traversal).
    """
    adj: dict[str, list[dict]] = defaultdict(list)
    for e in graph["edges"]:
        adj[e["from"]].append(e)

    visited: set[str] = set()
    queue = deque([root_doi])
    visited.add(root_doi)
    subedges: list[dict] = []
    while queue:
        node = queue.popleft()
        for e in adj.get(node, []):
            subedges.append(e)
            if e["to"] not in visited:
                visited.add(e["to"])
                queue.append(e["to"])

    node_map = {n["doi"]: n for n in graph["nodes"]}
    subnodes = [node_map[d] for d in visited if d in node_map]

    return {
        "root": root_doi,
        "n_nodes": len(subnodes),
        "n_edges": len(subedges),
        "roots": [root_doi],
        "nodes": subnodes,
        "edges": subedges,
    }


def to_dot(graph: dict) -> str:
    """
    Convert graph dict to Graphviz DOT format.
    DOI strings are shortened for readability (last 15 chars).
    """
    def _short(doi: str) -> str:
        doi = doi.replace('"', "")
        return doi[-20:] if len(doi) > 20 else doi

    lines = ["digraph protocol_lineage {", "  rankdir=LR;", "  node [shape=box fontsize=10];"]

    for n in graph.get("nodes", []):
        doi = n["doi"]
        label = _short(doi)
        types = ", ".join(n.get("organoid_types", []))
        tooltip = f"{doi} | {types}" if types else doi
        lines.append(f'  "{doi}" [label="{label}" tooltip="{tooltip}"];')

    for e in graph.get("edges", []):
        change = e.get("change_description", "")[:40].replace('"', "'")
        lines.append(f'  "{e["from"]}" -> "{e["to"]}" [label="{change}"];')

    lines.append("}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

def _load_from_local_predictions() -> list[dict]:
    records: list[dict] = []
    if not PRED_DIR.exists():
        return records
    for pred_file in sorted(PRED_DIR.glob("*.json")):
        pmcid = pred_file.stem
        try:
            p = json.loads(pred_file.read_text())
        except json.JSONDecodeError:
            continue
        src_doi = p.get("source_doi", "")
        otype = p.get("organoid_type", "unknown")
        for mod in p.get("modifications") or []:
            records.append({
                "source_doi": src_doi,
                "cited_doi": mod.get("cited_doi", ""),
                "change_description": mod.get("change_description", ""),
                "pmcid": pmcid,
                "organoid_type": otype,
            })
    return records


def _load_from_extraction_summary() -> list[dict]:
    if not SUMMARY_PATH.exists():
        return []
    try:
        data = json.loads(SUMMARY_PATH.read_text())
    except json.JSONDecodeError:
        return []
    records: list[dict] = []
    for row in data.get("rows") or []:
        src_doi = row.get("doi", "")
        pmcid = row.get("pmcid", "")
        otype = row.get("organoid_type", "unknown")
        for mod in row.get("modifications") or []:
            if isinstance(mod, dict):
                records.append({
                    "source_doi": src_doi,
                    "cited_doi": mod.get("cited_doi", ""),
                    "change_description": mod.get("change_description", ""),
                    "pmcid": pmcid,
                    "organoid_type": otype,
                })
    return records


def load_all_modifications() -> list[dict]:
    local = _load_from_local_predictions()
    summary = _load_from_extraction_summary()

    # Deduplicate by (source_doi, cited_doi, change[:60])
    seen: set[tuple] = set()
    merged: list[dict] = []
    for rec in local + summary:
        key = (rec.get("source_doi", ""), rec.get("cited_doi", ""),
               rec.get("change_description", "")[:60])
        if key not in seen:
            seen.add(key)
            merged.append(rec)
    return merged


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(description="Build protocol lineage graph from ProtocolModification data")
    ap.add_argument("--dot", action="store_true", help="Also write Graphviz DOT file")
    ap.add_argument("--root", default=None,
                    help="Output subgraph reachable from this DOI only")
    ap.add_argument("--output", "-o", default=None, help="Output JSON path")
    args = ap.parse_args()

    modifications = load_all_modifications()

    if not modifications:
        print(
            "No ProtocolModification records found. "
            "Run tier1 extraction on A100: python pipeline/tier1_extract.py",
            file=sys.stderr,
        )
        graph = {"n_nodes": 0, "n_edges": 0, "roots": [], "nodes": [], "edges": []}
    else:
        graph = build_graph(modifications)
        if args.root:
            graph = subgraph_from_root(graph, args.root)

    out_path = Path(args.output) if args.output else OUT_JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(graph, indent=2))
    print(f"Lineage graph → {out_path}")
    print(f"  Nodes: {graph['n_nodes']}, Edges: {graph['n_edges']}")
    if graph.get("roots"):
        print(f"  Root (seminal) DOIs: {graph['roots'][:5]}")

    if args.dot:
        dot_str = to_dot(graph)
        OUT_DOT.parent.mkdir(parents=True, exist_ok=True)
        OUT_DOT.write_text(dot_str)
        print(f"  DOT → {OUT_DOT}")


if __name__ == "__main__":
    main()
