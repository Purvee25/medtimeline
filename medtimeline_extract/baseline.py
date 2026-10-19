"""Rule-based extractor: the no-LLM baseline that Claude has to beat.

Matches each line against the marker catalogue's names and aliases (longest first), then
reads the number and unit that follow. Free and deterministic, but brittle on layouts
or OCR noise it was not written for, which is exactly what the comparison should show.

Two passes per row: a strict "<label> <value> <unit>" rule, then a loose one for column-layout
text layers where the specimen, method and reference columns are interleaved with the value.
"""

import re
from datetime import date
from functools import cache

from medtimeline_eval.markers import MARKERS, normalise_unit, unit_spellings

from .llm import ExtractedResult, Extraction

# "<label> [dots/colon] <value> [H|L] <unit>", e.g. "Hemoglobin ..... 13.2 g/dL (12.0 - 17.0)"
_VALUE_UNIT = re.compile(r"^[\s.:\-]*(?P<value>\d+(?:\.\d+)?)\s*(?:[HL]\s+)?(?P<unit>[^\s()]+)")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY_DATE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_DMON_DATE = re.compile(rf"\b(\d{{1,2}})[-/ ]({'|'.join(_MONTHS)})[a-z]*[-/ ](\d{{4}})\b", re.IGNORECASE)
_COLLECTION_HINT = re.compile(r"collect|sample", re.IGNORECASE)

# Loose rows: "<label> (<specimen>) ... <value><glued text> ... <unit>". The specimen may be left
# unclosed when the text layer wraps it onto the next line.
_SPECIMEN = re.compile(r"^\s*(?:\([^)\d]*\)?)?")
# Indian grouping (3,92,000), Western grouping (10,630), then a plain decimal. Not anchored at the end:
# pdftotext glues the value to the method or reference column ("62.2Flowcytometry").
_LOOSE_VALUE = re.compile(r"(?<![\d.,])(\d{1,2}(?:,\d{2})+,\d{3}|\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)")
# Cell counts: a per-volume unit, optionally scaled ("Million / cu.mm", "Lakhs/cumm", "/cu.mm").
_PER_VOLUME = re.compile(r"cu\.?\s*mm|mm3|/\s*[uµ]l\b", re.IGNORECASE)
_MILLION = re.compile(r"\bmill(?:ion)?s?\b", re.IGNORECASE)
_LAKH = re.compile(r"\blakhs?\b", re.IGNORECASE)


def _build_labels() -> list[tuple[re.Pattern[str], str]]:
    labels = [(label, m.code) for m in MARKERS.values() for label in (m.name, *m.aliases)]
    labels.sort(key=lambda pair: len(pair[0]), reverse=True)
    return [(re.compile(rf"^\s*{re.escape(label)}(?![\w-])", re.IGNORECASE), code) for label, code in labels]


_LABELS = _build_labels()


def _collection_date(text: str) -> date | None:
    for line in text.splitlines():
        hint = _COLLECTION_HINT.search(line)
        if not hint:
            continue
        # Prefer the date after the hint: rows often also carry "Labelled on" / "Received on" dates.
        for segment in (line[hint.start() :], line):
            if found := _parse_date(segment):
                return found
    return None


def _parse_date(text: str) -> date | None:
    if m := _ISO_DATE.search(text):
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))
    if m := _DMY_DATE.search(text):
        return _safe_date(int(m[3]), int(m[2]), int(m[1]))
    if m := _DMON_DATE.search(text):
        return _safe_date(int(m[3]), _MONTHS.index(m[2].lower()) + 1, int(m[1]))
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


@cache
def _valid_units(code: str) -> frozenset[str]:
    marker = MARKERS[code]
    return frozenset({marker.canonical_unit, *marker.alt_units})


def _find_unit(code: str, row: str) -> str | None:
    """First unit in `row` that is valid for `code`, or None. Units must not run on from a word ("mg/dL")."""
    if _PER_VOLUME.search(row):
        count_unit = "10^6/uL" if _MILLION.search(row) else "lakhs/cumm" if _LAKH.search(row) else "/uL"
        if normalise_unit(count_unit) in _valid_units(code):
            return count_unit
    lowered = row.lower()
    for spelling in unit_spellings(code):
        if re.search(rf"(?<![a-z]){re.escape(spelling)}", lowered):
            return spelling
    return None


def _parse_loose(code: str, printed_name: str, rest: str, continuation: str) -> ExtractedResult | None:
    body = rest[_SPECIMEN.match(rest).end() :]
    value = _LOOSE_VALUE.search(body)
    unit = _find_unit(code, f"{rest} {continuation}")
    if not value or not unit:
        return None
    return ExtractedResult(marker=code, printed_name=printed_name, value=float(value[1].replace(",", "")), unit=unit)


def _match_label(line: str) -> tuple[str, re.Match[str]] | None:
    for pattern, code in _LABELS:
        if label := pattern.match(line):
            return code, label
    return None


def _parse_line(line: str, continuation: str = "") -> ExtractedResult | None:
    matched = _match_label(line)
    if not matched:
        return None
    code, label = matched
    printed_name, rest = label.group(0).strip(), line[label.end() :]
    if strict := _VALUE_UNIT.match(rest):
        return ExtractedResult(
            marker=code, printed_name=printed_name, value=float(strict["value"]), unit=strict["unit"]
        )
    return _parse_loose(code, printed_name, rest, continuation)


def extract_baseline(text: str) -> Extraction:
    """Extract results from report text with fixed rules; never calls a model."""
    lines = text.splitlines()
    results = []
    for i, line in enumerate(lines):
        following = lines[i + 1] if i + 1 < len(lines) else ""
        # A wrapped row continues on the next line (e.g. "EDTA ) cu.mm") unless that line starts a new test.
        continuation = "" if _match_label(following) else following
        if row := _parse_line(line, continuation):
            results.append(row)
    return Extraction(collected_on=_collection_date(text), results=results)
