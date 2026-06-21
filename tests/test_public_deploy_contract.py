import csv
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_manifest_counts_match_render_copy():
    manifest = json.loads((ROOT / "exports/public/manifest.json").read_text())

    assert manifest["license_filter"] == "CC0/CC-BY (no NC/ND)"
    assert manifest["n_papers"] == 582
    assert manifest["tables"] == {"protocols": 582, "reagents": 5458}


def test_public_landing_page_does_not_claim_local_corpus_counts():
    html = (ROOT / "serve/templates/index.html").read_text()

    assert "582</div><div class=\"l\">public protocols" in html
    assert "5458</div><div class=\"l\">public rows" in html
    assert "0</div><div class=\"l\">full-text bodies" in html
    assert "/llms.txt" in html
    assert "28</div><div class=\"l\">protocols extracted" not in html
    assert "311</div><div class=\"l\">reagents" not in html


def test_llms_txt_route_documents_public_api_and_limits():
    plugin = (ROOT / "serve/plugins/ask.py").read_text()

    assert "LLMS_TXT" in plugin
    assert "582 papers, 582" in plugin
    assert "5458 public reagent/protocol rows" in plugin
    assert "does not redistribute" in plugin
    assert "/atlas/protocols.json" in plugin
    assert "/atlas/reagents.json" in plugin
    assert r"^/llms\.txt$" in plugin


def test_public_ask_page_is_honest_without_model():
    html = (ROOT / "serve/templates/pages/ask.html").read_text()

    assert "model synthesis unavailable here" in html
    assert "evidence retrieved" in html
    assert "public Render deployment" in html


def test_is_public_license_excludes_nc_nd_and_nonfree():
    sys.path.insert(0, str(ROOT / "pipeline"))
    from export_public import is_public_license
    # freely redistributable -> public
    for lic in ["CC-BY", "CC-BY-4.0", "CC BY 4.0", "cc-by", "CC0", "CC0-1.0", "CC-BY-SA"]:
        assert is_public_license(lic), lic
    # NonCommercial / NoDerivatives / non-CC -> excluded from public build
    for lic in ["CC-BY-NC", "CC-BY-NC-ND", "CC-BY-ND", "author-manuscript",
                "unknown", "", None]:
        assert not is_public_license(lic), lic


def test_evidence_quote_cap_enforced():
    """Committed reagents.jsonl must respect PUBLIC_SNIPPET_MAX (no full method paragraphs)."""
    sys.path.insert(0, str(ROOT / "pipeline"))
    from export_public import PUBLIC_SNIPPET_MAX
    reagents_path = ROOT / "exports/public/reagents.jsonl"
    over = []
    for line in reagents_path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        eq = r.get("evidence_quote") or ""
        if len(eq) > PUBLIC_SNIPPET_MAX:
            over.append(eq[:80])
    assert not over, (
        f"{len(over)} reagent rows exceed PUBLIC_SNIPPET_MAX={PUBLIC_SNIPPET_MAX}: "
        f"{over[:3]}"
    )


def test_public_manifest_includes_all_corpus_cc_papers():
    """Every CC-eligible paper in corpus.tsv must be in the public manifest.
    Catches the case where export_public.py is re-run and accidentally drops CC papers,
    or where corpus.tsv is updated with new CC papers but the export isn't regenerated."""
    sys.path.insert(0, str(ROOT / "pipeline"))
    from export_public import is_public_license
    corpus_tsv = ROOT / "data" / "corpus" / "corpus.tsv"
    cc_pmcids = {
        r["pmcid"]
        for r in csv.DictReader(corpus_tsv.open(encoding="utf-8-sig"), delimiter="\t")
        if is_public_license(r.get("license"))
    }
    manifest = json.loads((ROOT / "exports/public/manifest.json").read_text())
    manifest_pmcids = set(manifest["papers"])
    missing = cc_pmcids - manifest_pmcids
    assert not missing, (
        f"{len(missing)} CC-eligible papers from corpus.tsv absent from public manifest "
        f"(run pipeline/export_public.py to regenerate): {sorted(missing)[:5]}"
    )


def test_public_manifest_excludes_non_cc_corpus_papers():
    """No NC/ND/author-manuscript paper in corpus.tsv may appear in the public manifest.
    Guards the license-clean public export contract."""
    sys.path.insert(0, str(ROOT / "pipeline"))
    from export_public import is_public_license
    corpus_tsv = ROOT / "data" / "corpus" / "corpus.tsv"
    non_cc = {
        r["pmcid"]
        for r in csv.DictReader(corpus_tsv.open(encoding="utf-8-sig"), delimiter="\t")
        if not is_public_license(r.get("license"))
    }
    manifest = json.loads((ROOT / "exports/public/manifest.json").read_text())
    manifest_pmcids = set(manifest["papers"])
    violation = non_cc & manifest_pmcids
    assert not violation, (
        f"{len(violation)} non-CC papers from corpus.tsv found in public manifest "
        f"(license policy violation): {sorted(violation)[:5]}"
    )
