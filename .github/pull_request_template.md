## Scope

- [ ] This PR is one small, single-purpose change.
- [ ] It does not change `organoid_demo/schema.py` / `OrganoidProtocol`, or it clearly versions and explains the schema change.
- [ ] It does not silently hide or remove the known eval failure modes documented in `organoid_demo/HANDOFF.md` and `AGENTS.md`.

## Evidence And Data Integrity

- [ ] Every extracted value that can carry evidence is backed by a verbatim source quote and DOI, or is explicitly marked ungrounded / not reported.
- [ ] No full-text bodies, figure images, local predictions, model transcripts, or generated SQLite databases are committed.
- [ ] New corpus additions include why the paper is acceptable and why rejected candidates were rejected, when relevant.

## Verification

- [ ] `pytest -q`
- [ ] Acceptance gate / eval harness result is reported when extraction, normalization, KG, or corpus behavior changes.
- [ ] User-facing site changes were checked in a browser or with an equivalent rendered-output inspection.

## Review Notes

What should the reviewer look at most carefully?
