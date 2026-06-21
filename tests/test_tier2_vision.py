"""
Offline tests for Tier-2 vision sanitizers (pure logic, no model, no image):
clean_concentration, confirm_reagents (confirm-don't-originate), clean_stages.
Guards the exact funkiness seen in the prototype on real figures.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import tier2_vision as t2  # noqa: E402


# --------------------------------------------------------------------------- #
# clean_concentration
# --------------------------------------------------------------------------- #

def test_keeps_real_dose_normalizes_unit():
    # "1 µM retinoic acid" must survive with a normalized unit
    assert t2.clean_concentration(1, "µM") == (1, "uM")
    assert t2.clean_concentration(50, "μM") == (50, "uM")


def test_drops_isoform_number_with_no_unit():
    # "recombinant human laminin 111" -> value 111 / unit None is NOT a dose
    assert t2.clean_concentration(111, None) == (None, None)


def test_drops_abbreviation_in_unit_field():
    # "Activin A" with unit "ACTA" — ACTA is not a concentration unit
    assert t2.clean_concentration(None, "ACTA") == (None, None)
    assert t2.clean_concentration(5, "ACTA") == (None, None)


# --------------------------------------------------------------------------- #
# confirm_reagents (vision confirms text, never originates)
# --------------------------------------------------------------------------- #

T1 = {"CHIR99021", "BMP4", "Activin A"}   # this paper's Tier-1 reagent canonicals


def test_confirms_reagent_in_tier1_with_evidence():
    out = t2.confirm_reagents([{"name": "CHIR99021", "value": 3, "unit": "uM"}], T1)
    assert len(out) == 1
    r = out[0]
    assert r["canonical"] == "CHIR99021" and r["figure_confirmed"] is True
    assert r["evidence_figure_text"] == "CHIR99021"
    assert (r["value"], r["unit"]) == (3, "uM")


def test_drops_markers_and_panel_labels_not_in_text():
    # VSX2/OTX2 are markers; "A. MH" is a panel label — none are in Tier-1 -> dropped
    out = t2.confirm_reagents(
        [{"name": "VSX2"}, {"name": "OTX2"}, {"name": "A. MH"}, {"name": "DAPI"}], T1)
    assert out == []


def test_drops_resolvable_reagent_absent_from_this_paper():
    # Noggin resolves to a curated factor but isn't in THIS paper's Tier-1 set
    assert t2.confirm_reagents([{"name": "Noggin"}], T1) == []


# --------------------------------------------------------------------------- #
# clean_stages
# --------------------------------------------------------------------------- #

def test_nulls_days_on_hour_scale_label():
    out = t2.clean_stages([{"name": "4h", "day_start": 0, "day_end": 0}])
    assert out == [{"name": "4h", "day_start": None, "day_end": None}]


def test_keeps_day_label_days():
    out = t2.clean_stages([{"name": "day 7", "day_start": 7, "day_end": 7}])
    assert out[0]["day_start"] == 7


def test_dedups_repeated_stages():
    stages = [{"name": "differentiation day 7", "day_start": 7, "day_end": None}] * 3
    assert len(t2.clean_stages(stages)) == 1
