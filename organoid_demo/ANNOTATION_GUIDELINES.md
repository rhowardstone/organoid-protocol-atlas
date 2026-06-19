# Annotation Guidelines — Organoid Protocol Gold Standard

These rules govern how a human curator produces `gold_annotations.json`. They
also define the conventions the harness grades against, so changing a rule here
means re-annotating, not just re-scoring.

## 1. Reporting status is mandatory on matrix and base_media

For every protocol, mark each as one of:

- `reported` — the source states it. Record the value.
- `not_reported` — the source omits it (tacit lab knowledge, or deferred to a
  cited protocol). Value is null. This is a finding, not a gap.
- `not_applicable` — the field does not apply to this protocol type.

Never use a null value without a reporting status. The distinction between
"the paper didn't say" and "the extractor missed it" is the whole point.

## 2. Bucketing: signaling factors vs supplements

A reagent goes in `signaling_factors` only if it instructs cell fate —
morphogens, growth factors, pathway agonists/antagonists, small-molecule
inhibitors (e.g. EGF, Noggin, R-spondin, Wnt3a, CHIR99021, FGF9, SB431542,
Y-27632).

Media supplements that support viability without directing fate go in
`media_supplements` (e.g. B27, N2, N-acetylcysteine, nicotinamide,
penicillin/streptomycin). When in doubt, the domain expert decides; record the
decision so the gold is reproducible.

This boundary is deliberately tested: B27/N2 belong in supplements. An
extractor that grounds them correctly but files them as signaling factors is
wrong, and the harness must catch that.

## 3. Reagent identity and synonyms

Annotate the canonical name. Treat these as the same entity: R-spondin /
R-spondin1 / RSPO1; bFGF / FGF2; Y-27632 / ROCK inhibitor (when named). The
gold lists each reagent once. A prediction that lists a synonym separately is a
duplicate (a precision error), not a second factor.

## 4. Concentrations

Record `value` and `canonical_unit` in normalized form: ng/mL, ug/mL, uM, nM,
mM, %. If the source gives only a qualitative amount ("low bFGF"), set
concentration to null — do not invent a number.

## 5. Provenance

Every annotated reagent should be traceable to a verbatim span in the source.
Gold does not need to store the span, but the annotator must be able to point
to it. A reagent you cannot locate in the text does not belong in gold.

## 6. Growing the gold set

Start at 3 protocols, expand to 30–50 spanning intestinal, cerebral, kidney,
liver, lung, and gastric systems. Prioritize papers the cheap extraction pass
scores with low grounding confidence — those are the hard cases worth the
annotation effort, and they feed the router's escalation policy.
