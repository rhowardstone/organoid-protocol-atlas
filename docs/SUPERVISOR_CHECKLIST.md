# Supervisor Checklist

This project is moving quickly and its main risk is not velocity; it is unreviewed
changes to evidence, provenance, and evaluation behavior. Use this checklist as
the supervisory gate for changes before they merge.

## Roles

- Engineering agent: implements one scoped change, tests it, opens a pull request,
  and waits. It must not merge its own PRs.
- Codex supervisor: reviews PRs, runs or checks tests, leaves findings, requests
  changes when needed, and merges PRs that satisfy this checklist.
- Human owner: remains the authority for destructive actions, legal/privacy calls,
  credentials, external transmissions, and any explicit human-review-required label.

GitHub may show the authenticated `rhowardstone` account as the actor for Codex
connector actions. Codex-authored issues, comments, PRs, and merges should say so
in the body or title when provenance matters.

## Current Gate

- Default branch: `master`.
- CI: `.github/workflows/test.yml` runs `pytest -q` on push and pull request.
- Non-trivial changes should land through PRs.
- Codex is delegated to merge PRs that pass the criteria below, unless the PR is
  marked human-review-required or touches one of the human-only categories.

## PR Requirements

Each PR should include:

- The intended single-purpose scope.
- The issue it addresses, or a reason no issue exists.
- The test command and result.
- The relevant eval or acceptance-gate result when extraction, normalization,
  corpus, KG, schema, or reporting behavior changes.
- A note on evidence integrity: what new values were admitted, rejected, or
  deliberately left unmerged.
- Browser/rendered inspection notes for user-facing views.
- Clean-clone and local-artifact assumptions when serving, KG build, or generated
  data behavior changes.

## Codex Merge Criteria

Codex may merge a PR only when all applicable checks pass:

1. Scope is narrow and not bundled with unrelated work.
2. GitHub Actions is green for the PR head.
3. Codex has inspected the diff line-by-line.
4. Local tests pass on the PR branch or on the merge result when feasible.
5. The merge result is conflict-free against current `master`.
6. The PR does not commit local-only data: full text, figure images, predictions,
   model transcripts, generated SQLite databases, browser screenshots, or caches.
7. Evidence/provenance semantics are explicit and conservative.
8. Issue-closing keywords are intentional and will not close tracking issues early.
9. Public-facing UI changes have browser/rendered QA, or the lack of browser QA is
   called out before merge.
10. Post-merge, Codex verifies `master` and checks CI for the merge commit.

Codex should merge with an expected head SHA so GitHub rejects the merge if the PR
moves after review.

## Request Changes

Codex should request changes or leave a blocking comment when a PR:

- Modifies `OrganoidProtocol` without an explicit versioned schema decision.
- Removes or masks known failure modes without a measured harness improvement.
- Attributes inherited protocols from Tier 3 without human confirmation.
- Adds corpus records that are thin, noisy, marker-heavy, or not methods-grounded.
- Changes normalization in a way that collapses biologically distinct entities.
- Makes clean-clone behavior misleading.
- Lets a successful command produce an empty or meaningless artifact without warning.
- Reports a metric or UI claim that is not backed by the committed summaries or KG.

## Human-Only Decisions

Codex must not merge without explicit human confirmation when a change:

- Deletes or suppresses public data in response to legal, privacy, or takedown claims.
- Sends messages, uploads private files, changes permissions, or transmits secrets.
- Introduces authoritative Tier-3 inherited-protocol ingestion.
- Changes licensing, repository visibility, or release/publication state.
- Touches credentials, billing, deployment secrets, or external accounts.
- Is labeled `human-review-required`.

## Heartbeat Procedure

Every scheduled Codex supervisor pass should:

1. Inspect latest commits, open PRs, issues, and CI since the prior pass.
2. Prioritize open PRs over new feature work.
3. For each PR, apply the merge criteria above.
4. If the PR passes, leave a Codex approval note and merge it.
5. If the PR fails, leave concrete requested changes and do not merge.
6. If the coding loop pushed directly to `master`, audit the commit and open a
   follow-up issue for any risk that should have been PR-gated.
7. Report in the Codex thread: findings first, then action taken, then verification.

## Near-Term Supervisory Actions

1. Merge this supervisor gate so future work has a durable operating contract.
2. Enable branch protection on `master` when practical: require PRs and `test`.
3. Expand CI beyond unit tests when practical: acceptance-gate smoke, KG build
   smoke, and rendered frontend smoke for custom Datasette pages.
4. Keep schema v0.3 follow-up, Tier-3 policy, clean-clone serve behavior, and
   residual extraction errors tracked as GitHub issues until resolved.
