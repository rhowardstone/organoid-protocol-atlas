# Porting the prototype onto Claude-Code-Scientist

The prototype is deliberately a thin vertical slice. Each module maps to an
existing component in the real repo. The schema (`schema.py`) is the contract
and does not change; everything else is a backend swap.

| Prototype module      | Real repo target                                            | What changes on port |
|-----------------------|-------------------------------------------------------------|----------------------|
| `corpus.py`           | `craig/literature/extraction/{grobid,pymupdf,sections}.py`  | Methods text comes from real PDF → section extraction instead of fixtures. Same `{doi, text}` shape. |
| `extractors.py` (rule)| keep as the **baseline** in `workspace/evals`               | Stays. It is the control arm of the benchmark. |
| `extractors.py` (LLM) | `craig/llm_providers/`                                      | Wire `LLMExtractor(complete=...)` to the provider layer (Anthropic API or local vLLM on the A100s). Prompt already in `EXTRACTION_PROMPT`. |
| `extractors.py` (NER) | `craig/literature/knowledge_graph/scientific_ner.py`        | Reagent/cell-line/marker recognition graduates from a dictionary to the existing NER + a normalization pass (ChEBI/PR/CL/Uberon). This is where the R-spondin double-count gets solved. |
| `store_query.py`      | `craig/literature/knowledge_graph/{storage,schema,query}.py`| Protocols become typed KG nodes; `signaling_comparison` becomes a graph traversal. FAISS (`embeddings.py`) adds retrieval for the RAG path. |
| coverage note         | `workspace/evals/graders/provenance_grader.py`, `doi_validator.py` | The eval harness already exists. Add field-level exact-match, unit-normalization accuracy, and hallucinated-field graders alongside the provenance grader you already wrote. |

## The honest one-liner

> A general scientific-research substrate already existed, so the organoid-specific
> layer was built on top of it — schema, a baseline extractor, a grounded comparison
> query — specifically to find where the hard problems are. They're entity
> normalization and distinguishing "not reported" from "not extracted." That's where
> the research effort belongs.

## What is NOT done (current limitations)

- A 3-protocol *fixture* gold (`gold_annotations.json`) exists for harness validation;
  real accuracy numbers begin with a 10–12 protocol PMC-OA gold over actual extracted
  methods text. Current metrics are harness/pipeline sanity checks, not model accuracy.
- No ontology grounding → `ontology_id` fields are stubs.
- No retrieval/RAG path exercised → comparison is over a fixed 3-doc set.
- Rule baseline double-counts synonyms → demonstrates the normalization gap,
  not yet solved.
