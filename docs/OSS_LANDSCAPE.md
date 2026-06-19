# OSS & Tooling Landscape — Protocol / Scientific IE

What exists for extracting and structuring scientific protocols, what works, what fails, and
what that implies for this project. Survey June 2026 (sourced; reproducibility/identifiability
stats are peer-reviewed and quotable; LLM-hallucination/schema-drift claims are preprint-grade;
**MIOR** is brand-new and unratified).

## Reuse (alive, permissive)
| Tool | Purpose | License | Note |
|---|---|---|---|
| **scispaCy** | biomedical NER + UMLS/MeSH/GO/HPO linking | Apache-2.0 | strongest off-the-shelf linker |
| **Cellosaurus** (+ API) | cell-line authority; `CVCL_*` accession *is* the RRID | CC-BY / GPL-3 | no fuzzy matcher — build our own |
| **SciCrunch / RRID resolver** | reagent/cell-line/tool RRID resolution | hosted (key) | service, not a library |
| **Google LangExtract** | schema-controlled LLM extraction with exact source grounding | Apache-2.0 | most relevant to our provenance core |
| **instructor / outlines** | Pydantic-validated / constrained-decoding structured output | MIT / Apache | |
| **BioCypher** | ontology-mapped biomedical KG construction | Apache-2.0 | maps extraction → CL/Uberon schema |
| **GraphRAG / KGGen / iText2KG** | LLM triple extraction + entity resolution over corpora | MIT / Apache | |
| **PaperQA2 / OpenScholar** | citation-grounded RAG over scientific PDFs | Apache-2.0 | model for the query layer |
| WNUT-2020 WLP, X-WLP, SciREX | wet-lab-protocol NER/RE data + doc-level IE | MIT / Apache | data/baselines (SciREX healthiest repo) |

## Avoid — the dead-standard trap
Do **not** invent a formal protocol ontology or executable language. EXACT and SMART Protocols
(dead 2014–19), Autoprotocol (dormant), Aquarium (winding down), BioCoder are graveyards. The
model that **won** is protocols.io: pragmatic, versioned, DOI'd, queryable records with
provenance — it won on citability and friction-removal, *not* machine semantics. LabOP/ex-PAML
(SBOL/COMBINE-backed) is the one credible executable-protocol survivor, but niche.

## What fails in practice (quotable)
- **Identifiability is the ceiling:** only 43% of cell lines / 55% of antibodies uniquely
  identifiable across >200 articles; 0 of 193 Cancer-Biology experiments designable from the
  paper alone. Detail an extractor simply cannot recover.
- **Entity normalization is hard:** gene-name homonyms ~66% in some corpora; spreadsheet
  gene-symbol corruption ~31% by 2021.
- **Access:** ~50% of articles paywalled; PDF is layout-only; critical detail hides in
  non-standardized **supplementary files** (mining them raised recall up to ~50%).
- **Schema brittleness:** fixed JSON schemas induce hallucinated field-fills, worst on the
  "no relation / unspecified" majority case.
- **Evaluation:** no common methodology for protocol IE; tables resist parsing.

## What users want / adoption lessons
- **Provenance is non-negotiable** — every fact traceable to a source span (Reactome makes the
  LLM emit quotations for verification).
- **Human-in-the-loop, low review burden** — full automation fails; if review costs more than
  manual curation, adoption collapses; hallucinated IDs destroy trust.
- **Friction/cost removal drives adoption** — protocols.io won on DOIs, versioning, free
  hosting, a usable API; formal ontologies died.
- **Capture tacit detail** Methods omit (the "5 µL not 1 µL" tweak).
- **Academic tools die** from bit-rot/install-friction — ship permissive OSS + Docker + stable
  hosting that fits existing workflow.
- **Organoid-specific:** the field admits a standardization gap; **MIOR** (Minimum Information
  about Organoid Research, 6 modules) recently proposed but unratified; Matrigel batch
  variability and "what is a high-quality organoid" are named, unresolved pains.

## Implications for this project
1. **Reuse, don't rebuild.** scispaCy + Cellosaurus/SciCrunch for entity grounding; LangExtract
   (or instructor/outlines) for schema-controlled extraction with built-in spans; BioCypher to
   map output to an ontology-grounded schema; PaperQA2/OpenScholar patterns for the query layer.
   Mine **supplementary files**, not just full text.
2. **Make span-level claim→evidence verification the differentiator, enforced as a QA gate.**
   Off-the-shelf builders do answer-level citations, not span-level field→evidence verification.
   Reject any protocol field not traceable to a supporting span — the trust feature curators
   actually want and competitors lack. (This is exactly what the eval harness measures.)
3. **Avoid the dead-standard trap.** Pragmatic, versioned, queryable record (JSON/graph) with
   DOIs and provenance — the model that won.
4. **Design for schema drift + HITL from day one.** Extensible schema; confidence and
   `unspecified`/`unknown` as first-class values (the common real answer); surface
   low-confidence fields for fast human review.
5. **Align to community norms.** Map records toward MIOR modules; explicitly capture variability
   culprits (Matrigel lot, passage number, media).
