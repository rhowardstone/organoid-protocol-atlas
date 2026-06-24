# Sample cookbook-protocol records (frontend contract, #178)

`cookbook_sample.json` — a list of 3 protocol records (cerebral / intestinal / tumor),
the data contract for the `/protocols/<pmcid>` recipe page. SAMPLE data: flat fields are
production-real (from tier1), `stages[]` is from the v2 prototype (will be production once
the vLLM batched re-extraction lands). Per-record fields:

- `pmcid`, `doi`, `citation{first_author,year,journal,doi}`, `license` — page header + attribution
- `organoid_type`, `is_generation_protocol` (gate; false ⇒ render as "uses organoids as assay")
- `source_cells{cell_type,line_name,species}`, `final_organoid` — "from X → Y"
- `matrix`, `base_media` — header chips
- `materials[]` — `{name,value,unit,role,kind}` table (kind ∈ signaling_factors|small_molecules|media_supplements)
- `stages[]` — ORDERED. each: `{name,start_day,end_day,culture_vessel,medium_base,
  reagents[{name,concentration,unit,role}],transition}`. Render as the numbered recipe;
  `start_day/end_day` may be null (condition-keyed protocols) — fall back to `transition` text.
- `assay_endpoints[]` — characterization readouts (NOT culture stages); render as an "Endpoints" section.

Render order suggestion: header → source→organoid → materials table → numbered stages
(group each stage's reagents under it) → endpoints → citation. Cerebral is the richest
day-keyed example; intestinal is condition-keyed (null days); tumor exercises the
is_generation_protocol gate (1 culture stage + many endpoints).
