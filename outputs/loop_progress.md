
## Iteration 1 — 2026-06-20 — Visual QA (browser)
- Opened localhost:8002; screenshotted landing + a recipe card (Spence PMC3033971).
- Critique: recipe card is strong — axes grid + cocktail table (grounded/ungrounded badges) + the **source-methods panel with evidence spans highlighted in context works**. Landing is functional but flat/generic ("nice Datasette skin"). Faux pas: stat grid orphaned the 6th card ("140") onto its own row.
- Fix: `.apa-stats` -> balanced 6-across (responsive 3/2 on narrower). Verified visually (clean single row).
- Next: design polish (hero impact, feature-card hierarchy/typography), then extraction-completeness audit (read one paper fully — figures + supplement — vs what's in PaperStack).

## Iteration 2 — 2026-06-20 — Extraction-completeness audit + fix
- Audit (outputs/extraction_audit.md): Tier-1 filled only ~half the schema; small_molecules/timeline/passaging/assay_endpoints were 0/25 — the prompt never asked.
- Fix (no schema change): expanded Tier-1 prompt+mapping to extract timeline, passaging, assay_endpoints. Re-ran 25/25.
- Result: timeline 0→15/25, passaging 0→21/25, assay_endpoints 0→15/25; grounding 0.78.
- Honest limit found: long papers (e.g. Driehuis 81k methods) truncated at 9k window → passaging beyond the window missed. Next: chunk/raise cap for long methods.
- FLAGGED for supervisor: schema v0.3 new categories (culture_conditions temp/CO2/O2, seeding_density, passage_number, cell_line RRID) — needs approval before touching schema.py.
- Next: surface timeline/passaging/endpoints in KG + recipe card.

## Iteration 3 — 2026-06-20 — Surface new fields + CAUGHT & FIXED prompt-example parroting
- Surfaced timeline/passaging/assay_endpoints in KG (build_kg columns) + recipe card; browser-verified (Huch 2015 liver card renders all three + highlight panel).
- GUT-CHECK CAUGHT a real bug from iteration 2: my prompt's example values were being parroted — 'definitive endoderm' in 10/25 timelines, 'PAX6' in 13/25 endpoints, across unrelated organoid types (fabricated, inflated coverage).
- Fix: (1) removed parrotable examples from the prompt; (2) deterministic substring-grounding — drop any timeline stage / endpoint not appearing verbatim in the source text. Re-ran corpus.
- Result: parroting collapsed (definitive endoderm 10→1, PAX6 13→1, forskolin 12→0, Lgr5 12→0). Surviving endpoints now paper-specific & correct (liver→ALB/HNF4α, intestinal→CDX2, gastric→PAS staining). timeline 4/25 real (was 15/25 inflated). grounding 0.78.
- Lesson: never put parrotable concrete examples in an extraction prompt; ground free-text fields by substring. Note: 2/25 extraction errors this run (kept prior); full re-run ~16min, deferred.

## Iteration 4 — 2026-06-20 — Entity normalization (honest reuse call)
- Inspected craig/scientific_ner: it's a HF NER *tagger* (entity typing), NOT a synonym canonicalizer — wrong tool for collapsing R-spondin variants. Reused the prototype's NAME_CANON *insight* instead of force-fitting; scientific_ner deferred to when we need entity DETECTION on raw text.
- Built pipeline/normalize.py: curated organoid-reagent CANON map (bFGF=FGF2, RSPO1=R-spondin1, Y-27632 incl 'ROCK inhibitor Y-27632', ...) + corpus-aware collapse of case/space/punct variants. Wired a `canonical` column into the KG; comparison query + per-reagent links + a facet now group by canonical.
- Result: signaling 85 raw → 65 canonical (20 collapsed). R-spondin1 ← {R-Spondin1,RSPO1,R-spondin 1,R-spondin}; FGF2 ← {FGF2,bFGF}; Activin A, SB431542, A83-01 collapsed; R-spondin3 kept distinct (correct). Browser/JSON-verified.
- Surfaced real variety: R-spondin1 as recombinant (ng/mL) vs conditioned-medium (%v/v) — a genuine cross-protocol comparison insight.
- Next: A100 vision (Qwen2.5-VL, solve figure fetch); then frontend parity (Q&A/heatmap/dark mode); ChEBI/PR ontology_id enrichment later.

## Iteration 5 — 2026-06-20 — A100 vision (Tier-2) on REAL figures
- Solved the figure-fetch blocker: NCBI OA packages are FTP-only and the HTML render
  endpoints (ptpmcrender / .../bin/) hang behind this host's firewall. Working route =
  the PMC Open Access mirror on the AWS Registry of Open Data (S3 over HTTPS, not
  firewalled): https://pmc-oa-opendata.s3.amazonaws.com/PMC<id>.<ver>/<file>.jpg
- pipeline/fetch_figures.py: license-gated (CC-/open only) S3 figure acquisition; images
  cached LOCAL-ONLY (data/figures/local/, git-ignored). 59 figures across 8 CC papers.
- pipeline/tier2_vision.py: gemma3:12b (A100) vision on caption-FLAGGED schematics only
  (router/cost guardrail — 24 of 59 figures), grounded against paper text. Verified the
  model reads figures correctly (schematic vs microscopy classification is right; OCR is
  accurate — it transcribed "Protocol schematic", marker names, factor abbreviations).
- Measured honestly: substring-grounding alone leaks noise (panel labels A.MH, reporters
  mCherry/shNT, assay compounds cisplatin/lucifer-yellow pass because they appear in body
  text). Added a culture-factor vocabulary gate (normalize.canonical_or_none + FIG_ABBREV:
  ACTA->Activin A, NOG->Noggin, SB->SB431542). Gate -> 10 clean factors, 0 noise.
- KEY FINDING: 9/10 gated figure-factors were ALREADY in the Tier-1 text extraction; only
  1 net-new (Forskolin, PMC6376275 — and that's the CFTR swelling *assay* reagent, not a
  culture factor, so auto-merging would have been WRONG). So Tier-2's value here is
  CROSS-MODAL CORROBORATION, not new reagents. Merged as an ANNOTATION only:
  reagents.figure_confirmed / protocols.n_figure_confirmed. 7 reagents now confirmed by
  both text + figure schematic (lung Activin A/Noggin/SB431542/SAG/FGF4, kidney CHIR99021,
  retinal Retinoic acid). Surfaced: 📷 badge + cocktail-header count + reagents facet.
- Did NOT inject noisy figure reagents into the KG (build discipline: prove the metric,
  don't merge "looks better"). Vision-broad outputs kept as local experimental artifacts.
- Next: scale flagging beyond caption cues (some schematics have terse captions); consider
  Qwen2.5-VL for harder OCR; then frontend parity (#8: Q&A / heatmap / dark mode).

## Iteration 6 — 2026-06-20 — Morphogen-grammar heatmap (frontend parity #8, part 1)
- Built /heatmap: a Datasette custom page (serve/templates/pages/heatmap.html) rendering
  the signature view — canonical signaling factor (rows) × organoid type (cols), colour =
  #protocols, 📷 = figure-confirmed (Tier-2). Client-side aggregation from the reagents JSON
  API; cells link to the filtered reagents view; row/col headers drill down; a "used in ≥N
  types" control. Styled in serve/static/atlas.css (CSS grid + color-mix intensity ramp),
  on-brand with the existing theme. Linked from index topbar + a feature card.
- USING the viz surfaced a real normalization bug: "Retinoic acid" and "all-trans retinoic
  acid" were separate rows. Fixed in normalize.CANON (alltransretinoicacid/atra -> Retinoic
  acid). Rebuilt: 65 -> 64 canonical signaling; Retinoic acid now unifies 4 surface forms.
- The grammar is legible at a glance: Noggin (7/8), Wnt3a/Activin A/EGF (6), CHIR/FGF2/
  R-spondin1/Y-27632 (5) are near-universal; FGF10/A83-01 cluster on endodermal systems;
  SB431542/SAG on neural. Tests green.
- Next (frontend parity cont.): dark mode toggle, then a grounded AI Q&A ask-proxy on the
  local model (must cite evidence spans — missing evidence beats false evidence).

## Iteration 7 — 2026-06-20 — Dark mode + grounded AI Q&A ask-proxy (frontend parity #8 done)
- Dark mode: global serve/static/atlas.js (toggle injected on every Datasette page,
  persisted in localStorage, applied pre-paint) + a full dark palette in atlas.css
  ([data-theme="dark"]). Caught a bug while testing — the top bar used var(--ink) for its
  background, which flips light in dark mode; added a dedicated --bar (stays dark in both).
  Verified across index/heatmap/ask/table views.
- Grounded Q&A ask-proxy: serve/plugins/ask.py (Datasette register_routes -> /-/ask).
  RAG over the FTS index: retrieve reagent rows (organoid-type-led + FTS on meaningful,
  non-stopword terms), feed ONLY those rows to a LOCAL model (llama3.1:8b via ollama), force
  inline [PMCID] citations, and refuse ("I don't have grounded evidence...") when nothing
  relevant is retrieved. No API. serve/templates/pages/ask.html renders the answer (citations
  linked to recipe cards), a grounded/no-evidence badge, and evidence cards (reagent, dose,
  verbatim quote, DOI, 📷).
- Tested honestly: first version over-refused because FTS matched stopwords (which/signaling/
  factors) and pulled off-topic rows; fixed with a stoplist + organoid-type-led retrieval +
  a synthesize-from-usage prompt. Faithfulness verified against the KG (kidney CHIR 3.0 μM
  matches PMC4620584; recovered "8-10 μM" from PMC4747858's evidence quote where the parsed
  value was null); refuses on out-of-corpus questions ("best pizza topping").
- Added serve/run.sh (reproducible launch incl. --plugins-dir). Tests green.
- Next: Tier-3 protocol-by-reference via craig/citation_expander+acquisition (#9, ≤20% cap);
  design polish (#2).

## Iteration 8 — 2026-06-20 — Tier-3 protocol-by-reference: detection + feasibility (#9)
- Audited craig before building (per instruction). craig/literature/citation_expander.py +
  acquisition.py are CORPUS-EXPANSION tools (given seeds, discover MORE related papers via
  OpenAlex/Semantic-Scholar graphs) and pull heavy deps (sentence-transformers ~500MB +
  internal API clients). That's the wrong tool for "resolve a specific in-text citation to
  its protocol source" — same honest call as scientific_ner in iter 4; did NOT force-fit.
  Only craig/doi_fetcher.py (CrossRef DOI->metadata, no auth) is cleanly reusable later.
- Right architecture = reuse MY OWN Tier-0 (PMCID->methods via Europe PMC) on the cited
  paper. Built pipeline/tier3_detect.py: flags papers that DELEGATE their culture protocol
  to an EXTERNAL citation ("differentiation ... as previously described [11]"). Gating:
  external-only (excludes self-refs "step 13"/"section above"/"Extended Procedures"),
  culture-context-only (excludes sequencing/immuno/mouse/imaging assay delegations),
  requires a resolvable citation marker (numbered ref or "(Author et al., year)").
  Result: 9/25 papers delegate a culture protocol — the ≤20% cap = 5, so Tier-3 MUST
  prioritize (more papers delegate than the cap allows; logged, not hidden).
- Proved resolution feasibility: Europe PMC free-text search resolves "Sato 2011 intestinal
  organoid Lgr5" -> the right Sato 2011 papers. BUT a loose "Kadoshima forebrain 2013" query
  returned 2025/2026 reviews — so resolution MUST use fielded (AUTH:/PUB_YEAR:) queries +
  verification before attributing protocol to a cited DOI. Fetching the wrong paper would
  fabricate provenance (core invariant) — so the fetch+extract+attribute build is deferred to
  its own iteration with verification discipline, NOT rushed here.
- Committed the detector + candidates.json (router signal) + unit tests (5, gating logic on
  synthetic text — CI-safe, no corpus needed). Full suite green (7).
- Next: build Tier-3 fetch+extract+attribute on the verified-resolvable subset (provenance =
  the CITED paper's DOI, clearly labeled "inherited via reference"); then design polish #2.

## Iteration 9 — 2026-06-20 — Tier-3 resolve+verify; honest STOP on auto-ingestion (#9)
- Built pipeline/tier3_resolve.py: resolves NAMED culture-protocol delegations to the cited
  paper's PMCID via a FIELDED Europe PMC query (AUTH:/PUB_YEAR:), then VERIFIES before trust.
- Finding 1 — named citations are rare here: only PMC6376275 (lung/EMBO) uses parenthesized
  "(Author, year)" form (Sato 2011, Dekkers 2013, Koo 2011); the rest use numbered superscript
  refs, which need fragile marker->reference-list mapping and are deliberately NOT auto-resolved
  (would risk false provenance). Also fixed an nbsp/space bug in the named-citation regex
  ("Sato et\xa0al , 2011 )").
- Finding 2 — auto-resolution is UNSAFE (the important one): my first verification gate
  (author+year+loose topic) resolved "Koo 2011" to a MAMMARY-gland paper. Strengthened the gate
  to require an organoid/intestinal/Lgr5/crypt term in the TITLE; Koo now correctly falls to
  UNVERIFIED, Sato->Lgr5/crypt paper and Dekkers->CFTR-organoid paper verify. But residual
  ambiguity remains (two valid "Sato 2011" organoid papers exist; the resolver can't know which
  one the authors cited).
- DECISION (STOP-AND-ASK per invariants): Tier-3 output is a HUMAN-REVIEW QUEUE
  (outputs/tier3/resolved.json), NOT auto-ingested into the authoritative KG. Auto-attributing
  an inherited protocol to a resolved DOI would fabricate provenance given the Koo-class false
  positives + Sato-class ambiguity. Recommend: surface "this paper delegates its protocol to
  [ref]" as a flagged provenance note for the delegating papers, and only ingest inherited
  protocols after human confirmation. Needs supervisor OK before any KG ingestion.
- Committed detection + resolve/verify + 8 CI-safe unit tests (gating logic, no network/corpus).
  Full suite green (10).

## Iteration 10 — 2026-06-20 — Design polish + UX gut-check (#2)
- Used the site as a user across index / protocols-table / recipe card, light + dark, and a
  390px mobile viewport (stats reflow 2-up, cards stack, topbar wraps — responsive OK).
- Correctness: landing stats were stale — fixed reagents 280->287, grounding 77%->81%
  (improved since entity-norm + rebuilds), supplement files 140->144, to match the live KG.
- Dark-mode faux-pas caught + fixed: the source-methods highlighter panel (.apa-source) had a
  hardcoded dark text colour (#2b343d) -> dark-on-dark, nearly invisible in dark mode. Switched
  to var(--ink); verified computed colour now light (rgb(230,237,243)) with yellow highlights
  still legible. Datasette table views + custom pages otherwise theme cleanly.
- Tests green.

## Iteration 11 — 2026-06-20 — NEW category: consensus recipes (/consensus) (#11)
- Built /consensus: per organoid type, the canonical recipe synthesized from the corpus —
  each canonical signaling factor's usage frequency across that type's protocols, split into
  CORE cocktail (used by >=50%) vs VARIABLE additions, with the modal dose (+N others) and a
  link to the evidence. Client-side aggregation from protocols + signaling reagents JSON.
- Grounded + honest: shows k/n per factor; small-n types are labelled, not overstated
  ("single protocol — not a consensus" for retinal n=1; "only 2 protocols — provisional" for
  gastric). Verified content: intestinal core = EGF/Noggin/R-spondin1 (3/3) + Wnt3a (2/3) —
  the canonical ENR cocktail. Works in light + dark.
- Normalization win surfaced by the view: "Prostaglandine E2" now collapses to PGE2 (CANON);
  64 -> 63 canonical signaling factors. Rebuilt KG. Tests green (10).
- Linked from index topbar + a feature card.

## Iteration 12 — 2026-06-20 — Corpus expansion (retinal) + incremental pipeline (#12)
- Added incremental --only flags to tier0_extract.py and tier1_extract.py so new papers are
  fetched/extracted WITHOUT re-processing (or perturbing) the stable corpus; both merge into the
  existing manifest/summary rather than clobbering.
- Curated + added one new retinal methods paper: PMC11194494 (Harkin 2024, PNAS, CC-BY-NC-ND) —
  "highly reproducible/efficient retinal organoid differentiation". Clean extraction: BMP4
  50 ng/mL + LDN-193189 200 nM (canonical retinal induction), 100% grounded; Tier-2 vision ran
  on its figures too.
- GUT-CHECK rejected a second candidate (PMC6895716, Brooks 2019): thin methods (2271 chars) led
  the model to misclassify retinal MARKER genes (CHX10/VSX2, BRN3A, PKCα, CALB) as signaling
  factors. Ingesting it would pollute the heatmap/consensus — removed it (manifest + bundle +
  pred + pruned reporting artifacts). Quality over quantity; missing data beats false data.
- Result: corpus 25->26, retinal 1->2 (consensus now "provisional" not "single protocol"),
  reagents 293, figure_confirmed 9, corpus grounding held at 0.81. Landing stats updated. Full
  vision_summary regenerated (9 CC papers). Tests green (10).
- Note: gastric (n=2) still needs a clean foundational paper — search returned only reviews;
  deferred to careful curation. data/corpus/pmc_oa_25.tsv filename now understates the count
  (26) — rename to corpus.tsv is a pending cleanup (5 refs).

## Iteration 13 — 2026-06-20 — README refresh + corpus-file rename (repo presentation)
- Renamed data/corpus/pmc_oa_25.tsv -> corpus.tsv (the "25" understated the grown corpus);
  updated the 4 code/doc refs; build_kg + tests verified green. (separate commit)
- Rewrote README.md: it was stale (described the GROBID/Haiku prototype, "no text yet", 25
  papers) and mentioned NONE of the built system. Now accurately documents the real pipeline
  (Tier 0 Europe PMC XML → Tier 1 local gemma3 + grounding → Tier 2 vision figure-confirmation
  → Tier 3 protocol-by-reference review queue → normalization → KG), the four views
  (recipe cards, /heatmap, /consensus, /ask), the evidence/honesty guarantees, the current repo
  map, run instructions (serve/run.sh), and the local-A100/no-API stance. De-id verified clean.
- Next: gastric still needs a clean foundational paper (deferred); otherwise keep asking what
  NEW category adds value. Flagged (supervisor): #5 schema v0.3, #10 Tier-3 ingestion.

## Iteration 14 — 2026-06-20 — Gastric expansion + non-reagent guard (corpus + quality)
- Targeted curation found the clean foundational gastric paper: PMC7951181 (Broda 2019,
  Nat Protoc, "Generation of human antral and fundic gastric organoids"). Tier-0 (NCBI efetch,
  40k methods chars) -> Tier-1. Gastric 2->3, crossing the consensus threshold.
- GUT-CHECK caught the model listing equipment/software as signaling factors ("Nikon A1
  confocal", "NIS-Elements software"). Rather than reject the key paper, added a deterministic
  NON-REAGENT guard to tier1 (is_non_reagent: instruments/microscopes/software/imaging systems)
  — a generalizable quality check like suspect_unit. Broda now: Activin A, BMP4, FGF4, FGF10,
  CHIR99021, Retinoic acid (6 clean canonical factors). Scan of all existing preds: 0 residual
  junk (guard is conservative, no false positives). +2 unit tests.
- Normalization: added spelled-out aliases (Bone morphogenetic protein 4->BMP4, Fibroblast
  growth factor 4/10->FGF4/10, epidermal/hepatocyte/VEGF) so Broda's long-form names merge with
  the rest. Verified BMP4/FGF10 now unify surface forms.
- Result: corpus 26->27, reagents 299, grounding held 0.816, gastric consensus now "7 core · 8
  variable" (Activin A/BMP4/CHIR/EGF/FGF4/FGF10/RA core — sensible endoderm->gastric induction).
  Stats updated. Tests green (12).

## Iteration 15 — 2026-06-20 — Retinal #3: every organoid type now n>=3 (milestone)
- Goal: make every type's /consensus non-provisional (retinal was the last at n=2).
- Tried Capowski 2019 (PMC6340149, the canonical retinal staging paper) — but its PMC record
  is front-matter only (no OA full-text body via Europe PMC or efetch), so 0 methods extracted.
  Removed it cleanly (unusable, not noisy).
- Added Bohrer 2025 (PMC12625545, Stem Cell Res Ther, CC-BY, "clinical-grade iPSC retinal
  organoids w/ transplantable photoreceptors"). Clean extraction: Matrigel / Essential 8 base,
  factors rhBMP4 1.5 + all-trans retinoic acid 1.0 — the canonical early retinal induction pair
  (matches Harkin's BMP4+LDN). Thin (2 factors) but correct, no equipment/marker junk. Tier-2
  vision ran on its figures (CC-BY).
- MILESTONE: corpus 27->28, retinal 1->...->3; ALL 8 organoid types now have >=3 protocols, so
  every consensus card is non-provisional. Grounding held 0.813.
- Normalization: added recombinant aliases (rhBMP4->BMP4, rhNoggin->Noggin, rhEGF->EGF);
  BMP4 now unifies BMP4 / "Bone morphogenetic protein 4" / rhBMP4.
- Tooling: gave tier2_vision.py the same incremental-summary merge as tier0/tier1 (subset runs
  no longer clobber vision_summary). Stats updated. Tests green (12).
