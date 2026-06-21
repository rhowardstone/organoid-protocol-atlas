"""
Public JSONL schema conformance tests — verify exports/public/*.jsonl
satisfies structural and quality invariants across all rows.

Runs offline; reads committed JSONL files, no network, no DB.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROTOCOLS_JSONL = REPO / "exports" / "public" / "protocols.jsonl"
REAGENTS_JSONL = REPO / "exports" / "public" / "reagents.jsonl"

PROTOCOL_REQUIRED = {
    "pmcid", "doi", "organoid_type", "license",
    "n_signaling_factors", "grounding_rate",
    "reagents_grounded", "reagents_total",
}
REAGENT_REQUIRED = {
    "pmcid", "doi", "name", "kind", "role",
    "grounded", "evidence_quote",
}
# build_kg.py maps signaling_factors→"signaling", small_molecules→"small_molecule"
VALID_KINDS = {"signaling", "supplement", "small_molecule"}
VALID_ROLES = {"component", "primary", "supplement", "inhibitor", "activator",
               "small_molecule", "scaffold", "other", None}
PUBLIC_LICENSE_OK = {"CC-BY", "CC0", "CC-BY-SA"}
PUBLIC_SNIPPET_MAX = 500


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


# ─── Protocol schema ───────────────────────────────────────────────────────────

def test_protocols_have_required_keys():
    rows = _load_jsonl(PROTOCOLS_JSONL)
    missing_by_field: dict[str, int] = {}
    for row in rows:
        for key in PROTOCOL_REQUIRED:
            if key not in row:
                missing_by_field[key] = missing_by_field.get(key, 0) + 1
    assert not missing_by_field, f"Missing required keys: {missing_by_field}"


def test_protocols_have_valid_pmcids():
    rows = _load_jsonl(PROTOCOLS_JSONL)
    bad = [r["pmcid"] for r in rows if not str(r.get("pmcid", "")).startswith("PMC")]
    assert not bad, f"Invalid PMCIDs: {bad[:5]}"


def test_protocols_license_is_public_safe():
    rows = _load_jsonl(PROTOCOLS_JSONL)
    bad = [r["pmcid"] for r in rows if r.get("license") not in PUBLIC_LICENSE_OK]
    assert not bad, f"Non-public license in public export: {bad[:5]}"


def test_protocols_grounding_rate_is_valid():
    rows = _load_jsonl(PROTOCOLS_JSONL)
    bad = [
        (r["pmcid"], r.get("grounding_rate"))
        for r in rows
        if not (isinstance(r.get("grounding_rate"), (int, float))
                and 0.0 <= r["grounding_rate"] <= 1.0)
    ]
    assert not bad, f"Invalid grounding_rate values: {bad[:5]}"


def test_protocols_signaling_factors_non_negative():
    rows = _load_jsonl(PROTOCOLS_JSONL)
    bad = [(r["pmcid"], r.get("n_signaling_factors"))
           for r in rows if (r.get("n_signaling_factors") or 0) < 0]
    assert not bad, f"Negative n_signaling_factors: {bad[:5]}"


def test_protocols_reagents_totals_consistent():
    """reagents_grounded must be <= reagents_total for every row."""
    rows = _load_jsonl(PROTOCOLS_JSONL)
    bad = [(r["pmcid"], r.get("reagents_grounded"), r.get("reagents_total"))
           for r in rows
           if (r.get("reagents_grounded") or 0) > (r.get("reagents_total") or 0)]
    assert not bad, f"reagents_grounded > reagents_total: {bad[:5]}"


def test_protocols_organoid_type_is_specific():
    """No protocol row should have organoid_type == 'other' in the public export.

    build_kg.py and export_public.py both use corpus.tsv as the authoritative
    type source (line: oty = cm.get("organoid_type") or p.get("organoid_type")).
    If corpus.tsv is populated from the discovery CSV at ingest time, 'other'
    should never appear. This test guards against marathon_ingest.py forgetting
    to copy the discovery CSV type into corpus.tsv for new papers.
    """
    rows = _load_jsonl(PROTOCOLS_JSONL)
    other = [r["pmcid"] for r in rows if r.get("organoid_type") == "other"]
    assert not other, (
        f"{len(other)} rows have organoid_type='other' — ingest likely failed to "
        f"propagate the discovery-CSV type into corpus.tsv: {other[:5]}"
    )


def test_protocols_no_duplicate_pmcids():
    rows = _load_jsonl(PROTOCOLS_JSONL)
    pmcids = [r["pmcid"] for r in rows]
    dups = [p for p in set(pmcids) if pmcids.count(p) > 1]
    assert not dups, f"Duplicate PMCIDs in protocols.jsonl: {dups[:5]}"


def test_protocols_doi_format_when_present():
    """When a DOI is present it must start with '10.' (valid DOI prefix).
    Null/empty DOIs are allowed — some PMC articles have PMC IDs but no DOI."""
    rows = _load_jsonl(PROTOCOLS_JSONL)
    bad = [r["pmcid"] for r in rows
           if r.get("doi") and not r["doi"].startswith("10.")]
    assert not bad, f"Malformed DOIs (present but invalid format): {bad[:5]}"


# ─── Reagent schema ────────────────────────────────────────────────────────────

def test_reagents_have_required_keys():
    rows = _load_jsonl(REAGENTS_JSONL)
    missing_by_field: dict[str, int] = {}
    for row in rows:
        for key in REAGENT_REQUIRED:
            if key not in row:
                missing_by_field[key] = missing_by_field.get(key, 0) + 1
    assert not missing_by_field, f"Missing required keys: {missing_by_field}"


def test_reagents_kind_values_are_valid():
    """Reagent 'kind' must be one of the three values build_kg.py emits.
    Guards against schema drift between build_kg.py and the exported JSONL."""
    rows = _load_jsonl(REAGENTS_JSONL)
    bad = [(r.get("pmcid"), r.get("kind"))
           for r in rows if r.get("kind") not in VALID_KINDS]
    assert not bad, (
        f"{len(bad)} rows have invalid 'kind' values: {bad[:5]}. "
        f"Expected one of {VALID_KINDS}"
    )


def test_reagents_evidence_quote_is_snippet_only():
    rows = _load_jsonl(REAGENTS_JSONL)
    over = [(r.get("pmcid"), len(r.get("evidence_quote") or ""))
            for r in rows if len(r.get("evidence_quote") or "") > PUBLIC_SNIPPET_MAX]
    assert not over, (
        f"{len(over)} reagent rows exceed PUBLIC_SNIPPET_MAX={PUBLIC_SNIPPET_MAX}: {over[:3]}"
    )


def test_reagents_grounded_is_boolean():
    rows = _load_jsonl(REAGENTS_JSONL)
    bad = [r.get("name") for r in rows if not isinstance(r.get("grounded"), (bool, int))]
    assert not bad[:5], f"Non-boolean 'grounded' field: {bad[:5]}"


def test_reagents_each_has_valid_pmcid():
    rows = _load_jsonl(REAGENTS_JSONL)
    bad = [r.get("name") for r in rows if not str(r.get("pmcid", "")).startswith("PMC")]
    assert not bad, f"Reagents with invalid PMCIDs: {bad[:5]}"


def test_reagents_all_pmcids_are_in_protocols():
    protocol_pmcids = {r["pmcid"] for r in _load_jsonl(PROTOCOLS_JSONL)}
    reagent_pmcids = {r["pmcid"] for r in _load_jsonl(REAGENTS_JSONL)}
    orphan = reagent_pmcids - protocol_pmcids
    assert not orphan, (
        f"{len(orphan)} reagent PMCIDs not in protocols.jsonl: {sorted(orphan)[:5]}"
    )


# ─── Cross-file consistency ────────────────────────────────────────────────────

def test_corpus_grounding_rate_floor():
    """Corpus average grounding rate must stay above 0.80 (quality regression guard)."""
    rows = _load_jsonl(PROTOCOLS_JSONL)
    rates = [r["grounding_rate"] for r in rows if r.get("grounding_rate") is not None]
    avg = sum(rates) / len(rates) if rates else 0.0
    assert avg >= 0.80, f"Corpus avg grounding rate {avg:.3f} < 0.80 floor"
