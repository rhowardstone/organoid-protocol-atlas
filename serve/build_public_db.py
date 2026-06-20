#!/usr/bin/env python3
"""
Build the public Datasette DB from the committed license-safe JSONL exports.

Runs at image build / container start (the .db itself is never committed — gate
rule). Reuses the exact KG schema from pipeline/build_kg.py so the Datasette
metadata, templates, and FTS work unchanged.

Run:  python serve/build_public_db.py   ->  data/kg/atlas_public.db
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
from build_kg import SCHEMA  # noqa: E402 — single source of truth for the KG schema

# Basename MUST be atlas.db so Datasette serves it as the "atlas" database that
# serve/metadata.yaml, the templates, and the ask plugin all reference. Kept in a
# separate dir so it never clobbers the local full data/kg/atlas.db.
EXPORTS = REPO / "exports" / "public"
DB = REPO / "data" / "public" / "atlas.db"


def main():
    if not (EXPORTS / "protocols.jsonl").exists():
        raise SystemExit(f"missing exports at {EXPORTS}; run pipeline/export_public.py first")
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    for t in ("protocols", "reagents"):   # no `sources` table in the public build
        rows = [json.loads(l) for l in (EXPORTS / f"{t}.jsonl").read_text().splitlines() if l.strip()]
        for r in rows:
            cols = ",".join(r.keys())
            ph = ",".join("?" * len(r))
            conn.execute(f"INSERT INTO {t} ({cols}) VALUES ({ph})", list(r.values()))
        print(f"  {t}: {len(rows)} rows")
    conn.execute("INSERT INTO reagents_fts(reagents_fts) VALUES ('optimize')")
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM protocols").fetchone()[0]
    conn.close()
    print(f"built {DB} ({n} public protocols)")


if __name__ == "__main__":
    main()
