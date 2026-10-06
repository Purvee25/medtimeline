"""Rule-based extractor: the no-LLM baseline that Claude has to beat.

Matches each line against the marker catalogue's names and aliases (longest first), then
reads the number and unit that follow. Free and deterministic, but brittle on layouts
or OCR noise it was not written for, which is exactly what the comparison should show.
"""

import re
from datetime import date

from medtimeline_eval.markers import MARKERS

from .llm import ExtractedResult, Extraction

# "<label> [dots/colon] <value> [H|L] <unit>", e.g. "Hemoglobin ..... 13.2 g/dL (12.0 - 17.0)"
_VALUE_UNIT = re.compile(r"^[\s.:\-]*(?P<value>\d+(?:\.\d+)?)\s*(?:[HL]\s+)?(?P<unit>[^\s()]+)")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY_DATE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")


def _build_labels() -> list[tuple[re.Pattern[str], str]]:
    labels = [(label, m.code) for m in MARKERS.values() for label in (m.name, *m.aliases)]
    labels.sort(key=lambda pair: len(pair[0]), reverse=True)
    return [(re.compile(rf"^\s*{re.escape(label)}(?![\w-])", re.IGNORECASE), code) for label, code in labels]


_LABELS = _build_labels()


def _collection_date(text: str) -> date | None:
    for line in text.splitlines():
        if not re.search(r"collect|sample", line, re.IGNORECASE):
            continue
        if m := _ISO_DATE.search(line):
            return _safe_date(int(m[1]), int(m[2]), int(m[3]))
        if m := _DMY_DATE.search(line):
            return _safe_date(int(m[3]), int(m[2]), int(m[1]))
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_line(line: str) -> ExtractedResult | None:
    for pattern, code in _LABELS:
        label = pattern.match(line)
        if not label:
            continue
        rest = _VALUE_UNIT.match(line[label.end() :])
        if not rest:
            return None
        return ExtractedResult(
            marker=code, printed_name=label.group(0).strip(), value=float(rest["value"]), unit=rest["unit"]
        )
    return None


def extract_baseline(text: str) -> Extraction:
    """Extract results from report text with fixed rules; never calls a model."""
    results = [row for line in text.splitlines() if (row := _parse_line(line))]
    return Extraction(collected_on=_collection_date(text), results=results)
