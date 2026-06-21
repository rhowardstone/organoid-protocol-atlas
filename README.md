# Organoid Protocol Atlas

*Evidence-grounded extraction, grounding, and analytics for organoid culture protocols.*

Turn organoid-culture papers into structured, queryable, **evidence-grounded** protocol
records — the axes along which protocols actually differ (source cells, matrix, base media,
signaling cocktail, timeline, passaging, endpoints) — where every extracted value that can
carry an evidence span is backed by a **verbatim quote** from the source and a DOI.

This is **not a scraper**. The work is in what's hard: entity normalization, distinguishing
*not reported* from *not extracted*, cross-modal confirmation from figures, and detecting
protocols stated by reference to a cited paper. The guiding rule throughout is
**missing evidence beats false evidence** — values without grounding are dropped or flagged,
never fabricated.

Everything runs on a **local A100** (models via [ollama](https://ollama.com)) — no API, no keys.

## Corpus

- **582 papers · 26 organoid types** (intestinal, cerebral, cardiac, kidney, liver, lung,
  pancreatic, thyroid, retinal, gastric, and more)
- **5,458 grounded reagent records** across the full corpus
- Schema v0.4: `FailureMode`, `ProtocolModification`, `Evidence.sentence_id`
- Public exports: `exports/public/protocols.jsonl`, `exports/public/reagents.jsonl`,
  `exports/public/manifest.json`

## Pipeline

```
paper (PMC)
  └─ Tier 0   Europe PMC JATS XML → methods + supplement + tables + figures + refs   (deterministic)
  └─ Tier 1   local LLM (gemma3:12b) → OrganoidProtocol JSON, each value verbatim-grounded
  └─ Tier 2   local vision (gemma3:12b) on figure schematics → cross-modal figure-confirmed factors
  └─ Tier 3   detect protocols delegated to a citation ("…as previously described (Sato 2011)")
              → resolve + verify the cited paper (human-review queue; never auto-attribute provenance)
  └─ S1       live SRI / Cellosaurus grounding → CURIE resolution with three-state reporting
  └─ S2       Biolink-validated KGX export (nodes.tsv + edges.tsv + kgx_manifest.json)
  └─ entity normalization (bFGF≡FGF2, RSPO1≡R-spondin1, …)
  └─ analytics pipeline → coverage · quality · consensus · failure modes · lineage · assay endpoints
  └─ REST API (Datasette plugin, 18 routes)
```

## Analytics API

All endpoints return JSON and degrade gracefully (404 + `hint` when not yet computed).

```
GET /analytics                          index of all endpoints + generate commands
GET /analytics/summary                  dashboard: corpus stats, quality distribution, top types
GET /analytics/status                   live system health (corpus + artifact inventory)
GET /analytics/consensus                list available per-type consensus files
GET /analytics/consensus/{type}         consensus concentrations + reagents + timeline for one type
GET /analytics/coverage                 per-type corpus coverage and completeness report
GET /analytics/coverage/{type}          coverage for one organoid type
GET /analytics/quality                  per-paper quality scores (gold ≥ 0.80 / silver ≥ 0.55 / bronze)
GET /analytics/reagent?q=TERM           cross-corpus reagent lookup: usage, concentrations, evidence quotes
GET /analytics/reagent-network?q=TERM  reagent co-occurrence: which reagents most often appear in the same papers
GET /analytics/type-similarity          pairwise organoid type Jaccard similarity on canonical reagent sets
GET /analytics/assay-endpoints          assay endpoint cluster summary (12 clusters, per-type + cross-type)
GET /analytics/failure-modes            failure mode cluster summary across the corpus
GET /analytics/lineage                  DOI→DOI protocol lineage graph (ProtocolModification data)
GET /analytics/compare/{a}/{b}          protocol diff between two papers (pre-computed cache)
GET /analytics/substitutions?q=TERM    search ProtocolModification records for reagent substitutions
GET /analytics/mior                     MIOR completeness per paper + corpus (12 items, 5 modules)
GET /analytics/candidates               OA/license verification status of candidate pool (issue #14)
```

### TRAPI (Translator Reasoner API 1.5)

```
POST /trapi/query                       single-hop Biolink query over the committed KGX graph
GET  /trapi/meta_knowledge_graph        KGX summary: node categories, predicates, edge counts
GET  /trapi                             HTML explainer + interactive try-it console
```

The TRAPI endpoint serves the committed `exports/kgx/{nodes,edges}.tsv` as a live-queryable
[TRAPI 1.5](https://github.com/NCATSTranslator/ReasonerAPI) graph. Nodes carry Biolink CURIEs
resolved via SRI; edges use `biolink:mentions` predicates. See `serve/plugins/trapi_endpoint.py`.

Generate all analytics outputs:

```bash
make all-analytics                              # regenerate everything in dependency order
# or individually:
python pipeline/generate_coverage_report.py     # → outputs/analysis/coverage_report.json
python pipeline/score_protocol_quality.py       # → outputs/analysis/protocol_quality_scores.json
python pipeline/compute_consensus.py --all      # → outputs/analysis/consensus_*.json
python pipeline/aggregate_failure_modes.py      # → outputs/analysis/failure_mode_summary.json
python pipeline/build_lineage.py                # → outputs/analysis/protocol_lineage.json
python pipeline/aggregate_assay_endpoints.py    # → outputs/analysis/assay_endpoint_summary.json
python pipeline/score_mior.py                   # → outputs/analysis/mior_completeness.json
python pipeline/check_concentration_consistency.py  # → outputs/validation/concentration_consistency.json
python pipeline/system_status.py                # check what's missing
```

## Evidence & honesty

- Every reagent's `evidence_quote` is a **verbatim substring** of the source — never paraphrased.
- Three-state `grounding_status`: `resolved` (real CURIE from SRI/Cellosaurus), `not_found`,
  `not_attempted`. Resolved means a real service response was cached as a fixture.
- Tier 2 adds figure factors only as a `figure_confirmed` annotation — vision corroborates,
  it doesn't inject unverified data.
- Tier 3 emits a **review queue**, never auto-ingested records.
- Implausible units (e.g. a growth factor in mg/mL) are flagged, not silently "fixed".
- No metric, count, or rate appears in docs unless generated by a committed artifact.
- `reported` / `not_reported` / `not_extracted` / `not_applicable` distinctions are preserved.

## Repo map

```
pipeline/
  tier0_extract.py           Tier 0: Europe PMC JATS → evidence bundles
  tier1_extract.py           Tier 1: local-LLM structured extraction + verbatim grounding
  tier2_vision.py            Tier 2: local vision on figure schematics (cross-modal)
  fetch_figures.py           figure-image acquisition (PMC OA AWS S3 mirror; local-only)
  tier3_detect.py            Tier 3: detect delegated-citation protocols
  tier3_resolve.py           Tier 3: resolve + verify cited paper (review queue)
  ground.py                  S1: live SRI Name Resolver + Cellosaurus grounding (cached fixtures)
  export_kgx.py              S2: Biolink-validated KGX export (nodes/edges TSV)
  normalize.py               reagent entity canonicalization
  ingest_orchestrator.py     discovery → QC → ingestion pipeline
  ingestion_auth.py          R4: ingestion authorization gate (who can ingest what tier)
  citation_expand.py         citation expansion (expand references of accepted papers)
  hybrid_discover.py         semantic + lexical hybrid discovery
  semantic_index.py          dense semantic index (sentence-transformers, A100)
  compute_consensus.py       consensus reagents/concentrations per organoid type
  aggregate_failure_modes.py failure mode cluster aggregation
  build_lineage.py           DOI→DOI protocol lineage graph
  generate_coverage_report.py per-type coverage + completeness scoring
  score_protocol_quality.py  per-paper quality scorer (gold/silver/bronze)
  aggregate_assay_endpoints.py assay endpoint cluster analysis (12 clusters)
  reagent_lookup.py          cross-corpus reagent search with concentration stats
  compare_protocols.py       pairwise protocol diff
  find_substitutions.py      ProtocolModification substitution search
  system_status.py           system health CLI (corpus + analytics artifact inventory)
  trapi.py                   minimal TRAPI responder shape
  export_public.py           export public protocols/reagents JSONL snapshots
  validate_evidence.py       evidence fidelity validator (verbatim substring checks)
  validate_predictions.py    prediction file schema validator (v0.4, offline, pre-PR gate)
  relabel_organoid_type.py   rescue corpus.tsv 'other' rows to discovery-CSV type (idempotent, --dry-run)
  audit_units.py             unit plausibility audit (R2: concentration vs. in-vivo/volume/percent)
  check_concentration_consistency.py  cross-paper concentration outlier detection (≥10x median)
  score_mior.py              MIOR completeness scorer (12 items, 5 modules, per-paper + corpus)
  score_protocol_quality.py  per-paper quality scorer (gold/silver/bronze)
  ground_predictions.py      S1→S2 handoff: ground prediction entities, write sidecars
  discover_candidates.py     keyword-based candidate discovery
serve/
  run.sh                     serve the atlas (Datasette + plugins)
  metadata.yaml              facets + canned queries
  plugins/
    analytics_endpoint.py    17-route analytics REST API (pure handlers + thin Datasette wrappers)
    ask.py                   grounded Q&A (RAG over FTS → local model)
  templates/                 landing, recipe cards, /heatmap, /consensus
  static/atlas.css|js        theme + dark-mode toggle
exports/
  public/
    protocols.jsonl          582 papers, 26 organoid types (public snapshot)
    reagents.jsonl           5,458 grounded reagent records
    manifest.json            counts + schema version
  kgx/
    nodes.tsv                KGX nodes (Biolink categories + CURIEs)
    edges.tsv                KGX edges (biolink:mentions predicates)
    kgx_manifest.json        counts + validation report
data/
  corpus/corpus.tsv          PMC corpus manifest
  corpus/incoming/           candidate CSVs (QC-gated, not yet ingested)
  predictions/local/         Tier 1/2 predictions (A100, git-ignored)
  predictions/local/grounded/ S1 grounding sidecars (git-ignored)
outputs/
  analysis/                  pre-computed analytics (coverage, quality, consensus, etc.)
  kgx/                       KGX graph export
  comparison/                pre-computed protocol diffs
tests/                       offline test suite (724 tests, no network, no GPU)
docs/                        SUPERVISOR_CHECKLIST.md, PLAN, RESEARCH_BRIEF
```

Full text, figure images, and predictions are **local-only** (git-ignored); only metadata,
count-level summaries, public snapshots, and grounded CURIEs are committed.

## Run

```bash
# serve the atlas
./serve/run.sh                          # → http://localhost:8002

# pipeline (local A100 + ollama)
python pipeline/tier0_extract.py        # evidence bundles
python pipeline/tier1_extract.py        # extraction + grounding
python pipeline/tier2_vision.py         # figure confirmation
python pipeline/ground.py               # S1: live SRI/Cellosaurus grounding
python pipeline/export_kgx.py          # S2: KGX graph export
python pipeline/system_status.py        # check health / what needs generating

# analytics pipeline (no GPU needed)
python pipeline/compute_consensus.py --all
python pipeline/generate_coverage_report.py
python pipeline/score_protocol_quality.py
python pipeline/aggregate_failure_modes.py
python pipeline/build_lineage.py
python pipeline/aggregate_assay_endpoints.py

make test                               # run offline test suite (724 tests)
make validate-batch                     # pre-PR check: tests + prediction schema + evidence
# or: pytest -q
```
