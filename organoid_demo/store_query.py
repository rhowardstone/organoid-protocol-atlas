"""
Store + query
=============
A thin SQLite store for extracted protocols and one grounded comparison query.
This stands in for craig/literature/knowledge_graph/storage.py. On port, the
protocols become typed nodes in your existing KG instead of JSON blobs, and the
comparison query becomes a graph traversal. The point it proves now: protocol
knowledge is queryable AND every answer cell carries a citation.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

from schema import OrganoidProtocol


class ProtocolStore:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS protocols "
            "(doi TEXT PRIMARY KEY, organoid_type TEXT, payload TEXT)"
        )

    def add(self, proto: OrganoidProtocol) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO protocols VALUES (?, ?, ?)",
            (proto.source_doi, proto.organoid_type.value, proto.model_dump_json()),
        )
        self.conn.commit()

    def all(self) -> list[OrganoidProtocol]:
        rows = self.conn.execute("SELECT payload FROM protocols").fetchall()
        return [OrganoidProtocol.model_validate_json(r[0]) for r in rows]

    def signaling_comparison(self) -> dict:
        """
        'How do these protocols differ in signaling factors?' — answered with
        provenance. Each reported reagent comes with the source DOI and the
        verbatim span it was grounded in.
        """
        result = {}
        for proto in self.all():
            factors = []
            for r in proto.signaling_factors:
                conc = ""
                if r.concentration and r.concentration.value is not None:
                    conc = f" @ {r.concentration.value} {r.concentration.canonical_unit or r.concentration.unit or ''}".strip()
                cite = ""
                if r.evidence:
                    cite = f"[{r.evidence.source_doi}] \"{r.evidence.quote[:60]}...\""
                factors.append({
                    "reagent": r.name, "role": r.role,
                    "concentration": conc.strip(), "citation": cite,
                })
            result[proto.organoid_type.value] = {"doi": proto.source_doi, "factors": factors}
        return result
