# Tier 0 — Evidence-Bundle Extraction Report

Deterministic XML-first extraction over the 25-paper corpus. No LLM. Full text is
local-only (git-ignored); this report and the manifest carry metadata + checksums only.

| pmcid | type | route | methods_ch | supp_ch | supp_files | figs | links | tables | refs | warnings |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| PMC3033971 | intestinal | europe_pmc_xml | 1347 | 32 | 3 | 4 | 3 | 0 | 30 | supplement_external_only; external_supplement_files; figures_present |
| PMC6428276 | intestinal | ncbi_efetch_xml | 4590 | 446 | 16 | 7 | 3 | 0 | 54 | external_supplement_files; figures_present |
| PMC4120977 | intestinal | ncbi_efetch_xml | 39557 | 2099 | 7 | 6 | 0 | 1 | 25 | tables_present; external_supplement_files; figures_present |
| PMC6906116 | cerebral | ncbi_efetch_xml | 25086 | 42 | 4 | 9 | 8 | 3 | 40 | supplement_external_only; tables_present; external_supplement_files; figures_present |
| PMC4489980 | cerebral | ncbi_efetch_xml | 14882 | 53 | 1 | 5 | 5 | 0 | 44 | supplement_external_only; external_supplement_files; figures_present |
| PMC4900885 | cerebral | ncbi_efetch_xml | 3962 | 67 | 9 | 7 | 5 | 0 | 37 | supplement_external_only; external_supplement_files; figures_present |
| PMC5659341 | cerebral | ncbi_efetch_xml | 43103 | 197 | 5 | 11 | 5 | 1 | 43 | supplement_external_only; tables_present; external_supplement_files; figures_present |
| PMC4519016 | cerebral | ncbi_efetch_xml | 3707 | 62 | 8 | 7 | 6 | 0 | 52 | supplement_external_only; external_supplement_files; figures_present |
| PMC4620584 | kidney | ncbi_efetch_xml | 13222 | 868 | 4 | 8 | 4 | 0 | 54 | external_supplement_files; figures_present |
| PMC4747858 | kidney | ncbi_efetch_xml | 10081 | 32 | 2 | 6 | 1 | 0 | 51 | supplement_external_only; external_supplement_files; figures_present |
| PMC5113819 | kidney | ncbi_efetch_xml | 18792 | 0 | 0 | 3 | 1 | 2 | 51 | no_supplementary_material_inline; tables_present; figures_present |
| PMC4313365 | liver | ncbi_efetch_xml | 22096 | 1024 | 6 | 15 | 3 | 0 | 61 | external_supplement_files; figures_present |
| PMC3634804 | liver | ncbi_efetch_xml | 1803 | 292 | 7 | 4 | 3 | 0 | 30 | supplement_external_only; external_supplement_files; figures_present |
| PMC10739970 | liver | ncbi_efetch_xml | 8054 | 80 | 1 | 7 | 3 | 0 | 36 | supplement_external_only; external_supplement_files; figures_present |
| PMC5722201 | liver | ncbi_efetch_xml | 27639 | 463 | 9 | 6 | 6 | 0 | 73 | external_supplement_files; figures_present |
| PMC4370217 | lung | ncbi_efetch_xml | 10387 | 459 | 3 | 22 | 37 | 0 | 89 | external_supplement_files; figures_present |
| PMC6376275 | lung | ncbi_efetch_xml | 40289 | 1659 | 17 | 4 | 24 | 1 | 75 | tables_present; external_supplement_files; figures_present |
| PMC6531049 | lung | ncbi_efetch_xml | 32557 | 54 | 2 | 5 | 10 | 4 | 41 | supplement_external_only; tables_present; external_supplement_files; figures_present |
| PMC8516798 | lung | ncbi_efetch_xml | 26294 | 548 | 7 | 7 | 29 | 1 | 76 | tables_present; external_supplement_files; figures_present |
| PMC4274199 | gastric | ncbi_efetch_xml | 3916 | 29 | 1 | 6 | 2 | 0 | 34 | supplement_external_only; external_supplement_files; figures_present |
| PMC4270898 | gastric | ncbi_efetch_xml | 32407 | 74 | 10 | 14 | 7 | 0 | 42 | supplement_external_only; external_supplement_files; figures_present |
| PMC4334572 | pancreatic | ncbi_efetch_xml | 3581 | 157 | 15 | 7 | 1 | 0 | 59 | supplement_external_only; external_supplement_files; figures_present |
| PMC4753163 | pancreatic | ncbi_efetch_xml | 14043 | 88 | 2 | 6 | 2 | 1 | 31 | supplement_external_only; tables_present; external_supplement_files; figures_present |
| PMC7757566 | pancreatic | ncbi_efetch_xml | 81107 | 0 | 0 | 8 | 4 | 9 | 17 | no_supplementary_material_inline; tables_present; figures_present |
| PMC4370190 | retinal | ncbi_efetch_xml | 13259 | 27 | 1 | 8 | 2 | 0 | 70 | supplement_external_only; external_supplement_files; figures_present |

## Aggregate
- Papers: 25
- Source routes: {'europe_pmc_xml': 1, 'ncbi_efetch_xml': 24}
- Methods section found: 25/25
- Supplement text inline (>=400 chars): 8/25 (low is expected — real supplements are external files, see below)
- Papers with external supplement files: 23/25 (140 files total)
- Papers with figures: 25/25 (192 figures total)
- Papers with tables: 9/25 (recipe sometimes lives in tables)

## What is captured vs. deferred (by design)
Captured (Tier 0, deterministic text): methods prose, full body text, table text,
**figure captions**, references, in-paper **links**, and an **inventory** of external
supplement files (filenames/types).

Deferred:
- **External supplement files** (.doc/.pdf/.xlsx) — inventoried, not yet downloaded/
  parsed. Supplementary methods/data often live here → the next deterministic step.
- **Figure graphics** (timeline schematics, gels) — image content needs **Tier 2
  (targeted vision)**; only captions are text-extractable now.
- **Cited protocols** ('as previously described [ref]') — **Tier 3 (agent)**.

## Next step (separate, on approval)
- Run rule_based_v1 over the local bundles for the first real error analysis; and/or
- Add the deterministic supplement-file fetch+parse pass (docx/pdf/xlsx) before Tier 1.
