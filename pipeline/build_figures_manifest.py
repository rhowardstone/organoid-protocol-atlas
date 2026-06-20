#!/usr/bin/env python3
"""Build the public CC-BY figure gallery manifest.

The source figure inventories, evidence bundles, and Tier-2 vision outputs are
local/A100 artifacts, so they are not expected to exist in a clean public clone.
When they are mounted, this script regenerates the committed static manifest
without committing image files or non-CC-BY papers.
"""

import csv, json, os, sys, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

ROOT = os.environ.get(
    "ORGANOID_ATLAS_ROOT",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)
CORPUS = os.path.join(ROOT, "data/corpus/corpus.tsv")
FIG_DIR = os.path.join(ROOT, "data/figures/local")
BUNDLE_DIR = os.path.join(ROOT, "data/evidence_bundles/local")
TIER2_DIR = os.path.join(ROOT, "data/predictions/local/tier2")
OUT = os.path.join(ROOT, "serve/static/figures.json")
S3_BASE = "https://pmc-oa-opendata.s3.amazonaws.com/"

if not os.path.exists(CORPUS):
    raise SystemExit(f"Missing corpus TSV: {CORPUS}")

def basename(p):
    return p.rsplit("/", 1)[-1] if p else ""

# 1. CC-BY papers only (exact match)
papers = []
with open(CORPUS, newline="") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        if row.get("license") == "CC-BY":
            papers.append({
                "pmcid": row["pmcid"].strip(),
                "doi": row.get("doi", "").strip(),
                "organoid_type": row.get("organoid_type", "").strip(),
            })

print(f"CC-BY papers in corpus: {len(papers)}")

def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def url_ok(url, timeout=25):
    try:
        req = urllib.request.Request(url, method="GET", headers={"Range": "bytes=0-1023"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status in (200, 206)
    except urllib.error.HTTPError as e:
        return e.code in (200, 206)
    except Exception:
        return False

# Gather candidate figures
candidates = []  # (paper, key, caption, label, is_schem, factors)
for p in papers:
    pmcid = p["pmcid"]
    figs = load_json(os.path.join(FIG_DIR, pmcid, "figures.json"))
    if not figs:
        print(f"  WARN no figures.json for {pmcid}")
        continue
    # double-check license inside figures.json too
    if figs.get("license") and figs.get("license") != "CC-BY":
        print(f"  SKIP {pmcid}: figures.json license={figs.get('license')}")
        continue

    bundle = load_json(os.path.join(BUNDLE_DIR, pmcid + ".json")) or {}
    bmap = {}
    for bf in bundle.get("figures", []):
        bn = basename(bf.get("graphic_href", ""))
        if bn:
            bmap[bn] = bf

    tier2 = load_json(os.path.join(TIER2_DIR, pmcid + ".json")) or {}
    t_by_file, t_by_label = {}, {}
    for tf in tier2.get("figures", []):
        if tf.get("file"):
            t_by_file[basename(tf["file"])] = tf
        if tf.get("label"):
            t_by_label[tf["label"].strip()] = tf

    for fig in figs.get("figures", []):
        key = fig.get("key")
        if not key:
            continue
        bn = basename(key)
        bf = bmap.get(bn)
        if bf:
            label = bf.get("label") or bn
            caption = bf.get("caption") or ""
        else:
            label = bn
            caption = ""
        # tier2 match by file basename, fallback label
        tf = t_by_file.get(bn)
        if not tf and label in t_by_label:
            tf = t_by_label[label]
        if tf:
            factors = [c.get("canonical") for c in tf.get("culture_factors", []) if c.get("canonical")]
            is_schem = bool(tf.get("is_protocol_schematic", False))
        else:
            factors = []
            is_schem = False
        candidates.append((p, key, caption, label, is_schem, factors))

print(f"Candidate figures (pre-verify): {len(candidates)}")

# 2. verify URLs live (parallel)
urls = [S3_BASE + c[1] for c in candidates]
with ThreadPoolExecutor(max_workers=16) as ex:
    results = list(ex.map(url_ok, urls))

records = []
skipped = 0
papers_included = set()
for (p, key, caption, label, is_schem, factors), url, ok in zip(candidates, urls, results):
    if not ok:
        skipped += 1
        continue
    records.append({
        "pmcid": p["pmcid"],
        "doi": p["doi"],
        "organoid_type": p["organoid_type"],
        "label": label,
        "caption": caption,
        "s3_url": url,
        "is_protocol_schematic": is_schem,
        "confirmed_factors": factors,
    })
    papers_included.add(p["pmcid"])

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    json.dump(records, f, indent=2, ensure_ascii=False)

print(f"\n=== RESULT ===")
print(f"Papers included: {len(papers_included)}")
print(f"Figures included: {len(records)}")
print(f"Skipped (non-200): {skipped}")
print(f"\nSamples:")
for r in records[:3]:
    print(f"  {r['pmcid']} | {r['label']} | {r['s3_url']} | factors={r['confirmed_factors']}")

# validate JSON
json.load(open(OUT))
print(f"\nVALID JSON: {OUT}")
