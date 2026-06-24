#!/usr/bin/env python3
"""
protocols.io ingester — pull organoid PROTOCOLS (the dedicated protocol repository)
into the same pipeline as journal/preprint papers.

protocols.io is a large repository of step-by-step experimental protocols — exactly the
"protocol lives here" source the journal corpus under-covers. Its v3 REST API exposes
public protocols (steps + materials) as JSON. We search organoid protocols, fetch each
full record, synthesize a methods_text from its steps + materials, and write a
tier1-ready evidence bundle so the SAME extractor produces an OrganoidProtocol.

AUTH (read-only, public data): a "client access token" from
https://www.protocols.io/developers (Client access without OAuth). Provide it via:
  - env  PROTOCOLS_IO_TOKEN, or
  - a gitignored file  ~/.protocols_io_token  or  /atb-data/rye/.protocols_io_token
NO token -> prints how-to and exits 0 (clean no-op). The token is a secret: never
commit it; rotate (REFRESH on the dev page) if it leaks.

Output (mirrors tier0/biorxiv): bundles data/evidence_bundles/local/PROTOCOLSIO_<id>.json,
candidates data/corpus/incoming/organoid_corpus_candidates_protocols_io.csv,
summary outputs/ingest/protocols_io_ingest_summary.json. Resumable. Network-only. Run:
  python pipeline/fetch_protocols_io.py                 # default organoid query
  python pipeline/fetch_protocols_io.py --query "intestinal organoid" --limit 50
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUNDLES = REPO / "data" / "evidence_bundles" / "local"
CAND = REPO / "data" / "corpus" / "incoming" / "organoid_corpus_candidates_protocols_io.csv"
OUT = REPO / "outputs" / "ingest" / "protocols_io_ingest_summary.json"
API = "https://www.protocols.io/api/v3"

CAND_COLS = ["organoid_type", "doi", "pmcid", "first_author", "year", "journal", "species",
             "source_cell_type", "license", "has_methods", "has_supplement", "gold_candidate",
             "flags", "notes", "pmid", "title", "cited_by", "in_current_corpus"]
TOKEN_FILES = [Path.home() / ".protocols_io_token", Path("/atb-data/rye/.protocols_io_token")]


def load_token() -> str | None:
    if os.environ.get("PROTOCOLS_IO_TOKEN"):
        return os.environ["PROTOCOLS_IO_TOKEN"].strip()
    for f in TOKEN_FILES:
        try:
            if f.exists():
                t = f.read_text().strip()
                if t:
                    return t
        except Exception:  # noqa: BLE001
            pass
    return None


def api_get(path: str, token: str, params: dict | None = None, tries: int = 4) -> dict:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "organoid-protocol-atlas/1.0 (academic research)"})
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(req, timeout=40))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            code = getattr(e, "code", None)
            if code in (401, 403):
                raise RuntimeError(f"auth rejected ({code}) — token invalid/expired; REFRESH it") from e
            if code is not None and 400 <= code < 500 and code != 429:
                raise
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"unreachable: {url}")


def methods_from_protocol(p: dict) -> str:
    """Synthesize a methods_text from a protocol's materials + ordered steps."""
    parts = []
    mats = p.get("materials") or []
    if mats:
        parts.append("[MATERIALS] " + "; ".join(
            (m.get("name") or "").strip() for m in mats if m.get("name")))
    for i, st in enumerate(p.get("steps") or [], 1):
        # a step's text lives in components (type 1 = description) or a 'title'
        txt = ""
        for c in (st.get("components") or []):
            src = c.get("source") or {}
            if isinstance(src, dict) and src.get("body"):
                txt += " " + src["body"]
        txt = (txt or st.get("title") or "").strip()
        if txt:
            parts.append(f"[STEP {i}] {txt}")
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--query", default="organoid")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--page-size", type=int, default=50)
    args = ap.parse_args()

    token = load_token()
    if not token:
        print("protocols.io: NO TOKEN — skipping (clean no-op).\n"
              "  Get a 'client access token' at https://www.protocols.io/developers\n"
              "  then: export PROTOCOLS_IO_TOKEN=... (or write it to ~/.protocols_io_token)\n"
              "  Re-run; the ingester will then fetch public organoid protocols.", flush=True)
        return 0

    BUNDLES.mkdir(parents=True, exist_ok=True)
    CAND.parent.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in BUNDLES.glob("PROTOCOLSIO_*.json")}
    print(f"protocols.io ingest query={args.query!r} (existing: {len(existing)})", flush=True)

    new_rows, n_seen, n_new, n_skip, n_thin, n_fail = [], 0, 0, 0, 0, 0
    page = 1
    while n_seen < args.limit:
        try:
            res = api_get("/protocols", token, {"filter": "public", "key": args.query,
                                                "page_size": args.page_size, "page_id": page})
        except RuntimeError as e:
            print(f"  [stop] {e}", flush=True)
            break
        items = res.get("items") or []
        if not items:
            break
        for it in items:
            n_seen += 1
            pid = it.get("id")
            key = f"PROTOCOLSIO_{pid}"
            if key in existing:
                n_skip += 1
                continue
            try:
                full = api_get(f"/protocols/{pid}", token).get("protocol") or it
                methods = methods_from_protocol(full)
            except Exception as e:  # noqa: BLE001
                print(f"  [fail] {key}: {type(e).__name__}: {e}", flush=True)
                n_fail += 1
                continue
            if len(methods) < 400:
                n_thin += 1
                continue
            doi = full.get("doi") or it.get("doi") or ""
            uri = full.get("uri") or it.get("uri") or ""
            title = (full.get("title") or it.get("title") or "").strip()
            lic = "CC-BY"  # protocols.io public protocols are CC-BY by default
            bundle = {"doi": doi, "pmcid": key, "organoid_type": "", "license": lic,
                      "source_route": "protocols_io", "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "methods_text": methods, "body_text": methods, "methods_detected": True,
                      "body_chars": len(methods), "supplementary_text": "", "supplementary_files": [],
                      "figures": [], "tables": [], "section_titles": [], "warnings": []}
            (BUNDLES / f"{key}.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2))
            n_new += 1
            new_rows.append({c: "" for c in CAND_COLS} | {
                "organoid_type": "", "doi": doi, "pmcid": key, "license": lic,
                "year": str(full.get("created_on", "") or "")[:4], "journal": "protocols.io",
                "has_methods": "1", "has_supplement": "0", "title": title,
                "notes": f"protocols.io ingest {uri}", "in_current_corpus": "0",
            })
            if n_seen >= args.limit:
                break
        page += 1
        time.sleep(0.3)

    if new_rows:
        new = not CAND.exists()
        with CAND.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CAND_COLS)
            if new:
                w.writeheader()
            w.writerows(new_rows)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query": args.query, "seen": n_seen, "new_bundles": n_new, "skipped_existing": n_skip,
        "thin": n_thin, "failed": n_fail, "candidates_csv": str(CAND.relative_to(REPO))}, indent=2))
    print(f"\nprotocols.io: {n_seen} seen | {n_new} new bundles | {n_skip} skipped | {n_thin} thin | {n_fail} fail\n"
          f"-> bundles {BUNDLES.relative_to(REPO)}; candidates {CAND.relative_to(REPO)}\n"
          f"   next: tier1 extract the PROTOCOLSIO_* keys, then QC into corpus.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
