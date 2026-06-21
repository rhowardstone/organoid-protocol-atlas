"""
Grounding fixture schema integrity tests (offline).

Validates that all committed fixtures under data/grounding/cache/ have the
structural shape expected by ground.py. Catches malformed fixtures from batch
PRs before they silently break grounding lookups.

Three fixture types:
  cellosaurus/*.json  — Cellosaurus API response for cell-line lookup
  norm/*.json         — SRI Name Resolver /normalize response (keyed by CURIE)
  name/*.json         — SRI Name Resolver /lookup response (list of hits)

No network. No GPU.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "data" / "grounding" / "cache"
CELLOSAURUS_DIR = CACHE / "cellosaurus"
NORM_DIR = CACHE / "norm"
NAME_DIR = CACHE / "name"

CURIE_PREFIX_RE = __import__("re").compile(r"^[A-Z][A-Za-z0-9.]+:\S+$")


def _load_all(directory: Path) -> list[tuple[Path, dict | list]]:
    files = sorted(directory.glob("*.json"))
    out = []
    for f in files:
        try:
            out.append((f, json.loads(f.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, OSError) as e:
            raise AssertionError(f"Cannot parse fixture {f.name}: {e}") from e
    return out


# --------------------------------------------------------------------------- #
# Cellosaurus fixtures
# --------------------------------------------------------------------------- #

def test_cellosaurus_fixtures_parse():
    """All cellosaurus/*.json files must be valid JSON."""
    fixtures = _load_all(CELLOSAURUS_DIR)
    assert fixtures, f"No cellosaurus fixtures found in {CELLOSAURUS_DIR}"
    # test just validates they loaded (parse errors raise in _load_all)


def test_cellosaurus_fixtures_have_required_structure():
    """Each fixture must have Cellosaurus.cell-line-list (may be empty for 'not found')."""
    for path, data in _load_all(CELLOSAURUS_DIR):
        assert isinstance(data, dict), f"{path.name}: root must be dict"
        assert "Cellosaurus" in data, f"{path.name}: missing 'Cellosaurus' key"
        cello = data["Cellosaurus"]
        assert "cell-line-list" in cello, f"{path.name}: missing 'cell-line-list'"
        assert isinstance(cello["cell-line-list"], list), (
            f"{path.name}: 'cell-line-list' must be list"
        )


def test_cellosaurus_fixtures_have_primary_accession():
    """Non-empty Cellosaurus fixtures must have at least one CVCL_ primary accession."""
    for path, data in _load_all(CELLOSAURUS_DIR):
        cell_list = data["Cellosaurus"]["cell-line-list"]
        if not cell_list:
            continue  # empty list = "not found" fixture, valid
        for cell in cell_list:
            accessions = cell.get("accession-list", [])
            primary = [a for a in accessions if a.get("type") == "primary"]
            assert primary, f"{path.name}: no primary accession in cell entry"
            cvcl = primary[0].get("value", "")
            assert cvcl.startswith("CVCL_"), (
                f"{path.name}: primary accession value {cvcl!r} must start with 'CVCL_'"
            )


# --------------------------------------------------------------------------- #
# SRI norm fixtures
# --------------------------------------------------------------------------- #

def test_norm_fixtures_parse():
    """All norm/*.json files must be valid JSON."""
    fixtures = _load_all(NORM_DIR)
    assert fixtures, f"No norm fixtures found in {NORM_DIR}"


def test_norm_fixtures_have_required_structure():
    """Each fixture must be a dict with a CURIE key containing id.identifier."""
    for path, data in _load_all(NORM_DIR):
        assert isinstance(data, dict), f"{path.name}: root must be dict"
        assert data, f"{path.name}: root dict is empty"

        # The dict has one top-level key — the CURIE — as its only/primary key
        keys = [k for k in data if not k.startswith("_")]
        assert keys, f"{path.name}: no non-metadata keys found"

        curie_key = keys[0]
        entry = data[curie_key]
        assert isinstance(entry, dict), (
            f"{path.name}: value for {curie_key!r} must be dict, got {type(entry)}"
        )
        assert "id" in entry, f"{path.name}[{curie_key}]: missing 'id' field"
        assert "identifier" in entry["id"], (
            f"{path.name}[{curie_key}]: missing 'id.identifier'"
        )
        assert "equivalent_identifiers" in entry, (
            f"{path.name}[{curie_key}]: missing 'equivalent_identifiers'"
        )
        assert isinstance(entry["equivalent_identifiers"], list), (
            f"{path.name}[{curie_key}]: 'equivalent_identifiers' must be list"
        )


def test_norm_fixtures_identifier_matches_filename():
    """The CURIE in id.identifier should correspond to the fixture's filename.

    Filename convention: chebi_606564.json → CHEBI:606564.
    This catches copy-paste errors where the file is named for one CURIE but
    contains another entity's response.
    """
    for path, data in _load_all(NORM_DIR):
        keys = [k for k in data if not k.startswith("_")]
        if not keys:
            continue
        curie_key = keys[0]
        identifier = data[curie_key].get("id", {}).get("identifier", "")
        if not identifier:
            continue

        # Normalise: "CHEBI:606564" → "chebi_606564"
        # "PUBCHEM.COMPOUND:44288444" → "pubchem_compound_44288444" (dot→underscore too)
        normalised = identifier.lower().replace(":", "_").replace(".", "_")
        stem = path.stem.lower()
        assert stem == normalised, (
            f"{path.name}: filename stem '{stem}' does not match normalised "
            f"identifier '{normalised}' (from id.identifier={identifier!r}). "
            f"Possible copy-paste error — the fixture content may be for the wrong entity."
        )


def test_norm_fixtures_have_biolink_type():
    """Each norm fixture should declare at least one biolink: type."""
    for path, data in _load_all(NORM_DIR):
        keys = [k for k in data if not k.startswith("_")]
        if not keys:
            continue
        entry = data[keys[0]]
        types = entry.get("type", [])
        assert isinstance(types, list), f"{path.name}: 'type' must be list"
        biolink_types = [t for t in types if str(t).startswith("biolink:")]
        assert biolink_types, (
            f"{path.name}: no 'biolink:' type found in {types[:3]} — "
            f"fixture may be malformed or from wrong API endpoint"
        )


# --------------------------------------------------------------------------- #
# SRI name lookup fixtures
# --------------------------------------------------------------------------- #

def test_name_fixtures_parse():
    """All name/*.json files must be valid JSON."""
    fixtures = _load_all(NAME_DIR)
    assert fixtures, f"No name fixtures found in {NAME_DIR}"


def test_name_fixtures_are_lists():
    """Name lookup fixtures must be JSON arrays (list of hit objects)."""
    for path, data in _load_all(NAME_DIR):
        assert isinstance(data, list), (
            f"{path.name}: expected list of hits, got {type(data).__name__}"
        )


def test_name_fixtures_hits_have_curie_and_label():
    """Each hit in a name fixture must have 'curie' and 'label'."""
    for path, data in _load_all(NAME_DIR):
        for i, hit in enumerate(data):
            assert isinstance(hit, dict), (
                f"{path.name}[{i}]: hit must be dict, got {type(hit)}"
            )
            assert "curie" in hit, f"{path.name}[{i}]: missing 'curie'"
            assert "label" in hit, f"{path.name}[{i}]: missing 'label'"
            curie = hit.get("curie", "")
            assert CURIE_PREFIX_RE.match(str(curie)), (
                f"{path.name}[{i}]: 'curie' {curie!r} does not look like a CURIE "
                f"(expected PREFIX:identifier)"
            )


def test_name_fixtures_hits_have_types():
    """Each name fixture hit must have 'types' list with at least one biolink: type."""
    for path, data in _load_all(NAME_DIR):
        for i, hit in enumerate(data):
            types = hit.get("types", [])
            assert isinstance(types, list), f"{path.name}[{i}]: 'types' must be list"
            biolink = [t for t in types if str(t).startswith("biolink:")]
            assert biolink, (
                f"{path.name}[{i}]: hit curie={hit.get('curie')} has no biolink: type"
            )


# --------------------------------------------------------------------------- #
# Cross-fixture consistency
# --------------------------------------------------------------------------- #

def test_all_fixture_directories_non_empty():
    """All three fixture subdirectories must exist and contain fixtures."""
    for d in (CELLOSAURUS_DIR, NORM_DIR, NAME_DIR):
        assert d.exists(), f"Fixture directory missing: {d}"
        files = list(d.glob("*.json"))
        assert files, f"No .json fixtures found in {d}"


def test_total_fixture_count_above_floor():
    """Sanity check: we expect at least 100 committed grounding fixtures total.
    If this fails, fixtures were accidentally deleted or the cache was cleared."""
    total = sum(
        len(list(d.glob("*.json")))
        for d in (CELLOSAURUS_DIR, NORM_DIR, NAME_DIR)
        if d.exists()
    )
    assert total >= 100, (
        f"Only {total} grounding fixtures found (floor: 100) — "
        f"fixtures may have been deleted or the cache was cleared"
    )
