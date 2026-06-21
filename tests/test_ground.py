"""
S1 grounding tests — run OFFLINE against committed SRI/Cellosaurus fixtures
(data/grounding/cache/). No network: every assertion is backed by a real cached
service response, per the sprint contract (resolved requires a real cached call).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import ground  # noqa: E402

OFF = dict(offline=True)


def test_small_molecule_resolves_to_chebi():
    r = ground.ground_entity("CHIR99021", "reagent", **OFF)
    assert r["grounding_status"] == "resolved"
    assert r["curie"] == "CHEBI:91091"
    assert r["biolink_category"] == "biolink:SmallMolecule"


def test_protein_growth_factor_resolves_to_gene_clique():
    # honest reality: SRI conflates gene/protein; EGF lands on its NCBIGene clique leader
    r = ground.ground_entity("EGF", "reagent", **OFF)
    assert r["grounding_status"] == "resolved"
    assert r["curie"].startswith("NCBIGene:")


def test_abbreviation_collision_is_typed_as_chemical():
    # regression: 'SAG' must NOT resolve to the S-antigen gene; curated small-molecule
    # gate constrains it to a CHEBI chemical.
    r = ground.ground_entity("SAG", "reagent", **OFF)
    assert r["curie"].startswith("CHEBI:")
    assert r["biolink_category"] == "biolink:SmallMolecule"


def test_species_resolves_to_ncbitaxon():
    assert ground.ground_entity("Homo sapiens", "species", **OFF)["curie"] == "NCBITaxon:9606"


def test_cell_line_resolves_to_cellosaurus_rrid():
    # WA09 is the H9 hESC; its Cellosaurus accession / RRID is CVCL_9773
    assert ground.ground_cell_line("WA09", **OFF)["curie"] == "Cellosaurus:CVCL_9773"


def test_pge2_now_resolves_correctly_via_curated_alias():
    # PR #9 found raw "PGE2" -> 15-Keto-PGE2 (near-miss, held as needs_review). The
    # curated ALIAS "pge2" -> "prostaglandin E2" now makes SRI return the correct
    # compound, which _verify accepts -> resolved. The CURIE still comes from SRI
    # (not hardcoded); see test_ground_aliases. The near-miss-not-accepted guard is
    # still enforced for un-aliased terms by test_wrong_entity below.
    r = ground.ground_entity("PGE2", "reagent", **OFF)
    assert r["grounding_status"] == "resolved"
    assert r["curie"] == "CHEBI:606564"
    assert "alias:prostaglandin E2" in r["flags"]


def test_wrong_entity_is_not_accepted_resolved():
    # PR #9 review regression: TGF-β1 -> pig TGF-beta *receptor* is the wrong entity.
    r = ground.ground_entity("TGF-β1", "reagent", **OFF)
    assert r["grounding_status"] == "needs_review"
    assert r["curie"] is not None and "label_mismatch" in r["flags"]


def test_accepted_resolved_has_no_mismatch_flag():
    r = ground.ground_entity("CHIR99021", "reagent", **OFF)
    assert r["grounding_status"] == "resolved" and r["flags"] == []


def test_zero_hit_is_not_found_never_guessed():
    r = ground.ground_entity("zzqnotarealreagent42", "reagent", **OFF)
    assert r["grounding_status"] == "not_found"
    assert r["curie"] is None


def test_uncached_offline_is_not_attempted():
    # offline + no fixture -> honest not_attempted (no call made, nothing guessed)
    r = ground.ground_entity("neverbeencalledxyz", "reagent", **OFF)
    assert r["grounding_status"] == "not_attempted"
    assert r["curie"] is None
