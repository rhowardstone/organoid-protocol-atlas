# Organoid Protocol Intelligence — Build Handoff

**Audience:** the builder (Claude Code / agent on the A100 box), supervised human-in-the-loop.
**Status:** prototype exists (`organoid_demo/`, runs on 3 papers, rule-based baseline + eval harness). This doc is the path from that prototype to a real ingestion system.
**Operating principle (from the repo):** execute to verify; missing evidence beats false evidence; every phase ends with a runnable command and an expected eval result that is its acceptance gate. Do not advance a phase until its gate passes.

---

## 1. Goal

Turn organoid-culture papers into structured, queryable, evidence-grounded protocol records. A record captures the axes along which protocols actually differ — source cells, matrix, base media, signaling cocktail, timeline, passaging, endpoints — and every populated field carries a provenance span. The system must be able to answer comparison and consensus queries ("signaling factors for human intestinal organoids, with citations") over the resulting knowledge.

This is not a scraper. The research content is in *what's hard*: entity normalization, distinguishing "not reported" from "not extracted," and resolving protocols stated by reference to a cited source.

---

## 2. The contract (do not change without versioning)

`organoid_demo/schema.py` → `OrganoidProtocol`. The schema is the interface between every component. Two design rules are load-bearing:

- **Evidence is mandatory on fields that matter.** A value with no source span is a defect, not a low-confidence success.
- **Absence is typed.** `Reporting = {reported, not_reported, not_applicable}`. Omission is a measurable signal, not a null. The routing policy (§5) reads this field.

Concentrations are parsed into `{value, unit, canonical_unit, raw}` so the same reagent reported three ways collapses to one comparable form.

---

## 3. Architecture — cost-tiered cascade

The system is a router over four tiers, cheapest first. Most papers terminate early. Only the residue reaches the expensive tiers. The router's inputs are the eval signals defined in §4, so the benchmark and the production policy are the same object.

```mermaid
flowchart TD
    A[Paper: DOI + PDF] --> T0

    subgraph T0[Tier 0 — Deterministic · free]
        G[GROBID / PyMuPDF sections] --> TB[Table detection]
        TB --> RG[Reference graph]
        RG --> EB[Evidence bundle:<br/>methods + supp + tables + refs]
    end

    EB --> T1

    subgraph T1[Tier 1 — Structured extraction · Haiku/Sonnet · batch]
        EX[LLM extract to OrganoidProtocol]
    end

    EX --> R{Router reads eval signals}

    R -->|low not_reported<br/>high grounding| DONE[Commit to KG]
    R -->|table/figure pages<br/>flagged| T2
    R -->|high not_reported<br/>+ &quot;as previously described [ref]&quot;| T3

    subgraph T2[Tier 2 — Targeted vision · Sonnet/Opus]
        V[Page image + structured table<br/>cross-check]
    end

    subgraph T3[Tier 3 — Agent escalation · Opus · ~10-20% of papers]
        AG[Follow citation chain · fetch source ·<br/>clone repo · provenance-chained extract]
    end

    V --> DONE
    T3 --> DONE
    DONE --> KG[(Knowledge graph:<br/>typed protocol nodes)]
    KG --> Q[Comparison / consensus query<br/>with citations]
```

**Tier 0 — Deterministic (free).** Acquire the PDF, extract sections, detect table regions, build the local reference graph. Output is one *evidence bundle* per paper: methods text + supplementary text + parsed tables + reference list. No model.

**Tier 1 — Structured extraction (Haiku/Sonnet, batch).** One LLM call per paper over the evidence bundle, emitting `OrganoidProtocol` JSON with mandatory evidence spans. Prompt is `EXTRACTION_PROMPT` in `extractors.py`. Most papers terminate here.

**Tier 2 — Targeted vision (Sonnet/Opus).** Triggered only for pages flagged as table-heavy, timeline-figure, or low-text-confidence. Send the page *image alongside the structured table extraction* so the model cross-checks rather than re-OCRs. Do not send vision on prose the text layer already captured.

**Tier 3 — Agent escalation (Opus, expensive).** Triggered only when Tier 1 returns high `not_reported` **and** a reference pattern is detected ("as previously described [12]", "see ref. 8", "Supplementary Methods"). The agent follows the citation chain, fetches the cited source, clones the analysis repo if the protocol is computational, and returns an extraction whose evidence spans point *across* papers. Cap this tier at ~20% of the corpus.

---

## 4. Evaluation — the same metrics, at every tier

Gold set lives in `gold_annotations.json` (3 protocols now → grow to 30–50 spanning intestinal, cerebral, kidney, liver, lung, gastric). The harness (`eval_protocol_extraction.py`, ported into `workspace/evals/`) produces:

| Metric | What it catches |
|---|---|
| Scalar exact match | basic field correctness |
| Reporting-status accuracy | `not_reported` vs `not_extracted` confusion — the core ambiguity |
| Signaling-factor precision / recall | over- and under-extraction of the cocktail |
| Unit-normalization accuracy | concentration canonicalization |
| Evidence grounding | every value tied to a real span |
| Wrong-bucket / duplicate rate | synonym duplication + miscategorization |

