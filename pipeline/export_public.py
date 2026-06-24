#!/usr/bin/env python3
"""
Export a LICENSE-SAFE public subset of the knowledge graph as committed JSONL.

Only open-access (CC-licensed) PMC papers are included, so the exported text — including
the full `sources` methods text used by the in-context evidence highlighter — is
redistributable. Author-manuscript / unknown-license papers and non-PMC sources (bioRxiv,
protocols.io) stay LOCAL-ONLY and are never exported here.

These JSONL files are committed and are the seed the public Datasette image builds
its DB from (so we never commit a generated .db, and a clean clone can build the
public KG offline — closes the clean-clone gap).

Run:  python pipeline/export_public.py   ->  exports/public/{protocols,reagents,sources}.jsonl

Gate logic (all three must pass):
  1. pmcid starts with "PMC"     — standard PubMed Central ID, resolvable URL, known schema
  2. is_public_license(license)  — CC0 or CC-BY without NC/ND restriction
  3. organoid_type not None and not 'other'  — ingest must have resolved the type
"""

from __future__ import annotations

import datetime
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

# Evidence snippet cap: keeps quotes readable as attribution context without
# redistributing full method-step paragraphs. Aligns with llms.txt policy
# ("does not redistribute full methods text"). KGX uses 300; public UI gets
# slightly more context at 500.
PUBLIC_SNIPPET_MAX = 500


def is_public_license(license: str | None) -> bool:
    """Public-redistributable iff CC0 or CC-BY (incl. -SA) without NC or ND.

    Normalises variant spellings (underscores, spaces, case) before matching.
    CC0_NG ("no guarantee") is treated as CC0 — the NG suffix is a bioRxiv
    metadata artefact, not a usage restriction.

    Excluded: author-manuscript, unknown, CC-BY-NC*, CC-BY-ND*, CC-BY-NC-ND*,
    and any license string that doesn't begin with CC0 or CC-BY after normalisation.
    """
    if not license:
        return False
    s = license.upper().strip().replace(" ", "-").replace("_", "-")
    # Strip trailing "-NG" (bioRxiv "no guarantee" artefact) before NC/ND check
    s = s.removesuffix("-NG")
    if "NC" in s or "ND" in s:
        return False
    return s.startswith("CC-BY") or s.startswith("CC0")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # Three-gate filter: PMC ID + public license + resolved organoid_type
    rows_meta = conn.execute(
        "SELECT pmcid, license, organoid_type FROM protocols"
    ).fetchall()
    cc = sorted(
        r["pmcid"] for r in rows_meta
        if r["pmcid"] and r["pmcid"].startswith("PMC")
        and is_public_license(r["license"])
        and r["organoid_type"] and r["organoid_type"] != "other"
    )

    ph = ",".join("?" * len(cc))
    n_types = len({r["organoid_type"] for r in
                   conn.execute(
                       "SELECT organoid_type FROM protocols WHERE pmcid IN ({})".format(ph), cc
                   )
                   if r["organoid_type"]})
    manifest = {
        "license_filter": "CC0/CC-BY (no NC/ND), PMC-ID-only, organoid_type resolved",
        "schema_version": "0.5",
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "n_papers": len(cc),
        "n_types": n_types,
        "papers": sorted(cc),
        "tables": {},
    }
    for t in TABLES:
        rows = conn.execute(f"SELECT * FROM {t} WHERE pmcid IN ({ph})", cc).fetchall()
        with open(OUT / f"{t}.jsonl", "w") as f:
            for r in rows:
                row = {k: r[k] for k in r.keys()}
                eq = row.get("evidence_quote")
                if eq and len(eq) > PUBLIC_SNIPPET_MAX:
                    row["evidence_quote"] = eq[:PUBLIC_SNIPPET_MAX]
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        manifest["tables"][t] = len(rows)
        print(f"  {t}: {len(rows)} rows")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"exported CC-only PMC-only public subset ({len(cc)} papers, {n_types} types) -> {OUT}")


if __name__ == "__main__":
    main()
