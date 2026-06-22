"""
Offline tests for the dropped-percent fix (normalize.fix_concentration_unit) and the
extraction-fidelity audit detectors (audit_extraction_fidelity). Pure logic, no data.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from normalize import fix_concentration_unit  # noqa: E402
import audit_extraction_fidelity as af  # noqa: E402


# --------------------------------------------------------------------------- #
# fix_concentration_unit — corrects the dropped-% parse
# --------------------------------------------------------------------------- #

def test_fix_recovers_percent_from_quote():
    # the n=22 audit's real failures: "30% Wnt3A conditioned medium" -> unit was "conditioned medium"
    assert fix_concentration_unit(30, "conditioned medium", "30% Wnt3A conditioned medium") == "%"
    assert fix_concentration_unit(4, "conditioned medium", "4% Noggin conditioned medium") == "%"


def test_fix_keeps_real_molar_dose():
    assert fix_concentration_unit(5, "µM", "5 µM emricasan") == "uM"
    assert fix_concentration_unit(50, "ng/mL", "50 ng/mL EGF") == "ng/mL"


def test_fix_no_quote_or_no_value_is_just_canon():
    assert fix_concentration_unit(None, "µM", "") == "uM"
    assert fix_concentration_unit(10, "nM", "") == "nM"


# --------------------------------------------------------------------------- #
# audit detectors
# --------------------------------------------------------------------------- #

def test_value_in_quote():
    assert af.value_in_quote(50, "50 ng/mL EGF") is True
    assert af.value_in_quote(5, "added 50 ng/mL") is False   # 5 is not a standalone token


def test_pct_cm_bug_flags_bare_nonpct_unit_only():
    # dropped-% (unit carries no '%') -> flagged
    assert af.pct_cm_bug(30, "conditioned medium", "30% Wnt3A conditioned medium") is True
    # valid percent variants already carry '%' -> NOT flagged
    assert af.pct_cm_bug(10, "% v/v", "10% v/v") is False
    assert af.pct_cm_bug(10, "% conditioned medium", "10% noggin conditioned medium") is False
    # a real molar dose with no '%' in quote -> NOT flagged
    assert af.pct_cm_bug(5, "uM", "5 uM CHIR99021") is False
