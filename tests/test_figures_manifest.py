import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _corpus_by_pmcid():
    with (ROOT / "data/corpus/corpus.tsv").open(newline="") as f:
        return {row["pmcid"]: row for row in csv.DictReader(f, delimiter="\t")}


def test_public_figures_manifest_is_cc_by_only_and_s3_linked():
    corpus = _corpus_by_pmcid()
    figures = json.loads((ROOT / "serve/static/figures.json").read_text(encoding="utf-8"))

    assert len(figures) == 57
    assert len({fig["pmcid"] for fig in figures}) == 8

    for fig in figures:
        assert corpus[fig["pmcid"]]["license"] == "CC-BY"
        assert fig["s3_url"].startswith("https://pmc-oa-opendata.s3.amazonaws.com/")
        assert fig["doi"]
        assert fig["label"]
        assert isinstance(fig["is_protocol_schematic"], bool)
        assert isinstance(fig["confirmed_factors"], list)


def test_public_static_assets_do_not_commit_figure_images():
    image_suffixes = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff"}
    committed_images = [
        path
        for path in (ROOT / "serve/static").rglob("*")
        if path.suffix.lower() in image_suffixes
    ]

    assert committed_images == []


def test_figures_page_uses_static_manifest_and_discloses_cc_by():
    html = (ROOT / "serve/templates/pages/figures.html").read_text(encoding="utf-8")

    assert "fetch('/static/figures.json')" in html
    assert "CC-BY" in html
    assert "PMC Open Access" in html
    assert "no images redistributed" in html


def test_figure_manifest_builder_is_repo_relative():
    script = (ROOT / "pipeline/build_figures_manifest.py").read_text(encoding="utf-8")

    assert "/atb-data/" not in script
    assert "ORGANOID_ATLAS_ROOT" in script
    assert "CC-BY" in script
