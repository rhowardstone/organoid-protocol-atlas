## Scope

- [ ] This PR is one small, single-purpose change.
- [ ] It does not change `organoid_demo/schema.py` / `OrganoidProtocol`, or it clearly versions and explains the schema change.
- [ ] It does not silently hide or remove the known eval failure modes documented in `organoid_demo/HANDOFF.md` and `AGENTS.md`.
- [ ] It links the relevant issue or explicitly says why no issue exists.

## Evidence And Data Integrity

- [ ] Every extracted value that can carry evidence is backed by a verbatim source quote and DOI, or is explicitly marked ungrounded / not reported / not extracted.
- [ ] No full-text bodies, figure images, local predictions, model transcripts, or generated SQLite databases are committed.
- [ ] New corpus additions include why the paper is acceptable and why rejected candidates were rejected, when relevant.
- [ ] Provenance-changing behavior is review-queue first unless a human has confirmed the source attribution.

## Verification

- [ ] `pytest -q`
- [ ] Acceptance gate / eval harness result is reported when extraction, normalization, KG, corpus, schema, or reporting behavior changes.
- [ ] User-facing site changes were checked in a browser or with an equivalent rendered-output inspection.
- [ ] Clean-clone / local-artifact assumptions are stated when the change affects serving, KG build, or regenerated data.

## Codex Supervisor Gate

Codex may approve and merge this PR when all applicable conditions are true:

- [ ] The diff is scoped and does not bundle unrelated work.
- [ ] GitHub Actions is green for the PR head.
- [ ] Codex has inspected the diff line-by-line.
- [ ] Codex has run local tests or a local merge-result test when feasible; if not feasible, the reason is stated.
- [ ] No high-risk policy decision is hidden in implementation details.
- [ ] Any issue-closing keywords are intentional.

Human confirmation is still required for destructive actions, public-data removals, legal/privacy matters, credentials, external transmissions, or authoritative Tier-3 ingestion.

## Review Notes

What should Codex inspect most carefully before merge?
