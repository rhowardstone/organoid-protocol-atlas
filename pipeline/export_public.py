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

# Evidence snippet cap: keeps quotes readable as attribution context without
# redistributing full method-step paragraphs. Aligns with llms.txt policy
# ("does not redistribute full methods text"). KGX uses 300; public UI gets
# slightly more context at 500.
PUBLIC_SNIPPET_MAX = 500

# Public-export schema version. Bump on a breaking change to the JSONL/manifest shape
# so deploy consumers can detect it (deploy contract pins this).
SCHEMA_VERSION = "0.4"

# organoid_type label normalization applied at export time so the public data is
# canonical regardless of upstream labels (e.g. a stray "hepatic" -> "liver"). Keeps
# the manifest n_types and the no-hepatic deploy contract self-consistent without a
# separate hand-run relabel step.
TYPE_ALIASES = {"hepatic": "liver", "hepatobiliary": "liver"}


def canon_type(t: str | None) -> str | None:
    if not t:
        return t
    return TYPE_ALIASES.get(t.strip().lower(), t)


def is_public_license(license: str | None) -> bool:
    """Public-redistributable iff CC0 or CC-BY (incl. -SA) and NOT NonCommercial (NC)
    or NoDerivatives (ND). Excludes author-manuscript / unknown / CC-BY-NC /
    CC-BY-NC-ND / CC-BY-ND. (NC/ND content isn't freely redistributable for a public
    Translator resource; ND also forbids the KG derivative.) Per codex PR #24 finding 2."""
    s = (license or "").upper().strip().replace(" ", "-").replace("_", "-")
    if "NC" in s or "ND" in s:
        return False
    return s.startswith("CC-BY") or s.startswith("CC0")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cc = sorted({r["pmcid"] for r in conn.execute("SELECT pmcid, license FROM protocols")
                 if is_public_license(r["license"])})
    ph = ",".join("?" * len(cc))
    manifest = {"schema_version": SCHEMA_VERSION,
                "license_filter": "CC0/CC-BY (no NC/ND)", "n_papers": len(cc),
                "papers": sorted(cc), "tables": {}}
    types: set[str] = set()
    for t in TABLES:
        rows = conn.execute(f"SELECT * FROM {t} WHERE pmcid IN ({ph})", cc).fetchall()
        with open(OUT / f"{t}.jsonl", "w") as f:
            for r in rows:
                row = {k: r[k] for k in r.keys()}
                if "organoid_type" in row:
                    row["organoid_type"] = canon_type(row["organoid_type"])
                    if t == "protocols" and row["organoid_type"]:
                        types.add(row["organoid_type"])
                eq = row.get("evidence_quote")
                if eq and len(eq) > PUBLIC_SNIPPET_MAX:
                    row["evidence_quote"] = eq[:PUBLIC_SNIPPET_MAX]
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        manifest["tables"][t] = len(rows)
        print(f"  {t}: {len(rows)} rows")
    manifest["n_types"] = len(types)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"exported CC-only public subset ({len(cc)} papers, {len(types)} types) -> {OUT}")


if __name__ == "__main__":
    main()
