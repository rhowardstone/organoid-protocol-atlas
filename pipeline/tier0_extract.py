#!/usr/bin/env python3
"""
Tier 0 — Evidence-bundle extraction (deterministic, no LLM).

For each paper in data/corpus/corpus.tsv, fetch JATS full text (Europe PMC
fullTextXML first, NCBI efetch fallback) and extract a per-paper evidence bundle:
methods text, supplementary text, tables, references, and a section map.

IMPORTANT — licensing: full extracted text is NOT redistributable for the
author-manuscript / unknown-license rows in this corpus. So full bundles are
written ONLY to data/evidence_bundles/local/ (git-ignored). What is committed is
metadata + checksums + summaries:
  - data/evidence_bundles/manifest.jsonl   (per-paper metadata, NO body text)
  - outputs/tier0/evidence_bundle_summary.json
  - outputs/tier0/extraction_report.md

No LLM calls. No schema changes.

Run:
    python pipeline/tier0_extract.py            # all 25
    python pipeline/tier0_extract.py --limit 3  # smoke test
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import lxml.etree as ET

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "data" / "corpus" / "corpus.tsv"
LOCAL_DIR = REPO / "data" / "evidence_bundles" / "local"
MANIFEST = REPO / "data" / "evidence_bundles" / "manifest.jsonl"
OUT_DIR = REPO / "outputs" / "tier0"

UA = "organoid-protocol-atlas/0.1 (research; mailto:19674552+rhowardstone@users.noreply.github.com)"

METHODS_TITLE_RE = re.compile(
    r"(materials?\s*(and|&)\s*methods?|^\s*methods?\b|methodology"
    r"|experimental\s+(procedures?|methods?|section|design)|star\s*methods"
    r"|online\s*methods|methods?\s*summary)",
    re.I,
)
METHODS_SECTYPE_RE = re.compile(r"method|materials", re.I)
SUPP_RE = re.compile(r"supplementary|supporting\s+information", re.I)
# Sections that are NOT methods. A top-level body section is treated as
# methods/procedural unless its title matches one of these — this captures
# descriptively-titled methods (e.g. "Generation of human intestinal organoids")
# that title-only matching misses, while excluding intro/results/discussion/etc.
NON_METHODS_RE = re.compile(
    r"\b(introduction|background|results?|discussion|conclusion|abstract|"
    r"acknowledg|author\s+contribution|competing|conflict\s+of\s+interest|funding|"
    r"data\s+availability|code\s+availability|references?|bibliography|"
    r"supplementary|supporting\s+information)\b",
    re.I,
)


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #

def http_get(url: str, timeout: int = 40) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def fetch_xml(pmcid: str) -> tuple[str, bytes | None, str]:
    """Return (source_route, xml_bytes_or_None, note)."""
    numeric = pmcid.replace("PMC", "")
    # 1) Europe PMC JATS full text
    try:
        st, body = http_get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")
        if st == 200 and b"<article" in body:
            return "europe_pmc_xml", body, ""
    except urllib.error.HTTPError as e:
        note_epmc = f"epmc HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        note_epmc = f"epmc {type(e).__name__}"
    else:
        note_epmc = "epmc no <article>"
    # 2) NCBI efetch fallback
    try:
        st, body = http_get(
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={numeric}&rettype=xml"
        )
        if st == 200 and b"<article" in body:
            return "ncbi_efetch_xml", body, note_epmc
    except urllib.error.HTTPError as e:
        return "unavailable", None, f"{note_epmc}; efetch HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return "unavailable", None, f"{note_epmc}; efetch {type(e).__name__}"
    return "unavailable", None, f"{note_epmc}; efetch no <article>"


# --------------------------------------------------------------------------- #
# Parse
# --------------------------------------------------------------------------- #

def _text(el) -> str:
    return " ".join(t.strip() for t in el.itertext() if t and t.strip())


def _title(sec) -> str:
    t = sec.find("{*}title")
    return _text(t) if t is not None else ""


def parse_jats(xml_bytes: bytes) -> dict:
    parser = ET.XMLParser(recover=True, huge_tree=True, resolve_entities=False, load_dtd=False)
    root = ET.fromstring(xml_bytes, parser=parser)
    body = root.find(".//{*}body")
    warnings: list[str] = []
    article_type = root.get("article-type", "")

    all_secs = list(body.iter("{*}sec")) if body is not None else []
    top_secs = body.findall("{*}sec") if body is not None else []

    def _is_methods_sec(sec) -> bool:
        st = (sec.get("sec-type") or "").lower()
        if "supplementary" in st:
            return False
        if METHODS_SECTYPE_RE.search(st):
            return True
        # exclusion: a top-level section is methods/procedural unless recognizably not
        return not NON_METHODS_RE.search(_title(sec))

    body_method_secs = [s for s in top_secs if _is_methods_sec(s)]
    # back-matter methods (e.g. Nature "Online Methods")
    back = root.find(".//{*}back")
    back_method_secs = []
    if back is not None:
        for s in back.findall("{*}sec"):
            st = (s.get("sec-type") or "").lower()
            if METHODS_SECTYPE_RE.search(st) or METHODS_TITLE_RE.search(_title(s)):
                back_method_secs.append(s)
    method_secs = body_method_secs + back_method_secs

    # Full body text is always preserved in the (local-only) bundle so nothing is
    # lost when methods detection under-captures; methods_text is a convenience view.
    body_text = _text(body) if body is not None else ""
    body_chars = len(body_text)
    methods_detected = bool(method_secs)
    methods_text = "\n\n".join(_text(s) for s in method_secs) if methods_detected else body_text

    # section map = top-level body sections (title -> char length), for coverage diagnosis
    section_map: dict[str, int] = {}
    section_titles: list[str] = []
    for sec in top_secs:
        ti = _title(sec) or "(untitled)"
        section_titles.append(ti)
        section_map[ti] = len(_text(sec))

    # supplementary: inline supplementary-material + any supplement-titled sec
    supp_parts: list[str] = []
    n_supp_elems = 0
    for sm in root.findall(".//{*}supplementary-material"):
        n_supp_elems += 1
        supp_parts.append(_text(sm))
    for s in all_secs:
        if SUPP_RE.search(_title(s)):
            supp_parts.append(_text(s))
    supplementary_text = "\n\n".join(p for p in dict.fromkeys(supp_parts) if p)

    # tables
    tables = []
    for tw in root.findall(".//{*}table-wrap"):
        label = tw.findtext("{*}label") or ""
        cap_el = tw.find("{*}caption")
        caption = _text(cap_el) if cap_el is not None else ""
        tables.append({"label": label.strip(), "caption": caption, "text": _text(tw)})

    # references
    refs = []
    ref_els = root.findall(".//{*}ref-list//{*}ref") or root.findall(".//{*}ref")
    for r in ref_els:
        refs.append({"id": r.get("id", ""), "citation": _text(r)[:500]})

    XLINK = "{http://www.w3.org/1999/xlink}href"

    # figures: captions are text and often carry concentrations/timing; the graphic
    # href is recorded for a future Tier-2 vision pass (we do NOT read the image here).
    figures = []
    for f in root.findall(".//{*}fig"):
        cap = f.find("{*}caption")
        g = f.find(".//{*}graphic")
        figures.append({
            "label": (f.findtext("{*}label") or "").strip(),
            "caption": _text(cap) if cap is not None else "",
            "graphic_href": g.get(XLINK) if g is not None else None,
        })

    # external supplementary files ("attached things"): INVENTORY ONLY — we record
    # the filenames/types so we know what exists; downloading + parsing them (where
    # supplementary methods/data live) is a separate deterministic step.
    supplementary_files = []
    for sm in root.findall(".//{*}supplementary-material"):
        media = sm.find(".//{*}media")
        href = sm.get(XLINK) or (media.get(XLINK) if media is not None else None)
        mt = media.get("mimetype") if media is not None else None
        if href:
            supplementary_files.append({"label": (sm.findtext("{*}label") or "").strip(),
                                        "href": href, "mimetype": mt})

    # links/identifiers in the paper (data/code availability, protocols.io, accession URLs)
    links = []
    for el in root.findall(".//{*}ext-link"):
        href = el.get(XLINK)
        if href:
            links.append(href)
    links = list(dict.fromkeys(links))

    # warnings (diagnostics only, no body text)
    if not methods_detected:
        warnings.append("methods_fallback_full_body (no section delimiters; used whole body)")
    if back_method_secs:
        warnings.append(f"methods_in_back ({len(back_method_secs)})")
    if n_supp_elems and len(supplementary_text) < 400:
        warnings.append(f"supplement_external_only ({n_supp_elems} supp elems, captions only)")
    if not n_supp_elems:
        warnings.append("no_supplementary_material_inline")
    if tables:
        warnings.append(f"tables_present ({len(tables)}) — recipe may live in tables")
    if supplementary_files:
        warnings.append(f"external_supplement_files ({len(supplementary_files)}) NOT fetched — supp methods/data likely here (next step)")
    if figures:
        warnings.append(f"figures_present ({len(figures)}) — captions captured; graphics not read (Tier 2 vision)")
    if body is None:
        warnings.append("no_body_in_xml (front-matter only; likely not OA full text)")

    return {
        "methods_text": methods_text,
        "methods_detected": methods_detected,
        "body_text": body_text,
        "body_chars": body_chars,
        "supplementary_text": supplementary_text,
        "supplementary_files": supplementary_files,
        "figures": figures,
        "links": links,
        "tables": tables,
        "references": refs,
        "section_map": section_map,
        "section_titles": section_titles,
        "extraction_warnings": warnings,
        "article_type": article_type,
    }


def content_sha256(parsed: dict) -> str:
    payload = {
        "methods_text": parsed["methods_text"],
        "body_text": parsed["body_text"],
        "supplementary_text": parsed["supplementary_text"],
        "supplementary_files": parsed["supplementary_files"],
        "figures": parsed["figures"],
        "links": parsed["links"],
        "tables": parsed["tables"],
        "references": parsed["references"],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description="Tier 0 evidence-bundle extraction (XML-first, no LLM)")
    ap.add_argument("--limit", type=int, default=0, help="process only the first N rows (0 = all)")
    ap.add_argument("--only", default="", help="comma-separated PMCIDs to process (incremental; "
                                               "merges into the existing manifest)")
    ap.add_argument("--sleep", type=float, default=0.34, help="delay between fetches (politeness)")
    args = ap.parse_args()

    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(open(CORPUS), delimiter="\t"))
    only = {p.strip() for p in args.only.split(",") if p.strip()}
    if only:
        rows = [r for r in rows if r["pmcid"] in only]
    elif args.limit:
        rows = rows[: args.limit]

    manifest_records = []
    for i, row in enumerate(rows, 1):
        pmcid, doi = row["pmcid"], row["doi"]
        print(f"[{i}/{len(rows)}] {pmcid} ({row['organoid_type']}) ...", flush=True)
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        route, xml_bytes, note = fetch_xml(pmcid)

        if xml_bytes is None:
            rec = {
                "pmcid": pmcid, "doi": doi, "organoid_type": row["organoid_type"],
                "license": row["license"], "source_route": route, "fetched_at": fetched_at,
                "methods_chars": 0, "supplement_chars": 0, "table_count": 0,
                "reference_count": 0, "section_titles": [],
                "warnings": [f"fetch_failed: {note}"], "sha256": None, "bundle_committed": False,
            }
            manifest_records.append(rec)
            time.sleep(args.sleep)
            continue

        try:
            parsed = parse_jats(xml_bytes)
        except Exception as e:  # noqa: BLE001
            rec = {
                "pmcid": pmcid, "doi": doi, "organoid_type": row["organoid_type"],
                "license": row["license"], "source_route": route, "fetched_at": fetched_at,
                "methods_chars": 0, "supplement_chars": 0, "table_count": 0,
                "reference_count": 0, "section_titles": [],
                "warnings": [f"parse_failed: {type(e).__name__}: {e}"], "sha256": None,
                "bundle_committed": False,
            }
            manifest_records.append(rec)
            time.sleep(args.sleep)
            continue

        sha = content_sha256(parsed)
        bundle = {
            "doi": doi, "pmcid": pmcid, "organoid_type": row["organoid_type"],
            "license": row["license"], "source_route": route, "fetched_at": fetched_at,
            **parsed,
        }
        # full text -> LOCAL ONLY (git-ignored)
        (LOCAL_DIR / f"{pmcid}.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2))

        rec = {
            "pmcid": pmcid, "doi": doi, "organoid_type": row["organoid_type"],
            "license": row["license"], "source_route": route, "fetched_at": fetched_at,
            "methods_chars": len(parsed["methods_text"]),
            "methods_detected": parsed["methods_detected"],
            "body_chars": parsed["body_chars"],
            "supplement_chars": len(parsed["supplementary_text"]),
            "supplement_file_count": len(parsed["supplementary_files"]),
            "supplement_files": [s["href"] for s in parsed["supplementary_files"]],
            "figure_count": len(parsed["figures"]),
            "link_count": len(parsed["links"]),
            "table_count": len(parsed["tables"]),
            "reference_count": len(parsed["references"]),
            "section_titles": parsed["section_titles"],   # titles are structural metadata, not body text
            "warnings": parsed["extraction_warnings"],
            "sha256": sha, "bundle_committed": False,
        }
        manifest_records.append(rec)
        time.sleep(args.sleep)

    # write metadata manifest (NO body text). For incremental (--only) runs, merge
    # the freshly processed records into the existing manifest instead of clobbering it.
    if only and MANIFEST.exists():
        prior = [json.loads(l) for l in MANIFEST.read_text().splitlines() if l.strip()]
        done = {r["pmcid"] for r in manifest_records}
        manifest_records = [r for r in prior if r["pmcid"] not in done] + manifest_records
    with open(MANIFEST, "w") as f:
        for rec in manifest_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    write_summary(manifest_records)
    write_report(manifest_records)
    print(f"\nWrote {MANIFEST}, {OUT_DIR}/evidence_bundle_summary.json, extraction_report.md")
    print(f"Full bundles (local-only, git-ignored): {LOCAL_DIR}")


def write_summary(records: list[dict]):
    from collections import Counter
    routes = Counter(r["source_route"] for r in records)
    n = len(records)
    methods_ok = sum(1 for r in records if r["methods_chars"] > 0)
    supp_ok = sum(1 for r in records if r["supplement_chars"] >= 400)
    tables_any = sum(1 for r in records if r["table_count"] > 0)
    no_methods = sum(1 for r in records if any(w.startswith("no_methods_section") for w in r["warnings"]))
    fetch_failed = sum(1 for r in records if r["source_route"] in ("unavailable",))
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "papers": n,
        "source_routes": dict(routes),
        "methods_section_found": methods_ok,
        "no_methods_section": no_methods,
        "supplement_text_inline_ge400chars": supp_ok,
        "papers_with_tables": tables_any,
        "fetch_failed": fetch_failed,
        "license_breakdown": dict(Counter(r["license"] for r in records)),
        "median_methods_chars": _median([r["methods_chars"] for r in records]),
        "median_reference_count": _median([r["reference_count"] for r in records]),
        "papers_with_external_supplement_files": sum(1 for r in records if r.get("supplement_file_count", 0) > 0),
        "total_external_supplement_files": sum(r.get("supplement_file_count", 0) for r in records),
        "papers_with_figures": sum(1 for r in records if r.get("figure_count", 0) > 0),
        "total_figures": sum(r.get("figure_count", 0) for r in records),
        "papers_with_links": sum(1 for r in records if r.get("link_count", 0) > 0),
        "deferred_modalities": {
            "external_supplement_files": "inventoried, NOT downloaded/parsed yet (next deterministic step)",
            "figure_graphics": "captions captured; image content needs Tier 2 (targeted vision)",
            "cited_protocols": "'as previously described [ref]' resolution is Tier 3 (agent)",
        },
    }
    (OUT_DIR / "evidence_bundle_summary.json").write_text(json.dumps(summary, indent=2))


def _median(xs: list[int]):
    xs = sorted(xs)
    if not xs:
        return 0
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def write_report(records: list[dict]):
    lines = [
        "# Tier 0 — Evidence-Bundle Extraction Report",
        "",
        "Deterministic XML-first extraction over the 25-paper corpus. No LLM. Full text is",
        "local-only (git-ignored); this report and the manifest carry metadata + checksums only.",
        "",
        "| pmcid | type | route | methods_ch | supp_ch | supp_files | figs | links | tables | refs | warnings |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in records:
        warn = "; ".join(w.split(" (")[0] for w in r["warnings"]) or "-"
        lines.append(
            f"| {r['pmcid']} | {r['organoid_type']} | {r['source_route']} | "
            f"{r['methods_chars']} | {r['supplement_chars']} | {r.get('supplement_file_count', 0)} | "
            f"{r.get('figure_count', 0)} | {r.get('link_count', 0)} | {r['table_count']} | "
            f"{r['reference_count']} | {warn} |"
        )
    # aggregate
    from collections import Counter
    routes = Counter(r["source_route"] for r in records)
    methods_ok = sum(1 for r in records if r["methods_chars"] > 0)
    supp_ok = sum(1 for r in records if r["supplement_chars"] >= 400)
    tables_any = sum(1 for r in records if r["table_count"] > 0)
    supp_files = sum(r.get("supplement_file_count", 0) for r in records)
    supp_files_papers = sum(1 for r in records if r.get("supplement_file_count", 0) > 0)
    figs = sum(r.get("figure_count", 0) for r in records)
    lines += [
        "",
        "## Aggregate",
        f"- Papers: {len(records)}",
        f"- Source routes: {dict(routes)}",
        f"- Methods section found: {methods_ok}/{len(records)}",
        f"- Supplement text inline (>=400 chars): {supp_ok}/{len(records)} "
        "(low is expected — real supplements are external files, see below)",
        f"- Papers with external supplement files: {supp_files_papers}/{len(records)} "
        f"({supp_files} files total)",
        f"- Papers with figures: {sum(1 for r in records if r.get('figure_count',0)>0)}/{len(records)} "
        f"({figs} figures total)",
        f"- Papers with tables: {tables_any}/{len(records)} (recipe sometimes lives in tables)",
        "",
        "## What is captured vs. deferred (by design)",
        "Captured (Tier 0, deterministic text): methods prose, full body text, table text,",
        "**figure captions**, references, in-paper **links**, and an **inventory** of external",
        "supplement files (filenames/types).",
        "",
        "Deferred:",
        "- **External supplement files** (.doc/.pdf/.xlsx) — inventoried, not yet downloaded/",
        "  parsed. Supplementary methods/data often live here → the next deterministic step.",
        "- **Figure graphics** (timeline schematics, gels) — image content needs **Tier 2",
        "  (targeted vision)**; only captions are text-extractable now.",
        "- **Cited protocols** ('as previously described [ref]') — **Tier 3 (agent)**.",
        "",
        "## Next step (separate, on approval)",
        "- Run rule_based_v1 over the local bundles for the first real error analysis; and/or",
        "- Add the deterministic supplement-file fetch+parse pass (docx/pdf/xlsx) before Tier 1.",
    ]
    (OUT_DIR / "extraction_report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
