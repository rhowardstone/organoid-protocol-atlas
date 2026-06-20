
## Iteration 1 — 2026-06-20 — Visual QA (browser)
- Opened localhost:8002; screenshotted landing + a recipe card (Spence PMC3033971).
- Critique: recipe card is strong — axes grid + cocktail table (grounded/ungrounded badges) + the **source-methods panel with evidence spans highlighted in context works**. Landing is functional but flat/generic ("nice Datasette skin"). Faux pas: stat grid orphaned the 6th card ("140") onto its own row.
- Fix: `.apa-stats` -> balanced 6-across (responsive 3/2 on narrower). Verified visually (clean single row).
- Next: design polish (hero impact, feature-card hierarchy/typography), then extraction-completeness audit (read one paper fully — figures + supplement — vs what's in PaperStack).
