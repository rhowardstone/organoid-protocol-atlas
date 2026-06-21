"""
Grounded Q&A ask-proxy (Datasette plugin) — the PaperStack/CaseStack pattern,
retooled for the organoid corpus and pointed at a LOCAL model (A100, ollama).

Discipline (same as the rest of the pipeline): the model answers ONLY from rows
retrieved out of the knowledge graph (RAG over the FTS index), must cite the
source PMCIDs, and is told to refuse when the retrieved context does not contain
the answer — missing evidence beats false evidence. No outside knowledge, no API.

Routes:
- GET /-/ask?q=... -> {question, answer, sources:[...], grounded: bool}
- GET /llms.txt    -> agent-readable public API and provenance guide
"""

from __future__ import annotations

import asyncio
import json
import re
import os
import urllib.request
from pathlib import Path

from datasette import hookimpl, Response

# Configurable so the public deployment can point at a tunneled A100, or leave it
# unset to serve a graceful "runs on the local model" message instead of erroring.
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
TOP_K = 12

# Load public corpus counts from the committed manifest so llms.txt and the
# landing page stay in sync with the actual export — never hand-maintained.
_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "exports" / "public" / "manifest.json"
try:
    _manifest = json.loads(_MANIFEST_PATH.read_text())
except (FileNotFoundError, json.JSONDecodeError):
    _manifest = {"n_papers": 0, "tables": {}}

_N_PAPERS = _manifest.get("n_papers", 0)
_N_PROTOCOLS = _manifest.get("tables", {}).get("protocols", _N_PAPERS)
_N_REAGENTS = _manifest.get("tables", {}).get("reagents", 0)
_N_ROWS = _N_PROTOCOLS + _N_REAGENTS

# Expose manifest to Jinja2 templates (index.html uses {{ public_counts.n_papers }})
PUBLIC_COUNTS = {
    "n_papers": _N_PAPERS,
    "n_protocols": _N_PROTOCOLS,
    "n_reagents": _N_REAGENTS,
    "n_types": _manifest.get("n_types", 0),
}


