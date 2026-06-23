"""Tests for pipeline/tier0_extract.py — deterministic JATS evidence-bundle extraction.

Tier 0 is the only extraction tier that previously had no test (tier1/2/3 do).
These tests guard the parse + fetch-fallback behaviour the rest of the pipeline
depends on, using synthetic JATS XML fixtures. Fully offline: the one network
function (`fetch_xml`) is exercised only through a monkeypatched `http_get`.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import tier0_extract as t0  # noqa: E402


# A rich, realistic JATS article exercising every extraction branch.
RICH_JATS = b"""<?xml version="1.0"?>
<article article-type="research-article"
         xmlns:xlink="http://www.w3.org/1999/xlink">
  <body>
    <sec sec-type="intro"><title>Introduction</title>
      <p>Background text about intestinal organoids and prior work.</p></sec>
    <sec sec-type="methods"><title>Materials and Methods</title>
      <p>Cells were cultured in Matrigel with 50 ng/mL EGF for 7 days.</p></sec>
    <sec><title>Generation of intestinal organoids</title>
      <p>Crypts were embedded in Matrigel and overlaid with WENR medium.</p></sec>
    <sec sec-type="results"><title>Results</title>
      <p>Organoids formed within 5 days of plating.</p></sec>
    <sec><title>Discussion</title><p>These findings suggest broad utility.</p></sec>
    <table-wrap><label>Table 1</label>
      <caption><p>Media composition for expansion.</p></caption>
      <table><tr><td>EGF</td><td>50 ng/mL</td></tr></table></table-wrap>
    <fig><label>Figure 1</label>
      <caption><p>Differentiation timeline over 14 days.</p>
        <graphic xlink:href="fig1.jpg"/></caption></fig>
    <sec sec-type="supplementary-material"><title>Supplementary Information</title>
      <p>Extended supplementary methods are provided here with substantial additional
         protocol detail deliberately repeated and expanded so that this inline
         supplementary block comfortably exceeds the four hundred character threshold
         used by the extractor to decide whether inline supplementary text is present
         rather than living only in external attached files referenced elsewhere.</p></sec>
    <supplementary-material xlink:href="supp1.docx">
      <label>Supplementary File 1</label>
      <media xlink:href="supp1.docx" mimetype="application/msword"/></supplementary-material>
    <ext-link xlink:href="https://www.protocols.io/view/abc">protocol</ext-link>
  </body>
  <back>
    <ref-list>
      <ref id="r1"><citation>Sato et al. 2009</citation></ref>
      <ref id="r2"><citation>Clevers 2016</citation></ref>
    </ref-list>
  </back>
