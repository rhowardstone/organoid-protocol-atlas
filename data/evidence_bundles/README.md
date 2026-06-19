# Evidence bundles (Tier 0 output)

Tier 0 (`pipeline/tier0_extract.py`) turns each corpus paper into a deterministic
**evidence bundle**: methods text, supplementary text, tables, references, and a section
map. XML-first (Europe PMC `fullTextXML` → NCBI `efetch` fallback; GROBID/PyMuPDF reserved
as a future PDF fallback). The `source_route` is recorded per paper so failures are
diagnosable.

## What is committed vs. local-only

**Full bundles are NOT committed.** The corpus includes PMC *author-manuscript* and
unknown-license rows whose text is free to read/extract but **not to redistribute**. So the
full bundles are written to `local/` (git-ignored). What's tracked here is metadata only:

| Path | Tracked? | Contents |
|---|---|---|
| `local/{pmcid}.json` | ❌ git-ignored | full bundle: methods_text, supplementary_text, tables, references, section_map |
| `manifest.jsonl` | ✅ | per-paper metadata: route, char counts, table/ref counts, section **titles**, warnings, `sha256` of bundle content, `bundle_committed: false` — **no body text** |
| `../../outputs/tier0/evidence_bundle_summary.json` | ✅ | aggregate stats |
| `../../outputs/tier0/extraction_report.md` | ✅ | human-readable per-paper + aggregate report |

Section *titles* are structural metadata (not article body) and are kept for diagnosis;
section *contents* and methods/supplement text are not committed.

## Reproduce
```bash
python pipeline/tier0_extract.py          # all 25 → local/ bundles + manifest + reports
python pipeline/tier0_extract.py --limit 3
```
`sha256` in the manifest lets anyone with the same fetched sources verify they reconstructed
the identical bundle content locally.
