"""
Ingestion-orchestrator QC tests — run OFFLINE, no network/Ollama.

We test the two pure decision functions the orchestrator is built around:
`select_candidates` (dedup + has_methods + CC-only + limit) and `verdict`
(the QC gate over a process_one result). Per the sprint contract, every QC
boundary that decides what enters the corpus has an explicit, offline test.
The network/Ollama-bound `process_one` is intentionally not exercised here;
its output dict shape is what `verdict` consumes, and that shape is fixed by
the assertions below.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import ingest_orchestrator as o  # noqa: E402


def _cand(pmcid, doi="", has_methods="yes", license="CC BY 4.0", **kw):
    return {"pmcid": pmcid, "doi": doi, "has_methods": has_methods,
            "license": license, "organoid_type": "cardiac", **kw}


# --- select_candidates: dedup, has_methods, cc-only, limit ---

def test_select_skips_pmcid_already_in_corpus():
    rows = [_cand("PMC1"), _cand("PMC2")]
    out = o.select_candidates(rows, have_pmc={"PMC1"}, have_doi=set())
    assert [c["pmcid"] for c in out] == ["PMC2"]


def test_select_skips_doi_already_in_corpus_case_insensitive():
    rows = [_cand("PMC3", doi="10.1/AbC")]
    out = o.select_candidates(rows, have_pmc=set(), have_doi={"10.1/abc"})
    assert out == []


def test_select_requires_has_methods_yes():
    rows = [_cand("PMC4", has_methods="no"), _cand("PMC5", has_methods="")]
    out = o.select_candidates(rows, have_pmc=set(), have_doi=set())
    assert out == []


def test_select_cc_only_filters_non_cc():
    rows = [_cand("PMC6", license="CC BY 4.0"), _cand("PMC7", license="Elsevier (c)"),
            _cand("PMC8", license="")]
    out = o.select_candidates(rows, have_pmc=set(), have_doi=set(), cc_only=True)
    assert [c["pmcid"] for c in out] == ["PMC6"]


def test_select_without_cc_only_keeps_all_licensed():
    rows = [_cand("PMC6", license="CC BY 4.0"), _cand("PMC7", license="Elsevier (c)")]
    out = o.select_candidates(rows, have_pmc=set(), have_doi=set(), cc_only=False)
    assert [c["pmcid"] for c in out] == ["PMC6", "PMC7"]


def test_select_limit_truncates():
    rows = [_cand(f"PMC{i}") for i in range(10)]
    out = o.select_candidates(rows, have_pmc=set(), have_doi=set(), limit=3)
    assert len(out) == 3


def test_select_missing_pmcid_skipped():
    rows = [{"pmcid": "", "has_methods": "yes"}, {"has_methods": "yes"}]
    out = o.select_candidates(rows, have_pmc=set(), have_doi=set())
    assert out == []


# --- verdict: the QC gate over a process_one result dict ---

def test_verdict_propagates_early_reason():
    # process_one returns {"reason": ...} for no_full_text/no_methods/parse_error/extract_error
    for reason in ("no_full_text", "no_methods", "parse_error:KeyError",
                   "extract_error:TimeoutError"):
        assert o.verdict({"pmcid": "PMC1", "reason": reason}, 0.5) == reason


def test_verdict_no_signaling_when_zero_factors():
    r = {"pmcid": "PMC1", "n_signaling": 0, "grounding_rate": 1.0}
    assert o.verdict(r, 0.5) == "no_signaling"


def test_verdict_low_grounding_below_threshold():
    r = {"pmcid": "PMC1", "n_signaling": 5, "grounding_rate": 0.4}
    assert o.verdict(r, 0.5) == "low_grounding=0.4"


def test_verdict_accept_returns_none():
    r = {"pmcid": "PMC1", "n_signaling": 5, "grounding_rate": 0.9}
    assert o.verdict(r, 0.5) is None


def test_verdict_accept_at_exact_threshold():
    # grounding_rate == threshold is NOT below threshold -> accept
    r = {"pmcid": "PMC1", "n_signaling": 3, "grounding_rate": 0.8}
    assert o.verdict(r, 0.8) is None


# --- stage_accepted: dry-run write boundary (no network/Ollama) ---

class _Proto:
    def model_dump_json(self, indent=None):
        return '{"stub": true}'


def _accept_result(pmcid="PMC9"):
    return {"pmcid": pmcid, "doi": "10.1/x", "grounding_rate": 0.9,
            "bundle": {"pmcid": pmcid, "methods_text": "..."}, "proto": _Proto(),
            "cand": {"organoid_type": "cardiac", "doi": "10.1/x", "pmcid": pmcid,
                     "first_author": "Doe", "year": "2025", "journal": "J",
                     "species": "human", "source_cell_type": "iPSC", "license": "CC BY 4.0"}}


def test_stage_accepted_dry_run_writes_nothing_and_returns_none(tmp_path):
    ld, pd = tmp_path / "bundles", tmp_path / "preds"
    row = o.stage_accepted(_accept_result(), dry_run=True, local_dir=ld, pred_dir=pd)
    assert row is None
    assert not ld.exists() and not pd.exists()


def test_stage_accepted_real_run_writes_bundle_pred_and_returns_row(tmp_path):
    ld, pd = tmp_path / "bundles", tmp_path / "preds"
    row = o.stage_accepted(_accept_result("PMC9"), dry_run=False, local_dir=ld, pred_dir=pd)
    assert (ld / "PMC9.json").exists() and (pd / "PMC9.json").exists()
    assert row["pmcid"] == "PMC9" and row["flags"] == "auto-ingested"
    # row carries every corpus column (DictWriter would otherwise raise)
    assert set(row) == set(o.CORPUS_COLS)
