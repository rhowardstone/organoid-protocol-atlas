"""Unit tests for the concentration consistency checker."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import check_concentration_consistency as cc


def test_median_odd():
    assert cc.median([1, 3, 5]) == 3


def test_median_even():
    assert cc.median([1, 2, 3, 4]) == 2.5


def test_no_flagged_when_values_within_threshold():
    from collections import defaultdict
    groups = {("EGF", "ng/mL"): [
        {"id": 1, "pmcid": "PMC1", "organoid_type": "gut", "name": "EGF",
         "value": 50.0, "evidence_quote": "EGF 50 ng/mL"},
        {"id": 2, "pmcid": "PMC2", "organoid_type": "gut", "name": "EGF",
         "value": 100.0, "evidence_quote": "EGF 100 ng/mL"},
    ]}
    # 100/50=2x, within 10x threshold — should not flag
    med = cc.median([50.0, 100.0])
    for m in groups[("EGF", "ng/mL")]:
        ratio = m["value"] / med
        assert ratio <= cc.OUTLIER_THRESHOLD and ratio >= (1 / cc.OUTLIER_THRESHOLD)


def test_flags_10x_outlier():
    vals = [50.0, 50.0, 50000.0]  # 50000 is 1000x the median of 50
    med = cc.median(vals)
    outlier_val = 50000.0
    ratio = outlier_val / med
    assert ratio > cc.OUTLIER_THRESHOLD


def test_main_runs_and_produces_output(tmp_path):
    import json
    # Write minimal reagents.jsonl
    reagents = [
        {"id": 1, "canonical": "EGF", "canonical_unit": "ng/mL", "value": 50,
         "pmcid": "PMC1", "organoid_type": "gut", "name": "EGF", "evidence_quote": "EGF 50 ng/mL"},
        {"id": 2, "canonical": "EGF", "canonical_unit": "ng/mL", "value": 100,
         "pmcid": "PMC2", "organoid_type": "gut", "name": "EGF", "evidence_quote": "EGF 100 ng/mL"},
        {"id": 3, "canonical": "EGF", "canonical_unit": "ng/mL", "value": 50000,
         "pmcid": "PMC3", "organoid_type": "gut", "name": "EGF", "evidence_quote": "EGF 50 ug/mL"},
    ]
    r_path = tmp_path / "reagents.jsonl"
    r_path.write_text("\n".join(json.dumps(r) for r in reagents))
    out_path = tmp_path / "out.json"
    # Monkeypatch paths
    import check_concentration_consistency as cc2
    orig_r, orig_o = cc2.REAGENTS, cc2.OUT
    cc2.REAGENTS, cc2.OUT = r_path, out_path
    try:
        cc2.main()
        result = json.loads(out_path.read_text())
        assert result["n_flagged_outliers"] == 1
        assert result["flagged"][0]["canonical"] == "EGF"
    finally:
        cc2.REAGENTS, cc2.OUT = orig_r, orig_o
