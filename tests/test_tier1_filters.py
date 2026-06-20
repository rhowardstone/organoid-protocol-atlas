"""
Unit tests for the Tier-1 non-reagent guard.

The extractor occasionally lists lab equipment / software / imaging systems as
signaling factors (they appear verbatim in methods, so substring-grounding alone
won't catch them). This guard must drop the equipment without touching real
reagents — the regression we pin after a gastric paper surfaced "Nikon A1
confocal" and "NIS-Elements software" as signaling factors.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from tier1_extract import is_non_reagent  # noqa: E402


def test_equipment_and_software_are_rejected():
    for junk in ["Nikon A1 single photon confocal",
                 "NIS-Elements Advanced Research imaging software",
                 "Zeiss LSM 880 microscope", "FlowJo", "ImageJ",
                 "GraphPad Prism", "tabletop centrifuge"]:
        assert is_non_reagent(junk), junk


def test_real_reagents_are_kept():
    for ok in ["Activin A", "BMP4", "Bone morphogenetic protein 4", "CHIR99021",
               "R-spondin1", "FGF10", "Noggin", "Y-27632", "Retinoic acid",
               "EGF", "SB431542", "Wnt3a"]:
        assert not is_non_reagent(ok), ok
