"""Data-hygiene guards for build_kg (#225 year, #234 TaqMan misclass, #235 dedup)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import build_kg as b  # noqa: E402


def test_clean_year_rejects_implausible():
    # #225: protocols.io created_on epoch sliced to "1715" etc.
    for bad in ["1715", "1545", "1484", "", None, "2099", "abc"]:
        assert b.clean_year(bad) is None, bad
    for ok in ["1990", "2023", "2026", "2027"]:
        assert b.clean_year(ok) == ok


def test_taqman_panel_dropped():
    # #234: qPCR assay IDs are measured genes, not culture reagents.
    items = [{"name": "AREG", "evidence": {"quote": "AREG (Hs00950669_m1)"}},
             {"name": "BDNF", "evidence": {"quote": "BDNF (Hs02718934_s1)"}},
             {"name": "EGF", "concentration": {"value": 50, "unit": "ng/mL"}, "evidence": {"quote": "50 ng/mL EGF"}}]
    out = b.select_reagents(items, {})
    assert [r["name"] for r in out] == ["EGF"]


def test_dedup_prefers_dose_bearing():
    # #235: duplicate rows collapse to one, keeping the mention that carries a dose.
    items = [{"name": "EGF", "concentration": {"value": None}},
             {"name": "EGF", "concentration": {"value": 50, "unit": "ng/mL"}},
             {"name": "R-spondin", "concentration": {"value": 500}}]
    out = b.select_reagents(items, {})
    assert [r["name"] for r in out] == ["EGF", "R-spondin"]
    egf = next(r for r in out if r["name"] == "EGF")
    assert egf["concentration"]["value"] == 50


def test_canonical_dedup_merges_synonyms():
    # dedup is by canonical name, so synonyms collapse when canon_map maps them together.
    items = [{"name": "Y27632", "concentration": {"value": 10}},
             {"name": "Y-27632", "concentration": {"value": None}}]
    out = b.select_reagents(items, {"Y27632": "Y-27632", "Y-27632": "Y-27632"})
    assert len(out) == 1 and out[0]["concentration"]["value"] == 10
