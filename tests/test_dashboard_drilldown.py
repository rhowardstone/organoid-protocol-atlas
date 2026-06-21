"""
Guard: the analytics dashboard's per-type rows must drill DOWN TO SOURCE — i.e. link to
the filtered protocol list (which leads to detail pages with DOI + verbatim quotes), not
only to the aggregate JSON endpoint. Regression guard for issue #114.
"""

from pathlib import Path

DASH = Path(__file__).resolve().parent.parent / "serve" / "templates" / "pages" / "dashboard.html"


def test_dashboard_type_rows_link_to_filtered_protocols():
    html = DASH.read_text()
    # both render paths (summary topTypes + coverage fallback) must drill to source
    assert html.count("/atlas/protocols?organoid_type__exact=${encodeURIComponent") >= 4


def test_drilldown_links_are_url_encoded():
    html = DASH.read_text()
    # never build the drill-down href from a raw, unencoded organoid_type
    assert "organoid_type__exact=${esc(r.organoid_type)}" not in html
