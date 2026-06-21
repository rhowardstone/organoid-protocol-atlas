#!/usr/bin/env python3
"""
Prediction-file schema validator (offline, no GPU/network).

Validates OrganoidProtocol JSON prediction files produced by tier1_extract.py
against schema v0.4 before they are committed or promoted.

Checks:
  - Pydantic schema parse (catches structural violations)
  - schema_version == "0.4"
  - source_doi is present and looks like a DOI (starts "10.")
  - All Evidence objects have non-empty quote strings
  - Evidence.sentence_id is None or a non-negative int (never a string)
  - Evidence.confidence in [0.0, 1.0]
  - FailureMode.description is non-empty
  - ProtocolModification.change_description is non-empty
  - ProtocolModification.cited_doi matches DOI pattern when present
  - Reagent names are non-empty
  - Concentration: value present implies unit present (don't parse "ng/mL None")

Returns exit code 0 if all files pass, 1 if any error found.

Usage:
  python pipeline/validate_predictions.py                 # data/predictions/local/
  python pipeline/validate_predictions.py --path /tmp/x  # any directory or file
  python pipeline/validate_predictions.py --strict        # warnings → errors
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_PRED_DIR = REPO / "data" / "predictions" / "local"

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+")
CURRENT_SCHEMA = "0.4"


# --------------------------------------------------------------------------- #
# Issue collector
# --------------------------------------------------------------------------- #

class Result:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


# --------------------------------------------------------------------------- #
# Individual checks (operate on raw dict so they run before Pydantic parse)
# --------------------------------------------------------------------------- #

def _check_evidence(ev: dict, context: str, r: Result) -> None:
    if not isinstance(ev, dict):
        r.error(f"{context}: evidence is not a dict")
        return
    quote = ev.get("quote")
    if not quote or not str(quote).strip():
        r.error(f"{context}: evidence.quote is empty or missing")
    elif len(str(quote)) < 5:
        r.warn(f"{context}: evidence.quote very short ({len(str(quote))} chars) — may be truncated")

    sid = ev.get("sentence_id")
    if sid is not None:
        if not isinstance(sid, int) or sid < 0:
            r.error(f"{context}: evidence.sentence_id must be non-negative int or null, got {sid!r}")

    conf = ev.get("confidence")
    if conf is not None:
        if not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
            r.error(f"{context}: evidence.confidence must be 0.0-1.0, got {conf!r}")


def _check_reagent(reagent: dict, context: str, r: Result) -> None:
    name = reagent.get("name")
    if not name or not str(name).strip():
        r.error(f"{context}: reagent name is empty or missing")

    conc = reagent.get("concentration")
    if conc and isinstance(conc, dict):
        val = conc.get("value")
        unit = conc.get("unit")
        if val is not None and not unit:
            r.warn(f"{context}: concentration.value={val} but unit is missing")

    ev = reagent.get("evidence")
    if ev:
        _check_evidence(ev, f"{context}.evidence", r)


def _check_failure_mode(fm: dict, idx: int, r: Result) -> None:
    desc = fm.get("description")
    if not desc or not str(desc).strip():
        r.error(f"failure_modes[{idx}]: description is empty or missing")
    ev = fm.get("evidence")
    if ev:
        _check_evidence(ev, f"failure_modes[{idx}].evidence", r)


def _check_modification(mod: dict, idx: int, r: Result) -> None:
    desc = mod.get("change_description")
    if not desc or not str(desc).strip():
        r.error(f"modifications[{idx}]: change_description is empty or missing")

    cited = mod.get("cited_doi")
    if cited:
        if not DOI_RE.match(str(cited)):
            r.error(f"modifications[{idx}]: cited_doi {cited!r} does not match DOI pattern 10.xxxx/...")
        ev = mod.get("evidence")
        if ev and isinstance(ev, dict):
            quote = ev.get("quote") or ""
            # Anti-fabrication: a cited_doi that doesn't appear anywhere in the quote
            # is suspicious (they're often extracted together). Warn, not error, since
            # the DOI may be derived from context rather than the quote itself.
            if cited not in quote:
                r.warn(
                    f"modifications[{idx}]: cited_doi {cited!r} not found verbatim in "
                    f"evidence.quote — verify this is a real in-text citation"
                )
    ev = mod.get("evidence")
    if ev:
        _check_evidence(ev, f"modifications[{idx}].evidence", r)


def validate_file(path: Path) -> Result:
    r = Result(path)

    # --- Parse JSON ---
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        r.error(f"Cannot parse JSON: {e}")
        return r

    if not isinstance(data, dict):
        r.error("Top-level value must be a JSON object")
        return r

    # --- Pydantic schema parse ---
    try:
        sys.path.insert(0, str(REPO / "organoid_demo"))
        from schema import OrganoidProtocol  # noqa: PLC0415
        OrganoidProtocol(**data)
    except Exception as e:
        r.error(f"Pydantic schema validation failed: {e}")
        # Continue checking raw dict anyway — we want all issues, not just the first

    # --- schema_version ---
    sv = data.get("schema_version")
    if sv != CURRENT_SCHEMA:
        r.error(f"schema_version is {sv!r}, expected {CURRENT_SCHEMA!r}")

    # --- source_doi ---
    doi = data.get("source_doi")
    if not doi:
        r.error("source_doi is missing")
    elif not DOI_RE.match(str(doi)):
        r.error(f"source_doi {doi!r} does not start with '10.' — not a valid DOI")

    # --- organoid_type ---
    VALID_TYPES = {
        "intestinal", "gastric", "cerebral", "kidney", "liver",
        "lung", "retinal", "pancreatic",
        "tumor", "cardiac", "vascular", "cholangiocyte", "skin",
        "mammary", "endometrial", "bone", "prostate", "inner-ear",
        "salivary-gland", "bladder", "neuromuscular", "esophageal",
        "blood-brain-barrier", "thyroid", "fallopian-tube",
        "other",
    }
    ot = data.get("organoid_type", "other")
    if ot not in VALID_TYPES:
        r.warn(f"organoid_type {ot!r} not in known set {sorted(VALID_TYPES)}")

    # --- Reagents ---
    for field in ("signaling_factors", "small_molecules", "media_supplements"):
        for i, rg in enumerate(data.get(field) or []):
            if isinstance(rg, dict):
                _check_reagent(rg, f"{field}[{i}]", r)

    # --- Timeline reagents ---
    for i, stage in enumerate(data.get("timeline") or []):
        if isinstance(stage, dict):
            for j, rg in enumerate(stage.get("reagents") or []):
                if isinstance(rg, dict):
                    _check_reagent(rg, f"timeline[{i}].reagents[{j}]", r)
            ev = stage.get("evidence")
            if ev:
                _check_evidence(ev, f"timeline[{i}].evidence", r)

    # --- Sub-model evidence ---
    for field in ("source_cells", "matrix", "base_media", "passaging", "culture_conditions"):
        sub = data.get(field)
        if isinstance(sub, dict):
            ev = sub.get("evidence")
            if ev:
                _check_evidence(ev, f"{field}.evidence", r)

    # --- FailureModes ---
    for i, fm in enumerate(data.get("failure_modes") or []):
        if isinstance(fm, dict):
            _check_failure_mode(fm, i, r)

    # --- Modifications ---
    for i, mod in enumerate(data.get("modifications") or []):
        if isinstance(mod, dict):
            _check_modification(mod, i, r)

    return r


def validate_dir(directory: Path) -> list[Result]:
    files = sorted(directory.glob("*.json"))
    if not files:
        print(f"No .json files found in {directory}", file=sys.stderr)
    return [validate_file(f) for f in files]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description="Validate OrganoidProtocol prediction JSON files")
    ap.add_argument("--path", type=Path, default=DEFAULT_PRED_DIR,
                    help="Directory or single file to validate (default: data/predictions/local/)")
    ap.add_argument("--strict", action="store_true",
                    help="Treat warnings as errors")
    ap.add_argument("--quiet", action="store_true",
                    help="Only report files with issues")
    args = ap.parse_args()

    target = args.path
    if not target.exists():
        print(f"Path does not exist: {target}", file=sys.stderr)
        print("(prediction files are git-ignored; run tier1_extract.py to generate them)")
        return 0  # Not an error — just nothing to validate yet

    results: list[Result]
    if target.is_file():
        results = [validate_file(target)]
    else:
        results = validate_dir(target)

    n_ok = n_warn = n_err = 0
    for res in results:
        has_issue = res.errors or res.warnings
        if not has_issue and args.quiet:
            n_ok += 1
            continue

        status = "✗ FAIL" if res.errors else ("⚠ WARN" if res.warnings else "✓ ok")
        print(f"{status}  {res.path.name}")

        for e in res.errors:
            print(f"     ERROR: {e}")
        for w in res.warnings:
            print(f"     WARN:  {w}")

        if res.errors:
            n_err += 1
        elif res.warnings:
            n_warn += 1
        else:
            n_ok += 1

    if args.quiet and n_ok:
        print(f"{n_ok} files ok (not shown)")

    print(f"\n{len(results)} files: {n_ok} ok, {n_warn} warnings, {n_err} errors")

    if n_err:
        return 1
    if args.strict and n_warn:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
