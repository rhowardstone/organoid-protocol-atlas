# Corpus — PMC-OA 25-paper organoid benchmark seed

`pmc_oa_25.tsv` is the selection manifest for the first real benchmark corpus: 25 organoid
papers with **full text retrievable from PMC** (so the Methods are extractable), spanning
8 organoid systems. This is the seed that turns the prototype from a 3-fixture demo into a
real benchmark.

This manifest is a **selection artifact only** — no methods text is extracted yet. Tier 0
(evidence-bundle extraction) is a later, separate step.

## Columns
| column | meaning |
|---|---|
| `organoid_type` | tissue/system (intestinal, cerebral, kidney, liver, lung, gastric, pancreatic, retinal) |
| `doi` | DOI — canonical identifier (authoritative) |
| `pmcid` | PubMed Central ID — full-text source (authoritative; verified via NCBI/PMC ID-converter) |
| `first_author` | first author surname (human-readable handle; `tbd` where not yet confirmed) |
| `year`, `journal` | publication metadata |
| `species` | source organism (`tbd` where unverified) |
| `source_cell_type` | `iPSC/ESC` (pluripotent), `adult_stem`, or `primary_tissue` |
| `license` | `CC-BY` / `CC-BY-NC-ND` / `author-manuscript` (free in PMC, not CC-BY) / `unknown` |
| `has_methods` | `yes` (all full-text papers have a Methods section) |
| `has_supplement` | `tbd` — confirmed at Tier 0 (supplements often hold the real recipe) |
| `gold_candidate` | `yes` → selected for hand annotation in `gold_set_v0.1` |
| `flags` | eval-relevant tags: `canonical`, `protocol-by-reference`, `known-omission`, `biobank` |
| `notes` | one-line description |

> **Honesty note.** Authoritative fields are `doi`, `pmcid`, `organoid_type`, `license`,
> and `flags` (from verified research). Biological-detail columns (`species`,
> `source_cell_type`, `has_supplement`) and exact titles are seeded from known metadata and
> will be **verified/completed during Tier 0 extraction and annotation** — `tbd` marks what
> is not yet confirmed. Verbatim titles are intentionally omitted (DOI + first_author + year
> + journal identify each paper) to avoid recording unverified text.

## Selection policy
Option (b): **CC-BY + PMC author-manuscript** full text, to reach 25 with full tissue
coverage. Eight CC-BY/open papers plus PMC author-manuscripts (free full text, not CC-BY —
fine to *read/extract*, not to redistribute). License is labeled per row so downstream use
respects it. The licensing spread is itself a benchmark realism feature.

Deliberately **excluded** (closed / not in PMC → methods not legally extractable from PMC):
Sato 2009 intestinal `10.1038/nature07935`, Sato 2011 `10.1053/j.gastro.2011.07.050`,
Lancaster 2013 cerebral `10.1038/nature12517`, Takasato 2015 kidney `10.1038/nature15695`,
Barker 2010 gastric `10.1016/j.stem.2009.11.013`, Dekkers 2013 `10.1038/nm.3201`. These two
flagships (Sato 2009, Lancaster 2013) are the field's foundational protocols but are not in
PMC; treat as metadata-only anchors or source separately.

## Coverage
- **25 papers**, 8 systems: intestinal 3, cerebral 5, kidney 3, liver 4, lung 4, gastric 2,
  pancreatic 3, retinal 1.
- **Licenses:** 8 CC-BY/CC-BY-NC-ND, 16 author-manuscript, 1 unknown.
- **Gold candidates:** 12 (2 per core system × intestinal/cerebral/kidney/liver/lung/gastric)
  — the targets for `data/gold/gold_set_v0.1.json` (next milestones).
- **Deliberate edge cases:** 4 `protocol-by-reference` (Mariani, Takasato 2016, Broutier,
  Driehuis, Cell Rep 2021) and 2 `known-omission` (Mariani 2015, Cell Rep 2021) to exercise
  the `not_reported` vs `not_extracted` and citation-resolution failure modes.

## Acceptance gate (this manifest)
1. Every row has a DOI **and** a PMCID. ✓
2. Every row has an `organoid_type`. ✓
3. Every row is open-access / full-text retrievable from PMC. ✓
4. ≥ 5 organoid systems represented (8). ✓
5. 10–12 rows marked `gold_candidate` (12). ✓
6. No extraction code in this change. ✓

## Next milestones (each its own change)
1. **Evidence-bundle extraction (Tier 0)** — `data/evidence_bundles/{pmcid}.json` (methods +
   supplementary + tables + references). No LLM.
2. **Rule baseline on real text** — `outputs/real_corpus/` predictions + error analysis.
3. **Gold annotations** — `data/gold/gold_set_v0.1.json` (the 12 gold candidates).
4. **Tier 1 LLM extractor** — then compare `rule_based_v1` vs `llm_v1`.
