# Codex Supervisor Handoff

This repo is supervised by a PR-gated Codex loop. Use this document when a new
AI/Codex instance needs to continue without relying on chat history.

## Where To Start

Canonical repo:

```text
https://github.com/rhowardstone/organoid-protocol-atlas
```

On Rowan's Windows machine, the current working checkout used by the supervisor
thread has been:

```text
C:\Users\rhowa\Documents\Codex\2026-06-20\github-app-connector-76869538009648d5b282a4bb21c3d157\work\full-state-audit
```

A fresh AI does not need that exact folder if it is unavailable. It can clone the
repo anywhere, then run:

```powershell
git clone https://github.com/rhowardstone/organoid-protocol-atlas.git
cd organoid-protocol-atlas
python -m pytest -q
python serve\build_public_db.py
```

If testing the public Datasette app locally:

```powershell
python -m datasette serve data\public\atlas.db --metadata serve\metadata.yaml --template-dir serve\templates --static static:serve\static --plugins-dir serve\plugins --host 127.0.0.1 --port 8017
```

Then check:

```text
http://127.0.0.1:8017/
http://127.0.0.1:8017/explore
http://127.0.0.1:8017/llms.txt
http://127.0.0.1:8017/ask
```

Live public deployment:

```text
https://organoid-protocol-atlas.onrender.com/
```

## Supervisor Policy

Apply `docs/SUPERVISOR_CHECKLIST.md` first. Also enforce issue #8:

1. S1 live SRI/Cellosaurus grounding.
2. S2 Biolink-validated KGX export.
3. S3 human-verified gold evaluation.

UI and public-hosting polish are allowed, but they must remain PR-gated and must
not bury S1/S2/S3.

Do not merge human-only categories without explicit owner approval:

- destructive actions;
- public-data removals, legal, privacy, licensing, repository visibility, or
  release-state changes;
- credentials, secrets, or new external transmissions;
- authoritative Tier-3 ingestion;
- unverified gold-signoff claims;
- PRs labeled `human-review-required`.

Because the GitHub connector often authenticates as `rhowardstone`, formal GitHub
reviews may fail as self-review. Use explicit PR comments:

```text
Codex supervisor approval
Codex supervisor requested changes
```

Merges are still allowed when policy permits. Merge with the exact expected head
SHA, then verify `master` and CI.

## Current Standing Priorities

Always inspect GitHub for current truth before acting. As of 2026-06-20 20:45 UTC,
the important threads were:

- PR #9, S1 SRI/Cellosaurus grounding: merged as `f918dff`. The next S-tier work is
  S2: Biolink-validated KGX export that consumes only accepted `resolved`
  groundings and preserves `needs_review` candidates as non-fact review items.
- PR #17, CC-BY figure gallery: merged as `5ac0045` after explicit owner approval
  for CC-BY figure embedding from the PMC OA mirror. Verify Render serves
  `/figures` after deployment catches up.
- PR #18, scaled ingestion orchestrator: requested changes. It needed local-output
  `.gitignore` protection, removal or stabilization of generated dry-run reports,
  and tests for dedupe/QC/dry-run behavior before merge.
- Issue #14 tracks scaling the public hosted corpus toward hundreds, but only with
  explicit OA/license gates, snippet-only policy, provenance tests, and manifest
  counts.

## Public Deployment Contract

The public Render deployment is a license-safe Datasette build, not the full local
working corpus. It should expose structured rows and short evidence snippets, not
full paper bodies or methods text.

Current public baseline after PR #13/#16/#17:

- `/llms.txt` exists and documents agent/API usage.
- `/explore` is a custom search page over public reagent rows.
- `/figures` is a CC-BY-only figure gallery backed by PMC OA S3 URLs, with no
  committed image binaries.
- `serve/build_public_db.py` builds `data/public/atlas.db` from committed public
  JSONL exports.
- Public counts should match `exports/public/manifest.json`.

If Render serves work that is not on `master`, fix the drift. Prefer making
Render deploy from reviewed `master`, not from a long-lived feature branch.

## Review Checklist For Any PR

Before approval/merge:

1. Fetch PR metadata, head SHA, base branch, comments, CI.
2. Inspect the diff line by line.
3. Run local tests or merge-result tests when feasible:

   ```powershell
   python -m pytest -q
   python serve\build_public_db.py
   ```

4. Check for generated/local-only data leaks:

   ```powershell
   git diff --name-status origin/master..HEAD
   git ls-tree -r --name-only HEAD
   ```

5. Check for:
   - full paper text, methods bodies, figures/images, PDFs, DBs, model transcripts;
   - generated metric/count claims without provenance;
   - fabricated IDs/CURIEs;
   - stale schema/version/contract docs;
   - premature `closes #...` keywords;
   - circular or non-human gold-evaluation claims;
   - external-service calls without captured fixtures where tests depend on them.

6. For UI work, verify routes locally and, when browser tools work, take screenshots.
   If browser tools fail, say so rather than claiming screenshot QA.
7. If approved, comment with the exact head SHA and merge using that SHA.
8. After merge, verify fresh `master`, CI, and the live Render endpoint if public UI
   changed.

## Git Hygiene

Generated files frequently appear during tests/builds. Do not commit them unless
the PR explicitly owns them and they are reviewed artifacts.

Common generated artifacts to clean after local verification:

```powershell
git restore -- organoid_demo\outputs\predictions.json
Remove-Item -LiteralPath (Resolve-Path data\public).Path -Recurse -Force
```

Before removing recursively, confirm the resolved path is inside the checkout.

Real local-only corpus artifacts should be ignored and never accidentally committed:

```text
data/evidence_bundles/local/
data/predictions/local/
data/public/
```

## What Good Supervision Looks Like

Be helpful but strict. The coding loop is allowed to be ambitious, but every claim
must be grounded:

- S1 grounding must distinguish accepted `resolved` IDs from `needs_review`
  candidates.
- Public corpus expansion must maximize usefulness while preserving license and
  provenance safety.
- Human-verified gold evaluation must be human-verified, not model-asserted.
- UI polish should make the atlas easier to use, but never by hiding uncertainty or
  moving unreviewed live code away from `master`.

When in doubt, request changes with concrete fixes rather than letting the loop
continue on a shaky assumption.
