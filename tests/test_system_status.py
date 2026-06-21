"""
Offline tests for system_status pure logic.
No network, no real corpus file reads (uses tmp_path fixtures).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import system_status as ss


# --------------------------------------------------------------------------- #
# check_corpus
# --------------------------------------------------------------------------- #

def _make_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_check_corpus_missing_file():
    result = ss.check_corpus(Path("/tmp/nonexistent_corpus_xyz.jsonl"))
    assert not result["ok"]
    assert "not found" in result["error"]


def test_check_corpus_empty_file(tmp_path):
    p = tmp_path / "protocols.jsonl"
    p.write_text("\n\n")
    result = ss.check_corpus(p)
    assert not result["ok"]


def test_check_corpus_basic(tmp_path):
    p = tmp_path / "protocols.jsonl"
    _make_jsonl(p, [
        {"organoid_type": "cardiac", "grounding_rate": 0.9,
         "reagents_grounded": 9, "reagents_total": 10},
        {"organoid_type": "retinal", "grounding_rate": 0.8,
         "reagents_grounded": 8, "reagents_total": 10},
    ])
    result = ss.check_corpus(p)
    assert result["ok"]
    assert result["n_papers"] == 2
    assert result["n_organoid_types"] == 2
    assert result["avg_grounding_rate"] == pytest.approx(0.85)
    assert result["pooled_grounding_rate"] == pytest.approx(0.85)


def test_check_corpus_counts_bad_lines(tmp_path):
    p = tmp_path / "protocols.jsonl"
    p.write_text('{"organoid_type": "cardiac"}\n{BROKEN}\n')
    result = ss.check_corpus(p)
    assert result["ok"]
    assert result["bad_lines"] == 1
    assert result["n_papers"] == 1


def test_check_corpus_missing_grounding_rate_ok(tmp_path):
    p = tmp_path / "protocols.jsonl"
    _make_jsonl(p, [{"organoid_type": "cardiac"}])
    result = ss.check_corpus(p)
    assert result["ok"]
    assert result["avg_grounding_rate"] is None


def test_check_corpus_pooled_grounding_zero_total(tmp_path):
    p = tmp_path / "protocols.jsonl"
    _make_jsonl(p, [{"organoid_type": "cardiac", "reagents_grounded": 0, "reagents_total": 0}])
    result = ss.check_corpus(p)
    assert result["pooled_grounding_rate"] is None


# --------------------------------------------------------------------------- #
# check_analytics_artifacts
# --------------------------------------------------------------------------- #

def test_check_artifacts_all_missing(tmp_path):
    artifacts = [
        ss.AnalyticsArtifact("foo", tmp_path / "foo.json", "python foo.py"),
        ss.AnalyticsArtifact("bar", tmp_path / "bar.json", "python bar.py"),
    ]
    results = ss.check_analytics_artifacts(artifacts)
    assert all(not r["ok"] for r in results)
    assert all(not r["exists"] for r in results)


def test_check_artifacts_present_and_valid(tmp_path):
    path = tmp_path / "failure_mode_summary.json"
    path.write_text(json.dumps({"total_failure_modes": 42}))
    artifacts = [ss.AnalyticsArtifact("failure_mode_summary", path, "python x.py")]
    results = ss.check_analytics_artifacts(artifacts)
    assert results[0]["ok"]
    assert results[0]["record_count"] == 42


def test_check_artifacts_malformed_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{BROKEN")
    artifacts = [ss.AnalyticsArtifact("bad", path, "python x.py")]
    results = ss.check_analytics_artifacts(artifacts)
    assert not results[0]["ok"]


def test_check_artifacts_empty_file(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("")
    artifacts = [ss.AnalyticsArtifact("empty", path, "python x.py")]
    results = ss.check_analytics_artifacts(artifacts)
    assert not results[0]["ok"]


def test_check_artifacts_record_count_n_nodes(tmp_path):
    path = tmp_path / "lineage.json"
    path.write_text(json.dumps({"n_nodes": 15, "n_edges": 20}))
    artifacts = [ss.AnalyticsArtifact("protocol_lineage", path, "python x.py")]
    results = ss.check_analytics_artifacts(artifacts)
    assert results[0]["record_count"] == 15


# --------------------------------------------------------------------------- #
# check_consensus_files
# --------------------------------------------------------------------------- #

def test_check_consensus_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "OUTPUTS", tmp_path / "nonexistent")
    result = ss.check_consensus_files()
    assert result["n_files"] == 0
    assert result["types"] == []


def test_check_consensus_finds_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "OUTPUTS", tmp_path)
    (tmp_path / "consensus_cardiac.json").write_text("{}")
    (tmp_path / "consensus_retinal.json").write_text("{}")
    result = ss.check_consensus_files()
    assert result["n_files"] == 2
    assert "cardiac" in result["types"]
    assert "retinal" in result["types"]


# --------------------------------------------------------------------------- #
# check_manifest
# --------------------------------------------------------------------------- #

def test_check_manifest_missing(tmp_path):
    result = ss.check_manifest(tmp_path / "nonexistent.json")
    assert not result["ok"]


def test_check_manifest_ok(tmp_path):
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"n_papers": 582, "version": "1.0"}))
    result = ss.check_manifest(m)
    assert result["ok"]
    assert result["n_papers_manifest"] == 582


def test_check_manifest_malformed(tmp_path):
    m = tmp_path / "manifest.json"
    m.write_text("{BROKEN")
    result = ss.check_manifest(m)
    assert not result["ok"]


# --------------------------------------------------------------------------- #
# compute_status
# --------------------------------------------------------------------------- #

def test_compute_status_all_ok():
    corpus = {"ok": True, "n_papers": 582}
    artifacts = [{"name": "a", "ok": True, "required": True,
                  "generate_cmd": "x", "record_count": None}]
    consensus = {"n_files": 5, "types": ["cardiac"]}
    manifest = {"ok": True, "n_papers_manifest": 582}
    status = ss.compute_status(corpus, artifacts, consensus, manifest)
    assert status["healthy"]
    assert status["missing_required"] == []


def test_compute_status_missing_required():
    corpus = {"ok": True, "n_papers": 10}
    artifacts = [{"name": "failure_mode_summary", "ok": False, "required": True,
                  "generate_cmd": "python x.py", "record_count": None}]
    consensus = {"n_files": 0, "types": []}
    manifest = {"ok": True}
    status = ss.compute_status(corpus, artifacts, consensus, manifest)
    assert not status["healthy"]
    assert "failure_mode_summary" in status["missing_required"]
    assert "python x.py" in status["generate_commands_needed"]


def test_compute_status_corpus_not_ok():
    corpus = {"ok": False, "error": "file missing"}
    status = ss.compute_status(corpus, [], {"n_files": 0, "types": []}, {"ok": False})
    assert not status["healthy"]


# --------------------------------------------------------------------------- #
# render_text
# --------------------------------------------------------------------------- #

def test_render_text_healthy():
    corpus = {
        "ok": True,
        "n_papers": 582,
        "n_organoid_types": 26,
        "avg_grounding_rate": 0.87,
        "pooled_grounding_rate": 0.86,
        "reagents_grounded_total": 5000,
        "reagents_total": 5800,
        "n_local_predictions": 0,
    }
    artifacts = [{"name": "failure_mode_summary", "ok": True, "required": True,
                  "generate_cmd": "x", "record_count": 120}]
    consensus = {"n_files": 5, "types": ["cardiac", "retinal"]}
    manifest = {"ok": True, "n_papers_manifest": 582}
    status = ss.compute_status(corpus, artifacts, consensus, manifest)
    text = ss.render_text(status)
    assert "582" in text
    assert "26" in text
    assert "failure_mode_summary" in text


def test_render_text_missing_corpus():
    corpus = {"ok": False, "error": "file not found"}
    status = ss.compute_status(corpus, [], {"n_files": 0, "types": []}, {"ok": False})
    text = ss.render_text(status)
    assert "file not found" in text


def test_render_text_shows_generate_cmd():
    corpus = {"ok": True, "n_papers": 10, "n_organoid_types": 1,
              "avg_grounding_rate": None, "pooled_grounding_rate": None,
              "reagents_grounded_total": 0, "reagents_total": 0, "n_local_predictions": 0}
    artifacts = [{"name": "coverage_report", "ok": False, "required": True,
                  "generate_cmd": "python pipeline/generate_coverage_report.py",
                  "record_count": None}]
    consensus = {"n_files": 0, "types": []}
    manifest = {"ok": False}
    status = ss.compute_status(corpus, artifacts, consensus, manifest)
    text = ss.render_text(status)
    assert "generate_coverage_report" in text
