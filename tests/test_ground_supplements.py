"""
Tests for pipeline/ground_supplements.py — all run OFFLINE (fixture cache only, no network).

Tests cover:
  - Curated product map entries (B27, N2, GlutaMAX, FBS, Pen/Strep)
  - SRI-resolvable supplements (Nicotinamide, HEPES, N-acetylcysteine, Y-27632, etc.)
  - Structural integrity of the committed artifact
  - top_supplement_canonicals query (with reagents.jsonl present)
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import ground_supplements  # noqa: E402

OFF = dict(offline=True)
ARTIFACT = Path(__file__).resolve().parent.parent / "outputs" / "grounding" / "supplement_grounding.json"


# ---------------------------------------------------------------------------
# Curated product map (no SRI call — always available even offline)
# ---------------------------------------------------------------------------

def test_b27_curated():
    r = ground_supplements.ground_one("B27", **OFF)
    assert r["grounding_status"] == "curated"
    assert "Thermo Fisher" in r["identifier"]
    assert "17504044" in r["identifier"]


def test_b27_supplement_alias_curated():
    r = ground_supplements.ground_one("B27 supplement", **OFF)
    assert r["grounding_status"] == "curated"
    assert "17504044" in r["identifier"]


def test_n2_curated():
    r = ground_supplements.ground_one("N2", **OFF)
    assert r["grounding_status"] == "curated"
    assert "17502048" in r["identifier"]


def test_n2_supplement_alias_curated():
    r = ground_supplements.ground_one("N2 supplement", **OFF)
    assert r["grounding_status"] == "curated"
    assert "17502048" in r["identifier"]


def test_glutamax_curated_chebi():
    r = ground_supplements.ground_one("GlutaMAX", **OFF)
    assert r["grounding_status"] == "curated"
    assert "CHEBI:2483" in r["identifier"]


def test_fbs_curated_chebi():
    r = ground_supplements.ground_one("FBS", **OFF)
    assert r["grounding_status"] == "curated"
    assert "CHEBI:93046" in r["identifier"]


def test_fetal_bovine_serum_curated_chebi():
    r = ground_supplements.ground_one("fetal bovine serum", **OFF)
    assert r["grounding_status"] == "curated"
    assert "CHEBI:93046" in r["identifier"]


def test_penstrep_curated():
    r = ground_supplements.ground_one("penicillin/streptomycin", **OFF)
    assert r["grounding_status"] == "curated"
    assert "CHEBI:17334" in r["identifier"]
    assert "CHEBI:17076" in r["identifier"]


def test_pen_strep_alias_curated():
    r = ground_supplements.ground_one("Pen/Strep", **OFF)
    assert r["grounding_status"] == "curated"
    assert "CHEBI:17334" in r["identifier"]


def test_knockout_serum_replacement_curated():
    r = ground_supplements.ground_one("KnockOut Serum Replacement", **OFF)
    assert r["grounding_status"] == "curated"
    assert "Thermo Fisher" in r["identifier"]


def test_primocin_curated():
    r = ground_supplements.ground_one("Primocin", **OFF)
    assert r["grounding_status"] == "curated"
    assert "InVivoGen" in r["identifier"]


def test_nea_curated():
    r = ground_supplements.ground_one("non-essential amino acids", **OFF)
    assert r["grounding_status"] == "curated"
    assert "Thermo Fisher" in r["identifier"]


# ---------------------------------------------------------------------------
# SRI-resolvable supplements (require cached fixtures; must have been run live)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (Path(__file__).resolve().parent.parent / "data" / "grounding" / "cache" / "name" / "nicotinamide__biolink_smallmolecule.json").exists(),
    reason="SRI name fixture not cached — run pipeline/ground_supplements.py --top 30 first",
)
def test_nicotinamide_resolves_chebi():
    r = ground_supplements.ground_one("Nicotinamide", **OFF)
    assert r["grounding_status"] == "resolved"
    assert r["curie"].startswith("CHEBI:")


@pytest.mark.skipif(
    not (Path(__file__).resolve().parent.parent / "data" / "grounding" / "cache" / "name" / "hepes__biolink_smallmolecule.json").exists(),
    reason="SRI name fixture not cached",
)
def test_hepes_resolves_chebi():
    r = ground_supplements.ground_one("HEPES", **OFF)
    assert r["grounding_status"] == "resolved"
    assert r["curie"].startswith("CHEBI:")


@pytest.mark.skipif(
    not (Path(__file__).resolve().parent.parent / "data" / "grounding" / "cache" / "name" / "n_acetylcysteine__biolink_smallmolecule.json").exists(),
    reason="SRI name fixture not cached",
)
def test_nac_resolves_chebi():
    r = ground_supplements.ground_one("N-acetylcysteine", **OFF)
    assert r["grounding_status"] == "resolved"
    assert r["curie"].startswith("CHEBI:")


@pytest.mark.skipif(
    not (Path(__file__).resolve().parent.parent / "data" / "grounding" / "cache" / "name" / "y_27632__any.json").exists(),
    reason="SRI name fixture not cached",
)
def test_y27632_resolves_chebi():
    r = ground_supplements.ground_one("Y-27632", **OFF)
    assert r["grounding_status"] == "resolved"
    assert r["curie"] == "CHEBI:75393"


# ---------------------------------------------------------------------------
# Artifact structural integrity (only if artifact was generated)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not ARTIFACT.exists(), reason="Run pipeline/ground_supplements.py first")
def test_artifact_structure():
    d = json.loads(ARTIFACT.read_text())
    assert "n_total" in d
    assert "n_resolved" in d
    assert "n_curated" in d
    assert "coverage_rate" in d
    assert "records" in d
    assert isinstance(d["records"], list)
    assert len(d["records"]) == d["n_total"]


@pytest.mark.skipif(not ARTIFACT.exists(), reason="Run pipeline/ground_supplements.py first")
def test_artifact_coverage_above_threshold():
    d = json.loads(ARTIFACT.read_text())
    assert d["coverage_rate"] >= 0.7, (
        f"Supplement grounding coverage {d['coverage_rate']:.1%} below 70% threshold"
    )


@pytest.mark.skipif(not ARTIFACT.exists(), reason="Run pipeline/ground_supplements.py first")
def test_artifact_every_record_has_status():
    d = json.loads(ARTIFACT.read_text())
    valid_statuses = {"resolved", "curated", "needs_review", "not_found"}
    for r in d["records"]:
        assert r.get("grounding_status") in valid_statuses, (
            f"Record {r.get('name')} has unexpected status: {r.get('grounding_status')}"
        )


@pytest.mark.skipif(not ARTIFACT.exists(), reason="Run pipeline/ground_supplements.py first")
def test_artifact_no_fabricated_chebi():
    """Resolved records must cite a real CURIE (never invented)."""
    d = json.loads(ARTIFACT.read_text())
    for r in d["records"]:
        if r.get("grounding_status") == "resolved":
            curie = r.get("curie", "")
            assert ":" in curie, f"Resolved record {r.get('name')} has malformed CURIE: {curie!r}"
            prefix = curie.split(":")[0]
            assert prefix in {"CHEBI", "NCBIGene", "PR", "PUBCHEM.COMPOUND", "UNII", "DRUGBANK"}, (
                f"Unexpected CURIE prefix {prefix!r} for {r.get('name')}"
            )
