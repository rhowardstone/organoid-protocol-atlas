# Incoming Corpus Candidates

This directory holds discovery artifacts that are useful for corpus expansion but
are not accepted extraction-corpus rows yet.

`organoid_corpus_candidates_180.csv` was generated from Europe PMC query buckets.
It includes adjacent items such as reviews, microtissues, chips, disease models,
and protocol-looking papers. Treat it as a candidate queue, not as protocol
ground truth.

Before moving a row into the accepted corpus manifest, verify:

- the paper is methods-grounded and relevant to organoid protocol extraction;
- PMC OA/license status is checked through the PMC OA service, not only Europe
  PMC metadata;
- the row has an explicit `ingest_status`;
- any protocol-by-reference paper is routed to review rather than authoritative
  inherited-protocol ingestion.

