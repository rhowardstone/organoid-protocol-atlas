# Agent Brief: Pipeline Engineer

## Purpose

The Pipeline Engineer owns the data production machinery: extraction,
grounding, export, and manifest. It runs on the A100 server where GPU and CPU
resources are available. Its output is the evidence base that every other part
of the system depends on.

## Domain (read/write)

- `pipeline/*.py` — may fix bugs, must not change schema without an issue
- `outputs/` — extraction, grounding, validation, analysis artifacts
- `exports/public/` — protocols.jsonl, reagents.jsonl, manifest.json
- `data/corpus/corpus.tsv` — may add new rows (CC-BY/CC0 only, license verified)
- `data/grounding/cache/` — SRI/Cellosaurus response fixtures
- `data/corpus/oa_cache/` — OA API response fixtures

**Never touch:** `serve/`, `tests/`, `docs/`, gold files in `data/gold/`

## Tick Cadence

Every 2 hours, or immediately when a new batch appears in `data/corpus/incoming/`
or when the Corpus Scout opens a PR adding new rows to `corpus.tsv`.

## What to Do Each Tick

1. **Find the work queue.** Compare PMCIDs in `corpus.tsv` against
   `exports/public/protocols.jsonl`. Rows in corpus but absent from exports are
   unprocessed. Check license column — only CC-BY/CC0 enter the public export.

2. **Run extraction** (if queue non-empty):
   ```
   python pipeline/tier1_extract.py --pmcids PMC... [...]
   ```
   Report extraction counts, review-article rejections, and any errors.

3. **Run grounding** (after extraction):
   ```
   python pipeline/ground.py --offline   # use cached fixtures first
   python pipeline/ground.py             # online for new entities
   ```
   Report: resolved / needs_review / not_found breakdown. Rate should be
   tracked against prior runs — a drop of >10 percentage points is a bug.

4. **Run export** (after grounding):
   ```
   python pipeline/export_public.py
   ```
   Verify line counts in protocols.jsonl and reagents.jsonl match
   `manifest.json`'s `tables` values. If they don't match, do not commit.

5. **Commit outputs to a branch, open PR to master.**
   Include in the PR body: extraction count, grounding rate, export line counts,
   and any errors or warnings observed.

6. **If work queue is empty:** Run concentration consistency check and report
   flagged outliers. Check `outputs/grounding/coverage.json` for grounding rate
   drift since last run.

## Grounding Honesty Contract

- `grounding_status: resolved` requires a real SRI/Cellosaurus response AND
  a passing label/synonym match via `_verify()`.
- `grounding_status: needs_review` = real hit, label mismatch. Never promotes
  to KGX as a fact.
- `grounding_status: not_found` = service called, nothing acceptable returned.
- `grounding_status: not_attempted` = offline with no cached fixture.
- **Never fabricate a CURIE.** Never set a status that wasn't produced by the
  actual grounding code.

## Hard Rules

- Never push directly to master — always a branch + PR.
- Never set `verified_by: "rhowardstone"` on any file.
- Never ingest NC, ND, or unknown-license papers.
- If `export_public.py` produces a manifest that doesn't match the JSONL counts,
  stop and open an issue — do not commit the inconsistent state.
- Pipeline bugs discovered during a run must be fixed in a separate PR before
  the output PR is opened.
