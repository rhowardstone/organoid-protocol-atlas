"""
Organoid Protocol Schema
========================
An evidence-grounded data model for extracting organoid culture protocols
from biomedical methods sections.

Design principles (these are the talking points, not just code comments):

1. EVERY non-trivial field carries provenance. A value the model cannot tie
   to a source span is a liability, not a feature. `Evidence` is mandatory on
   the fields that matter, optional-but-tracked elsewhere.

2. ABSENCE IS DATA. Methods sections omit tacit lab knowledge constantly
   (passage number, exact Matrigel lot, ROCK-inhibitor washout timing).
   We model "not reported" distinctly from "not applicable" so that
   omission becomes a measurable, analyzable signal rather than a silent gap.

3. CONCENTRATIONS ARE STRUCTURED, NOT STRINGS. "50 ng/mL EGF" is parsed into
   value + unit + analyte so we can normalize and compare across papers that
   report the same reagent three different ways. Unit normalization is one of
   the core research problems, so it gets a first-class representation.

4. THE SCHEMA IS DELIBERATELY LOSSY AT THE EDGES. We do not try to capture
   everything a wet-lab protocol contains. We capture the axes along which
   protocols actually differ and along which "consensus" is a meaningful
   question: source cells, matrix, media base, signaling cocktail, timeline,
   passaging, endpoints.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Provenance primitives
# --------------------------------------------------------------------------- #

class Evidence(BaseModel):
    """Ties an extracted value back to a source span. Grounding, made concrete."""
    source_doi: str = Field(..., description="DOI of the paper the value came from.")
    quote: str = Field(..., description="Verbatim source span supporting the value.")
    section: Optional[str] = Field(None, description="e.g. 'Methods', 'Supplementary'.")
    page: Optional[int] = None
    # Extractor's self-reported confidence. Calibration of this number against
    # the gold set is itself an evaluation target.
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class Reporting(str, Enum):
    """Why a field is empty. 'Not reported' and 'not applicable' are different findings."""
    REPORTED = "reported"
    NOT_REPORTED = "not_reported"   # tacit/omitted — a measurable gap
    NOT_APPLICABLE = "not_applicable"


# --------------------------------------------------------------------------- #
# Controlled vocabularies (stubs — the ontology-grounding layer plugs in here)
# --------------------------------------------------------------------------- #

class OrganoidType(str, Enum):
    INTESTINAL = "intestinal"
    GASTRIC = "gastric"
    CEREBRAL = "cerebral"
    KIDNEY = "kidney"
    LIVER = "liver"
    LUNG = "lung"
    RETINAL = "retinal"
    PANCREATIC = "pancreatic"
    OTHER = "other"


class SourceCellType(str, Enum):
    IPSC = "iPSC"
    ESC = "ESC"
    ADULT_STEM = "adult_stem_cell"
    PRIMARY = "primary_tissue"
    OTHER = "other"


# --------------------------------------------------------------------------- #
# Quantitative primitives
# --------------------------------------------------------------------------- #

class Concentration(BaseModel):
    """
    A parsed reagent concentration. Normalization target: we want
    50 ng/mL, 50 ng·mL-1, and '50ng/ml' to collapse to one canonical form.
    """
    value: Optional[float] = None
    unit: Optional[str] = Field(None, description="Raw unit string as reported.")
    canonical_unit: Optional[str] = Field(None, description="Normalized unit, if resolvable.")
    raw: Optional[str] = Field(None, description="Original surface form, always retained.")


class Reagent(BaseModel):
    """A growth factor, small molecule, or supplement."""
    name: str = Field(..., description="As reported (e.g. 'R-spondin1', 'Y-27632').")
    canonical_name: Optional[str] = Field(None, description="Resolved standard name.")
    ontology_id: Optional[str] = Field(None, description="ChEBI/PR/other ID once grounded.")
    role: Optional[str] = Field(None, description="e.g. 'Wnt agonist', 'ROCK inhibitor'.")
    concentration: Optional[Concentration] = None
    evidence: Optional[Evidence] = None


# --------------------------------------------------------------------------- #
# Protocol components
# --------------------------------------------------------------------------- #

class SourceCells(BaseModel):
    cell_type: SourceCellType = SourceCellType.OTHER
    line_name: Optional[str] = Field(None, description="e.g. 'H9', 'WTC-11', patient-derived ID.")
    species: Optional[str] = Field(None, description="e.g. 'Homo sapiens', 'Mus musculus'.")
    reporting: Reporting = Reporting.REPORTED
    evidence: Optional[Evidence] = None


class Matrix(BaseModel):
    name: Optional[str] = Field(None, description="e.g. 'Matrigel', 'Cultrex BME-2', synthetic hydrogel.")
    percent: Optional[float] = Field(None, description="If embedded at a given %.")
    reporting: Reporting = Reporting.REPORTED
    evidence: Optional[Evidence] = None


class BaseMedia(BaseModel):
    """
    The basal culture medium. Modeled like Matrix (not a bare string) so that
    absence is typed and the value can carry provenance. This is the field the
    kidney case exercises: the source omits it (`not_reported`), which is a
    finding — distinct from the extractor simply missing it.
    """
    name: Optional[str] = Field(None, description="e.g. 'Advanced DMEM/F12', 'mTeSR1'.")
    reporting: Reporting = Reporting.REPORTED
    evidence: Optional[Evidence] = None


class TimelineStage(BaseModel):
    """One differentiation/maturation stage. Step-ordering is an eval target."""
    name: str = Field(..., description="e.g. 'embryoid body', 'neural induction', 'expansion'.")
    day_start: Optional[int] = None
    day_end: Optional[int] = None
    reagents: list[Reagent] = Field(default_factory=list)
    evidence: Optional[Evidence] = None


class Passaging(BaseModel):
    method: Optional[str] = Field(None, description="e.g. 'mechanical', 'enzymatic (TrypLE)'.")
    split_ratio: Optional[str] = Field(None, description="e.g. '1:4'.")
    interval_days: Optional[int] = None
    reporting: Reporting = Reporting.REPORTED
    evidence: Optional[Evidence] = None


# --------------------------------------------------------------------------- #
# Top-level protocol
# --------------------------------------------------------------------------- #

class OrganoidProtocol(BaseModel):
    """A single organoid culture protocol extracted from one source."""
    source_doi: str
    organoid_type: OrganoidType = OrganoidType.OTHER

    source_cells: SourceCells = Field(default_factory=SourceCells)
    matrix: Matrix = Field(default_factory=Matrix)
    base_media: BaseMedia = Field(default_factory=BaseMedia)
    media_supplements: list[Reagent] = Field(default_factory=list)
    signaling_factors: list[Reagent] = Field(
        default_factory=list,
        description="Growth factors / morphogens defining the protocol's identity.",
    )
    small_molecules: list[Reagent] = Field(default_factory=list)

    timeline: list[TimelineStage] = Field(default_factory=list)
    passaging: Passaging = Field(default_factory=Passaging)

    assay_endpoints: list[str] = Field(
        default_factory=list,
        description="What the protocol validates against (markers, imaging, function).",
    )

    # Extraction-level metadata for evaluation
    schema_version: str = "0.2"
    extractor_version: Optional[str] = None
    notes: Optional[str] = None


if __name__ == "__main__":
    # Tiny smoke test so this file is demonstrably runnable, not aspirational.
    p = OrganoidProtocol(
        source_doi="10.1038/nature07935",  # Sato et al., intestinal organoids
        organoid_type=OrganoidType.INTESTINAL,
        source_cells=SourceCells(cell_type=SourceCellType.ADULT_STEM, species="Mus musculus"),
        matrix=Matrix(name="Matrigel"),
        base_media=BaseMedia(name="Advanced DMEM/F12"),
        signaling_factors=[
            Reagent(
                name="EGF",
                role="growth factor",
                concentration=Concentration(value=50, unit="ng/mL", canonical_unit="ng/mL", raw="50 ng/ml"),
                evidence=Evidence(
                    source_doi="10.1038/nature07935",
                    quote="...supplemented with EGF (50 ng/ml)...",
                    section="Methods",
                    confidence=0.92,
                ),
            ),
            Reagent(name="R-spondin1", role="Wnt agonist"),
            Reagent(name="Noggin", role="BMP inhibitor"),
        ],
        assay_endpoints=["Lgr5 expression", "crypt-villus morphology"],
    )
    print(p.model_dump_json(indent=2))
