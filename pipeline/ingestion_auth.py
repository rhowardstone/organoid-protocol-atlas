#!/usr/bin/env python3
"""
Ingestion Authorization Gate (R4) — classify candidates before ingestion.

Classifies each candidate dict (from discover_candidates or hybrid_discover output)
into one of three authorization states:

  auto_ingest      — safe to run through Tier-1 extraction automatically
  review_required  — flag for human review before ingestion
  blocked          — do not ingest (hard rules violated)

All classification logic is pure (no network I/O), fully unit-testable offline.

Run:
    python pipeline/ingestion_auth.py
    python pipeline/ingestion_auth.py --candidates data/corpus/incoming/candidates.csv
    python pipeline/ingestion_auth.py --corpus data/corpus/corpus.tsv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
from discover_candidates import TYPE_QUERIES  # noqa: E402

CORPUS = REPO / "data" / "corpus" / "corpus.tsv"
CANDIDATES_DEFAULT = REPO / "data" / "corpus" / "incoming" / "organoid_corpus_candidates_generated.csv"
OUT = REPO / "outputs" / "ingestion" / "auth_report.json"

# License strings that are considered public (CC-BY variants without NC/ND, and CC0).
# Everything else (NC, ND, unknown, author-manuscript, etc.) is NOT public.
_PUBLIC_PREFIXES = ("cc-by", "cc0", "cc by", "ccby")
_BLOCKED_SUBSTRINGS = ("nc", "nd", "unknown", "author-manuscript", "author manuscript")


def is_public_license(lic: str | None) -> bool:
    """Returns True only for CC-BY (without NC/ND) and CC0.

    CC-BY-SA is considered public (share-alike only).
    CC-BY-NC, CC-BY-ND, author-manuscript, unknown, and empty are NOT public.
    """
    if not lic:
        return False
    normalized = lic.strip().lower().replace("_", "-").replace(" ", "-")
    # Must start with a known public prefix
    is_cc_family = any(normalized.startswith(p.replace(" ", "-")) for p in _PUBLIC_PREFIXES)
    if not is_cc_family:
        return False
    # Must not contain NC or ND modifiers
    parts = set(normalized.split("-"))
    if "nc" in parts or "nd" in parts:
        return False
    return True


def _normalize_pmcid(pmcid: str) -> str:
    return (pmcid or "").strip().upper()


def _normalize_doi(doi: str) -> str:
    return (doi or "").strip().lower()


def classify(candidate: dict, existing_pmcids: set, existing_dois: set) -> tuple[str, str]:
    """Classify one candidate into an authorization state.

    Returns (decision, reason) where decision is one of:
      'blocked' | 'review_required' | 'auto_ingest'
    and reason is a short descriptive string.

    Precedence: blocked checks run first, then review_required, then auto_ingest.
    """
    pmcid = _normalize_pmcid(candidate.get("pmcid", ""))
    doi = _normalize_doi(candidate.get("doi", ""))
    lic = candidate.get("license")

    # --- BLOCKED checks (hard rules) ---

    # 1. Empty pmcid
    if not pmcid:
        return "blocked", "pmcid=empty"

    # 2. Non-public license
    if not is_public_license(lic):
        return "blocked", f"license={lic!r}"

    # 3. Already in corpus by pmcid
    norm_existing_pmcids = {_normalize_pmcid(p) for p in existing_pmcids}
    if pmcid in norm_existing_pmcids:
        return "blocked", f"already_in_corpus:pmcid={pmcid}"

    # 4. Already in corpus by doi
    norm_existing_dois = {_normalize_doi(d) for d in existing_dois}
    if doi and doi in norm_existing_dois:
        return "blocked", f"already_in_corpus:doi={doi}"

    # 5. Tier3 without human confirmation
    if candidate.get("tier") == "tier3" and candidate.get("human_confirmed") is not True:
        return "blocked", "tier3:no_human_confirmation"

    # --- REVIEW_REQUIRED checks ---

    # 6. Low semantic relevance score
    sem_score = candidate.get("sem_score")
    if sem_score is not None:
        try:
            if float(sem_score) < 0.3:
                return "review_required", f"sem_score={sem_score}<0.3"
        except (TypeError, ValueError):
            pass

    # 7. Low grounding rate (post-extraction signal)
    grounding_rate = candidate.get("grounding_rate")
    if grounding_rate is not None:
        try:
            if float(grounding_rate) < 0.4:
                return "review_required", f"grounding_rate={grounding_rate}<0.4"
        except (TypeError, ValueError):
            pass

    # 8. Unknown organoid type
    organoid_type = candidate.get("organoid_type")
    if organoid_type not in TYPE_QUERIES:
        return "review_required", f"organoid_type={organoid_type!r}:not_in_known_types"

    # 9. No methods section
    if candidate.get("has_methods") != "yes":
        return "review_required", f"has_methods={candidate.get('has_methods')!r}"

    # --- AUTO_INGEST ---
    return "auto_ingest", "all_checks_passed"


def classify_batch(
    candidates: list[dict],
    existing_pmcids: set,
    existing_dois: set,
) -> list[dict]:
    """Classify a batch of candidates, adding 'auth_decision' and 'auth_reason' to each.

    Returns new dicts (copies) with the two fields added; originals are not mutated.
    """
    results = []
    for cand in candidates:
        decision, reason = classify(cand, existing_pmcids, existing_dois)
        results.append({**cand, "auth_decision": decision, "auth_reason": reason})
    return results


def load_corpus_keys(corpus_path: Path) -> tuple[set[str], set[str]]:
    """Load existing pmcids and dois from corpus TSV."""
    pmcids: set[str] = set()
    dois: set[str] = set()
    if corpus_path.exists():
        with open(corpus_path, newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                p = (row.get("pmcid") or "").strip()
                d = (row.get("doi") or "").strip().lower()
                if p:
                    pmcids.add(p)
                if d:
                    dois.add(d)
    return pmcids, dois


def main() -> None:
    ap = argparse.ArgumentParser(description="R4 Ingestion Authorization Gate")
    ap.add_argument(
        "--candidates",
        type=Path,
        default=CANDIDATES_DEFAULT,
        help="Candidates CSV file to classify",
    )
    ap.add_argument(
        "--corpus",
        type=Path,
        default=CORPUS,
        help="Corpus TSV for dedup (default: data/corpus/corpus.tsv)",
    )
    args = ap.parse_args()

    # Load corpus keys for dedup
    existing_pmcids, existing_dois = load_corpus_keys(args.corpus)
    print(f"Corpus dedup baseline: {len(existing_pmcids)} pmcids, {len(existing_dois)} dois")

    # Load candidates
    if not args.candidates.exists():
        print(f"ERROR: candidates file not found: {args.candidates}", file=sys.stderr)
        sys.exit(1)

    with open(args.candidates, newline="") as f:
        candidates = list(csv.DictReader(f))
    print(f"Loaded {len(candidates)} candidates from {args.candidates.name}")

    # Classify
    classified = classify_batch(candidates, existing_pmcids, existing_dois)

    # Summary
    counts: dict[str, int] = {"auto_ingest": 0, "review_required": 0, "blocked": 0}
    for c in classified:
        counts[c["auth_decision"]] = counts.get(c["auth_decision"], 0) + 1

    print("\nAuthorization summary:")
    print(f"  auto_ingest     : {counts['auto_ingest']}")
    print(f"  review_required : {counts['review_required']}")
    print(f"  blocked         : {counts['blocked']}")
    print(f"  TOTAL           : {len(classified)}")

    # Write report
    OUT.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "corpus_path": str(args.corpus),
        "candidates_path": str(args.candidates),
        "total": len(classified),
        "counts": counts,
        "results": classified,
    }
    OUT.write_text(json.dumps(report, indent=2))
    print(f"\nWrote auth report to {OUT}")


if __name__ == "__main__":
    main()
