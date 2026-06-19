"""
Baseline regression test == reproducibility guard for the acceptance gate.

Runs the prototype's eval harness exactly as the gate does
(`python eval_protocol_extraction.py` inside organoid_demo/) and asserts the
rule_based_v1 baseline metrics are unchanged. These numbers encode the four
preserved failure modes (HANDOFF.md §9); if a change moves them, that change
must be intentional and documented — not silent. "No looks-better merges."
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = REPO_ROOT / "organoid_demo"
SUMMARY = DEMO_DIR / "outputs" / "evaluation_summary.json"

# Expected baseline for the deterministic control arm (rule_based_v1) over the
# 3-protocol fixture gold. The failures (reporting 4/6, precision 0.70,
# dup-rate 0.30) are intentional eval fixtures, not bugs.
EXPECTED = {
    "scalar_exact_match": 1.0,
    "reporting_status_accuracy": 0.6667,
    "signaling_factor_precision": 0.7,
    "signaling_factor_recall": 1.0,
    "unit_normalization_accuracy": 1.0,
    "evidence_grounding": 1.0,
    "wrong_bucket_or_duplicate_rate": 0.3,
}


def _run_gate() -> dict:
    """Run the acceptance-gate command and return the parsed metric summary."""
    proc = subprocess.run(
        [sys.executable, "eval_protocol_extraction.py"],
        cwd=DEMO_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"gate command failed:\n{proc.stderr}"
    assert SUMMARY.exists(), "eval did not write outputs/evaluation_summary.json"
    return json.loads(SUMMARY.read_text())


def _score(summary: dict, key: str):
    """Metrics are either a bare float or a dict carrying a 'score'/'rate'."""
    val = summary[key]
    if isinstance(val, dict):
        return val["score"] if "score" in val else val["rate"]
    return val


def test_baseline_metrics_unchanged():
    summary = _run_gate()
    for key, expected in EXPECTED.items():
        actual = _score(summary, key)
        assert actual == expected, f"{key}: expected {expected}, got {actual}"


def test_preserved_failure_modes_present():
    """The §9 failure modes must remain visible, not silently fixed."""
    summary = _run_gate()
    dup_examples = summary["wrong_bucket_or_duplicate_rate"]["examples"]
    joined = " | ".join(dup_examples).lower()
    assert "r-spondin" in joined, "synonym-duplication fixture missing"
    assert "b27" in joined and "n2" in joined, "wrong-bucket fixture (B27/N2) missing"
    report_errors = " | ".join(summary["reporting_status_accuracy"]["errors"]).lower()
    assert "not_reported" in report_errors, "not_reported-vs-miss fixture missing"
