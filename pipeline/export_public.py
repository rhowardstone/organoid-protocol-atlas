#!/usr/bin/env python3
"""
Export a LICENSE-SAFE public subset of the knowledge graph as committed JSONL.

Only open-access (CC-licensed) papers are included, so the exported text — including
the full `sources` methods text used by the in-context evidence highlighter — is
redistributable. Author-manuscript / unknown-license papers stay LOCAL-ONLY and are
never exported here.

These JSONL files are committed and are the seed the public Datasette image builds
its DB from (so we never commit a generated .db, and a clean clone can build the
public KG offline — closes the clean-clone gap).

Run:  python pipeline/export_public.py   ->  exports/public/{protocols,reagents,sources}.jsonl
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "kg" / "atlas.db"
OUT = REPO / "exports" / "public"
# protocols + reagents only. We deliberately do NOT export `sources` (full methods
# text) to the public build — even for CC papers — to respect the no-full-text-bodies
# gate. reagents carry SHORT single-sentence evidence snippets (the project's existing
# citation-snippet policy); the in-context highlighter is simply absent in public.
TABLES = ("protocols", "reagents")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cc = [r[0] for r in conn.execute(
        "SELECT pmcid FROM protocols WHERE license LIKE 'CC%'")]
    ph = ",".join("?" * len(cc))
    manifest = {"license_filter": "CC*", "n_papers": len(cc), "papers": sorted(cc), "tables": {}}
    for t in TABLES:
        rows = conn.execute(f"SELECT * FROM {t} WHERE pmcid IN ({ph})", cc).fetchall()
        with open(OUT / f"{t}.jsonl", "w") as f:
            for r in rows:
                f.write(json.dumps({k: r[k] for k in r.keys()}, ensure_ascii=False) + "\n")
        manifest["tables"][t] = len(rows)
        print(f"  {t}: {len(rows)} rows")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"exported CC-only public subset ({len(cc)} papers) -> {OUT}")


if __name__ == "__main__":
    main()
