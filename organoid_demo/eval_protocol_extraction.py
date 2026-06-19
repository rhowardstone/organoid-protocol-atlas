"""
Evaluation harness for organoid protocol extraction.

Grades any Extractor against gold_annotations.json and emits the metric set
the build handoff defines. The metrics are not a report card -- the
reporting-status and grounding numbers are the signals the production router
reads to decide tier escalation.

Run:
    python eval_protocol_extraction.py

Writes:
    outputs/predictions.json
    outputs/evaluation_summary.json
    outputs/error_analysis.md
"""

from __future__ import annotations

import json
import os

from corpus import CORPUS
from extractors import RuleBasedExtractor
from schema import OrganoidProtocol

GOLD_PATH = "gold_annotations.json"
OUT_DIR = "outputs"

# Names that refer to the same entity. Real port replaces this with the
# normalization pass over scientific_ner.py + an ontology.
NAME_CANON = {
    "r-spondin": "r-spondin1",
    "r-spondin1": "r-spondin1",
    "bfgf": "bfgf",
    "fgf2": "bfgf",
}


def canon(name: str) -> str:
    key = name.strip().lower()
    return NAME_CANON.get(key, key)


def load_gold() -> dict:
    with open(GOLD_PATH) as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def predict() -> dict[str, OrganoidProtocol]:
    ex = RuleBasedExtractor()
    out = {}
    for e in CORPUS:
        out[e["doi"]] = ex.extract(e["doi"], e["text"], e.get("organoid_hint"))
    return out


