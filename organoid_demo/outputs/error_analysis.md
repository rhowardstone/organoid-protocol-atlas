# Error Analysis -- rule_based_v1 baseline

Baseline extractor vs 3-protocol gold. These are the failures the research is about; do not silently fix them.

- Scalar exact match: 13/13 = 1.0
- Reporting-status accuracy: 4/6 = 0.6667
- Signaling factor precision: 0.7
- Signaling factor recall: 1.0
- Unit-normalization accuracy: 6/6 = 1.0
- Evidence grounding: 10/10 = 1.0
- Wrong-bucket / duplicate rate: 3/10 = 0.3

## Preserved failure modes

1. Synonym duplication:
   - intestinal: 'R-spondin' -> duplicate
   - cerebral: 'B27' -> wrong-bucket / not-in-gold
   - cerebral: 'N2' -> wrong-bucket / not-in-gold

2. Reporting-status confusion (omission vs miss):
   - kidney: matrix predicted unresolved_absence, gold not_reported
   - kidney: base_media predicted unresolved_absence, gold not_reported

3. Grounded but mis-typed: B27 and N2 are grounded in the text yet scored as wrong-bucket signaling factors. Grounding does not imply correct biological category.