def _build_llms_txt() -> str:
    _n_types = _manifest.get("n_types", 0)
    return f"""# Organoid Protocol Atlas

Public, license-safe Datasette deployment of the Organoid Protocol Atlas.

Base URL: https://organoid-protocol-atlas.onrender.com
Source: https://github.com/rhowardstone/organoid-protocol-atlas

## What is available here

This public deployment contains the CC-licensed public subset: {_N_PAPERS} papers, {_N_PROTOCOLS}
protocol rows, and {_N_REAGENTS} public reagent rows across {_n_types} organoid systems.
It does not redistribute full methods text or paper bodies. Evidence fields are short verbatim snippets
kept so agents can trace claims back to the source paper and DOI.

The larger local pipeline tracks a verified corpus and additional candidate papers,
but those are not all public on this hosted deployment. Schema version: 0.4.

## Table endpoints (Datasette JSON API)

- /atlas/protocols.json?_shape=array&_size=max
- /atlas/reagents.json?_shape=array&_size=max
- /atlas/reagents.json?_shape=array&_size=max&kind__exact=signaling
- /atlas/reagents.json?_shape=array&kind__exact=signaling&organoid_type__exact=kidney

Datasette table pages also support faceting, filtering, sorting, and JSON
exports. Prefer the JSON endpoints for programmatic use.

## Analytics REST endpoints (pre-computed, read-only)

- /analytics/summary          high-level corpus stats, quality distribution, top types
- /analytics/coverage         per-type corpus coverage and completeness (grounding rate, MIOR)
- /analytics/coverage/{type}  coverage for one organoid type (e.g. /analytics/coverage/kidney)
- /analytics/consensus/{type} consensus concentrations and reagents for one type
- /analytics/quality          per-paper quality scores (gold / silver / bronze tiers)
- /analytics/mior             MIOR completeness report (12-item, 5-module per paper)
- /analytics/reagent?q=EGF             cross-corpus reagent lookup with concentrations and evidence quotes
- /analytics/reagent-network?q=EGF     co-occurring reagents: which reagents appear in the same papers as EGF
- /analytics/type-similarity           pairwise Jaccard similarity between organoid types (canonical reagent sets)
- /analytics/type-timeseries           publication counts by year and organoid type (growth trends, first-appearance)
- /analytics/universal-reagents        canonical reagents in >= 50% of protocols per type; also cross-type universals
- /analytics/species-breakdown         species distribution per organoid type (human / mouse / other); ?type=kidney for one type
- /analytics/matrix-breakdown          extracellular matrix usage per organoid type (Matrigel / Geltrex / Vitronectin / ...); ?type=kidney for one type
- /analytics/base-media-breakdown      base media usage per organoid type (DMEM/F12 / mTeSR1 / Advanced DMEM/F12 / ...); ?type=kidney for one type
- /analytics/source-cell-breakdown     source cell type distribution per organoid type (iPSC / adult_stem_cell / primary_tissue / ESC); ?type=kidney for one type
- /analytics/protocol-complexity       per-type protocol complexity: avg n_signaling_factors, n_supplements, n_figure_confirmed, grounding_rate; ranked by complexity; ?type=kidney for one type
- /analytics/reporting-gaps            field reporting rates (species/matrix/base_media/source_cell_type/passaging/timeline) — transparency audit of systematic gaps; ?type=kidney for one type
- /analytics/year-trend                yearly trends: paper count, avg n_signaling_factors, avg grounding_rate, field reporting rates by publication year
- /analytics/grounding-quality         reagent grounding coverage: grounding_rate, evidence_quote_rate, suspect_unit_count by type and by kind; top ungrounded names for S1 prioritization
- /analytics/concentration-stats       aggregate concentration distributions per canonical reagent: median, min, max, std; top 50 by n_with_value; ?q=EGF for one reagent
- /analytics/temporal-reagent-adoption per-reagent temporal adoption: fraction of papers per year using each canonical reagent; ?q=EGF for year-by-year data, ?type=kidney for one type
- /analytics/kgx-summary               KGX graph state: n_nodes/n_edges by category, resolution rate, review queue breakdown, top not_found/needs_review entities for S1/S2 triage
- /analytics/concentration-by-type     per-organoid-type concentration stats for one canonical reagent; requires ?q=EGF; shows how dose differs across kidney/intestinal/liver/etc
- /analytics/journal-breakdown          journal contribution counts: cross-corpus top 50 + per-type top 5; ?type=kidney for full single-type breakdown
- /analytics/type-comparison           side-by-side organoid type comparison: shared/unique canonical reagents, Jaccard similarity, per-kind breakdown; ?a=intestinal&b=cerebral
- /analytics/concentration-deviation   dose inconsistency ranking: canonical reagents sorted by coefficient of variation (std/mean); most_variable and most_consistent lists; ?min_n= threshold
- /analytics/reagent-prevalence        type-breadth ranking: canonicals sorted by n_organoid_types; cross_field (>=20 types) + specialist (<=2 types) sub-lists; ?q=EGF for per-type breakdown
- /analytics/protocol-outliers         per-type outlier detection on n_signaling_factors: complex and minimal protocols with z-scores; ?type=kidney for one type; ?z_thresh= sensitivity
- /analytics/grounding-distribution    per-paper grounding rate histogram (10 buckets), per-type mean ranking, top/bottom 20 papers; ?type=kidney for one type; live from protocols.jsonl
- /analytics/type-maturity             field maturity per organoid type: first_year, trajectory (accelerating/stable/slowing), maturity_tier (established/developing/emerging); ?type=kidney
- /analytics/reagent-cooccurrence      pairwise signaling-factor co-occurrence: top pairs by n_papers with Jaccard similarity; ?q=EGF for all partners of one canonical; ?type= for one organoid type; ?min_papers= threshold
- /analytics/supplement-breakdown      per-type and cross-type breakdown of supplement canonicals: global top 50, cross-type list, per-type top 10; ?q=GlutaMAX for one canonical; ?type=kidney for one type; ?min_types= threshold
- /analytics/role-breakdown            normalized functional role distribution for signaling reagents: signaling_factor/growth_factor/differentiation/inhibitor/agonist etc.; ?q=differentiation for top canonicals; ?type= filter
- /analytics/type-reagent-heatmap      organoid type × canonical usage matrix: top_n canonicals (columns) × all types (rows), cell = n_papers; ?kind=signaling|supplement|all; ?top_n= (default 20)
- /analytics/canonical-name-variants   normalization complexity: for each canonical, all raw names that map to it; top 30 most-ambiguous by n_variants; ?q=FGF2 for one canonical; ?min_variants= threshold
- /analytics/concentration-unit-distribution  unit inconsistency report: canonicals using multiple unit systems; top 30 by n_units; ?q=EGF for full unit breakdown with min/median/max per unit; ?min_n= threshold
- /analytics/protocol-size-distribution  full histogram of n_signaling_factors and n_supplements per paper; global + per-type mean/median/std; ?type=kidney for one type with full histograms
- /analytics/evidence-quote-coverage   per-type and per-kind rate of verbatim evidence quotes in reagent records; overall_coverage_rate + by_kind breakdown + per_type sorted by coverage_rate; ?type=kidney for top canonicals; ?kind=signaling|supplement filter
- /analytics/failure-modes             failure mode cluster summary across the corpus
- /analytics/lineage                   DOI→DOI protocol lineage graph
- /analytics/assay-endpoints           assay endpoint cluster summary (per-type + cross-type)
- /analytics/candidates                OA/license verification status of the candidate pool
- /analytics                           index of all analytics endpoints with generate commands

## TRAPI (Translator Reasoner API 1.5)

The committed KGX graph (exports/kgx/nodes.tsv + edges.tsv) is live-queryable via TRAPI.

- POST /trapi/query                — single-hop Biolink query (TRAPI 1.5 request/response)
- GET  /trapi/meta_knowledge_graph — node categories, predicates, and edge counts
- GET  /trapi                      — HTML explainer and interactive console

Nodes carry SRI-resolved Biolink CURIEs; edges use biolink:mentions predicates connecting
organoid_protocol → reagent, with provenance back to the source PMCID and DOI.

## Grounded Q&A

- /-/ask?q=which%20factors%20define%20kidney%20organoids%3F

Natural-language synthesis is only available when the deployment can reach a local model;
otherwise the endpoint returns retrieved evidence rows without model synthesis.

## Evidence rules for agents

- Treat rows as extracted literature evidence, not clinical or wet-lab advice.
- Cite PMCID and DOI values from returned rows whenever making a claim.
- Do not infer that a factor is absent from biology because it is absent here.
- Respect grounding fields and evidence snippets; missing evidence beats false certainty.
- evidence_quote fields are verbatim substrings of the source paper's methods section.

## Public subset counts

- papers: {_N_PAPERS}
- organoid_types: {_n_types}
- protocols: {_N_PROTOCOLS}
- reagent rows: {_N_REAGENTS}
- schema_version: 0.4
- full text redistributed: no
"""


