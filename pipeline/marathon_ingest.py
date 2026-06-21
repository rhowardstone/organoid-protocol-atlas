#!/usr/bin/env python3
"""
Marathon driver for large-scale QC-gated ingestion of a candidate pool.

The orchestrator (ingest_orchestrator.py) extracts a whole --limit batch in memory
and writes the corpus append + bundles only AFTER the worker pool drains, so a single
huge run is all-or-nothing (a crash loses hours) and re-running re-processes the same
QC-rejected papers forever (rejects never enter the corpus, so they are re-selected).

This driver fixes both for a marathon:
  * slices the pool into fixed CHUNKS and runs the orchestrator once per chunk, so each
    chunk's accepted papers are committed to corpus.tsv atomically (~tens of minutes of
    loss at worst on a crash);
  * advances a checkpoint offset past every chunk (accepted AND rejected), so each
    candidate is processed exactly once;
  * resumes from the checkpoint on restart.

Public-first: by default keeps only CC0/CC-BY candidates (servable) and orders newest
first. The orchestrator still applies the real QC gate (signaling + grounding) per paper.

Run (background):
  python pipeline/marathon_ingest.py \
    --candidates data/corpus/incoming/organoid_corpus_candidates_mega.csv \
    --chunk 400 --workers 4 --min-grounding 0.5
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CKPT = REPO / "outputs" / "ingest" / "marathon_checkpoint.json"
PROGRESS = REPO / "outputs" / "ingest" / "marathon_progress.json"
PUBLIC_LICENSES = {"CC0", "CC-BY"}


def load_pool(path: Path, cc_only: bool) -> list[dict]:
    rows = list(csv.DictReader(open(path)))
    if cc_only:
        rows = [r for r in rows if (r.get("license") or "").strip() in PUBLIC_LICENSES]

    def year_key(r):
        y = (r.get("year") or "").strip()[:4]
        return int(y) if y.isdigit() else 0

    rows.sort(key=year_key, reverse=True)   # newest first (better protocol-era papers)
    return rows


def write_slice(rows: list[dict], header: list[str], out: Path) -> None:
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def run_chunk(slice_path: Path, chunk: int, workers: int, min_grounding: float) -> dict:
    """Run the orchestrator on one slice; return the parsed batch report (or {} on error)."""
    cmd = [sys.executable, str(REPO / "pipeline" / "ingest_orchestrator.py"),
           "--candidates", str(slice_path), "--limit", str(chunk),
           "--workers", str(workers), "--min-grounding", str(min_grounding), "--cc-only"]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    # the orchestrator prints "... -> outputs/ingest/batch_*.json" on its last line
    report_path = None
    for line in proc.stdout.splitlines():
        if "batch_" in line and ".json" in line:
            report_path = line.split("->")[-1].strip()
    sys.stdout.write(proc.stdout[-2000:])
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-2000:])
        return {"error": f"orchestrator rc={proc.returncode}"}
    if report_path and (REPO / report_path).exists():
        return json.loads((REPO / report_path).read_text())
    return {}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--chunk", type=int, default=400)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--min-grounding", type=float, default=0.5)
    ap.add_argument("--cc-only", action="store_true", default=True)
    ap.add_argument("--all-licenses", dest="cc_only", action="store_false")
    ap.add_argument("--max-chunks", type=int, default=0, help="0 = until pool exhausted")
    ap.add_argument("--reset", action="store_true", help="ignore checkpoint, start at 0")
    args = ap.parse_args()

    header = list(csv.DictReader(open(args.candidates)).fieldnames or [])
    pool = load_pool(args.candidates, args.cc_only)
    offset = 0
    if CKPT.exists() and not args.reset:
        offset = json.loads(CKPT.read_text()).get("offset", 0)
    print(f"pool={len(pool)} (cc_only={args.cc_only})  start_offset={offset}  "
          f"chunk={args.chunk}  workers={args.workers}", flush=True)

    slice_path = REPO / "outputs" / "ingest" / "_marathon_slice.csv"
    slice_path.parent.mkdir(parents=True, exist_ok=True)
    totals = {"considered": 0, "accepted": 0, "rejected": 0, "chunks": 0}
    chunk_no = 0
    while offset < len(pool):
        if args.max_chunks and chunk_no >= args.max_chunks:
            print(f"reached --max-chunks {args.max_chunks}", flush=True)
            break
        rows = pool[offset:offset + args.chunk]
        write_slice(rows, header, slice_path)
        rep = run_chunk(slice_path, args.chunk, args.workers, args.min_grounding)
        acc = rep.get("accepted", 0) or 0
        rej = rep.get("rejected", 0) or 0
        con = rep.get("candidates_considered", len(rows)) or len(rows)
        totals["accepted"] += acc
        totals["rejected"] += rej
        totals["considered"] += con
        totals["chunks"] += 1
        offset += len(rows)
        chunk_no += 1
        CKPT.write_text(json.dumps({"offset": offset, "pool_size": len(pool)}, indent=2))
        PROGRESS.write_text(json.dumps({
            **totals,
            "offset": offset,
            "pool_size": len(pool),
            "accept_rate": round(totals["accepted"] / totals["considered"], 3)
                           if totals["considered"] else None,
            "candidates": str(args.candidates),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, indent=2))
        print(f"[chunk {chunk_no}] offset={offset}/{len(pool)}  "
              f"+{acc} accepted / {rej} rejected  "
              f"(cumulative {totals['accepted']} accepted)", flush=True)

    print(f"\nMARATHON done: {totals['accepted']} accepted / {totals['rejected']} rejected "
          f"over {totals['chunks']} chunks (offset {offset}/{len(pool)})", flush=True)


if __name__ == "__main__":
    main()
