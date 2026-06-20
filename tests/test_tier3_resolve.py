"""
Unit tests for the Tier-3 RESOLVER's verification gate (no network).

The gate exists to stop same-author/same-year-but-wrong-paper resolutions from
fabricating provenance. The regression we pin: a "Koo 2011" citation must NOT
resolve to a mammary-gland paper just because the author+year match; the title
has to be about organoid / intestinal-epithelial culture.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from tier3_resolve import TITLE_OK, named_delegations  # noqa: E402


def test_title_gate_rejects_wrong_topic_paper():
    # the real false positive we caught: Koo 2011 -> a mammary-gland paper
    assert TITLE_OK.search("Survival and differentiation of mammary epithelial cells "
                           "in mammary gland") is None


def test_title_gate_accepts_organoid_source():
    assert TITLE_OK.search("Paneth cells constitute the niche for Lgr5 stem cells "
                           "in intestinal crypts")
    assert TITLE_OK.search("Controlled gene expression in primary Lgr5 organoid cultures")


def test_named_delegation_is_extracted():
    b = {"pmcid": "PMCX", "organoid_type": "lung",
         "methods_text": "Intestinal organoids were cultured as previously described "
                         "(Sato et al, 2011). Cells were maintained in Matrigel."}
    d = named_delegations(b)
    assert any(x["author"] == "Sato" and x["year"] == "2011" for x in d)
