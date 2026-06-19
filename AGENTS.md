# Operating contract for agents working in this repo

You are a build agent on the Organoid Protocol Intelligence system, supervised with
approval at every step. Execute the spec; do not redesign it.

## Ground truth — read before doing anything, in order
1. `organoid_demo/HANDOFF.md` — full spec (architecture, tiers, eval, iteration loop, repo map, cost, scope, failure modes).
2. `organoid_demo/` — the working prototype. `schema.py` is the contract; also `extractors.py`, `store_query.py`, `run_demo.py`, `eval_protocol_extraction.py`, `gold_annotations.json`.
3. The `craig/` modules named in HANDOFF §6 — live in the sibling `Claude-Code-Scientist` repo (`craig/literature/...`, `craig/llm_providers/...`, `workspace/evals/...`). Read them; don't assume.

Do not assume what these contain. Read them and confirm findings before proposing changes.

## How you work (non-negotiable loop)
- Small, single-purpose diffs. One change addresses one thing. Never bundle features into one PR.
- After every change: run it, run the eval harness, show the metrics table + the diff, then STOP for approval.
- No "looks better" merges. A change is done only when the harness verifies it.
- Before optimizing any component, prove it moves the metric you're targeting. Don't optimize off the hot path.

## Invariants (violating these is a failure, not a judgment call)
- `schema.py` / `OrganoidProtocol` is the contract. Do not change it without flagging + versioning.
- Every extracted value that can carry an `Evidence` span must carry one. Never fabricate a DOI, quote, or provenance span. **Missing evidence beats false evidence.**
- The four known failure modes (HANDOFF §9 — synonym duplication, grounded-but-miscategorized, not_reported vs not_extracted, protocol-by-reference) are EVAL FIXTURES. Resolve them only with a measured harness improvement, or log them in `error_analysis.md`. Never make them disappear quietly.
- The router and the benchmark are the same object. Build the metrics before any Tier 2/3 work.
- Respect scope (HANDOFF §8): no UI; no fine-tuning until prompt + retrieval + normalization is exhausted; don't route every paper through an agent; don't capture the full wet-lab protocol — only the comparison axes.
- Respect cost guardrails (HANDOFF §7): batch + prompt-cache by default *where the provider supports it* (see decisions below), Haiku/Sonnet for Tier 1, Opus only for Tier 3, hard cap Tier 3 at 20% of corpus.

## STOP and ask when
You would touch the schema; a "fix" would hide a failure mode; the Tier-3 cap would be
exceeded; the spec is ambiguous; or you're about to make an architectural choice the
handoff doesn't cover. When in doubt, ask rather than guess.

## Project context
An open research build on organoid protocol intelligence. Favor the artifacts that carry
the work: an airtight eval harness, documented annotation guidelines, honest error analysis,
reproducible MIT-licensed pipelines. See `docs/RESEARCH_BRIEF.md` for scientific positioning
(an open, evidence-grounded, ontology-aligned complement to the NIH SOM Center) and
`docs/PLAN.md` for the current plan and locked decisions.
