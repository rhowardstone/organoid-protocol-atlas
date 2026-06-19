"""
Extractors
==========
One interface, two backends:

  RuleBasedExtractor  -- runs here, no model. Dictionary + regex + sentence
                         grounding. This is the BASELINE you measure against.
  LLMExtractor        -- same interface, prompt included, backend pluggable.
                         On the A100 box, point `complete` at your provider
                         layer (Anthropic API or local vLLM). Until then it
                         raises, so the demo never silently fakes a model call.

The contract both honor: text in, list[OrganoidProtocol] out, every populated
field that can carry an Evidence span does.
"""

from __future__ import annotations

import re
from typing import Callable, Optional, Protocol

from schema import (
    Concentration,
    Evidence,
    Matrix,
    OrganoidProtocol,
    OrganoidType,
    Reagent,
    SourceCells,
    SourceCellType,
)

# --------------------------------------------------------------------------- #
# Domain dictionaries (the part a biologist would own and extend)
# --------------------------------------------------------------------------- #

REAGENT_ROLES = {
    "EGF": "growth factor",
    "Noggin": "BMP inhibitor",
    "R-spondin1": "Wnt agonist",
    "R-spondin": "Wnt agonist",
    "Wnt3a": "Wnt agonist",
    "CHIR99021": "GSK3 inhibitor (Wnt agonist)",
    "Y-27632": "ROCK inhibitor",
    "SB431542": "TGF-beta inhibitor",
    "A83-01": "TGF-beta inhibitor",
    "FGF9": "growth factor",
    "FGF2": "growth factor",
    "bFGF": "growth factor",
    "BMP4": "morphogen",
    "heparin": "cofactor",
    "Gastrin": "hormone",
    "Nicotinamide": "supplement",
    "B27": "supplement",
    "N2": "supplement",
}

MATRIX_TERMS = ["Matrigel", "Cultrex", "Geltrex", "BME", "basement membrane"]
MEDIA_TERMS = [
    "Advanced DMEM/F12", "DMEM/F12", "mTeSR1", "mTeSR", "Essential 8",
    "Neurobasal", "neural induction medium", "differentiation medium",
]

ORGANOID_KEYWORDS = {
    OrganoidType.INTESTINAL: ["intestinal", "crypt", "Lgr5"],
    OrganoidType.CEREBRAL: ["cerebral", "neural", "neuroepithelial", "embryoid"],
    OrganoidType.KIDNEY: ["kidney", "nephron", "primitive streak", "mesoderm"],
}

UNIT_CANON = {
    "ng/ml": "ng/mL", "ng/mL": "ng/mL",
    "ug/ml": "ug/mL", "µg/ml": "ug/mL",
    "um": "uM", "µm": "uM", "uM": "uM", "µM": "uM",
    "nm": "nM", "nM": "nM", "mm": "mM", "mM": "mM",
}

CONC_RE = re.compile(
    r"\(?\s*(\d+(?:\.\d+)?)\s*(ng/ml|ng/mL|ug/ml|µg/ml|uM|µM|um|nM|nm|mM|mm|%)\s*\)?",
    re.IGNORECASE,
)


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


class Extractor(Protocol):
    def extract(self, doi: str, text: str, organoid_hint: Optional[str] = None) -> OrganoidProtocol: ...


# --------------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------------- #

