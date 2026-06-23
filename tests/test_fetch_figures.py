"""Tests for pipeline/fetch_figures.py — figure-image acquisition for Tier-2 vision.

Guards the deterministic surface and the retry/backoff logic (recently hardened so a
single transient S3 503 cannot crash a 5000-paper batch). Fully offline: every network
call is exercised through a monkeypatched urlopen; sleeps are stubbed.
"""

import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import fetch_figures as ff  # noqa: E402


class _FakeResp:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data


# --------------------------------------------------------------------------- #
# figure_keys — pure publisher-pattern filter
# --------------------------------------------------------------------------- #

def test_figure_keys_accepts_known_publisher_patterns():
    keys = [
        "PMC1.1/nihms-1529307-f0001.jpg",   # NIHMS
        "PMC1.1/ncomms9715-f3.jpg",         # Nature
        "PMC1.1/41598_2019_Fig4_HTML.jpg",  # Springer
        "PMC1.1/gr1_lrg.jpg",               # Elsevier figure
        "PMC1.1/fx1.jpg",                   # Elsevier graphical abstract
    ]
    out = ff.figure_keys(keys)
    assert out == sorted(keys)              # all accepted, returned sorted


def test_figure_keys_excludes_supplements_thumbnails_and_nonimages():
    keys = [
        "PMC1.1/41598_2019_MOESM1_ESM.jpg",  # supplement (MOESM/ESM)
        "PMC1.1/nihms-1-f0001-s1.jpg",       # -s1 thumbnail/supp variant
        "PMC1.1/logo.png",                   # logo
        "PMC1.1/inline-1.jpg",               # inline
        "PMC1.1/table1.jpg",                 # not a figure pattern
        "PMC1.1/ncomms9715-f3.pdf",          # not an image extension
    ]
    assert ff.figure_keys(keys) == []


# --------------------------------------------------------------------------- #
# _read_url — retry/backoff semantics
# --------------------------------------------------------------------------- #

def test_read_url_returns_bytes_on_success(monkeypatch):
    monkeypatch.setattr(ff.urllib.request, "urlopen", lambda url, timeout=0: _FakeResp(b"IMG"))
    assert ff._read_url("http://x", timeout=1) == b"IMG"


def test_read_url_reraises_4xx_immediately_without_retry(monkeypatch):
    calls = {"open": 0, "sleep": 0}

    def boom(url, timeout=0):
        calls["open"] += 1
        raise urllib.error.HTTPError("http://x", 404, "Not Found", None, None)

    monkeypatch.setattr(ff.urllib.request, "urlopen", boom)
    monkeypatch.setattr(ff.time, "sleep", lambda s: calls.__setitem__("sleep", calls["sleep"] + 1))
    with pytest.raises(urllib.error.HTTPError):
        ff._read_url("http://x", timeout=1, tries=4)
    assert calls["open"] == 1     # 404 = client error: no retry
    assert calls["sleep"] == 0


def test_read_url_retries_transient_5xx_then_raises(monkeypatch):
    calls = {"open": 0, "sleep": 0}

    def boom(url, timeout=0):
        calls["open"] += 1
        raise urllib.error.HTTPError("http://x", 503, "Service Unavailable", None, None)

    monkeypatch.setattr(ff.urllib.request, "urlopen", boom)
    monkeypatch.setattr(ff.time, "sleep", lambda s: calls.__setitem__("sleep", calls["sleep"] + 1))
    with pytest.raises(urllib.error.HTTPError):
        ff._read_url("http://x", timeout=1, tries=3)
    assert calls["open"] == 3      # retried up to `tries`
    assert calls["sleep"] == 2      # backoff between attempts, not after the last


def test_read_url_retries_then_succeeds(monkeypatch):
    calls = {"open": 0}

    def flaky(url, timeout=0):
        calls["open"] += 1
        if calls["open"] < 2:
            raise urllib.error.URLError("temporary network blip")
        return _FakeResp(b"OK")

    monkeypatch.setattr(ff.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(ff.time, "sleep", lambda s: None)
    assert ff._read_url("http://x", timeout=1, tries=4) == b"OK"
    assert calls["open"] == 2


# --------------------------------------------------------------------------- #
# s3_list — version selection from the listing XML
# --------------------------------------------------------------------------- #

def test_s3_list_keeps_highest_version_only(monkeypatch):
    xml = (
        "<ListBucketResult>"
        "<Contents><Key>PMC123.1/nihms-f0001.jpg</Key></Contents>"
        "<Contents><Key>PMC123.1/old.txt</Key></Contents>"
        "<Contents><Key>PMC123.2/ncomms-f3.jpg</Key></Contents>"
        "</ListBucketResult>"
    ).encode()
    monkeypatch.setattr(ff, "_read_url", lambda url, timeout=30: xml)
    keys = ff.s3_list("PMC123")
    assert keys == ["PMC123.2/ncomms-f3.jpg"]   # only latest version prefix


def test_s3_list_empty_when_no_keys(monkeypatch):
    monkeypatch.setattr(ff, "_read_url", lambda url, timeout=30: b"<ListBucketResult></ListBucketResult>")
    assert ff.s3_list("PMC999") == []


# --------------------------------------------------------------------------- #
# fetch — license gate + resume (no network on these paths)
# --------------------------------------------------------------------------- #

def test_fetch_license_gated_skips_without_network(monkeypatch):
    """A non-open license must be skipped before any S3 access."""
    monkeypatch.setattr(ff, "s3_list", lambda p: pytest.fail("s3_list must not be called when gated"))
    rec = ff.fetch("PMC1", "author-manuscript")
    assert rec["skipped"] == "license-gated"


def test_fetch_resumes_from_existing_sidecar(monkeypatch, tmp_path):
    """A paper with a figures.json sidecar resumes instantly without re-listing S3."""
    monkeypatch.setattr(ff, "FIG_DIR", tmp_path)
    monkeypatch.setattr(ff, "s3_list", lambda p: pytest.fail("should not re-list when already fetched"))
    d = tmp_path / "PMC1"
    d.mkdir()
    (d / "figures.json").write_text(json.dumps({"pmcid": "PMC1", "n_figures": 2}))
    rec = ff.fetch("PMC1", "CC-BY")
    assert rec["skipped"] == "already-fetched"
    assert rec["n_figures"] == 2


def test_fetch_open_license_no_figures(monkeypatch, tmp_path):
    monkeypatch.setattr(ff, "FIG_DIR", tmp_path)
    monkeypatch.setattr(ff, "s3_list", lambda p: [])
    rec = ff.fetch("PMC2", "CC0")
    assert rec["skipped"] == "no-figures-on-mirror"