def evaluate(preds: dict[str, OrganoidProtocol], gold: dict) -> dict:
    scalar_hits = scalar_total = 0
    report_hits = report_total = 0
    tp = fp = fn = 0
    unit_hits = unit_total = 0
    grounded = factor_total = 0
    fp_examples = []
    report_errors = []

    for doi, g in gold.items():
        p = preds[doi]

        # --- scalar exact match (only on fields gold marks reported) ---
        scalar_checks = [
            (p.organoid_type.value, g["organoid_type"]),
            (p.source_cells.cell_type.value, g["source_cells"]["cell_type"]),
            (p.source_cells.species, g["source_cells"]["species"]),
        ]
        if g["matrix"]["reporting"] == "reported":
            scalar_checks.append((p.matrix.name, g["matrix"]["name"]))
        if g["base_media"]["reporting"] == "reported":
            scalar_checks.append((p.base_media.name, g["base_media"]["value"]))
        for got, want in scalar_checks:
            scalar_total += 1
            if got == want:
                scalar_hits += 1

        # --- reporting-status accuracy (matrix + base_media) ---
        # The baseline cannot tell omission from a miss: a None value still
        # carries a default 'reported' status, or no status at all. We score
        # that confusion explicitly.
        pred_matrix_status = "reported" if p.matrix.name else "unresolved_absence"
        report_total += 1
        if pred_matrix_status == g["matrix"]["reporting"]:
            report_hits += 1
        else:
            report_errors.append(f"{g['organoid_type']}: matrix predicted "
                                  f"{pred_matrix_status}, gold {g['matrix']['reporting']}")

        pred_media_status = "reported" if p.base_media.name else "unresolved_absence"
        report_total += 1
        if pred_media_status == g["base_media"]["reporting"]:
            report_hits += 1
        else:
            report_errors.append(f"{g['organoid_type']}: base_media predicted "
                                 f"{pred_media_status}, gold {g['base_media']['reporting']}")

        # --- signaling factors: precision / recall / dup / grounding ---
        gold_factors = {canon(f["name"]): f for f in g["signaling_factors"]}
        gold_conc = {canon(f["name"]): f.get("concentration") for f in g["signaling_factors"]}
        matched = set()
        for r in p.signaling_factors:
            factor_total += 1
            if r.evidence:
                grounded += 1
            ck = canon(r.name)
            if ck in gold_factors and ck not in matched:
                tp += 1
                matched.add(ck)
                # unit normalization on matched factors that have a gold conc
                gc = gold_conc[ck]
                if gc is not None:
                    unit_total += 1
                    if (r.concentration and r.concentration.value == gc["value"]
                            and (r.concentration.canonical_unit == gc["canonical_unit"])):
                        unit_hits += 1
            else:
                fp += 1
                reason = "duplicate" if ck in matched else "wrong-bucket / not-in-gold"
                fp_examples.append(f"{g['organoid_type']}: '{r.name}' -> {reason}")
        fn += len(gold_factors) - len(matched)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    return {
        "scalar_exact_match": {"hits": scalar_hits, "total": scalar_total,
                               "score": round(scalar_hits / scalar_total, 4) if scalar_total else None},
        "reporting_status_accuracy": {"hits": report_hits, "total": report_total,
                                      "score": round(report_hits / report_total, 4) if report_total else None,
                                      "errors": report_errors},
        "signaling_factor_precision": round(precision, 4),
        "signaling_factor_recall": round(recall, 4),
        "unit_normalization_accuracy": {"hits": unit_hits, "total": unit_total,
                                        "score": round(unit_hits / unit_total, 4) if unit_total else None},
        "evidence_grounding": {"hits": grounded, "total": factor_total,
                               "score": round(grounded / factor_total, 4) if factor_total else None},
        "wrong_bucket_or_duplicate_rate": {"count": fp, "of_predicted": factor_total,
                                           "rate": round(fp / factor_total, 4) if factor_total else None,
                                           "examples": fp_examples},
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    preds = predict()
    gold = load_gold()
    summary = evaluate(preds, gold)

    with open(f"{OUT_DIR}/predictions.json", "w") as f:
        json.dump({doi: json.loads(p.model_dump_json()) for doi, p in preds.items()}, f, indent=2)
    with open(f"{OUT_DIR}/evaluation_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    # error_analysis.md -- the error-analysis artifact
    sf = summary
    lines = [
        "# Error Analysis -- rule_based_v1 baseline",
        "",
        "Baseline extractor vs 3-protocol gold. These are the failures the "
        "research is about; do not silently fix them.",
        "",
        f"- Scalar exact match: {sf['scalar_exact_match']['hits']}/{sf['scalar_exact_match']['total']} = {sf['scalar_exact_match']['score']}",
        f"- Reporting-status accuracy: {sf['reporting_status_accuracy']['hits']}/{sf['reporting_status_accuracy']['total']} = {sf['reporting_status_accuracy']['score']}",
        f"- Signaling factor precision: {sf['signaling_factor_precision']}",
        f"- Signaling factor recall: {sf['signaling_factor_recall']}",
        f"- Unit-normalization accuracy: {sf['unit_normalization_accuracy']['hits']}/{sf['unit_normalization_accuracy']['total']} = {sf['unit_normalization_accuracy']['score']}",
        f"- Evidence grounding: {sf['evidence_grounding']['hits']}/{sf['evidence_grounding']['total']} = {sf['evidence_grounding']['score']}",
        f"- Wrong-bucket / duplicate rate: {sf['wrong_bucket_or_duplicate_rate']['count']}/{sf['wrong_bucket_or_duplicate_rate']['of_predicted']} = {sf['wrong_bucket_or_duplicate_rate']['rate']}",
        "",
        "## Preserved failure modes",
        "",
        "1. Synonym duplication:",
    ]
    for e in sf["wrong_bucket_or_duplicate_rate"]["examples"]:
        lines.append(f"   - {e}")
    lines += ["", "2. Reporting-status confusion (omission vs miss):"]
    for e in sf["reporting_status_accuracy"]["errors"]:
        lines.append(f"   - {e}")
    lines += [
        "",
        "3. Grounded but mis-typed: B27 and N2 are grounded in the text yet "
        "scored as wrong-bucket signaling factors. Grounding does not imply "
        "correct biological category.",
    ]
    with open(f"{OUT_DIR}/error_analysis.md", "w") as f:
        f.write("\n".join(lines))

    # console
    print("== Evaluation summary (rule_based_v1) ==\n")
    print(f"  Scalar exact match:        {sf['scalar_exact_match']['hits']}/{sf['scalar_exact_match']['total']} = {sf['scalar_exact_match']['score']}")
    print(f"  Reporting-status accuracy: {sf['reporting_status_accuracy']['hits']}/{sf['reporting_status_accuracy']['total']} = {sf['reporting_status_accuracy']['score']}")
    print(f"  Signaling factor precision:       {sf['signaling_factor_precision']}")
    print(f"  Signaling factor recall:          {sf['signaling_factor_recall']}")
    print(f"  Unit-normalization accuracy: {sf['unit_normalization_accuracy']['hits']}/{sf['unit_normalization_accuracy']['total']} = {sf['unit_normalization_accuracy']['score']}")
    print(f"  Evidence grounding:        {sf['evidence_grounding']['hits']}/{sf['evidence_grounding']['total']} = {sf['evidence_grounding']['score']}")
    print(f"  Wrong-bucket / duplicate rate: {sf['wrong_bucket_or_duplicate_rate']['count']}/{sf['wrong_bucket_or_duplicate_rate']['of_predicted']} = {sf['wrong_bucket_or_duplicate_rate']['rate']}")
    print(f"\n  Wrote {OUT_DIR}/predictions.json, evaluation_summary.json, error_analysis.md")


if __name__ == "__main__":
    main()
