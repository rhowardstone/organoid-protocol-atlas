#!/usr/bin/env python3
"""
Figure-image acquisition for Tier-2 vision.

The per-article OA *packages* (figures, full PDFs) are FTP-only on NCBI and the
HTML render endpoints (ptpmcrender / .../bin/) are firewalled from this host.
The working route is the PMC Open Access mirror on the AWS Registry of Open Data
(S3, plain HTTPS, not firewalled):

    https://pmc-oa-opendata.s3.amazonaws.com/PMC<id>.<ver>/<file>.jpg

Figure images are copyrighted even when the article is CC-BY (CC licenses cover
the article, individual figures may carry separate terms), so:
  - we fetch ONLY for CC-/open-licensed papers (license gate), and
  - images are cached LOCAL-ONLY (data/figures/local/, git-ignored). Nothing
    binary is committed; only this fetcher + downstream structured outputs are.

Run:
    python pipeline/fetch_figures.py            # all license-clean papers
    python pipeline/fetch_figures.py PMC6906116 # one paper
"""

from __future__ import annotations

import csv
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "data" / "corpus" / "pmc_oa_25.tsv"
BUNDLES = REPO / "data" / "evidence_bundles" / "local"
FIG_DIR = REPO / "data" / "figures" / "local"
S3 = "https://pmc-oa-opendata.s3.amazonaws.com"

# Licenses under which we are willing to fetch+process figure images locally.
OPEN_LICENSES = {"cc-by", "cc-by-nc-nd", "cc-by-nc", "cc-by-sa", "cc0"}

# figure image keys vary by publisher:
#   NIHMS    nihms-1529307-f0001.jpg      Nature   ncomms9715-f3.jpg
#   Springer 41598_..._Fig4_HTML.jpg      EMBO     EMBJ-38-e100300-g002.jpg
#   Elsevier gr1_lrg.jpg / fx1.jpg (fx = graphical abstract)
# Exclude supplement / ESM / thumbnail blobs.
_FIG_RE = re.compile(r"(fig\d|fig_|[-_]f\d|^f\d|[-_]?gr\d|[-_]g\d{3}|[-_]?fx\d)", re.I)
_SKIP_RE = re.compile(r"(supplement|MOESM|ESM|_ESM|graphic_|inline|logo|-s\d)", re.I)


def load_corpus() -> dict:
    return {r["pmcid"]: r for r in csv.DictReader(open(CORPUS), delimiter="\t")}


def s3_list(pmcid: str) -> list[str]:
    """All S3 keys under the latest version prefix for a PMCID."""
    url = f"{S3}/?list-type=2&prefix={pmcid}."
    xml = urllib.request.urlopen(url, timeout=30).read().decode()
    keys = re.findall(r"<Key>([^<]+)</Key>", xml)
    if not keys:
        return []
    # keep the highest version (PMC....2/ over PMC....1/)
    vers = sorted({k.split("/")[0] for k in keys})
    latest = vers[-1]
    return [k for k in keys if k.startswith(latest + "/")]


def figure_keys(keys: list[str]) -> list[str]:
    out = []
    for k in keys:
        name = k.split("/")[-1]
        if name.lower().endswith((".jpg", ".jpeg", ".png", ".gif")) \
                and _FIG_RE.search(name) and not _SKIP_RE.search(name):
            out.append(k)
    return sorted(out)


def fetch(pmcid: str, license_: str) -> dict:
    lic = (license_ or "").strip().lower()
    if lic not in OPEN_LICENSES:
        return {"pmcid": pmcid, "license": license_, "skipped": "license-gated"}
    keys = figure_keys(s3_list(pmcid))
    if not keys:
        return {"pmcid": pmcid, "license": license_, "skipped": "no-figures-on-mirror"}
    dest = FIG_DIR / pmcid
    dest.mkdir(parents=True, exist_ok=True)
    figs = []
    for k in keys:
        name = k.split("/")[-1]
        fp = dest / name
        if not fp.exists():
            data = urllib.request.urlopen(f"{S3}/{k}", timeout=120).read()
            fp.write_bytes(data)
        figs.append({"key": k, "file": str(fp.relative_to(REPO)), "bytes": fp.stat().st_size})
    rec = {"pmcid": pmcid, "license": license_, "n_figures": len(figs), "figures": figs}
    (dest / "figures.json").write_text(json.dumps(rec, indent=2))
    return rec


def main():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    corpus = load_corpus()
    targets = sys.argv[1:] or list(corpus)
    for pmcid in targets:
        cm = corpus.get(pmcid, {})
        r = fetch(pmcid, cm.get("license", ""))
        if "skipped" in r:
            print(f"[skip] {pmcid} ({r.get('license')}): {r['skipped']}")
        else:
            print(f"[ok]   {pmcid} ({r['license']}): {r['n_figures']} figures -> {FIG_DIR / pmcid}")


if __name__ == "__main__":
    main()