These are not just scores. The router (§3) reads `reporting-status` and `grounding` per paper to decide escalation. **Build the metrics before building Tier 2/3** — they are the control logic, not a report card.

---

## 5. Iteration loop

```
run cascade on gold → metrics → error analysis →
fix the CHEAPEST tier that addresses the dominant error class → re-run
```

Rules:
- Attack the dominant error class, one at a time. Do not co-optimize.
- Prefer the cheapest fix. A normalization-dictionary or prompt change beats fine-tuning. Exhaust prompt + retrieval before touching weights.
- Papers with low grounding confidence go to human review and *become new gold*. The corpus self-expands toward the hard cases.
- Every fix is verified by re-running the harness. No "looks better" merges.

---

## 6. Repo integration map

The prototype modules map onto existing components. The schema does not move; everything else is a backend swap.

| Prototype | Real target | Change on port |
|---|---|---|
| `corpus.py` | `craig/literature/extraction/{grobid,pymupdf,sections}.py` | fixtures → real PDF→section extraction; same `{doi, text}` shape |
| `extractors.py` (rule) | keep in `workspace/evals` | stays as the baseline / control arm |
| `extractors.py` (LLM) | `craig/llm_providers/` | wire `LLMExtractor(complete=...)`; prompt already written |
| reagent/cell-line NER | `craig/literature/knowledge_graph/scientific_ner.py` | dictionary → NER + normalization (ChEBI/PR/CL/Uberon); fixes the R-spondin dup |
| `store_query.py` | `craig/literature/knowledge_graph/{storage,schema,query}.py` | protocols → typed KG nodes; comparison → graph traversal; FAISS (`embeddings.py`) adds the RAG path |
| contradiction checks | `craig/literature/knowledge_graph/nli_detector.py` | same reagent / conflicting concentration across papers = a contradiction node |
| reference resolution | `craig/literature/{citation_expander,acquisition}.py` | the Tier-3 agent's fetch path |
| eval harness | `workspace/evals/{harness.py, graders/}` | extends existing `provenance_grader.py`, `doi_validator.py`; add field-match, unit-norm, hallucinated-field graders |

---

## 7. Cost model and guardrails

Per paper, batch rate, vision-on-flagged-pages-only (Tier 0/1 dominate; Tier 2/3 are the minority):

| Model (Tier 1 default) | Per paper | 1k papers | 10k papers |
|---|---|---|---|
| Haiku 4.5 | ~$0.05 | ~$50 | ~$500 |
| Sonnet 4.6 | ~$0.15 | ~$150 | ~$1,500 |
| Opus 4.8 (escalation) | ~$0.25 | escalation only | escalation only |

Guardrails:
- Batch everything that isn't interactive (50% off).
- Prompt-cache the schema, instructions, and few-shot examples (cached input ~90% cheaper).
- Default Tier 1 to Haiku/Sonnet; reserve Opus for Tier 3.
- Hard cap Tier 3 at 20% of corpus; alert if exceeded (signals a router or extraction regression).
- Self-hosted VLM on the A100s is the zero-marginal-cost alternative for Tier 2 once accuracy is validated against gold.

---

## 8. Scope boundaries (do NOT do these)

- No UI. Query interface is programmatic until extraction is trustworthy.
- No fine-tuning until the prompt + retrieval + normalization path is exhausted on gold.
- Do not route every paper through an agent. Agents are Tier 3 only.
- Do not try to capture the full wet-lab protocol. Capture the comparison axes in the schema; everything else is out of scope.
- Do not "fix" the baseline's known failures silently — they are eval fixtures (§9).

---

## 9. Known failure modes — preserve as eval signal

1. **Synonym duplication.** "R-spondin1" and "R-spondin" extracted twice. Solved by normalization (§6), measured by wrong-bucket/duplicate rate.
2. **Grounded ≠ correctly typed.** B27/N2 are grounded in the text but are supplements, not signaling factors. Grounding does not imply biological category.
3. **not_reported vs not_extracted.** The kidney case: matrix/base_media absent. Rules cannot tell omission from miss. This drives Tier-3 escalation.
4. **Protocol-by-reference.** "Cultured as previously described [12]." The reagents live in the cited paper. Single-shot extraction returns a correct-but-useless empty cocktail. The reason Tier 3 exists.

---

## 10. First build target (one PR)

Port the prototype onto `craig/`, wire `LLMExtractor` to the provider layer, run Tier 0 + Tier 1 over a 25-paper organoid corpus, and produce the eval table against the gold set.

**Acceptance gate:** `python eval_protocol_extraction.py` runs on the 25-paper output and emits the metrics table, with the four failure modes in §9 either resolved or explicitly logged in `error_analysis.md`. No Tier 2/3 yet.
