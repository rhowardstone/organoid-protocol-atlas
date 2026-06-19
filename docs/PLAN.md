# Build Plan — First Target

The first build target (HANDOFF §10, and only this): port the prototype onto `craig/`,
wire `LLMExtractor` to the provider layer, run **Tier 0 + Tier 1** over a 25-paper organoid
corpus, and produce the eval table against the gold set. **No Tier 2/3.**

**Acceptance gate:** `python eval_protocol_extraction.py` runs on the 25-paper output and
emits the metrics table, with the four §9 failure modes either resolved-and-measured or
logged in `error_analysis.md`.

## Environment facts (verified)
- Working dir: `/atb-data/rye/Organoid` (this repo). Prototype lives in `organoid_demo/`.
- `craig/` substrate: `../Claude-Code-Scientist/craig` (local clone in sync with
  `github.com/rhowardstone/Claude-Code-Scientist`, `origin/main`). All HANDOFF §6 targets present.
- `pydantic` 2.10.6 available. Prototype runs and reproduces its documented baseline exactly.

## Locked decisions
- **Auth/billing:** craig's `llm_providers/anthropic.py` uses OAuth subscription via the
  Claude CLI (`claude_agent_sdk`, `~/.claude/.credentials.json`) — same as Claude Code on a
  Max plan. In-TOS for the user's own use; tokens draw on the Max plan, **no per-token API fees**.
- **Batch API + prompt-cache breakpoints are raw-API features**, not exposed on the OAuth
  path. HANDOFF §7's batch/cache economics are *production-scale* (1k–10k papers), not the
  25-paper dev loop → defer; document; add a key-based provider when scaling out.
- **Model IDs:** craig's `ModelName` enum is stale. Current: Haiku 4.5 `claude-haiku-4-5`
  ($1/$5), Sonnet 4.6 `claude-sonnet-4-6` ($3/$15), Opus 4.8 `claude-opus-4-8` ($5/$25).
  **Tier 1 default → Sonnet 4.6**; Opus 4.8 reserved for Tier 3. Updating the enum is a
  small *versioned* change (flag before doing).
- **Grounding metric** framed as **ALCE-style** claim→span attribution (`Evidence.quote`
  is the span). Math identical to the prototype; just named/cited properly.

## Harness architecture (important)
craig's `workspace/evals/harness.py` is a **YAML-task / agent-execution** harness
(`grade(task, output) -> (bool, dict)`), a *different shape* from the prototype's
structured-extraction scorer. Reconciliation (pending decision #3 below): keep
`eval_protocol_extraction.py` as the runnable acceptance-gate entrypoint, and factor its
metrics into `workspace/evals/graders/` modules following craig's grader pattern (standalone
fn + `grade(task,output)` adapter + `main()`), reusing `provenance_grader.py` /
`doi_validator.py`. Honors both the literal gate and §6.

## Tier 0 mapping
`craig/literature/extraction/sections.py` yields `{section_name: text}`. The prototype's
`{doi, text}` corpus = `sections["methods"]` (+ supplementary) per paper. Schema untouched.

## Sequencing (each step = its own diff: run it, run harness, show metrics + diff, STOP)
1. Scaffold + port harness; green on current gold first (metrics before tiers).
   Frame grounding metric as ALCE-style; reuse provenance/doi graders.
2. Strengthen `ANNOTATION_GUIDELINES.md` → cross-reference ISSCR-2023 reporting + ontology
   targets (CL / Uberon / ChEBI / PR / Cellosaurus / OBI). (Doc only — not the schema.)
3. Tier 0 backend swap — `sections.py` → evidence bundle. No model.
4. Tier 1 wire-up — `LLMExtractor` → sync adapter over craig's async OAuth provider, Sonnet 4.6.
5. Run T0+T1 over 25 papers → eval table. §9 failure modes measured-or-logged. No T2/T3.

**Normalization / ontology grounding (R-spondin dup, §9 modes 1+2) is the NEXT milestone** —
only after the 25-paper baseline proves duplication is the dominant error class. Then
ChEBI/PR/Cellosaurus via `scientific_ner.py`. Do not co-optimize.

## Open decisions (awaiting supervisor)
1. **Corpus source** — (a) I fetch via craig acquisition from a DOI list; (b) you provide
   25 PDFs/DOIs; (c) I curate a 25-DOI list, you approve, then fetch. *(Recommend c.)*
2. **Gold coverage** — (a) annotate ~10–12 of the 25; (b) keep gold at 3, run 25;
   (c) annotate all 25. *(Recommend a.)*
3. **Harness design** — (a) gate entrypoint + factor metrics into craig graders;
   (b) keep fully standalone for now. *(Recommend a.)*
