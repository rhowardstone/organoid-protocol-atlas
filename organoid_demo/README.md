# Organoid Protocol Intelligence — Prototype Bundle

Self-contained vertical slice: extract organoid protocols from methods text into
an evidence-grounded schema, store them, query them, and evaluate against gold.

## Files
- `schema.py` ............... the contract: `OrganoidProtocol` (DO NOT change without versioning)
- `corpus.py` ............... 3 representative methods fixtures (swap real PDF text on port)
- `extractors.py` .......... rule-based baseline + pluggable `LLMExtractor`
- `store_query.py` ......... SQLite store + grounded comparison query
- `run_demo.py` ............ end-to-end pipeline (extract → store → query)
- `gold_annotations.json` .. hand-annotated reference
- `eval_protocol_extraction.py`  harness → metrics + outputs/
- `ANNOTATION_GUIDELINES.md`  how gold is produced (and what the harness enforces)
- `HANDOFF.md` ............. full build spec (architecture, tiers, iteration loop, repo map, cost)
- `PORTING.md` ............. prototype → craig/ module mapping
- `outputs/` ............... predictions.json, evaluation_summary.json, error_analysis.md

## Run
```bash
pip install pydantic
python run_demo.py                 # see the pipeline work
python eval_protocol_extraction.py # see the metrics + failure modes
```

## Expected baseline metrics (the failures are intentional)
```
Scalar exact match:        13/13 = 1.00
Reporting-status accuracy: 4/6   = 0.6667
Signaling factor precision:       0.70
Signaling factor recall:          1.00
Unit-normalization accuracy: 6/6  = 1.00
Evidence grounding:        10/10 = 1.00
Wrong-bucket / duplicate rate: 3/10 = 0.30
```
Start at HANDOFF.md §10 for the first build task.