LLMS_TXT = _build_llms_txt()

# organoid types we can detect in a question to bias retrieval (all 26 schema types)
_TYPES = [
    "intestinal", "gastric", "cerebral", "kidney", "liver", "lung",
    "retinal", "pancreatic",
    "tumor", "cardiac", "vascular", "cholangiocyte", "skin", "mammary",
    "endometrial", "bone", "prostate", "inner-ear", "salivary-gland",
    "bladder", "neuromuscular", "esophageal", "blood-brain-barrier",
    "thyroid", "fallopian-tube",
    "hepatic",  # legacy alias in corpus; normalizes to liver post-marathon
]

# generic words that shouldn't drive retrieval (they match half the corpus)
_STOP = {
    "which", "what", "how", "does", "do", "is", "are", "the", "for", "with",
    "and", "or", "you", "can", "tell", "give", "list", "show", "about",
    "used", "use", "uses", "using", "define", "defines", "defining",
    "signaling", "signalling", "factor", "factors", "organoid", "organoids",
    "protocol", "protocols", "culture", "cultured", "cell", "cells",
    "reagent", "reagents", "concentration", "concentrations", "dose", "doses",
    "differentiation", "medium", "media", "make", "made", "generate", "grow",
}

PROMPT = """You are the Organoid Protocol Atlas assistant. Each CONTEXT line is a \
reagent that a paper ACTUALLY USED in the stated organoid type, with its role, dose, \
source DOI, and a verbatim evidence quote.

Answer the QUESTION from these rows:
- Treat a reagent appearing for an organoid type as evidence it is used in that system.
- Synthesize across the rows; name the concrete reagents (and doses/roles when shown).
- Cite the paper(s) inline as [PMCID].
- Use ONLY the context, not outside knowledge.
- Only if NONE of the rows are relevant to the question, reply exactly:
  "I don't have grounded evidence for that in the corpus."
- Be concise (2–4 sentences).

CONTEXT:
{context}

QUESTION: {question}
ANSWER:"""


def _fts_query(q: str) -> str:
    toks = [t for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]+", q)
            if len(t) > 2 and t.lower() not in _STOP]
    # quote each token so hyphens / numerals don't trip the FTS5 parser
    return " OR ".join(f'"{t}"' for t in toks) if toks else '""'


