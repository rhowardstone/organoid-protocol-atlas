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

from datasette import hookimpl, Response

# Configurable so the public deployment can point at a tunneled A100, or leave it
# unset to serve a graceful "runs on the local model" message instead of erroring.
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
TOP_K = 12

LLMS_TXT = """# Organoid Protocol Atlas

Public, license-safe Datasette deployment of the Organoid Protocol Atlas.

Base URL: https://organoid-protocol-atlas.onrender.com
Source: https://github.com/rhowardstone/organoid-protocol-atlas

## What is available here

This public deployment contains the CC-licensed public subset: 10 papers, 10
protocol rows, and 122 public reagent/protocol rows. It does not redistribute
full methods text or paper bodies. Evidence fields are short citation snippets
kept so users and agents can trace claims back to the source paper.

The larger local pipeline tracks a verified 28-paper corpus and additional
candidate papers, but those are not all public on this hosted deployment.

## Useful endpoints

- /atlas/protocols.json?_shape=array&_size=max
- /atlas/reagents.json?_shape=array&_size=max
- /atlas/reagents.json?_shape=array&_size=max&kind__exact=signaling
- /-/ask?q=which%20factors%20define%20kidney%20organoids%3F

Datasette table pages also support faceting, filtering, sorting, and JSON
exports. Prefer the JSON endpoints for programmatic use.

## Evidence rules for agents

- Treat rows as extracted literature evidence, not clinical or wet-lab advice.
- Cite PMCID and DOI values from returned rows whenever making a claim.
- Do not infer that a factor is absent from biology because it is absent here.
- Respect grounding fields and evidence snippets; missing evidence beats false
  certainty.
- Natural-language synthesis from /-/ask is only available when the deployment
  can reach the local model; otherwise the endpoint returns retrieved evidence
  rows without model synthesis.

## Public subset counts

- papers: 10
- protocols: 10
- reagent/protocol rows: 122
- full text redistributed: no
"""

# organoid types we can detect in a question to bias retrieval
_TYPES = ["intestinal", "gastric", "cerebral", "kidney", "liver", "lung",
          "retinal", "pancreatic"]

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
