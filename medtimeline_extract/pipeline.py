"""End-to-end extraction: PDF → text → redact → Claude → validate → prediction JSON.

Writes one prediction file per report in the format `medtimeline_eval.evaluate` reads,
plus per-row validation issues and an overall `status` (`extracted` or `needs_review`).

Usage:
    python -m medtimeline_extract.pipeline --reports data/synthetic --out data/predictions
"""

import argparse
import json
import logging
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

import anthropic

from medtimeline_eval.markers import MARKERS, is_plausible, normalise_unit, to_canonical

from .llm import PROMPT_VERSION, ExtractedResult, extract_results
from .text import extract_text, redact_identifiers

logger = logging.getLogger(__name__)


class Status(StrEnum):
    EXTRACTED = "extracted"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


@dataclass
class ValidatedResult:
    marker: str
    printed_name: str
    value: float
    unit: str
    canonical_value: float | None
    issues: list[str] = field(default_factory=list)


def validate(row: ExtractedResult) -> ValidatedResult:
    """Normalise one extracted row and record anything that needs a human to check."""
    code = row.marker.value
    unit = normalise_unit(row.unit)
    result = ValidatedResult(code, row.printed_name, row.value, unit, canonical_value=None)
    if code not in MARKERS:
        result.issues.append("unrecognised_marker")
        return result
    try:
        result.canonical_value = round(to_canonical(code, row.value, unit), 4)
    except ValueError:
        result.issues.append("unit_mismatch")
        return result
    if not is_plausible(code, result.canonical_value):
        result.issues.append("implausible_value")
    return result


def analyse_report(pdf: Path, client: anthropic.Anthropic) -> dict:
    """Run the full pipeline on one PDF.

    Raises:
        Whatever text extraction or the Claude call raises; callers decide on retry.
    """
    text, method = extract_text(pdf)
    extraction = extract_results(redact_identifiers(text), client)

    rows = [validate(r) for r in extraction.results]
    markers = [r.marker for r in rows if r.marker in MARKERS]
    if len(markers) != len(set(markers)):
        for r in rows:
            if markers.count(r.marker) > 1:
                r.issues.append("duplicate_marker")
    needs_review = not rows or extraction.collected_on is None or any(r.issues for r in rows)
    return {
        "status": Status.NEEDS_REVIEW if needs_review else Status.EXTRACTED,
        "text_method": method,
        "prompt_version": PROMPT_VERSION,
        "collected_on": extraction.collected_on.isoformat() if extraction.collected_on else None,
        "results": [asdict(r) for r in rows],
    }


def process_report(pdf: Path, client: anthropic.Anthropic) -> dict:
    """Like `analyse_report`, but never raises: failures become status=failed."""
    try:
        return analyse_report(pdf, client)
    except Exception as exc:
        logger.exception("Extraction failed", extra={"file": pdf.name})
        return {"status": Status.FAILED, "error": f"{type(exc).__name__}: {exc}", "results": []}


def run(reports_dir: Path, out_dir: Path) -> dict[str, int]:
    """Process every PDF in `reports_dir`; return a count per status."""
    pdfs = sorted(reports_dir.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDFs in {reports_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic()
    counts: dict[str, int] = {}
    for pdf in pdfs:
        prediction = process_report(pdf, client)
        (out_dir / f"{pdf.stem}.json").write_text(json.dumps(prediction, indent=2))
        counts[prediction["status"]] = counts.get(prediction["status"], 0) + 1
        logger.info("Processed", extra={"file": pdf.name, "status": prediction["status"]})
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reports", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--out", type=Path, default=Path("data/predictions"))
    args = parser.parse_args()
    print(run(args.reports, args.out))


if __name__ == "__main__":
    main()
