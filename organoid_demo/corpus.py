"""
Tiny demo corpus: representative methods text for three canonical organoid
systems. The reagent cocktails are factual (textbook protocol chemistry);
the prose is paraphrased to a representative form. When you port this onto
the real repo, replace each `text` with the actual Methods/Supplementary
section extracted by craig/literature/extraction (GROBID or PyMuPDF), keyed
by the same DOI.

Each entry is what your extraction layer hands the extractor: a DOI + the
methods text. Nothing else.
"""

CORPUS = [
    {
        "doi": "10.1038/nature07935",  # Sato et al., intestinal organoids
        "organoid_hint": "intestinal",
        "text": (
            "Isolated mouse small intestinal crypts were embedded in Matrigel and "
            "overlaid with Advanced DMEM/F12 supplemented with EGF (50 ng/ml), "
            "Noggin (100 ng/ml) and R-spondin1 (500 ng/ml). Cultures were maintained "
            "at 37 C and passaged every 7 days by mechanical dissociation at a 1:4 "
            "ratio. Organoid formation was assessed by crypt-villus morphology and "
            "Lgr5 expression."
        ),
    },
    {
        "doi": "10.1038/nature12517",  # Lancaster et al., cerebral organoids
        "organoid_hint": "cerebral",
        "text": (
            "Human embryonic stem cells were aggregated to form embryoid bodies in "
            "low-bFGF medium, then transferred to neural induction medium. "
            "Neuroepithelial tissues were embedded in Matrigel droplets and cultured "
            "in differentiation medium containing B27 and N2 without added growth "
            "factors. Embedded organoids were grown in a spinning bioreactor for up "
            "to 40 days. Tissue identity was confirmed by PAX6 and SOX2 immunostaining."
        ),
    },
    {
        "doi": "10.1038/nature15695",  # Takasato et al., kidney organoids
        "organoid_hint": "kidney",
        "text": (
            "Human iPSCs (line CRL1502) were treated with CHIR99021 (8 uM) for 4 days "
            "to induce posterior primitive streak, followed by FGF9 (200 ng/ml) and "
            "heparin (1 ug/ml) to promote intermediate mesoderm. Cells were aggregated "
            "and cultured for 7 days, with a brief CHIR99021 pulse on day 7. Nephron "
            "formation was evaluated by WT1, PAX2 and nephrin expression."
        ),
    },
]
