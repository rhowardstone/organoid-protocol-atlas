import csv
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_manifest():
    return json.loads((ROOT / "exports/public/manifest.json").read_text())


def test_public_manifest_counts_match_render_copy():
    """Manifest structure and license filter are correct; counts are internally consistent
    with each other and with the actual JSONL files (no hardcoded expected values so this
    test does not need updating with every corpus batch merge)."""
    manifest = _load_manifest()

    assert manifest["license_filter"] == "CC0/CC-BY (no NC/ND)"
    assert isinstance(manifest["n_papers"], int) and manifest["n_papers"] > 0
    tables = manifest.get("tables", {})
    assert "protocols" in tables and "reagents" in tables
    # protocols count must equal n_papers (one row per paper in this schema)
    assert tables["protocols"] == manifest["n_papers"], (
        f"manifest.tables.protocols={tables['protocols']} != n_papers={manifest['n_papers']}"
    )
    # reagents must be at least as many as papers (every paper has ≥1 reagent)
    assert tables["reagents"] >= manifest["n_papers"], (
        f"manifest.tables.reagents={tables['reagents']} < n_papers={manifest['n_papers']}"
    )


def test_public_landing_page_uses_manifest_template_vars():
    """Landing page must use Jinja2 template vars from manifest, not hardcoded counts."""
    html = (ROOT / "serve/templates/index.html").read_text()

    assert "{{ public_counts.n_papers }}" in html
    assert "{{ public_counts.n_reagents }}" in html
    assert "0</div><div class=\"l\">full-text bodies" in html
    assert "/llms.txt" in html
    # No hardcoded corpus counts that would go stale
    assert "28</div><div class=\"l\">protocols extracted" not in html
    assert "311</div><div class=\"l\">reagents" not in html


def test_llms_txt_counts_match_manifest():
    """ask.py must build LLMS_TXT from the manifest, not hardcode stale counts."""
    sys.path.insert(0, str(ROOT / "serve" / "plugins"))
    # Reload to pick up current module state
    import importlib
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ask", ROOT / "serve" / "plugins" / "ask.py"
    )
    mod = importlib.util.module_from_spec(spec)
    # ask.py imports datasette which may not be installed — check gracefully
    try:
        spec.loader.exec_module(mod)
    except ImportError:
        import pytest
        pytest.skip("datasette not installed")

    manifest = _load_manifest()
    n_papers = manifest["n_papers"]
    n_reagents = manifest["tables"].get("reagents", 0)
    llms = mod.LLMS_TXT

    assert str(n_papers) in llms, f"n_papers={n_papers} not in LLMS_TXT"
    assert str(n_reagents) in llms, f"n_reagents={n_reagents} not in LLMS_TXT"
    assert "does not redistribute" in llms
    # Counts must be consistent — no stale "10 papers" from old demo
    assert "papers: 10" not in llms
    assert "protocols: 10" not in llms


def test_llms_txt_route_documents_public_api_and_limits():
    plugin = (ROOT / "serve/plugins/ask.py").read_text()

    assert "LLMS_TXT" in plugin
    assert "_build_llms_txt" in plugin
    assert "does not redistribute" in plugin
    assert "/atlas/protocols.json" in plugin
    assert "/atlas/reagents.json" in plugin
    assert r"^/llms\.txt$" in plugin


def test_public_ask_page_is_honest_without_model():
    html = (ROOT / "serve/templates/pages/ask.html").read_text()

    # PR #133 updated phrasing; check current template text (ask.html line 21)
    assert "synthesis is unavailable" in html
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


def test_public_jsonl_line_counts_match_manifest():
    """protocols.jsonl and reagents.jsonl line counts must match manifest.tables values.
    Catches stale manifests (export run but manifest not regenerated, or vice versa)."""
    manifest = _load_manifest()
    tables = manifest.get("tables", {})
    for table_name, expected_count in tables.items():
        jsonl_path = ROOT / "exports" / "public" / f"{table_name}.jsonl"
        actual_count = sum(1 for ln in jsonl_path.read_text().splitlines() if ln.strip())
        assert actual_count == expected_count, (
            f"exports/public/{table_name}.jsonl has {actual_count} non-empty lines "
            f"but manifest.tables.{table_name}={expected_count} — "
            f"re-run pipeline/export_public.py to sync"
        )