</article>"""


@pytest.fixture(scope="module")
def rich():
    return t0.parse_jats(RICH_JATS)


def test_methods_detected_by_sectype_and_descriptive_title(rich):
    """Methods are captured both from sec-type='methods' AND from a descriptively
    titled body section that is not recognisably non-methods (the case title-only
    matching misses)."""
    assert rich["methods_detected"] is True
    assert "Matrigel" in rich["methods_text"]       # from sec-type=methods
    assert "WENR" in rich["methods_text"]           # from descriptive-title sec


def test_methods_text_excludes_intro_results_discussion(rich):
    """Intro/Results/Discussion prose must not leak into methods_text."""
    assert "Background text" not in rich["methods_text"]
    assert "formed within 5 days" not in rich["methods_text"]
    assert "broad utility" not in rich["methods_text"]


def test_body_text_preserves_everything(rich):
    """Full body text is always preserved even when methods detection narrows."""
    assert "Background text" in rich["body_text"]
    assert "formed within 5 days" in rich["body_text"]
    assert rich["body_chars"] == len(rich["body_text"]) > 0


def test_tables_extracted(rich):
    assert len(rich["tables"]) == 1
    tbl = rich["tables"][0]
    assert tbl["label"] == "Table 1"
    assert "Media composition" in tbl["caption"]
    assert "50 ng/mL" in tbl["text"]


def test_figures_capture_caption_and_href_but_not_image(rich):
    """Figure captions + graphic href are recorded; the image itself is left for Tier 2."""
    assert len(rich["figures"]) == 1
    fig = rich["figures"][0]
    assert fig["label"] == "Figure 1"
    assert "timeline" in fig["caption"]
    assert fig["graphic_href"] == "fig1.jpg"


def test_supplementary_text_and_external_file_inventory(rich):
    assert len(rich["supplementary_text"]) >= 400
    assert len(rich["supplementary_files"]) == 1
    sf = rich["supplementary_files"][0]
    assert sf["href"] == "supp1.docx"
    assert sf["mimetype"] == "application/msword"


def test_links_deduped_and_captured(rich):
    assert "https://www.protocols.io/view/abc" in rich["links"]


def test_references_extracted(rich):
    ids = {r["id"] for r in rich["references"]}
    assert ids == {"r1", "r2"}
    assert any("Sato" in r["citation"] for r in rich["references"])


def test_section_map_and_titles(rich):
    assert "Introduction" in rich["section_titles"]
    assert "Results" in rich["section_titles"]
    assert rich["section_map"]["Results"] > 0


def test_article_type_captured(rich):
    assert rich["article_type"] == "research-article"


def test_no_body_xml_warns_and_empties_methods():
    """Front-matter-only XML (not OA full text) yields empty methods, zero body chars,
    and a no_body warning rather than crashing."""
    parsed = t0.parse_jats(
        b'<article article-type="correction"><front><x>meta</x></front></article>'
    )
    assert parsed["body_chars"] == 0
    assert parsed["methods_text"] == ""
    assert parsed["methods_detected"] is False
    assert any("no_body_in_xml" in w for w in parsed["extraction_warnings"])
    assert parsed["article_type"] == "correction"


def test_no_method_delimiters_falls_back_to_full_body():
    """When no section is recognisably methods, methods_text falls back to the whole
    body and a fallback warning is emitted (so downstream tiers still get text)."""
    xml = (b'<article><body>'
           b'<sec><title>Introduction</title><p>intro alpha</p></sec>'
           b'<sec><title>Results</title><p>result beta</p></sec>'
           b'</body></article>')
    parsed = t0.parse_jats(xml)
    assert parsed["methods_detected"] is False
    assert "intro alpha" in parsed["methods_text"]   # fell back to full body
    assert any("methods_fallback_full_body" in w for w in parsed["extraction_warnings"])


def test_content_sha256_is_deterministic_and_content_sensitive():
    a = t0.parse_jats(RICH_JATS)
    b = t0.parse_jats(RICH_JATS)
    assert t0.content_sha256(a) == t0.content_sha256(b)
    different = t0.parse_jats(
        RICH_JATS.replace(b"Organoids formed within 5 days", b"Organoids formed within 9 days")
    )
    assert t0.content_sha256(different) != t0.content_sha256(a)


# --------------------------------------------------------------------------- #
# fetch_xml fallback logic — offline, via monkeypatched http_get
# --------------------------------------------------------------------------- #

def test_fetch_xml_prefers_europe_pmc(monkeypatch):
    def fake_get(url, timeout=40):
        assert "europepmc" in url
        return 200, b"<article>europe body</article>"
    monkeypatch.setattr(t0, "http_get", fake_get)
    route, body, note = t0.fetch_xml("PMC123")
    assert route == "europe_pmc_xml"
    assert b"europe body" in body


def test_fetch_xml_falls_back_to_ncbi_when_epmc_lacks_article(monkeypatch):
    def fake_get(url, timeout=40):
        if "europepmc" in url:
            return 200, b"<html>no article here</html>"
        assert "eutils.ncbi" in url
        return 200, b"<article>ncbi body</article>"
    monkeypatch.setattr(t0, "http_get", fake_get)
    route, body, note = t0.fetch_xml("PMC123")
    assert route == "ncbi_efetch_xml"
    assert b"ncbi body" in body
    assert "epmc no <article>" in note


def test_fetch_xml_unavailable_when_both_fail(monkeypatch):
    def fake_get(url, timeout=40):
        raise ConnectionError("boom")
    monkeypatch.setattr(t0, "http_get", fake_get)
    route, body, note = t0.fetch_xml("PMC123")
    assert route == "unavailable"
    assert body is None


def test_median_handles_empty_odd_even():
    assert t0._median([]) == 0
    assert t0._median([5, 1, 3]) == 3          # odd -> middle of sorted
    assert t0._median([4, 2]) == 3             # even -> mean of two middle
