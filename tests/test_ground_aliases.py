"""
S1 curated-alias tests — OFFLINE against committed SRI fixtures (data/grounding/cache).

The ALIASES map fixes common typo/spacing/hyphen/descriptor variants of reagent
names that SRI misses on the raw string. The alias only rewrites the QUERY; the
CURIE is still resolved by name_lookup + the _verify gate (no hardcoded/fabricated
CURIEs), so each alias below must resolve to the correct chemical and carry an
`alias:` provenance flag.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import ground  # noqa: E402

OFF = dict(offline=True)

# raw corpus form -> (expected CURIE, aliased query string)
EXPECTED = {
    "ActivinA": ("CHEBI:81351", "Activin A"),
    "CHIR99201": ("CHEBI:91091", "CHIR99021"),       # typo of CHIR99021
    "FSK": ("CHEBI:93891", "forskolin"),
    "ROCK inhibitor Y-27632": ("CHEBI:75393", "Y-27632"),
    "A8301": ("CHEBI:233322", "A 83-01"),
    "Sant1": ("PUBCHEM.COMPOUND:6878030", "SANT-1"),
    "SB431542": ("CHEBI:91108", "SB 431542"),
    "IWP2": ("CHEBI:125649", "IWP-2"),
    "PGE2": ("CHEBI:606564", "prostaglandin E2"),
}


def test_aliases_resolve_to_correct_curie_with_flag():
    for raw, (curie, aliased) in EXPECTED.items():
        r = ground.ground_entity(raw, "reagent", **OFF)
        assert r["grounding_status"] == "resolved", (raw, r)
        assert r["curie"] == curie, (raw, r["curie"])
        assert f"alias:{aliased}" in r["flags"], (raw, r["flags"])
        # provenance: original query preserved, CURIE came from SRI (not hardcoded)
        assert r["query"] == raw
        assert r["source"] == "sri-name-resolver"


def test_alias_keys_are_normalized_and_chemical_only():
    # every alias key is the [^a-z0-9]-stripped lowercase form, and aliasing only
    # applies to reagents (gene/protein family terms are deliberately NOT aliased)
    import re
    for k in ground.ALIASES:
        assert k == re.sub(r"[^a-z0-9]", "", k), k


def test_gene_protein_family_terms_are_not_force_aliased():
    # TGF-beta / BMP4 / sonic hedgehog must NOT be in ALIASES (species-ambiguous;
    # belong in needs_review/not_found for human review — the PR #9 lesson).
    for term in ("tgfb", "tgfbeta", "bmp4", "sonichedgehog"):
        assert term not in ground.ALIASES


def test_non_aliased_reagent_unchanged():
    # a normal already-resolving reagent still works and carries no alias flag
    r = ground.ground_entity("CHIR99021", "reagent", **OFF)
    assert r["grounding_status"] == "resolved" and r["curie"] == "CHEBI:91091"
    assert not any(f.startswith("alias:") for f in r["flags"])