def _ollama(prompt: str) -> str:
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0, "num_predict": 400}}).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=120))["response"].strip()


async def ask(datasette, request):
    q = (request.args.get("q") or "").strip()
    if not q:
        return Response.json({"error": "pass ?q=your question"}, status=400)

    db = datasette.get_database("atlas")
    match = _fts_query(q)
    ql = q.lower()
    typ = next((t for t in _TYPES if t in ql), None)
    rows = []

    # 1) if the question names an organoid type, lead with that type's grounded
    #    signaling rows (the on-target context), so retrieval noise can't bury it.
    if typ:
        res2 = await db.execute(
            "SELECT pmcid, doi, organoid_type, kind, name, canonical, role, value, "
            "canonical_unit AS unit, evidence_quote, figure_confirmed FROM reagents "
            "WHERE organoid_type = :t AND kind='signaling' AND evidence_quote IS NOT NULL "
            "LIMIT :k", {"t": typ, "k": TOP_K})
        rows = [dict(r) for r in res2.rows]

    # 2) add FTS hits on the meaningful (non-stopword) terms.
    have = {(r["pmcid"], r["name"]) for r in rows}
    if match != '""':
        try:
            res = await db.execute(
                "SELECT r.pmcid, r.doi, r.organoid_type, r.kind, r.name, r.canonical, "
                "r.role, r.value, r.canonical_unit AS unit, r.evidence_quote, r.figure_confirmed "
                "FROM reagents r JOIN reagents_fts f ON r.id = f.rowid "
                "WHERE reagents_fts MATCH :m ORDER BY rank LIMIT :k",
                {"m": match, "k": TOP_K})
            for r in res.rows:
                d = dict(r)
                if (d["pmcid"], d["name"]) not in have:
                    rows.append(d)
                    have.add((d["pmcid"], d["name"]))
        except Exception:
            pass

    if not rows:
        return Response.json({
            "question": q, "grounded": False, "sources": [],
            "answer": "I don't have grounded evidence for that in the corpus.",
        })

    rows = rows[:TOP_K]
    ctx = "\n".join(
        f"[{r['pmcid']}] {r['organoid_type']} · {r.get('canonical') or r['name']}"
        f"{' ('+r['role']+')' if r.get('role') and r['role']!='not stated' else ''}"
        f"{' '+str(r['value'])+' '+(r.get('unit') or '') if r.get('value') is not None else ''}"
        f" — \"{(r.get('evidence_quote') or '').strip()}\" (doi:{r.get('doi')})"
        for r in rows)

    try:
        answer = await asyncio.to_thread(_ollama, PROMPT.format(context=ctx, question=q))
    except Exception:  # noqa: BLE001
        # No local model reachable (e.g. the public deployment has no A100/ollama).
        # Degrade gracefully: still return the grounded evidence rows, but be honest
        # that the natural-language synthesis runs on the local model only.
        return Response.json({
            "question": q, "grounded": False, "model_available": False,
            "answer": "Natural-language answers are generated by a local model on the "
                      "A100 and aren't available in this public deployment. The grounded "
                      "evidence retrieved for your question is shown below.",
            "sources": [
                {"pmcid": r["pmcid"], "doi": r["doi"], "organoid_type": r["organoid_type"],
                 "reagent": r.get("canonical") or r["name"], "value": r.get("value"),
                 "unit": r.get("unit"), "quote": r.get("evidence_quote")}
                for r in rows],
        })

    refused = "don't have grounded evidence" in answer.lower()
    # only surface sources the answer could have used (cited or all retrieved)
    return Response.json({
        "question": q, "grounded": not refused, "model": MODEL,
        "answer": answer,
        "sources": [] if refused else [
            {"pmcid": r["pmcid"], "doi": r["doi"], "organoid_type": r["organoid_type"],
             "reagent": r.get("canonical") or r["name"], "value": r.get("value"),
             "unit": r.get("unit"), "quote": r.get("evidence_quote"),
             "figure_confirmed": r.get("figure_confirmed")}
            for r in rows],
    })


async def llms_txt(datasette, request):
    return Response.text(LLMS_TXT)


@hookimpl
def register_routes():
    return [(r"^/-/ask$", ask), (r"^/llms\.txt$", llms_txt)]


@hookimpl
def extra_template_vars(datasette, request):
    """Inject manifest-derived counts into every Jinja2 template context."""
    return {"public_counts": PUBLIC_COUNTS}
