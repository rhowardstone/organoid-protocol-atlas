import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_manifest_counts_match_render_copy():
    manifest = json.loads((ROOT / "exports/public/manifest.json").read_text())

    assert manifest["license_filter"] == "CC0/CC-BY (no NC/ND)"
    assert manifest["n_papers"] == 578
    assert manifest["tables"] == {"protocols": 578, "reagents": 5423}


def test_public_landing_page_does_not_claim_local_corpus_counts():
    html = (ROOT / "serve/templates/index.html").read_text()

    assert "578</div><div class=\"l\">public protocols" in html
    assert "5423</div><div class=\"l\">public rows" in html
    assert "0</div><div class=\"l\">full-text bodies" in html
    assert "/llms.txt" in html
    assert "28</div><div class=\"l\">protocols extracted" not in html
    assert "311</div><div class=\"l\">reagents" not in html


def test_llms_txt_route_documents_public_api_and_limits():
    plugin = (ROOT / "serve/plugins/ask.py").read_text()

    assert "LLMS_TXT" in plugin
    assert "578 papers, 578" in plugin
    assert "5423 public reagent/protocol rows" in plugin
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
