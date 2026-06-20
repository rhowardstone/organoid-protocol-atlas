# Organoid Protocol Atlas

*Evidence-grounded extraction and comparison of organoid culture protocols.*

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

## Pipeline

```
paper (PMC)
  └─ Tier 0   Europe PMC JATS XML → methods + supplement + tables + figures + refs   (deterministic, no LLM)
  └─ Tier 1   local LLM (gemma3:12b) → OrganoidProtocol JSON, each value verbatim-grounded
  └─ Tier 2   local vision (gemma3:12b) on figure schematics → cross-modal "figure-confirmed" factors
  └─ Tier 3   detect protocols delegated to a citation ("…as previously described (Sato 2011)")
              → resolve + verify the cited paper (human-review queue; never auto-attribute provenance)
  └─ entity normalization (bFGF≡FGF2, RSPO1≡R-spondin1, …) → canonical knowledge graph
  └─ Datasette site: recipe cards · morphogen heatmap · consensus recipes · grounded Q&A
```

Corpus: **26 PMC papers across 8 organoid systems** (intestinal, gastric, cerebral, kidney,
liver, lung, retinal, pancreatic); corpus-wide evidence grounding ≈ **0.81**.

## What you can do

- **Browse protocols** — one recipe card per paper: cells, matrix, media, the signaling
  cocktail with concentrations, timeline/passaging/endpoints, and the source methods with
  every grounded value highlighted in context.
- **Morphogen grammar** (`/heatmap`) — every canonical signaling factor × every organoid
  system; which morphogens are universal (Noggin, Wnt3a, EGF…) vs. lineage-specific.
- **Consensus recipes** (`/consensus`) — the canonical recipe per organoid type: each
  factor's usage frequency (core cocktail vs. variable additions) + modal dose. Computed,
  not asserted; small-n types are labelled, never overstated.
- **Ask the Atlas** (`/ask`) — natural-language questions answered by a local model that
  retrieves from the knowledge graph, cites the source papers, and refuses when the corpus
  has no evidence.
- Full-text reagent search, per-reagent comparison across protocols, grounding-coverage view,
  light/dark themes.

## Evidence & honesty

- Every reagent's `evidence_quote` is checked to be a **verbatim substring** of the source;
  ungrounded values are not asserted as fact (`grounded=0`, shown as such).
- Tier 2 adds figure factors only as a **`figure_confirmed` annotation** on text-extracted
  values — vision corroborates, it doesn't inject unverified data.
- Tier 3 emits a **review queue**, not auto-ingested records — resolving the wrong citation
  would fabricate provenance, so attribution waits on human confirmation.
- Implausible units (e.g. a growth factor in mg/mL) are flagged, not silently "fixed".

## Repo map

```
organoid_demo/schema.py   OrganoidProtocol — the interface contract (versioned; do NOT change unversioned)
pipeline/
  tier0_extract.py     Tier 0: Europe PMC JATS → evidence bundles (--only for incremental)
  tier1_extract.py     Tier 1: local-LLM structured extraction + verbatim grounding
  tier2_vision.py      Tier 2: local vision on flagged figure schematics (cross-modal)
  fetch_figures.py     figure-image acquisition (PMC OA AWS S3 mirror; license-gated, local-only)
  tier3_detect.py      Tier 3: detect protocols delegated to a citation (the router signal)
  tier3_resolve.py     Tier 3: resolve + verify the cited paper (review queue)
  normalize.py         reagent entity canonicalization
  build_kg.py          build the SQLite knowledge graph (Datasette-servable)
serve/
  run.sh               serve the atlas (Datasette + templates + static + plugins)
  metadata.yaml        facets + canned comparison queries
  templates/           landing, recipe cards, /heatmap, /consensus, /ask
  static/atlas.css|js  theme + dark-mode toggle
  plugins/ask.py       grounded Q&A ask-proxy (RAG over FTS → local model)
data/
  corpus/corpus.tsv    PMC corpus manifest (selection metadata)
  evidence_bundles/    Tier 0 output — full bundles local-only (git-ignored); manifest committed
  figures/             Tier 2 figure cache — local-only (git-ignored)
  predictions/         Tier 1/2 predictions — local-only (git-ignored)
outputs/               committed metrics/summaries (no body text); loop_progress.md
tests/                 baseline regression + Tier-3 gating unit tests
docs/                  PLAN, RESEARCH_BRIEF, OSS_LANDSCAPE
```

Full text, figure images, and predictions are **local-only** (git-ignored); only metadata,
checksums, short citation snippets, and count-level summaries are committed.

## Run

```bash
# serve the atlas (builds the KG on first run if needed)
./serve/run.sh                      # → http://localhost:8002

# or run the pipeline yourself (local A100 + ollama)
python pipeline/tier0_extract.py            # evidence bundles
python pipeline/tier1_extract.py            # extraction + grounding
python pipeline/tier2_vision.py             # figure confirmation
python pipeline/build_kg.py                 # build data/kg/atlas.db
pytest -q                                   # tests
```

The `organoid_demo/` prototype (3-paper fixtures, rule-based baseline + eval harness) still
runs as the reproducible acceptance gate: `cd organoid_demo && python eval_protocol_extraction.py`.
