# Extraction-Completeness Audit (Iteration 2, 2026-06-20)

**Question:** is *everything* in the papers actually ingested into PaperStack?
**Answer:** no — Tier-1 currently fills only ~half the existing schema, and there are
real protocol axes the schema doesn't model yet.

## Corpus-wide schema coverage (25 protocols)
| Schema field | Populated | Note |
|---|---|---|
| organoid_type | 25/25 | (now from curated manifest) |
| source_cells | 25/25 | |
| matrix | 25/25 | |
| base_media | 25/25 | |
| signaling_factors | 25/25 (175 total) | |
| media_supplements | 23/25 | |
| **small_molecules** | **0/25** | schema field exists — prompt never asks |
| **timeline** | **0/25** | schema field exists — prompt never asks |
| **passaging** | **0/25** | schema field exists — prompt never asks |
| **assay_endpoints** | **0/25** | schema field exists — prompt never asks |

## Deep read — PMC7757566 (Driehuis, pancreatic; STAR Protocols, 81k-char methods)
Extracted well: 8 signaling factors (EGF, Wnt3a, R-spondin3, Noggin, Gastrin, FGF10,
PGE2, A83-01), matrix (Matrigel/BME), base media (Ad-DF+++). But the methods text mentions:
- **passaging: 79×** (incl. a whole "Figure 5 — Technical Aspects of Passaging") → extracted `passaging` = all null.
- **incubation/CO2: 45×** (37 °C, 5% CO2, humidified) → no schema field.
- **seeding density: 28×** (cells/well, cells/cm²) → no schema field.
- **ROCK inhibitor Y-27632: 19×** → not captured (belongs in small_molecules).
- **timeline/days: 6×** → `timeline` empty.

## Two distinct gaps
1. **Existing-schema under-extraction (fixable now, NO schema change):** expand the Tier-1
   prompt to also populate `timeline`, `passaging`, `small_molecules`, `assay_endpoints`.
   This is squarely "extract all the info" — the fields already exist.
2. **Missing categories (needs schema v0.3 — FLAG for approval):** real organoid-protocol
   comparison axes not modeled:
   - **culture_conditions** — temperature / CO2 / O2 / humidity (45 mentions in one paper).
   - **seeding_density** — cells per well/cm²/mL at plating/passage.
   - **passage_number / expansion** — how many passages, expansion potential.
   - **cell_line identity** — RRID / Cellosaurus accession for the source line.
   These align with MIOR (Minimum Information about Organoid Research) modules and are
   exactly what a biologist comparing protocols would want.

## Modality gaps (still open, by design / deferred)
- Figure **images** not read (only captions) — Tier 2 vision.
- Supplement **file contents** not parsed (only inventoried) — deferred deterministic step.

## Plan
- **Iteration 3 (in-bounds):** expand Tier-1 prompt + mapping to fill the 4 empty existing
  fields; re-run over 25; rebuild KG; verify coverage; browser-check.
- **Schema v0.3 (needs supervisor OK):** add culture_conditions / seeding_density /
  passage_number / cell_line RRID. Versioned, flagged — not done silently.
