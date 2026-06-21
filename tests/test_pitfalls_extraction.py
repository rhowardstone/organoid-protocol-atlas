"""
Offline tests for the failure_modes / modifications gating in tier1_extract
(build_failure_modes, build_modifications). Pure logic on synthetic model JSON --
no model call, no network. Guards the two anti-fabrication rules:

  * a modification's cited_doi is kept ONLY if it is a real DOI appearing verbatim in
    the source (kills bare reference indices and prompt-parroted example DOIs);
  * a failure mode's Evidence is attached ONLY when its quote is a verbatim substring.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "organoid_demo"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import tier1_extract as t1  # noqa: E402

SRC = "Cells were grown per the protocol in 10.1038/s41586-020-2724-8 with R-spondin."


# --------------------------------------------------------------------------- #
# modifications
# --------------------------------------------------------------------------- #

def test_modification_keeps_real_doi_verbatim_in_source():
    mods = t1.build_modifications(
        {"modifications": [{"cited_doi": "10.1038/s41586-020-2724-8",
                            "change_description": "added Wnt3a"}]}, "10.x/self", SRC)
    assert len(mods) == 1
    assert mods[0].cited_doi == "10.1038/s41586-020-2724-8"


def test_modification_drops_bare_reference_index():
    mods = t1.build_modifications(
        {"modifications": [{"cited_doi": "21", "change_description": "modified Mae et al."}]},
        "10.x/self", SRC)
    assert len(mods) == 1                      # the modification is kept...
    assert mods[0].cited_doi is None           # ...but the fake "DOI" is dropped


def test_modification_drops_parroted_doi_not_in_source():
    # a well-formed DOI the model invented (e.g. parroted from a prompt example)
    mods = t1.build_modifications(
        {"modifications": [{"cited_doi": "10.1038/nature12345",
                            "change_description": "x"}]}, "10.x/self", SRC)
    assert mods[0].cited_doi is None           # not verbatim in SRC -> dropped


def test_modification_requires_change_description():
    assert t1.build_modifications(
        {"modifications": [{"cited_doi": "10.1038/s41586-020-2724-8", "change_description": ""}]},
        "10.x/self", SRC) == []


def test_modifications_empty_and_nondict_safe():
    assert t1.build_modifications({}, "d", SRC) == []
    assert t1.build_modifications({"modifications": ["junk", None]}, "d", SRC) == []


# --------------------------------------------------------------------------- #
# failure_modes
# --------------------------------------------------------------------------- #

def test_failure_mode_requires_description():
    assert t1.build_failure_modes(
        {"failure_modes": [{"description": "", "condition": "x"}]}, "d", SRC) == []


def test_failure_mode_attaches_evidence_only_when_verbatim():
    fms = t1.build_failure_modes({"failure_modes": [
        {"description": "organoids collapse", "condition": "low Wnt",
         "evidence_quote": "with R-spondin"},                 # verbatim in SRC
        {"description": "cells die", "evidence_quote": "not in the source text"},  # not verbatim
    ]}, "10.x/self", SRC)
    assert len(fms) == 2
    assert fms[0].evidence is not None and fms[0].evidence.quote == "with R-spondin"
    assert fms[0].condition == "low Wnt"
    assert fms[1].evidence is None             # false quote dropped, never stored


def test_failure_mode_blank_condition_becomes_none():
    fms = t1.build_failure_modes(
        {"failure_modes": [{"description": "d", "condition": "  "}]}, "d", SRC)
    assert fms[0].condition is None
