
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
