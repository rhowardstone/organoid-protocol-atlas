# Research Brief — Organoid Protocol Intelligence Landscape

Scientific landscape and positioning for evidence-grounded extraction of organoid culture
protocols. Sources abbreviated; arXiv IDs flagged "(verify)" should be checked before citing.

## Motivation
Organoid protocols are reported inconsistently across the literature, which undermines
reproducibility, comparison, and consensus. The goal here is to turn organoid-culture papers
into structured, queryable, **evidence-grounded** protocol records — where every populated
field carries a provenance span — and to do so as an open, ontology-aligned pipeline with a
rigorous evaluation benchmark.

## Programs (motivation + adjacent efforts)
- **NIH SOM Center** (Standardized Organoid Modeling) — NCI / Frederick National Lab,
  ~$87M/3yr, announced late 2025. Standardized organoid protocols + AI/ML optimization +
  open-access protocols/data/materials (liver/lung/heart/intestine first). The most on-point
  effort and the natural point of comparison — notably with **no published methods yet**.
  Position this work as the open, evidence-grounded, ontology-aligned complement.
- **HCMI** (Human Cancer Models Initiative, NCI + CRUK/Sanger): ~1000 patient-derived
  models, >75% 3D organoids, harmonized QC — an organoid biobank with standardized
  characterization.
- **NCATS Tissue Chips / MPS** + **TraCe MPS** (NCATS + FDA): organ-on-chip qualification
  with an FDA drug-development-tool framing; shares the standardization problem.
- **HuBMAP** (ASCT+B tables — Anatomical Structures, Cell Types + Biomarkers): standardizes
  *vocabulary*, not protocols; a useful controlled reference for organoid composition.
- **Human Cell Atlas**: largely CZI + Wellcome Sanger/EMBL (not primarily NIH); reference
  cell-type maps to validate organoid cell types vs. in vivo.
- **NIH Rigor & Reproducibility policy (2016)**: the policy lever under which protocol
  reporting falls.

## Ontology / normalization stack (fills the schema's `ontology_id` / `canonical_name` stubs)
cell types → **Cell Ontology (CL)** · anatomy/tissue → **Uberon** · small-molecule
reagents (CHIR99021, Y-27632) → **ChEBI** · protein growth factors/markers (EGF, FGF2, BMP4,
Wnt3a, Noggin) → **Protein Ontology (PR)** · assays/protocols → **OBI** (+ **BAO** for
screening) · iPSC/ESC lines (H9, WTC-11, CRL1502) → **Cellosaurus** (RRID-linked) ·
harmonization spine → **EFO**. All under OBO Foundry + FAIR.
- **Key gap = novelty:** no dedicated organoid ontology exists (the Organoid Cell Atlas
  annotates with CL) → genuine white space for structured organoid protocol representation.
- **Reporting standard: ISSCR Standards (2023)** — the closest minimum-information standard
  for stem-cell/organoid work; its checklist should anchor `ANNOTATION_GUIDELINES.md`.

## Prior art (protocol mining + resource grounding)
- Wet-lab-protocol lineage: Kulkarni et al. 2018 (NAACL — 622 protocols as action graphs:
  Action + Reagent/Amount/Concentration/Device/Temp/Time) → **WNUT-2020 Task 1** (NER+RE,
  public baselines) → **X-WLP** (Tamari et al., EACL 2021 — Process Execution Graphs).
- Platforms/corpora: **protocols.io** (Teytelman 2016), Bio-protocol. Executable schemas:
  Autoprotocol, Aquarium, BioCoder. LLM-era: **ProtoCode** (2023), **BioProBench** (2025 —
  LLMs ~70% QA but only ~52% step-ordering → directly relevant to TimelineStage ordering),
  BioPlanner (2023).
- Resource extraction + grounding: **Ozyurt & Bandrowski 2025** (STAR-Methods key-resource
  tables — reagents/antibodies/cell lines) = closest published analogue. **RRID** / Resource
  Identification Initiative / Antibody Registry / Cellosaurus = grounding endpoints.
- **Organoid-specific, corpus-scale extraction/comparison is the gap** (OrganoidDB/Portal
  index transcriptomes, not protocols) — the strongest novelty claim.

## LLM scientific IE + grounding evaluation (baselines / metrics)
- IE lineage: SciERC (2018), **SciREX** (2020 — document-level N-ary RE, matches multi-entity
  protocol relations), SemEval-2017 ScienceIE; in-domain RE: BioRED, BC5CDR.
- Model baselines: SciBERT, PubMedBERT/BiomedBERT, BioGPT; **Galactica = the cautionary tale**
  (withdrawn for fabricated citations → motivates grounding).
- **Grounding/provenance (the core contribution):** **ALCE** (Gao 2023 — citation
  precision/recall; claim→span grounding, maps directly to the `Evidence.quote` span);
  FActScore / SAFE / VeriScore (atomic-fact support). Representation: **PROV-O** +
  **nanopublications** (one protocol fact = one nanopub). KG schema exemplars: Hetionet,
  PrimeKG, SPOKE.

## Framing takeaway
The general protocol-extraction stack is mature (WLP → X-WLP, protocols.io,
ProtoCode/BioProBench) and grounding metrics exist (ALCE, FActScore) — but there is **no
organoid-specific, corpus-scale, evidence-grounded extraction pipeline** and **no organoid
ontology** (the field reuses CL/Uberon + ISSCR-2023 reporting). Position the project as the
open, evidence-grounded, ontology-aligned complement, citing PROV-O / nanopublications for
provenance and ALCE-style metrics for grounding.