def test_public_manifest_paper_list_matches_n_papers():
    """manifest.papers list length must equal manifest.n_papers."""
    manifest = _load_manifest()
    assert len(manifest["papers"]) == manifest["n_papers"], (
        f"manifest.papers has {len(manifest['papers'])} entries "
        f"but n_papers={manifest['n_papers']}"
    )


def test_public_manifest_has_schema_version():
    """Manifest must declare schema_version so consumers can detect breaking changes."""
    manifest = _load_manifest()
    assert "schema_version" in manifest, "manifest.json is missing 'schema_version'"
    assert manifest["schema_version"] == "0.4", (
        f"Expected schema_version '0.4', got {manifest['schema_version']!r}"
    )


def test_public_manifest_n_types_matches_protocols_jsonl():
    """manifest.n_types must match the actual count of distinct organoid_type values
    in protocols.jsonl — guards against stale manifests after corpus batch merges."""
    manifest = _load_manifest()
    assert "n_types" in manifest, "manifest.json is missing 'n_types'"
    protocols_jsonl = ROOT / "exports" / "public" / "protocols.jsonl"
    types_in_data = {
        json.loads(ln).get("organoid_type")
        for ln in protocols_jsonl.read_text().splitlines()
        if ln.strip()
    } - {None, ""}
    assert manifest["n_types"] == len(types_in_data), (
        f"manifest.n_types={manifest['n_types']} but protocols.jsonl has "
        f"{len(types_in_data)} distinct non-empty organoid_type values: {sorted(types_in_data)}"
    )


def test_corpus_has_no_hepatic_label():
    """corpus.tsv must contain no 'hepatic' organoid_type entries —
    all should have been normalised to 'liver' by relabel_organoid_type.py.
    Re-run: python pipeline/relabel_organoid_type.py"""
    corpus_tsv = ROOT / "data" / "corpus" / "corpus.tsv"
    hepatic_rows = [
        r["pmcid"]
        for r in csv.DictReader(corpus_tsv.open(encoding="utf-8-sig"), delimiter="\t")
        if r.get("organoid_type") == "hepatic"
    ]
    assert not hepatic_rows, (
        f"{len(hepatic_rows)} corpus.tsv rows still have organoid_type='hepatic'; "
        f"run pipeline/relabel_organoid_type.py to normalise: {hepatic_rows[:5]}"
    )


def test_discover_data_route_registered():
    """The public /discover-data.json endpoint (data behind the /discover view, PR #202)
    must stay registered — it is part of the public deployment surface."""
    plugin = (ROOT / "serve/plugins/discover_endpoint.py").read_text()
    assert r"^/discover-data\.json$" in plugin, "/discover-data.json route registration missing"
    assert "route_discover_data" in plugin


def test_public_view_pages_exist():
    """Every public view page linked from the navbar must exist as a template so the
    route it backs can't silently 500/404. Datasette serves templates/pages/<name>.html
    at /<name>, so a missing template means a dead nav link. Guards all 8 page-backed
    navbar routes (the navbar also links /trapi, served by a plugin not a page template).
    Previously only compare (PR #186) and discover (PR #202) were guarded; explore is the
    canonical human browse view (human_redirect.py redirects raw Datasette pages to it,
    enhanced in PR #214) and was unguarded — extended to the full set."""
    for page in (
        "ask.html",
        "compare.html",
        "consensus.html",
        "dashboard.html",
        "discover.html",
        "explore.html",
        "figures.html",
        "heatmap.html",
    ):
        assert (ROOT / "serve" / "templates" / "pages" / page).exists(), (
            f"public view page serve/templates/pages/{page} is missing"
        )


def test_public_jsonl_has_no_hepatic_label():
    """protocols.jsonl must contain no 'hepatic' organoid_type entries.
    Re-run pipeline/export_public.py after relabel_organoid_type.py."""
    protocols_jsonl = ROOT / "exports" / "public" / "protocols.jsonl"
    hepatic = [
        json.loads(ln).get("pmcid")
        for ln in protocols_jsonl.read_text().splitlines()
        if ln.strip() and json.loads(ln).get("organoid_type") == "hepatic"
    ]
    assert not hepatic, (
        f"{len(hepatic)} protocols.jsonl rows have organoid_type='hepatic'; "
        f"re-run pipeline/export_public.py after relabel_organoid_type.py: {hepatic[:5]}"
    )
