#!/usr/bin/env python3
"""
System status report for organoid-protocol-atlas.

Single command showing:
  1. Corpus stats (from exports/public/protocols.jsonl — always available)
  2. Analytics output inventory (which pre-computed artifacts exist)
  3. What still needs to be generated
  4. Schema/version consistency check

Exit codes:
  0 — all analytics outputs present and corpus healthy
  1 — one or more analytics outputs missing or corpus not found

Run:
  python pipeline/system_status.py
  python pipeline/system_status.py --json
  python pipeline/system_status.py --quiet   # exit code only, minimal output
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent.parent
EXPORTS = REPO / "exports" / "public"
OUTPUTS = REPO / "outputs" / "analysis"
PREDICTIONS_LOCAL = REPO / "data" / "predictions" / "local"
CORPUS_TSV = REPO / "data" / "corpus" / "corpus.tsv"
MANIFEST = EXPORTS / "manifest.json"

PROTOCOLS_JSONL = EXPORTS / "protocols.jsonl"
REAGENTS_JSONL = EXPORTS / "reagents.jsonl"


# --------------------------------------------------------------------------- #
# Pure status checks (no I/O side effects)
# --------------------------------------------------------------------------- #

class AnalyticsArtifact(NamedTuple):
    name: str
    path: Path
    generate_cmd: str
    required: bool = True


ANALYTICS_ARTIFACTS = [
    AnalyticsArtifact(
        "failure_mode_summary",
        OUTPUTS / "failure_mode_summary.json",
        "python pipeline/aggregate_failure_modes.py",
    ),
    AnalyticsArtifact(
        "protocol_lineage",
        OUTPUTS / "protocol_lineage.json",
        "python pipeline/build_lineage.py",
    ),
    AnalyticsArtifact(
        "coverage_report",
        OUTPUTS / "coverage_report.json",
        "python pipeline/generate_coverage_report.py",
    ),
    AnalyticsArtifact(
        "assay_endpoint_summary",
        OUTPUTS / "assay_endpoint_summary.json",
        "python pipeline/aggregate_assay_endpoints.py",
    ),
    AnalyticsArtifact(
        "protocol_quality_scores",
        OUTPUTS / "protocol_quality_scores.json",
        "python pipeline/score_protocol_quality.py",
    ),
]


def check_corpus(protocols_path: Path) -> dict:
    """
    Read protocols.jsonl and compute summary stats.
    Pure function — returns a dict, never prints.
    """
    if not protocols_path.exists():
        return {"ok": False, "error": f"not found: {protocols_path}"}

    rows = []
    bad_lines = 0
    for line in protocols_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad_lines += 1

    if not rows:
        return {"ok": False, "error": "empty file"}

    n = len(rows)
    types = sorted(set(r.get("organoid_type", "?") for r in rows))
    grs = [r.get("grounding_rate") for r in rows if r.get("grounding_rate") is not None]
    try:
        grs_f = [float(x) for x in grs]
        avg_gr = round(sum(grs_f) / len(grs_f), 4) if grs_f else None
    except (TypeError, ValueError):
        avg_gr = None

    grounded_sum = sum(int(r.get("reagents_grounded") or 0) for r in rows)
    total_sum = sum(int(r.get("reagents_total") or 0) for r in rows)
    pooled_gr = round(grounded_sum / total_sum, 4) if total_sum > 0 else None

    local_pred_count = 0
    if PREDICTIONS_LOCAL.exists():
        local_pred_count = sum(1 for _ in PREDICTIONS_LOCAL.glob("*.json"))

    return {
        "ok": True,
        "n_papers": n,
        "bad_lines": bad_lines,
        "n_organoid_types": len(types),
        "organoid_types": types,
        "avg_grounding_rate": avg_gr,
        "pooled_grounding_rate": pooled_gr,
        "reagents_grounded_total": grounded_sum,
        "reagents_total": total_sum,
        "n_local_predictions": local_pred_count,
    }


def check_analytics_artifacts(artifacts: list[AnalyticsArtifact]) -> list[dict]:
    """Check which analytics artifacts exist and are non-empty."""
    results = []
    for a in artifacts:
        exists = a.path.exists()
        size = a.path.stat().st_size if exists else 0
        ok = exists and size > 10

        record_count = None
        if ok:
            try:
                d = json.loads(a.path.read_text())
                # Heuristic: look for common count fields
                for key in ("total_failure_modes", "n_nodes", "n_total_papers"):
                    if key in d:
                        record_count = d[key]
                        break
            except (json.JSONDecodeError, OSError):
                ok = False

        results.append({
            "name": a.name,
            "path": str(a.path),
            "exists": exists,
            "size_bytes": size,
            "ok": ok,
            "required": a.required,
            "generate_cmd": a.generate_cmd,
            "record_count": record_count,
        })
    return results


def check_consensus_files() -> dict:
    """Check how many consensus_*.json files exist."""
    if not OUTPUTS.exists():
        return {"n_files": 0, "types": []}
    files = sorted(OUTPUTS.glob("consensus_*.json"))
    types = [f.stem.replace("consensus_", "") for f in files]
    return {"n_files": len(files), "types": types}


def check_manifest(manifest_path: Path) -> dict:
    """Cross-check manifest.json against actual protocols.jsonl."""
    if not manifest_path.exists():
        return {"ok": False, "error": "manifest not found"}
    try:
        d = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return {"ok": False, "error": str(e)}

    manifest_n = d.get("n_papers") or d.get("n_protocols")
    return {
        "ok": True,
        "n_papers_manifest": manifest_n,
        "manifest_version": d.get("version") or d.get("schema_version"),
    }


def compute_status(
    corpus: dict,
    artifacts: list[dict],
    consensus: dict,
    manifest: dict,
) -> dict:
    """Combine all checks into a single status dict."""
    missing_required = [a for a in artifacts if a["required"] and not a["ok"]]
    all_ok = corpus["ok"] and len(missing_required) == 0

    return {
        "healthy": all_ok,
        "corpus": corpus,
        "analytics_artifacts": artifacts,
        "consensus_files": consensus,
        "manifest": manifest,
        "missing_required": [a["name"] for a in missing_required],
        "generate_commands_needed": [
            a["generate_cmd"] for a in artifacts if not a["ok"]
        ],
    }


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

_CHECK = "✓"
_CROSS = "✗"
_WARN  = "!"


def _pct(n: int, total: int) -> str:
    if total == 0:
        return "n/a"
    return f"{100*n/total:.0f}%"


def render_text(status: dict) -> str:
    lines = []
    corpus = status["corpus"]
    manifest = status["manifest"]
    consensus = status["consensus_files"]

    lines.append("─" * 60)
    lines.append("  Organoid Protocol Atlas — System Status")
    lines.append("─" * 60)

    if not corpus["ok"]:
        lines.append(f"  {_CROSS} CORPUS: {corpus.get('error', 'unknown error')}")
        lines.append("─" * 60)
        return "\n".join(lines)

    # Corpus block
    n = corpus["n_papers"]
    n_types = corpus["n_organoid_types"]
    avg_gr = corpus.get("avg_grounding_rate")
    pooled = corpus.get("pooled_grounding_rate")
    n_local = corpus.get("n_local_predictions", 0)

    lines.append(f"  CORPUS  ({PROTOCOLS_JSONL.name})")
    lines.append(f"    Papers:          {n}")
    lines.append(f"    Organoid types:  {n_types}")
    if avg_gr is not None:
        lines.append(f"    Avg grounding:   {avg_gr:.1%}  (mean of per-paper rates)")
    if pooled is not None:
        lines.append(f"    Pooled grounding:{pooled:.1%}  ({corpus.get('reagents_grounded_total',0)}/{corpus.get('reagents_total',0)} reagents)")
    if n_local:
        lines.append(f"    Local preds:     {n_local}  (data/predictions/local/, gitignored)")

    manifest_n = manifest.get("n_papers_manifest")
    if manifest_n is not None and manifest_n != n:
        lines.append(f"  {_WARN} manifest.json says {manifest_n} papers but protocols.jsonl has {n}")

    lines.append("")

    # Analytics artifacts block
    lines.append("  ANALYTICS OUTPUTS  (outputs/analysis/)")
    for a in status["analytics_artifacts"]:
        icon = _CHECK if a["ok"] else _CROSS
        extra = f"  [{a['record_count']} records]" if a.get("record_count") is not None else ""
        lines.append(f"    {icon} {a['name']:<30s}{extra}")
        if not a["ok"]:
            lines.append(f"        → Run: {a['generate_cmd']}")

    # Consensus sub-block
    cn = consensus["n_files"]
    ctypes = consensus["types"]
    icon = _CHECK if cn > 0 else _CROSS
    lines.append(f"    {icon} consensus files             [{cn} types: {', '.join(ctypes[:4])}{'…' if len(ctypes)>4 else ''}]")
    if cn == 0:
        lines.append(f"        → Run: python pipeline/compute_consensus.py --all")

    lines.append("")

    # Overall
    healthy = status["healthy"] and cn > 0
    lines.append("─" * 60)
    if healthy:
        lines.append(f"  {_CHECK} All systems OK")
    else:
        missing = status["missing_required"] + (["consensus_files"] if cn == 0 else [])
        lines.append(f"  {_CROSS} {len(missing)} item(s) need generation:")
        for cmd in status["generate_commands_needed"]:
            lines.append(f"      {cmd}")
        if cn == 0:
            lines.append(f"      python pipeline/compute_consensus.py --all")

    lines.append("─" * 60)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="System status for organoid-protocol-atlas")
    ap.add_argument("--json", action="store_true", help="Output JSON instead of text")
    ap.add_argument("--quiet", "-q", action="store_true",
                    help="Minimal output — exit code only (0=healthy, 1=issues)")
    args = ap.parse_args()

    corpus = check_corpus(PROTOCOLS_JSONL)
    artifacts = check_analytics_artifacts(ANALYTICS_ARTIFACTS)
    consensus = check_consensus_files()
    manifest = check_manifest(MANIFEST)
    status = compute_status(corpus, artifacts, consensus, manifest)

    if args.json:
        print(json.dumps(status, indent=2))
    elif not args.quiet:
        print(render_text(status))

    healthy = status["healthy"] and consensus["n_files"] > 0
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
