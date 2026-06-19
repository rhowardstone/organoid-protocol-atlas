# Organoid Protocol Atlas

*Evidence-grounded extraction and comparison of organoid culture protocols.*

Turn organoid-culture papers into structured, queryable, **evidence-grounded** protocol
records — capturing the axes along which protocols actually differ (source cells, matrix,
base media, signaling cocktail, timeline, passaging, endpoints), where every populated
value that can carry an evidence span does (provenance is mandatory on the fields that
matter, tracked elsewhere).

This is **not a scraper**. The research is in what's hard: entity normalization,
distinguishing *not reported* from *not extracted*, and resolving protocols stated by
reference to a cited source.

```
paper (PDF)
  └─ Tier 0  GROBID/PyMuPDF → methods + supplementary + tables + refs   (deterministic)
  └─ Tier 1  LLM extract → OrganoidProtocol JSON w/ evidence spans      (Haiku/Sonnet)
  └─ eval harness (the acceptance gate): field match · reporting status ·
             grounding · unit norm · wrong-bucket/dup  → routes escalation
  └─ queryable, comparable protocol atlas (typed KG nodes + citations)
```

## Status

Prototype stage. `organoid_demo/` is a working vertical slice (3-paper fixtures,
rule-based baseline + eval harness) that runs and reproduces a documented baseline.
The build target is to port it onto the `craig/` research substrate
(in the sibling `Claude-Code-Scientist` repo) and run Tier 0 + Tier 1 over a 25-paper
corpus against a gold set. See `docs/PLAN.md`.

## Repo map

```
organoid_demo/            the working prototype (the CONTRACT + baseline + eval harness)
  schema.py               OrganoidProtocol — the interface contract (do NOT change unversioned)
  corpus.py               3 representative methods fixtures (→ real PDF extraction on port)
  extractors.py           rule-based baseline + pluggable LLMExtractor (prompt included)
  store_query.py          SQLite store + grounded comparison query
  run_demo.py             end-to-end pipeline (extract → store → query)
  eval_protocol_extraction.py   the eval harness == the acceptance gate
  gold_annotations.json   hand-annotated gold (3 protocols now → grow to 30–50)
  ANNOTATION_GUIDELINES.md  how gold is produced + what the harness enforces
  HANDOFF.md              full build spec (architecture, tiers, iteration loop, cost)
  PORTING.md              prototype → craig/ module mapping
  outputs/                baseline predictions + metrics + error_analysis (reference)
pipeline/
  tier0_extract.py        Tier 0: XML-first evidence-bundle extraction (no LLM)
  tier1_extract.py        Tier 1: local-LLM structured extraction -> OrganoidProtocol (+ grounding)
  build_kg.py             build the SQLite protocol KG (Datasette-servable)
serve/metadata.yaml       Datasette config: facets + canned comparison queries (PaperStack serve layer)
data/
  corpus/pmc_oa_25.tsv    25-paper PMC-OA corpus manifest (selection only; no text yet)
  corpus/README.md        columns, selection policy, coverage, acceptance gate
  evidence_bundles/       Tier 0 output: full bundles local-only (git-ignored);
                          manifest.jsonl (metadata+checksums) + README committed
outputs/tier0/            evidence_bundle_summary.json + extraction_report.md
docs/
  PLAN.md                 first build target, sequencing, locked decisions, open questions
  RESEARCH_BRIEF.md       scientific landscape: NIH programs, ontologies, prior art, eval baselines
  OSS_LANDSCAPE.md        OSS tooling survey: reuse / avoid / differentiator
AGENTS.md                 operating contract for any agent working in this repo
```

## Run the prototype

```bash
pip install pydantic
cd organoid_demo
python run_demo.py                  # see the pipeline work
python eval_protocol_extraction.py  # metrics table + outputs/ (the acceptance gate)
```

Expected baseline (the failures are intentional eval fixtures — see HANDOFF.md §9):

```
Scalar exact match:        13/13 = 1.00
Reporting-status accuracy:  4/6  = 0.6667
Signaling factor precision:        0.70
Signaling factor recall:           1.00
Unit-normalization accuracy: 6/6  = 1.00
Evidence grounding:        10/10 = 1.00
Wrong-bucket / duplicate rate: 3/10 = 0.30
```

Start at `organoid_demo/HANDOFF.md` §10 for the first build task, then `docs/PLAN.md`.
