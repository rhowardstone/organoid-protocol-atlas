"""
Offline tests for relabel_organoid_type pure logic: discovery->enum mapping and the
'trust specific extractor call, rescue OTHER from discovery' resolution rule.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "organoid_demo"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import relabel_organoid_type as rl  # noqa: E402
from schema import OrganoidType  # noqa: E402


def test_expanded_enum_has_new_systems():
    vals = {t.value for t in OrganoidType}
    for v in ("tumor", "cardiac", "vascular", "cholangiocyte", "skin", "thyroid"):
        assert v in vals


def test_map_discovery_aliases_hepatic_to_liver():
    assert rl.map_discovery("hepatic") == "liver"
    assert rl.map_discovery("Hepatic") == "liver"


def test_map_discovery_passthrough_valid():
    assert rl.map_discovery("tumor") == "tumor"
    assert rl.map_discovery("cardiac") == "cardiac"


def test_map_discovery_unknown_is_none():
    assert rl.map_discovery("not-a-real-type") is None
    assert rl.map_discovery("") is None


def test_resolve_keeps_specific_extractor_call():
    # extractor said intestinal; discovery said tumor -> trust the text-derived label
    assert rl.resolve_type("intestinal", "tumor") == "intestinal"


def test_resolve_rescues_other_from_discovery():
    assert rl.resolve_type("other", "tumor") == "tumor"
    assert rl.resolve_type("other", "hepatic") == "liver"


def test_resolve_other_stays_other_when_no_discovery():
    assert rl.resolve_type("other", "") == "other"
    assert rl.resolve_type("other", "bogus") == "other"
