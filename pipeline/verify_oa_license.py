#!/usr/bin/env python3
"""
OA/license verification step (issue #14 step 2).

Queries the Europe PMC REST API to confirm each candidate's license, caching
every response as a fixture in data/corpus/oa_cache/ so tests run offline.
Writes a verification manifest to data/corpus/oa_verified/oa_results.json.

License decision logic:
  public_ok = CC0 or CC-BY (incl. CC-BY-SA) with no NC or ND
  rejected   = NC/ND, author-manuscript, unknown, not OA
  quarantine = API error / timeout (re-check before ingestion)

Run:  python pipeline/verify_oa_license.py [--pool PATH] [--offline] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "data" / "corpus" / "oa_cache"
OUT_DIR = REPO / "data" / "corpus" / "oa_verified"
DEFAULT_POOL = REPO / "data" / "corpus" / "incoming" / "organoid_corpus_candidates_180.csv"
EPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def _cache_path(pmcid: str) -> Path:
    return CACHE / f"{pmcid}.json"


def _normalize_license(raw: str | None) -> str:
    """Return a canonical license token or 'unknown'."""
    s = (raw or "").strip().upper().replace(" ", "-").replace("_", "-")
    if not s:
        return "unknown"
    # CC0
    if s.startswith("CC0") or s == "CC-ZERO":
        return "CC0"
    # CC-BY variants
    m = re.match(r"CC-BY(-SA)?(-[0-9.]+)?$", s)
    if m:
        return "CC-BY"
    if "CC-BY-NC-ND" in s:
        return "CC-BY-NC-ND"
    if "CC-BY-NC" in s:
        return "CC-BY-NC"
    if "CC-BY-ND" in s:
        return "CC-BY-ND"
    if "CC-BY-SA" in s:
        return "CC-BY"
    if s.startswith("CC-BY"):
        return "CC-BY"
    if "AUTHOR" in s or "MANUSCRIPT" in s or "NIHMS" in s:
        return "author-manuscript"
    return "unknown"


def is_public_ok(license_token: str) -> bool:
    return license_token in ("CC0", "CC-BY")


def fetch_epmc_license(pmcid: str, offline: bool = False) -> dict:
    """Return cached fixture or live Europe PMC response for one PMCID.
    Returns dict with keys: pmcid, license_raw, license, source, verified."""
    cp = _cache_path(pmcid)
    if cp.exists():
        return json.loads(cp.read_text())
    if offline:
        return {"pmcid": pmcid, "license_raw": None, "license": "unknown",
                "source": "cache_miss", "verified": False}
    # Live query
    params = {"query": f"PMCID:{pmcid}", "resultType": "core", "format": "json",
               "pageSize": "1"}
    url = f"{EPMC_URL}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        hits = (data.get("resultList") or {}).get("result") or []
        if not hits:
            result = {"pmcid": pmcid, "license_raw": None, "license": "unknown",
                      "source": "epmc_no_hit", "verified": True}
        else:
            h = hits[0]
            raw = h.get("license") or h.get("journalInfo", {}).get("journal", {}).get("nlmta")
            raw = h.get("license") or None
            result = {
                "pmcid": pmcid,
                "license_raw": raw,
                "license": _normalize_license(raw),
                "source": "epmc",
                "verified": True,
                "title": h.get("title", "")[:200],
                "journal": (h.get("journalInfo") or {}).get("journal", {}).get("title", ""),
                "doi": h.get("doi", ""),
            }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        result = {"pmcid": pmcid, "license_raw": None, "license": "unknown",
                  "source": f"error:{exc!r}", "verified": False}
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def verify_pool(pool_path: Path, offline: bool = False,
                limit: int = 0, sleep: float = 0.5) -> list[dict]:
    """Verify all candidates in pool_path. Returns list of result dicts."""
    rows = list(csv.DictReader(pool_path.open(encoding="utf-8-sig")))
    if limit:
        rows = rows[:limit]
    results = []
    for i, row in enumerate(rows):
        pmcid = row.get("pmcid", "").strip()
        candidate_license = row.get("license", "").strip()
        if not pmcid:
            continue
        api_result = fetch_epmc_license(pmcid, offline=offline)
        verdict = "public_ok" if is_public_ok(api_result["license"]) else \
                  "quarantine" if not api_result["verified"] else "rejected"
        results.append({
            "pmcid": pmcid,
            "doi": row.get("doi", "").strip(),
            "organoid_type": row.get("organoid_type", "").strip(),
            "candidate_license": _normalize_license(candidate_license),
            "verified_license": api_result["license"],
            "verified_license_raw": api_result.get("license_raw"),
            "license_match": _normalize_license(candidate_license) == api_result["license"],
            "verdict": verdict,
            "public_ok": is_public_ok(api_result["license"]),
            "source": api_result["source"],
            "title": api_result.get("title", ""),
            "journal": api_result.get("journal", ""),
        })
        if not offline and i < len(rows) - 1:
            time.sleep(sleep)
    return results


def write_manifest(results: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    public = [r for r in results if r["public_ok"]]
    rejected = [r for r in results if r["verdict"] == "rejected"]
    quarantine = [r for r in results if r["verdict"] == "quarantine"]
    mismatches = [r for r in results if not r["license_match"]]
    manifest = {
        "pool_size": len(results),
        "public_ok": len(public),
        "rejected": len(rejected),
        "quarantine": len(quarantine),
        "license_mismatches": len(mismatches),
        "public_pmcids": sorted(r["pmcid"] for r in public),
        "rejected_pmcids": [{"pmcid": r["pmcid"], "reason": r["verified_license"]}
                            for r in rejected],
        "quarantine_pmcids": [r["pmcid"] for r in quarantine],
        "mismatch_details": [{"pmcid": r["pmcid"],
                               "candidate": r["candidate_license"],
                               "verified": r["verified_license"]}
                             for r in mismatches],
    }
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"Wrote {out_path}")
    print(f"  public_ok={len(public)}  rejected={len(rejected)}  "
          f"quarantine={len(quarantine)}  mismatches={len(mismatches)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pool", default=str(DEFAULT_POOL),
                    help="candidate pool CSV (default: candidates_180.csv)")
    ap.add_argument("--offline", action="store_true",
                    help="cache-only, no network (fails if no fixture)")
    ap.add_argument("--limit", type=int, default=0,
                    help="verify only first N rows (0 = all)")
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="politeness delay between API calls (default 0.5s)")
    ap.add_argument("--out", default=str(OUT_DIR / "oa_results.json"),
                    help="output manifest path")
    args = ap.parse_args()
    results = verify_pool(Path(args.pool), offline=args.offline,
                          limit=args.limit, sleep=args.sleep)
    write_manifest(results, Path(args.out))


if __name__ == "__main__":
    main()
