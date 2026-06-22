# Negative-Control Experiment: What does `llms.txt` actually contribute?

**A pre-registered A/B protocol for the Organoid Protocol Atlas agent demo**
Prepared 2026-06-21. Pre-register (freeze this file in Git) *before* running Condition B.

---

## 1. The claim under test

> Given only the Atlas `llms.txt`, a generic agent produces **corpus-specific, numerically
> verifiable, source-grounded** analysis. Without it, the same agent on the same prompt
> produces **generic, field-knowledge-recited** analysis with few or no verifiable corpus facts.

This is falsifiable. It is wrong if Condition B (no interface) independently produces a
comparable density of *checkable* corpus facts — e.g. it browses to the Atlas or to PubMed
and reconstructs equivalent grounded numbers on its own.

### The two deltas (predict them separately — this is the crux)

| Delta | What it is | Can Condition B close it by browsing? |
|---|---|---|
| **Grounding delta** | Claims carry real DOIs/PMCIDs | **Partially.** A browsing agent can find papers and cite some DOIs unaided. |
| **Structured-analytics delta** | Corpus-wide audits (`103/582` timeline reporting) and *derived* analyses (within-type dose-variance decomposition) | **No.** You cannot compute a variance decomposition over 582 papers by reading abstracts. This is the robust, hard-to-dismiss delta. |

**Score the structured-analytics delta as the headline.**

---

## 2. Conditions

- **Condition A — Atlas-agent.** The exact original prompt, with the `llms.txt` URL.
- **Condition B — No-interface control.** Same prompt *shape*, Atlas URL and endpoint map removed.
- **(Condition C — Atlas + playbooks, later.)** Run *after* A/B is scored and frozen.

### Condition B prompt (use verbatim)

```
Investigate reproducibility challenges in organoid protocols. Conduct novel
investigative threads and produce a preliminary academic-style report with figures
where appropriate. Ask what a user or researcher would want to know, then attempt to
convey the answers convincingly. Cite sources. Include caveats and a
peer-review/self-audit pass. You may iterate; I will say "continue" when you stop.
```

Condition B must **not** receive: the `llms.txt`, any Atlas endpoint, corpus counts,
pre-fetched endpoint outputs, or any of the known statistics. Tool budget must match Condition A exactly.

---

## 3. Held-constant variables (record before running)

| Variable | Value (fill in) |
|---|---|
| Model name + version | |
| Date / time of each run | |
| Exact prompt text (per condition) | |
| Tools allowed (browsing? code exec? file write?) | |
| Max runtime / token budget | |
| Number of "continue" turns | |
| Output request | |
| Who scores, and whether blind | |

---

## 4. Primary metric: Verifiable Grounded Claims (VGC)

A **VGC** is a single sentence asserting a corpus fact that (a) contains a specific number and
(b) is checkable against a named source — either an Atlas endpoint or a DOI/PMCID.

- `timeline is reported in 103/582 protocols` → **VGC** (checkable against `/analytics/reporting-gaps`).
- `BMP4 in retinal induction converged to 1.5 nM across six papers (DOIs listed)` → **VGC**.
- `Matrigel is undefined and varies batch to batch` → **not a VGC** (true, but generic field knowledge).

### Derived-Analysis flag (the unbluffable one)

Mark each document yes/no for: **contains at least one analysis the agent computed
itself from row-level or endpoint data** (e.g. a variance decomposition, a within-type vs
between-type partition, a cross-year trend stitched from multiple calls).
Prediction: A = yes, B = no.

---

## 5. Scoring rubric (blind, 0-3 per criterion)

| Criterion | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| **Corpus specificity** | Generic claims only | Mentions organoid literature broadly | Some specific papers/data | Atlas-specific counts, rows, endpoint-derived facts |
| **Evidence grounding** | No/vague citations | Review citations only | DOI-level support | DOI/PMCID + verbatim evidence-row support |
| **Novel analysis** | Summary only | Descriptive synthesis | A chart/table from one readout | New *derived* analysis from row-level data |
| **Epistemic discipline** | Overclaims | Some caveats | Clear limitations | Separates missing / unextracted / ungrounded / absent / artifact |
| **Actionability** | Generic advice | Broad reporting advice | Prioritized targets | Specific reagent/type/metadata targets with audit trail |

---

## 6. Predicted result

| Condition | VGC / doc | Derived analysis | Rubric profile |
|---|---|---|---|
| **B — no interface** | ~0-3, browsing-sourced only | No | Strong on "Matrigel/reproducibility" talk; weak on numbers |
| **A — Atlas** | Many | Yes | Corpus audit, source-linked reagent claims, derived variance analysis |

---

## 7. What would falsify the claim

- Condition B independently produces >= the VGC density of Condition A.
- Condition B computes a comparable derived analysis without the endpoint map.
- The A/B difference disappears once you control for browsing being on in one and off in the other.

---

## 8. Run log template

| Cond | Turn | Endpoints / URLs hit | New VGCs added | Derived analysis added? | Visible self-correction? | Notes |
|---|---|---|---|---|---|---|

---

*Pre-registered 2026-06-21. Do not modify this file after Condition B has begun.*