class RuleBasedExtractor:
    """Deterministic. No model. The number the LLM has to beat."""

    name = "rule_based_v1"

    def extract(self, doi: str, text: str, organoid_hint: Optional[str] = None) -> OrganoidProtocol:
        sentences = _split_sentences(text)

        proto = OrganoidProtocol(source_doi=doi, extractor_version=self.name)
        proto.organoid_type = self._detect_type(text, organoid_hint)
        proto.source_cells = self._detect_cells(text, doi, sentences)
        proto.matrix = self._detect_matrix(text, doi, sentences)
        proto.base_media = self._detect_media(text)
        proto.signaling_factors = self._detect_reagents(doi, sentences)
        proto.assay_endpoints = self._detect_endpoints(text)
        return proto

    def _evidence_for(self, doi: str, sentences: list[str], needle: str, conf: float) -> Optional[Evidence]:
        for s in sentences:
            if needle.lower() in s.lower():
                return Evidence(source_doi=doi, quote=s, section="Methods", confidence=conf)
        return None

    def _detect_type(self, text: str, hint: Optional[str]) -> OrganoidType:
        scores = {ot: sum(kw.lower() in text.lower() for kw in kws)
                  for ot, kws in ORGANOID_KEYWORDS.items()}
        best = max(scores, key=scores.get)
        if scores[best] == 0:
            try:
                return OrganoidType(hint) if hint else OrganoidType.OTHER
            except ValueError:
                return OrganoidType.OTHER
        return best

    def _detect_cells(self, text: str, doi: str, sentences: list[str]) -> SourceCells:
        t = text.lower()
        ct = SourceCellType.OTHER
        if "ipsc" in t:
            ct = SourceCellType.IPSC
        elif "embryonic stem" in t or "esc" in t:
            ct = SourceCellType.ESC
        elif "crypt" in t or "adult" in t:
            ct = SourceCellType.ADULT_STEM
        species = "Mus musculus" if "mouse" in t else ("Homo sapiens" if "human" in t else None)
        return SourceCells(
            cell_type=ct, species=species,
            evidence=self._evidence_for(doi, sentences, "cell", 0.6),
        )

    def _detect_matrix(self, text: str, doi: str, sentences: list[str]) -> Matrix:
        for term in MATRIX_TERMS:
            if term.lower() in text.lower():
                return Matrix(name=term, evidence=self._evidence_for(doi, sentences, term, 0.85))
        return Matrix()

    def _detect_media(self, text: str) -> Optional[str]:
        for term in MEDIA_TERMS:
            if term.lower() in text.lower():
                return term
        return None

    def _detect_reagents(self, doi: str, sentences: list[str]) -> list[Reagent]:
        out: list[Reagent] = []
        seen = set()
        for s in sentences:
            for name, role in REAGENT_ROLES.items():
                if name.lower() in s.lower() and name not in seen:
                    seen.add(name)
                    conc = self._concentration_near(s, name)
                    out.append(Reagent(
                        name=name, role=role, concentration=conc,
                        evidence=Evidence(source_doi=doi, quote=s, section="Methods",
                                          confidence=0.9 if conc else 0.7),
                    ))
        return out

    def _concentration_near(self, sentence: str, reagent: str) -> Optional[Concentration]:
        idx = sentence.lower().find(reagent.lower())
        window = sentence[idx: idx + len(reagent) + 25]
        m = CONC_RE.search(window)
        if not m:
            return None
        val, unit = m.group(1), m.group(2)
        return Concentration(
            value=float(val), unit=unit,
            canonical_unit=UNIT_CANON.get(unit.lower(), unit), raw=m.group(0).strip(),
        )

    def _detect_endpoints(self, text: str) -> list[str]:
        eps = []
        for marker in ["Lgr5", "PAX6", "SOX2", "WT1", "PAX2", "nephrin",
                       "crypt-villus morphology", "immunostaining"]:
            if marker.lower() in text.lower():
                eps.append(marker)
        return eps


# --------------------------------------------------------------------------- #
# LLM backend (interface only — wire on port)
# --------------------------------------------------------------------------- #

EXTRACTION_PROMPT = """You are extracting an organoid culture protocol from a methods section.
Return ONLY JSON matching the OrganoidProtocol schema. For every reagent and the
matrix, include an `evidence.quote` that is a verbatim span from the text. If a
field is not stated, omit it rather than guessing. Methods text:

{text}
"""


class LLMExtractor:
    """Same contract, model-backed. `complete` is your provider call."""

    name = "llm_v1"

    def __init__(self, complete: Optional[Callable[[str], str]] = None):
        # On the A100 box: complete = lambda prompt: your_vllm_or_anthropic_call(prompt)
        self.complete = complete

    def extract(self, doi: str, text: str, organoid_hint: Optional[str] = None) -> OrganoidProtocol:
        if self.complete is None:
            raise NotImplementedError(
                "LLMExtractor needs a `complete` backend. Wire craig/llm_providers "
                "here when porting. The demo runs on RuleBasedExtractor until then."
            )
        raw = self.complete(EXTRACTION_PROMPT.format(text=text))
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        proto = OrganoidProtocol.model_validate_json(cleaned)
        proto.source_doi = doi
        proto.extractor_version = self.name
        return proto
