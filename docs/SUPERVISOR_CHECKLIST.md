# Supervisor Checklist

This project is moving quickly and its main risk is not velocity; it is unreviewed
changes to evidence, provenance, and evaluation behavior. Use this checklist as
the supervisory gate for changes before they merge.

## Current State

- Default branch: `master`.
- CI: `.github/workflows/test.yml` runs `pytest -q` on push and pull request.
- Local verification on 2026-06-20: `17 passed`.
- Public GitHub state on 2026-06-20 before supervisor setup: no open issues and no pull requests found.
- Branch protection should be enabled after this process gate lands.

## Required Gate

Every non-trivial change should land through a pull request, even for a solo
maintainer. The PR should include:

- The intended single-purpose scope.
- The test command and result.
- The relevant eval or acceptance-gate result when extraction, normalization,
  corpus, KG, or reporting behavior changes.
- A note on evidence integrity: what new values were admitted, rejected, or
  deliberately left unmerged.
- Browser/rendered inspection notes for user-facing views.

## Review Focus

Reviewers should block changes that:

- Modify `OrganoidProtocol` without an explicit versioned schema decision.
- Remove or mask known failure modes without a measured harness improvement.
- Attribute inherited protocols from Tier 3 without human confirmation.
- Add corpus records that are thin, noisy, marker-heavy, or not methods-grounded.
- Commit local-only data such as full text, figures, predictions, model outputs,
  or generated databases.
- Change normalization in a way that collapses biologically distinct entities.

## Near-Term Supervisory Actions

1. Require PRs for changes to `master`.
2. Require the `test` workflow before merge.
3. Add at least one reviewer or self-review pass for each PR.
4. Expand CI beyond unit tests when practical: acceptance-gate smoke, KG build
   smoke, and rendered frontend smoke for custom Datasette pages.
5. Turn the open supervisor decisions in `outputs/loop_progress.md` into tracked
   GitHub issues, especially schema v0.3 and Tier-3 ingestion policy.
